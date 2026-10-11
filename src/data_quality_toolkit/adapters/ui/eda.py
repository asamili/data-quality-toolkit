"""Pure UI-layer helper and compute functions for the Data Quality Toolkit dashboard."""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from statistics import NormalDist
from typing import Any, cast

import numpy as np
import pandas as pd

from data_quality_toolkit.application.workflow.preprocessing import (  # noqa: F401
    iqr_outlier_summary as _iqr_outlier_summary,
)
from data_quality_toolkit.application.workflow.preprocessing import (  # noqa: F401
    plan_preprocessing as _plan_preprocessing,
)
from data_quality_toolkit.domain.statistics.core import scipy_available as _scipy_available
from data_quality_toolkit.shared.constants import DEFAULT_HIGH_CARDINALITY_THRESHOLD

MAX_SUMMARY_COLUMNS = 100
MAX_CORRELATION_COLUMNS = 20
# Bounds the O(n^2) dependency-free Kendall tau-b fallback used when scipy is
# absent (pandas' own "kendall" method imports scipy.stats.kendalltau).
MAX_KENDALL_FALLBACK_ROWS = 2_000
MAX_OUTLIER_COLUMNS = 50
MAX_PLOT_ROWS = 5_000
MAX_TOP_CATEGORIES = 20
MAX_GROUP_CATEGORIES = 20
MAX_PAIRWISE_CELLS = 400
MAX_CROSSTAB_CATEGORIES = 20
MIN_HISTOGRAM_BINS = 2
DEFAULT_HISTOGRAM_BINS = 10
MAX_HISTOGRAM_BINS = 50
MIN_DENSITY_BINS = 5
DEFAULT_DENSITY_BINS = 30
MAX_DENSITY_BINS = 60
DATETIME_PARSE_THRESHOLD = 0.8

# --- Visual-discovery bounds (P2) --------------------------------------------
# Named ceilings for the guided visual-discovery builders. Where an equivalent
# bound already exists it is aliased rather than duplicated, so a single value
# governs every consumer and the two names cannot drift apart.
GENERAL_VISUAL_MAX_ROWS = MAX_PLOT_ROWS
QQ_MAX_POINTS = 1_000
QQ_MIN_OBSERVATIONS = 8
MISSINGNESS_PATTERN_MAX_ROWS = 200
MISSINGNESS_PATTERN_MAX_COLUMNS = 40
MISSINGNESS_ASSOC_MAX_ROWS = GENERAL_VISUAL_MAX_ROWS
MISSINGNESS_ASSOC_MAX_COLUMNS = 20
NUMERIC_CORRELATION_MAX_COLUMNS = MAX_CORRELATION_COLUMNS
CATEGORICAL_ASSOC_MAX_ROWS = GENERAL_VISUAL_MAX_ROWS
CATEGORICAL_ASSOC_MAX_COLUMNS = 8
CATEGORICAL_ASSOC_MAX_LEVELS = 20
PARETO_MAX_CATEGORIES = MAX_TOP_CATEGORIES
# Small-cell suppression: categories rarer than this are aggregated into the
# explicit "(other)" bucket instead of being displayed on their own.
PARETO_MIN_CATEGORY_COUNT = 5
# Conservative identifier-like refusal for category views: a column whose
# distinct values approach its row count carries no useful concentration story.
NEAR_UNIQUE_RATIO = 0.9
GUIDE_MAX_RECOMMENDATIONS = 8
TOP_RELATIONSHIP_PAIRS = 15

_MISSING_CATEGORY_LABEL = "(missing)"
_OTHER_CATEGORY_LABEL = "(other)"


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    """Return an empty DataFrame with stable display columns."""
    return pd.DataFrame(columns=columns)


def _builder_result(status: str, data: pd.DataFrame, **meta: Any) -> dict[str, Any]:
    """Return the common EDA chart-data builder contract."""
    result: dict[str, Any] = {"status": status, "data": data}
    result.update(meta)
    return result


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return min(max(int(value), minimum), maximum)


def _extract_trend_data(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract ts/score pairs from run history records, skipping rows missing either field."""
    result = []
    for r in records:
        ts = r.get("ts")
        score = r.get("score")
        if ts is None or score is None:
            continue
        result.append({"ts": ts, "score": score})
    return result


def _build_trend_df(trend: list[dict[str, Any]]) -> pd.DataFrame | None:
    """Build a DataFrame with parsed ts as index for st.line_chart. Returns None if empty after parse."""
    df = pd.DataFrame({"ts": [r["ts"] for r in trend], "Score": [r["score"] for r in trend]})
    df["ts"] = pd.to_datetime(df["ts"], format="ISO8601", errors="coerce")
    df = df.dropna(subset=["ts"]).set_index("ts")
    return df if not df.empty else None


def _extract_latest_issues(
    records: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (issues_by_severity, issues_by_category) from the latest record."""
    latest = records[-1]
    sev: dict[str, Any] = latest.get("issues_by_severity") or {}
    cat: dict[str, Any] = latest.get("issues_by_category") or {}
    return sev, cat


# In-memory, file-fingerprint-keyed cache over the load/profile/assess work so that
# repeated Streamlit reruns reuse the loaded dataset instead of re-reading the CSV on
# every widget interaction. Streamlit is imported lazily (see _get_cached_loader) so
# this module stays importable and unit-testable outside a Streamlit runtime.
_LoaderFn = Callable[[str, int, int, str | None], tuple[pd.DataFrame, dict[str, Any]]]
_cached_loader: _LoaderFn | None = None


def _compute_load_and_assess(path: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load, profile, and assess a CSV; raise on any failure (never swallow)."""
    from data_quality_toolkit.adapters.loaders.file.csv_loader import load_csv as _load_csv_h
    from data_quality_toolkit.domain.assessment.quality_checker import assess as _assess
    from data_quality_toolkit.domain.profiling.profiling_orchestrator import (
        run_profiling as _run_prof,
    )

    df, meta = _load_csv_h(path)
    prof = _run_prof(df, meta["dataset_id"])
    assessment = _assess(cast(dict[str, Any], prof))
    result: dict[str, Any] = {
        "run_id": prof["run_id"],
        "dataset_id": prof["dataset_id"],
        "ts": prof["ts"],
        "meta": meta,
        "profile": {
            "rows": prof["rows"],
            "cols": prof["cols"],
            "memory_mb": prof["memory_mb"],
            "columns": prof["columns"],
        },
        "assessment": assessment,
    }
    return df, result


def _cached_load_df_and_assess(
    resolved_path: str,
    size_bytes: int,
    modified_ns: int,
    sample_size_env: str | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Cached load/profile/assess.

    ``size_bytes``, ``modified_ns`` and ``sample_size_env`` participate in the cache
    key only (file-fingerprint invalidation); the computation reads ``resolved_path``
    (and, inside the loader, the same ``SAMPLE_SIZE`` env value). This function raises
    on failure so the outer wrapper can convert it to an error tuple — Streamlit's
    ``cache_data`` never caches exceptions, so transient errors are not memoized.
    """
    return _compute_load_and_assess(resolved_path)


def _get_cached_loader() -> _LoaderFn:
    """Return the fingerprint-keyed loader, building the Streamlit cache once.

    Falls back to the uncached function (recompute each call) when ``st.cache_data``
    is unavailable, so the module keeps working outside a Streamlit runtime. The cache
    is in-memory only (no ``persist=`` / disk persistence).
    """
    global _cached_loader
    if _cached_loader is not None:
        return _cached_loader
    try:
        import streamlit as st

        loader: _LoaderFn = st.cache_data(show_spinner=False)(_cached_load_df_and_assess)
    except Exception:
        loader = _cached_load_df_and_assess
    _cached_loader = loader
    return loader


def _file_fingerprint(path: str) -> tuple[str, int, int] | None:
    """Return ``(resolved_path, size_bytes, modified_ns)`` or None when unavailable.

    A None result means the file cannot be stat-ed (missing/unreadable); callers then
    recompute uncached so the loader raises its canonical error using the caller's
    original path (no resolved absolute path is surfaced to the user).
    """
    try:
        resolved = Path(path).expanduser().resolve()
        stat = resolved.stat()
    except (OSError, RuntimeError):
        return None
    return str(resolved), int(stat.st_size), int(stat.st_mtime_ns)


def _load_df_and_assess(
    path_str: str,
) -> tuple[pd.DataFrame | None, dict[str, Any] | None, str | None]:
    """Single-read path for the EDA/analysis pages.

    Loads the CSV once via the hardened csv_loader (max_rows guard, sha1 dataset_id,
    SAMPLE_SIZE env support), then runs profiling and assessment over the in-memory
    DataFrame. Repeated Streamlit reruns reuse the loaded/profiled/assessed dataset via
    an in-memory, file-fingerprint-keyed cache instead of re-reading the CSV on every
    widget interaction. Only successful work is cached; any failure is converted to
    (None, None, error_msg) and never cached. Returns (df, result_dict, None) on
    success or (None, None, error_msg) on failure.
    """
    path = path_str.strip()
    try:
        fingerprint = _file_fingerprint(path)
        if fingerprint is None:
            df, result = _compute_load_and_assess(path)
        else:
            resolved_path, size_bytes, modified_ns = fingerprint
            loader = _get_cached_loader()
            df, result = loader(resolved_path, size_bytes, modified_ns, os.getenv("SAMPLE_SIZE"))
        return df, result, None
    except Exception as exc:
        return None, None, str(exc)


def _build_overview_table(profile: Any) -> list[dict[str, Any]]:
    """Build per-column overview rows from a run_profiling result.

    Each row carries column name, dtype, null count, null percentage, unique
    count, and numeric min/max where the profiler computed them.
    """
    rows = profile.get("rows") or 0
    table: list[dict[str, Any]] = []
    for col in profile.get("columns") or []:
        nulls = col.get("nulls") or 0
        null_pct = round(nulls / rows * 100, 2) if rows else 0.0
        table.append(
            {
                "column": col.get("name"),
                "dtype": col.get("dtype"),
                "nulls": nulls,
                "null_pct": null_pct,
                "unique": col.get("unique"),
                "min": col.get("min"),
                "max": col.get("max"),
            }
        )
    return table


def _numeric_summary(df: pd.DataFrame) -> pd.DataFrame | None:
    """Return df.describe() for numeric columns, or None if there are none."""
    numeric = df.select_dtypes(include="number")
    if numeric.shape[1] == 0:
        return None
    return numeric.describe()


def _duplicate_row_count(df: pd.DataFrame) -> int:
    """Count fully-duplicated rows in the DataFrame."""
    return int(df.duplicated().sum())


def _dataset_profile(
    df: pd.DataFrame, profile: Mapping[str, Any] | None = None
) -> dict[str, int | float]:
    """Return safe dataset-level facts, reusing profiler output when supplied."""
    profile = profile or {}
    rows = int(profile.get("rows", len(df)))
    columns = int(profile.get("cols", df.shape[1]))
    memory_mb = profile.get("memory_mb")
    if memory_mb is None:
        memory_mb = float(df.memory_usage(index=True, deep=False).sum() / (1024**2))
    return {
        "rows": rows,
        "columns": columns,
        "missing_cells": int(df.isna().sum().sum()),
        "memory_mb": round(float(memory_mb), 2),
    }


def _missingness_summary(df: pd.DataFrame, max_columns: int = MAX_SUMMARY_COLUMNS) -> pd.DataFrame:
    """Return a bounded, consolidated per-column missingness table."""
    columns = df.columns[: max(0, max_columns)]
    row_count = len(df)
    records = []
    for position, column in enumerate(columns):
        missing_count = int(df[column].isna().sum())
        records.append(
            {
                "column": column,
                "dtype": str(df[column].dtype),
                "missing_count": missing_count,
                "missing_pct": round(missing_count / row_count * 100, 2) if row_count else 0.0,
                "_position": position,
            }
        )
    if not records:
        return pd.DataFrame(columns=["column", "dtype", "missing_count", "missing_pct"])
    summary = pd.DataFrame(records).sort_values(
        ["missing_count", "_position"], ascending=[False, True], kind="stable"
    )
    return summary.drop(columns="_position").reset_index(drop=True)


def _duplicate_row_summary(df: pd.DataFrame) -> dict[str, int | float]:
    """Return aggregate duplicate-row facts without exposing duplicate records."""
    row_count = len(df)
    duplicate_rows = _duplicate_row_count(df)
    return {
        "total_rows": row_count,
        "duplicate_rows": duplicate_rows,
        "unique_rows": row_count - duplicate_rows,
        "duplicate_pct": round(duplicate_rows / row_count * 100, 2) if row_count else 0.0,
    }


def _dtype_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """Return the number and share of columns for each pandas dtype."""
    total_columns = df.shape[1]
    if total_columns == 0:
        return pd.DataFrame(columns=["dtype", "column_count", "column_pct"])
    counts = pd.Series([str(dtype) for dtype in df.dtypes], dtype="object").value_counts(sort=False)
    return pd.DataFrame(
        {
            "dtype": counts.index,
            "column_count": counts.values,
            "column_pct": (counts.values / total_columns * 100).round(2),
        }
    )


CORRELATION_METHODS = ("pearson", "spearman", "kendall")


def _tie_term(values: np.ndarray) -> float:
    """Sum of ``t*(t-1)/2`` over groups of tied values (Kendall tau-b tie correction)."""
    _, counts = np.unique(values, return_counts=True)
    return float(np.sum(counts * (counts - 1)) / 2.0)


def _kendall_tau_b_pairwise(x: np.ndarray, y: np.ndarray) -> float | None:
    """Dependency-free Kendall's tau-b for two equal-length finite arrays.

    O(n^2); used only as the scipy-absent fallback in ``_correlation_matrix``,
    since pandas' own ``kendall`` method imports ``scipy.stats.kendalltau``
    internally and raises when scipy is not installed. Returns None when the
    tie-adjusted denominator is zero (e.g. a constant column).
    """
    n = x.size
    if n < 2:
        return None
    concordant = 0
    discordant = 0
    for i in range(n - 1):
        sign = np.sign(x[i + 1 :] - x[i]) * np.sign(y[i + 1 :] - y[i])
        concordant += int(np.count_nonzero(sign > 0))
        discordant += int(np.count_nonzero(sign < 0))
    n0 = n * (n - 1) / 2.0
    denominator = math.sqrt((n0 - _tie_term(x)) * (n0 - _tie_term(y)))
    if denominator == 0:
        return None
    return (concordant - discordant) / denominator


def _kendall_correlation_matrix(finite: pd.DataFrame, *, max_rows: int) -> pd.DataFrame:
    """Dependency-free pairwise Kendall's tau-b matrix (scipy-absent fallback).

    Mirrors pandas' pairwise-deletion semantics (``min_periods=2``): each pair
    is computed on its own jointly-finite rows, deterministically sub-sampled
    to ``max_rows`` when larger so the O(n^2) tau-b stays bounded.
    """
    columns = list(finite.columns)
    result = pd.DataFrame(np.eye(len(columns)), index=columns, columns=columns)
    for i in range(len(columns)):
        for j in range(i + 1, len(columns)):
            pair = finite.iloc[:, [i, j]].dropna()
            if pair.shape[0] > max_rows:
                pair = pair.sample(n=max_rows, random_state=0)
            x = pair.iloc[:, 0].to_numpy(dtype=float)
            y = pair.iloc[:, 1].to_numpy(dtype=float)
            value = _kendall_tau_b_pairwise(x, y)
            result.iat[i, j] = np.nan if value is None else value
            result.iat[j, i] = result.iat[i, j]
    return result


def _numeric_correlation_columns(
    df: pd.DataFrame,
    columns: Sequence[str] | None = None,
    *,
    max_columns: int = NUMERIC_CORRELATION_MAX_COLUMNS,
) -> list[str]:
    """Return the bounded numeric columns a correlation view should use.

    ``columns`` is an optional explicit operator selection; unknown or
    non-numeric names are dropped and the remaining names keep the operator's
    order. When nothing usable is supplied the deterministic default is the
    first ``max_columns`` numeric columns in DataFrame order — exactly the
    legacy behavior. Never mutates the input; never raises.
    """
    numeric = [str(column) for column in df.select_dtypes(include="number").columns]
    if columns:
        allowed = set(numeric)
        seen: set[str] = set()
        chosen = []
        for column in columns:
            name = str(column)
            if name in allowed and name not in seen:
                seen.add(name)
                chosen.append(name)
        if chosen:
            return chosen[: max(0, max_columns)]
    return numeric[: max(0, max_columns)]


def _correlation_matrix(
    df: pd.DataFrame,
    max_columns: int = MAX_CORRELATION_COLUMNS,
    method: str = "pearson",
    *,
    columns: Sequence[str] | None = None,
) -> pd.DataFrame | None:
    """Return a bounded correlation matrix for numeric columns.

    ``method`` is one of ``pearson``/``spearman``/``kendall``; an unknown
    method falls back to ``pearson``. Pearson and spearman are computed
    natively by pandas (no extra dependency). ``kendall`` uses pandas' native
    (scipy-backed) implementation when scipy is installed, and a bounded,
    dependency-free pure-numpy tau-b fallback when it is not, so this helper
    never requires scipy. ``columns`` optionally narrows the matrix to an
    explicit operator selection (see :func:`_numeric_correlation_columns`).
    """
    safe_method = method if method in CORRELATION_METHODS else "pearson"
    numeric_all = df.select_dtypes(include="number")
    selected = set(_numeric_correlation_columns(df, columns, max_columns=max_columns))
    # Positional selection keeps duplicate column labels safe and preserves the
    # deterministic DataFrame ordering regardless of how the operator picked.
    positions = [index for index, name in enumerate(numeric_all.columns) if str(name) in selected]
    numeric = numeric_all.iloc[:, positions]
    if numeric.shape[1] < 2:
        return None
    finite = numeric.mask(numeric.isin([float("inf"), float("-inf")]))
    if safe_method == "kendall" and not _scipy_available():
        return _kendall_correlation_matrix(finite, max_rows=MAX_KENDALL_FALLBACK_ROWS).round(3)
    return finite.corr(method=safe_method, min_periods=2).round(3)


def _aggregate_iqr_outlier_summary(
    df: pd.DataFrame, max_columns: int = MAX_OUTLIER_COLUMNS
) -> pd.DataFrame:
    """Return bounded IQR outlier statistics across numeric columns."""
    numeric_columns = df.select_dtypes(include="number").columns[: max(0, max_columns)]
    records: list[dict[str, Any]] = []
    for column in numeric_columns:
        finite = df[column].dropna()
        finite = finite[~finite.isin([float("inf"), float("-inf")])]
        stats = _iqr_outlier_summary(pd.DataFrame({column: finite}), column)
        if stats is None:
            records.append(
                {
                    "column": column,
                    "non_null_count": len(finite),
                    "q1": None,
                    "q3": None,
                    "iqr": None,
                    "lower_fence": None,
                    "upper_fence": None,
                    "outlier_count": None,
                    "outlier_pct": None,
                }
            )
            continue
        outlier_count = int(stats["outlier_count"])
        records.append(
            {
                "column": column,
                "non_null_count": len(finite),
                "q1": round(float(stats["q1"]), 3),
                "q3": round(float(stats["q3"]), 3),
                "iqr": round(float(stats["iqr"]), 3),
                "lower_fence": round(float(stats["lower_fence"]), 3),
                "upper_fence": round(float(stats["upper_fence"]), 3),
                "outlier_count": outlier_count,
                "outlier_pct": round(outlier_count / len(finite) * 100, 2),
            }
        )
    return pd.DataFrame.from_records(
        records,
        columns=[
            "column",
            "non_null_count",
            "q1",
            "q3",
            "iqr",
            "lower_fence",
            "upper_fence",
            "outlier_count",
            "outlier_pct",
        ],
    )


def _high_cardinality_flags(
    profile: Any, threshold: float = DEFAULT_HIGH_CARDINALITY_THRESHOLD
) -> list[str]:
    """Return column names whose unique/rows ratio exceeds *threshold*."""
    rows = profile.get("rows") or 0
    if rows <= 0:
        return []
    flagged: list[str] = []
    for col in profile.get("columns") or []:
        unique = col.get("unique") or 0
        if unique / rows > threshold:
            flagged.append(col.get("name"))
    return flagged


def _auto_histogram_bins(series: pd.Series, *, rule: str = "fd") -> int:
    """Return a data-driven histogram bin count, clamped to the allowed range.

    Drops missing/non-finite values, then applies the Freedman–Diaconis rule
    ``bin_width = 2 * IQR * n^(-1/3)`` and ``ceil(range / bin_width)``. When the
    IQR is zero, the data is degenerate, or ``rule`` is unsupported, it falls back
    to a square-root count. The result is clamped to
    ``[MIN_HISTOGRAM_BINS, MAX_HISTOGRAM_BINS]``. Never mutates the input; never
    raises. Returns ``DEFAULT_HISTOGRAM_BINS`` when fewer than two usable values
    remain (the histogram builder then reports ``insufficient_data``).
    """
    finite = series.dropna()
    finite = finite[~finite.isin([float("inf"), float("-inf")])]
    n = int(len(finite))
    if n < 2 or finite.nunique() < 2:
        return DEFAULT_HISTOGRAM_BINS
    span = float(finite.max()) - float(finite.min())
    bins = 0
    if rule == "fd":
        iqr = float(finite.quantile(0.75)) - float(finite.quantile(0.25))
        if iqr > 0 and span > 0:
            bin_width = 2.0 * iqr * (n ** (-1.0 / 3.0))
            if bin_width > 0:
                bins = int(math.ceil(span / bin_width))
    if bins <= 0:
        bins = int(math.ceil(math.sqrt(n)))
    return _clamp_int(bins, MIN_HISTOGRAM_BINS, MAX_HISTOGRAM_BINS)


def _numeric_histogram_data(
    df: pd.DataFrame, col: str, bins: int | None = DEFAULT_HISTOGRAM_BINS
) -> dict[str, Any]:
    """Return bounded histogram-bin data for a numeric column.

    ``bins=None`` selects a data-driven bin count via :func:`_auto_histogram_bins`;
    an explicit integer preserves the original fixed-bin behavior.
    """
    columns = ["bin", "count", "left", "right"]
    if col not in df.columns:
        return _builder_result("invalid_column", _empty_frame(columns), column=col)
    series = df[col].dropna()
    if not pd.api.types.is_numeric_dtype(series):
        return _builder_result("invalid_type", _empty_frame(columns), column=col)
    finite = series[~series.isin([float("inf"), float("-inf")])]
    if len(finite) < 2 or finite.nunique() < 2:
        return _builder_result("insufficient_data", _empty_frame(columns), column=col)
    auto = bins is None
    resolved_bins = _auto_histogram_bins(finite, rule="fd") if bins is None else int(bins)
    safe_bins = _clamp_int(resolved_bins, MIN_HISTOGRAM_BINS, MAX_HISTOGRAM_BINS)
    try:
        counts = pd.cut(finite, bins=safe_bins, duplicates="drop").value_counts().sort_index()
    except (OverflowError, ValueError, TypeError):
        return _builder_result("invalid_data", _empty_frame(columns), column=col)
    if counts.empty:
        return _builder_result("insufficient_data", _empty_frame(columns), column=col)
    records = []
    for interval, count in counts.items():
        records.append(
            {
                "bin": str(interval),
                "count": int(count),
                "left": round(float(interval.left), 6),
                "right": round(float(interval.right), 6),
            }
        )
    data = pd.DataFrame.from_records(records, columns=columns)
    return _builder_result(
        "ok",
        data,
        column=col,
        bins=int(len(data)),
        requested_bins=(int(bins) if bins is not None else None),
        effective_bins=safe_bins,
        auto=bool(auto),
        non_null_count=int(len(finite)),
    )


def _categorical_top_frequency_data(
    df: pd.DataFrame,
    col: str,
    n: int = MAX_TOP_CATEGORIES,
    *,
    include_missing: bool = False,
    missing_label: str = _MISSING_CATEGORY_LABEL,
    other_bucket: bool = False,
    other_label: str = _OTHER_CATEGORY_LABEL,
) -> dict[str, Any]:
    """Return top-N categorical frequencies with an optional missing/other bucket.

    When ``other_bucket`` is True and categories exceed the top-N cap, the
    remaining categories are aggregated into an explicit ``other_label`` row
    (instead of being dropped) so the displayed percentages cover the full
    population. Default behavior (``other_bucket=False``) is unchanged.
    """
    columns = ["category", "count", "pct"]
    if col not in df.columns:
        return _builder_result("invalid_column", _empty_frame(columns), column=col)
    series = df[col]
    if pd.api.types.is_numeric_dtype(series):
        return _builder_result("invalid_type", _empty_frame(columns), column=col)
    safe_n = _clamp_int(n, 1, MAX_TOP_CATEGORIES)
    working = series.astype("object")
    if include_missing:
        working = working.where(~working.isna(), missing_label)
    try:
        all_counts = working.value_counts(dropna=not include_missing)
        counts = all_counts.head(safe_n)
    except TypeError:
        return _builder_result("invalid_data", _empty_frame(columns), column=col)
    if include_missing and missing_label in all_counts.index and missing_label not in counts.index:
        counts = pd.concat([counts.head(max(safe_n - 1, 0)), all_counts.loc[[missing_label]]])
    if counts.empty:
        return _builder_result("no_data", _empty_frame(columns), column=col)
    truncated = bool(len(all_counts) > len(counts))
    other_count = int(all_counts[~all_counts.index.isin(counts.index)].sum())
    denominator = int(series.size if include_missing else series.notna().sum())
    records = [
        {
            "category": str(category),
            "count": int(count),
            "pct": round(int(count) / denominator * 100.0, 2) if denominator else 0.0,
        }
        for category, count in counts.items()
    ]
    if other_bucket and other_count > 0:
        records.append(
            {
                "category": other_label,
                "count": other_count,
                "pct": round(other_count / denominator * 100.0, 2) if denominator else 0.0,
            }
        )
    data = pd.DataFrame.from_records(records, columns=columns)
    return _builder_result(
        "ok",
        data,
        column=col,
        top_n=safe_n,
        include_missing=include_missing,
        total_categories=int(working.nunique(dropna=not include_missing)),
        included_count=int(data["count"].sum()),
        total_count=denominator,
        truncated=truncated,
        other_count=other_count,
    )


def _missingness_bar_data(
    df: pd.DataFrame, max_columns: int = MAX_SUMMARY_COLUMNS
) -> dict[str, Any]:
    """Return bounded per-column missingness data for a bar view."""
    columns = ["column", "missing_count", "missing_pct"]
    summary = _missingness_summary(df, max_columns=max_columns)
    if summary.empty:
        return _builder_result("no_columns", _empty_frame(columns))
    data = summary.loc[:, columns].copy()
    return _builder_result(
        "ok",
        data,
        columns_considered=int(len(data)),
        columns_total=int(df.shape[1]),
        truncated=bool(df.shape[1] > max_columns),
    )


def _correlation_heatmap_data(
    df: pd.DataFrame,
    max_columns: int = MAX_CORRELATION_COLUMNS,
    method: str = "pearson",
    *,
    selected_columns: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return long-form correlation data suitable for a heatmap.

    ``method`` selects pearson/spearman/kendall; the resolved method is echoed
    back in the result for display. ``selected_columns`` optionally narrows the
    matrix to an explicit operator selection; the deterministic default (first
    ``max_columns`` numeric columns) is used when it is empty or unusable.
    """
    columns = ["x", "y", "correlation"]
    safe_method = method if method in CORRELATION_METHODS else "pearson"
    matrix = _correlation_matrix(
        df, max_columns=max_columns, method=safe_method, columns=selected_columns
    )
    if matrix is None:
        return _builder_result("insufficient_numeric", _empty_frame(columns), method=safe_method)
    return _builder_result(
        "ok",
        _long_pair_frame(matrix, value_name="correlation"),
        matrix=matrix,
        method=safe_method,
        numeric_columns=int(matrix.shape[1]),
        numeric_columns_total=int(df.select_dtypes(include="number").shape[1]),
        truncated=bool(df.select_dtypes(include="number").shape[1] > max_columns),
        selected=bool(selected_columns),
        pairs=_ranked_matrix_pairs(matrix, value_name="correlation"),
    )


def _long_pair_frame(matrix: pd.DataFrame, *, value_name: str) -> pd.DataFrame:
    """Return a symmetric matrix in long ``x``/``y``/<value> form for a heatmap.

    Built cell by cell rather than by melting a reset index, so a column whose
    own label is ``x`` or ``y`` cannot collide with the output column names.
    The output size is bounded by the caller's column cap squared.
    """
    columns = ["x", "y", value_name]
    names = [str(name) for name in matrix.columns]
    records = [
        {"x": names[left], "y": names[right], value_name: matrix.iat[left, right]}
        for left in range(len(names))
        for right in range(len(names))
    ]
    data = pd.DataFrame.from_records(records, columns=columns)
    data[value_name] = pd.to_numeric(data[value_name], errors="coerce")
    return data


def _ranked_matrix_pairs(
    matrix: pd.DataFrame,
    *,
    value_name: str = "correlation",
    top_n: int = TOP_RELATIONSHIP_PAIRS,
) -> pd.DataFrame:
    """Rank the strongest off-diagonal pairs of a symmetric association matrix.

    Reads the upper triangle only, so the diagonal and mirrored duplicates can
    never appear. Rows are ordered by absolute strength (descending) with a
    stable ``(column_x, column_y)`` tie-break, then capped at ``top_n``.
    Non-finite cells are skipped. Never mutates the input; never raises.
    """
    columns = ["column_x", "column_y", value_name, f"abs_{value_name}"]
    names = [str(name) for name in matrix.columns]
    records: list[dict[str, Any]] = []
    for left in range(len(names)):
        for right in range(left + 1, len(names)):
            raw = matrix.iat[left, right]
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            records.append(
                {
                    "column_x": names[left],
                    "column_y": names[right],
                    value_name: round(value, 6),
                    f"abs_{value_name}": round(abs(value), 6),
                }
            )
    if not records:
        return _empty_frame(columns)
    ranked = pd.DataFrame.from_records(records, columns=columns).sort_values(
        [f"abs_{value_name}", "column_x", "column_y"],
        ascending=[False, True, True],
        kind="stable",
    )
    return ranked.head(max(0, int(top_n))).reset_index(drop=True)


def _skew_kurtosis_summary(
    df: pd.DataFrame, max_columns: int = MAX_SUMMARY_COLUMNS
) -> pd.DataFrame:
    """Return per-numeric-column skewness and (Fisher) kurtosis.

    Skewness needs at least 3 non-null finite values and kurtosis at least 4;
    below those thresholds the value is ``None`` rather than a fabricated number.
    """
    numeric = df.select_dtypes(include="number").iloc[:, : max(0, max_columns)]
    records: list[dict[str, Any]] = []
    for column in numeric.columns:
        series = numeric[column].replace([float("inf"), float("-inf")], pd.NA).dropna()
        count = int(len(series))
        skew = float(series.skew()) if count > 2 else None
        kurt = float(series.kurtosis()) if count > 3 else None
        records.append(
            {
                "column": column,
                "count": count,
                "skewness": round(skew, 4) if skew is not None and pd.notna(skew) else None,
                "kurtosis": round(kurt, 4) if kurt is not None and pd.notna(kurt) else None,
            }
        )
    return pd.DataFrame.from_records(records, columns=["column", "count", "skewness", "kurtosis"])


def _boxplot_data(
    df: pd.DataFrame, col: str, *, max_rows: int = MAX_PLOT_ROWS, seed: int = 0
) -> dict[str, Any]:
    """Return bounded finite values of a numeric column for a boxplot mark."""
    columns = ["value"]
    if col not in df.columns:
        return _builder_result("invalid_column", _empty_frame(columns), column=col)
    series = df[col]
    if not pd.api.types.is_numeric_dtype(series):
        return _builder_result("invalid_type", _empty_frame(columns), column=col)
    finite = series.dropna()
    finite = finite[~finite.isin([float("inf"), float("-inf")])]
    if len(finite) < 1:
        return _builder_result("insufficient_data", _empty_frame(columns), column=col)
    source_rows = int(len(finite))
    safe_max_rows = max(1, int(max_rows))
    sampled = source_rows > safe_max_rows
    plot = finite.sample(n=safe_max_rows, random_state=seed).sort_index() if sampled else finite
    data = pd.DataFrame({"value": plot.reset_index(drop=True)})
    return _builder_result(
        "ok",
        data,
        column=col,
        source_rows=source_rows,
        plot_rows=int(len(data)),
        sampled=sampled,
    )


def _density_curve_data(
    df: pd.DataFrame, col: str, bins: int = DEFAULT_HISTOGRAM_BINS
) -> dict[str, Any]:
    """Return a bounded density-style curve (normalized histogram) for a column.

    Reuses the bounded histogram builder and rescales counts to a probability
    density (area ≈ 1). Dependency-free; not a kernel density estimate.
    """
    columns = ["value", "density"]
    hist = _numeric_histogram_data(df, col, bins=bins)
    if hist["status"] != "ok":
        return _builder_result(hist["status"], _empty_frame(columns), column=col)
    data = hist["data"]
    total = int(data["count"].sum())
    if total <= 0:
        return _builder_result("insufficient_data", _empty_frame(columns), column=col)
    widths = (data["right"] - data["left"]).replace(0, pd.NA)
    density = (data["count"] / (total * widths)).astype(float)
    midpoints = ((data["left"] + data["right"]) / 2.0).round(6)
    out = pd.DataFrame({"value": midpoints, "density": density.round(6)})
    return _builder_result("ok", out, column=col, points=int(len(out)))


def _numeric_ecdf_data(
    df: pd.DataFrame, col: str, *, max_points: int = MAX_PLOT_ROWS
) -> dict[str, Any]:
    """Return a deterministic, bounded empirical CDF (ECDF) for a numeric column.

    Aggregates by unique finite value in ascending order and reports the
    cumulative share (0-1 scale) of values less than or equal to each value.
    Drops missing/non-finite values; never mutates the input; never raises.
    Output is bounded to ``max_points`` points via deterministic evenly-spaced
    downsampling that always preserves the first and last points (the last point
    carries cumulative probability ``1.0``). No random sampling is used, so the
    result is fully reproducible.
    """
    columns = ["value", "cumulative_probability", "count"]
    if col not in df.columns:
        return _builder_result("invalid_column", _empty_frame(columns), column=col)
    series = df[col]
    if not pd.api.types.is_numeric_dtype(series):
        return _builder_result("invalid_type", _empty_frame(columns), column=col)
    finite = series.dropna()
    finite = finite[~finite.isin([float("inf"), float("-inf")])]
    n = int(len(finite))
    if n < 1:
        return _builder_result("insufficient_data", _empty_frame(columns), column=col)
    counts = finite.value_counts().sort_index()
    values = counts.index.to_numpy(dtype=float)
    freq = counts.to_numpy()
    cumulative_probability = np.cumsum(freq) / float(n)
    unique_values = int(len(values))
    safe_max = max(2, int(max_points))
    sampled = unique_values > safe_max
    if sampled:
        positions = np.unique(np.linspace(0, unique_values - 1, safe_max).round().astype(int))
        values = values[positions]
        freq = freq[positions]
        cumulative_probability = cumulative_probability[positions]
    data = pd.DataFrame(
        {
            "value": np.round(values, 6),
            "cumulative_probability": np.round(cumulative_probability, 6),
            "count": freq.astype(int),
        }
    )
    return _builder_result(
        "ok",
        data,
        column=col,
        points=int(len(data)),
        unique_values=unique_values,
        non_null_count=n,
        sampled=sampled,
    )


def _percentile_domain(
    series: pd.Series,
    *,
    lower: float = 1.0,
    upper: float = 99.0,
) -> tuple[float, float] | None:
    """Return a ``(low, high)`` axis domain at the given percentiles, or None.

    Drops missing/non-finite values; returns None when fewer than two usable
    values remain or the resulting domain is non-finite/degenerate (low >= high).
    Never mutates the input; never raises.
    """
    finite = series.dropna()
    finite = finite[~finite.isin([float("inf"), float("-inf")])]
    if len(finite) < 2:
        return None
    low = float(finite.quantile(max(0.0, min(lower, 100.0)) / 100.0))
    high = float(finite.quantile(max(0.0, min(upper, 100.0)) / 100.0))
    if not (math.isfinite(low) and math.isfinite(high)) or low >= high:
        return None
    return (round(low, 6), round(high, 6))


def _linear_trendline_data(df: pd.DataFrame, x_col: str, y_col: str) -> pd.DataFrame:
    """Return two endpoint rows of an OLS (degree-1) fit of ``y_col`` on ``x_col``.

    Uses finite rows only; returns an empty DataFrame when fewer than two valid
    points remain or ``x_col`` has fewer than two unique values. Endpoint x values
    are the min/max of valid x; endpoint y values are the fitted values. Uses
    ``numpy.polyfit`` and never raises on singular/degenerate input.
    """
    columns = [x_col, y_col]
    if x_col not in df.columns or y_col not in df.columns:
        return _empty_frame(columns)
    pair = df[[x_col, y_col]].dropna()
    pair = pair[~pair[x_col].isin([float("inf"), float("-inf")])]
    pair = pair[~pair[y_col].isin([float("inf"), float("-inf")])]
    if len(pair) < 2 or pair[x_col].nunique() < 2:
        return _empty_frame(columns)
    x = pair[x_col].to_numpy(dtype=float)
    y = pair[y_col].to_numpy(dtype=float)
    try:
        slope, intercept = np.polyfit(x, y, 1)
    except (np.linalg.LinAlgError, ValueError, TypeError):
        return _empty_frame(columns)
    x_min, x_max = float(x.min()), float(x.max())
    return pd.DataFrame(
        {
            x_col: [round(x_min, 6), round(x_max, 6)],
            y_col: [
                round(float(slope * x_min + intercept), 6),
                round(float(slope * x_max + intercept), 6),
            ],
        }
    )


def _bounded_scatter_data(
    df: pd.DataFrame,
    col1: str,
    col2: str,
    *,
    max_rows: int = MAX_PLOT_ROWS,
    seed: int = 0,
    clip: bool = False,
    trend: bool = False,
    clip_lower: float = 1.0,
    clip_upper: float = 99.0,
) -> dict[str, Any]:
    """Return bounded numeric-vs-numeric scatter data and Pearson r.

    ``clip`` adds ``x_domain``/``y_domain`` percentile axis domains and ``trend``
    adds a ``trendline`` endpoint frame plus ``trendline_status`` to the metadata;
    both default off and leave the sampled data unchanged.
    """
    columns = [col1, col2]
    if col1 not in df.columns or col2 not in df.columns:
        return _builder_result("invalid_column", _empty_frame(columns), x=col1, y=col2)
    if not pd.api.types.is_numeric_dtype(df[col1]) or not pd.api.types.is_numeric_dtype(df[col2]):
        return _builder_result("invalid_type", _empty_frame(columns), x=col1, y=col2)
    pair = df[[col1, col2]].dropna()
    pair = pair[~pair[col1].isin([float("inf"), float("-inf")])]
    pair = pair[~pair[col2].isin([float("inf"), float("-inf")])]
    if len(pair) < 2 or pair[col1].nunique() < 2 or pair[col2].nunique() < 2:
        return _builder_result("insufficient_data", _empty_frame(columns), x=col1, y=col2)
    try:
        r_val = pair.corr().iloc[0, 1]
        r = None if pd.isna(r_val) else round(float(r_val), 6)
    except (ValueError, TypeError):
        r = None
    source_rows = int(len(pair))
    safe_max_rows = max(1, int(max_rows))
    sampled = source_rows > safe_max_rows
    plot = pair.sample(n=safe_max_rows, random_state=seed).sort_index() if sampled else pair.copy()
    plot = plot.reset_index(drop=True)
    extra: dict[str, Any] = {}
    if clip:
        extra["x_domain"] = _percentile_domain(plot[col1], lower=clip_lower, upper=clip_upper)
        extra["y_domain"] = _percentile_domain(plot[col2], lower=clip_lower, upper=clip_upper)
    if trend:
        trendline = _linear_trendline_data(plot, col1, col2)
        extra["trendline"] = trendline
        extra["trendline_status"] = "ok" if not trendline.empty else "insufficient_data"
    return _builder_result(
        "ok",
        plot,
        x=col1,
        y=col2,
        pearson_r=r,
        source_rows=source_rows,
        plot_rows=int(len(plot)),
        sampled=sampled,
        max_rows=safe_max_rows,
        **extra,
    )


def _bounded_density_heatmap_data(
    df: pd.DataFrame,
    col1: str,
    col2: str,
    *,
    bins: int = DEFAULT_DENSITY_BINS,
    clip: bool = False,
    clip_lower: float = 1.0,
    clip_upper: float = 99.0,
) -> dict[str, Any]:
    """Return long-form 2D binned-density data for two numeric columns.

    Bins the finite ``(col1, col2)`` pairs into a ``bins x bins`` grid via
    :func:`numpy.histogram2d` and returns one row per non-empty cell with the
    cell's axis-aligned edges plus ``count`` (raw row count) and ``density``
    (the cell's share of the total, a fraction). Unlike :func:`_bounded_scatter_data`
    this never samples: the output size is bounded by ``bins**2`` regardless of row
    count, so every finite row is represented. ``clip`` restricts the histogram
    range to the 1st/99th percentile domain (via :func:`_percentile_domain`) so
    outliers do not collapse the interior bins. Never mutates the input; never raises.
    """
    columns = ["x_left", "x_right", "y_left", "y_right", "count", "density"]
    if col1 not in df.columns or col2 not in df.columns:
        return _builder_result("invalid_column", _empty_frame(columns), x=col1, y=col2)
    if not pd.api.types.is_numeric_dtype(df[col1]) or not pd.api.types.is_numeric_dtype(df[col2]):
        return _builder_result("invalid_type", _empty_frame(columns), x=col1, y=col2)
    pair = df[[col1, col2]].dropna()
    pair = pair[~pair[col1].isin([float("inf"), float("-inf")])]
    pair = pair[~pair[col2].isin([float("inf"), float("-inf")])]
    if len(pair) < 2 or pair[col1].nunique() < 2 or pair[col2].nunique() < 2:
        return _builder_result("insufficient_data", _empty_frame(columns), x=col1, y=col2)
    safe_bins = _clamp_int(bins, MIN_DENSITY_BINS, MAX_DENSITY_BINS)
    x_domain = _percentile_domain(pair[col1], lower=clip_lower, upper=clip_upper) if clip else None
    y_domain = _percentile_domain(pair[col2], lower=clip_lower, upper=clip_upper) if clip else None
    hist_range = (
        [list(x_domain), list(y_domain)]
        if clip and x_domain is not None and y_domain is not None
        else None
    )
    try:
        counts, xedges, yedges = np.histogram2d(
            pair[col1].to_numpy(dtype=float),
            pair[col2].to_numpy(dtype=float),
            bins=safe_bins,
            range=hist_range,
        )
    except (ValueError, TypeError):
        return _builder_result("invalid_data", _empty_frame(columns), x=col1, y=col2)
    total = float(counts.sum())
    if total <= 0:
        return _builder_result("insufficient_data", _empty_frame(columns), x=col1, y=col2)
    records = []
    for i, j in np.argwhere(counts > 0):
        count = int(counts[i, j])
        records.append(
            {
                "x_left": round(float(xedges[i]), 6),
                "x_right": round(float(xedges[i + 1]), 6),
                "y_left": round(float(yedges[j]), 6),
                "y_right": round(float(yedges[j + 1]), 6),
                "count": count,
                "density": round(count / total, 6),
            }
        )
    data = pd.DataFrame.from_records(records, columns=columns)
    extra: dict[str, Any] = {}
    if clip:
        extra["x_domain"] = x_domain
        extra["y_domain"] = y_domain
    return _builder_result(
        "ok",
        data,
        x=col1,
        y=col2,
        bins_x=int(safe_bins),
        bins_y=int(safe_bins),
        source_rows=int(len(pair)),
        total_count=int(total),
        nonzero_cells=int(len(data)),
        cells=int(safe_bins * safe_bins),
        **extra,
    )


def _numeric_by_category_summary_data(
    df: pd.DataFrame,
    numeric_col: str,
    categorical_col: str,
    *,
    max_categories: int = MAX_GROUP_CATEGORIES,
) -> dict[str, Any]:
    """Return capped numeric distribution summaries by categorical level."""
    columns = ["category", "count", "mean", "median", "min", "q1", "q3", "max"]
    if numeric_col not in df.columns or categorical_col not in df.columns:
        return _builder_result(
            "invalid_column", _empty_frame(columns), numeric=numeric_col, category=categorical_col
        )
    if not pd.api.types.is_numeric_dtype(df[numeric_col]):
        return _builder_result(
            "invalid_type", _empty_frame(columns), numeric=numeric_col, category=categorical_col
        )
    if pd.api.types.is_numeric_dtype(df[categorical_col]):
        return _builder_result(
            "invalid_type", _empty_frame(columns), numeric=numeric_col, category=categorical_col
        )
    pair = df[[numeric_col, categorical_col]].dropna()
    pair = pair[~pair[numeric_col].isin([float("inf"), float("-inf")])]
    if pair.empty:
        return _builder_result(
            "no_data", _empty_frame(columns), numeric=numeric_col, category=categorical_col
        )
    safe_max = _clamp_int(max_categories, 1, MAX_GROUP_CATEGORIES)
    counts = pair[categorical_col].value_counts().head(safe_max)
    records = []
    for category in counts.index:
        values = pair.loc[pair[categorical_col] == category, numeric_col].dropna()
        if values.empty:
            continue
        records.append(
            {
                "category": str(category),
                "count": int(values.count()),
                "mean": round(float(values.mean()), 4),
                "median": round(float(values.median()), 4),
                "min": round(float(values.min()), 4),
                "q1": round(float(values.quantile(0.25)), 4),
                "q3": round(float(values.quantile(0.75)), 4),
                "max": round(float(values.max()), 4),
            }
        )
    if not records:
        return _builder_result(
            "no_data", _empty_frame(columns), numeric=numeric_col, category=categorical_col
        )
    data = pd.DataFrame.from_records(records, columns=columns)
    total_categories = int(pair[categorical_col].nunique(dropna=True))
    return _builder_result(
        "ok",
        data,
        numeric=numeric_col,
        category=categorical_col,
        total_categories=total_categories,
        displayed_categories=int(len(data)),
        truncated=bool(total_categories > safe_max),
    )


def _datetime_metric_error(
    df: pd.DataFrame, datetime_col: str, numeric_col: str | None, columns: list[str]
) -> dict[str, Any] | None:
    if numeric_col is None:
        return None
    if numeric_col not in df.columns:
        return _builder_result(
            "invalid_column", _empty_frame(columns), datetime=datetime_col, metric=numeric_col
        )
    if not pd.api.types.is_numeric_dtype(df[numeric_col]):
        return _builder_result(
            "invalid_type", _empty_frame(columns), datetime=datetime_col, metric=numeric_col
        )
    return None


_DATETIME_GRANULARITIES = ("day", "week", "month")


def _floor_to_granularity(parsed: pd.Series, granularity: str) -> pd.Series:
    """Bucket parsed timestamps to day/week/month period starts (unsupported → day)."""
    if granularity == "week":
        return parsed.dt.tz_localize(None).dt.to_period("W").dt.to_timestamp()
    if granularity == "month":
        return parsed.dt.tz_localize(None).dt.to_period("M").dt.to_timestamp()
    return parsed.dt.floor("D")


def _datetime_trend_data(
    df: pd.DataFrame,
    datetime_col: str,
    numeric_col: str | None = None,
    *,
    parse_threshold: float = DATETIME_PARSE_THRESHOLD,
    granularity: str = "day",
) -> dict[str, Any]:
    """Return row-count or numeric-mean trend data by day/week/month when parsing is confident.

    ``granularity`` is one of ``day``/``week``/``month`` (unsupported values fall
    back to ``day``). The count of unparseable/missing datetime values is surfaced
    in the result metadata as ``missing_datetime``.
    """
    columns = ["timestamp", "value"]
    if datetime_col not in df.columns:
        return _builder_result("invalid_column", _empty_frame(columns), datetime=datetime_col)
    if df.empty:
        return _builder_result("no_data", _empty_frame(columns), datetime=datetime_col)
    metric_error = _datetime_metric_error(df, datetime_col, numeric_col, columns)
    if metric_error is not None:
        return metric_error
    parsed = pd.to_datetime(df[datetime_col], errors="coerce", utc=True, format="mixed")
    parse_ratio = float(parsed.notna().mean()) if len(parsed) else 0.0
    missing_datetime = int(parsed.isna().sum())
    threshold = max(0.0, min(float(parse_threshold), 1.0))
    if parse_ratio < threshold:
        return _builder_result(
            "low_parse_confidence",
            _empty_frame(columns),
            datetime=datetime_col,
            metric=numeric_col or "row_count",
            parse_ratio=round(parse_ratio, 4),
            parse_threshold=threshold,
            missing_datetime=missing_datetime,
        )
    safe_granularity = granularity if granularity in _DATETIME_GRANULARITIES else "day"
    timestamps = _floor_to_granularity(parsed, safe_granularity)
    if numeric_col is None:
        frame = pd.DataFrame({"timestamp": timestamps}).dropna(subset=["timestamp"])
        if frame.empty:
            return _builder_result("no_data", _empty_frame(columns), datetime=datetime_col)
        grouped = frame.groupby("timestamp", sort=True).size().reset_index(name="value")
        metric = "row_count"
    else:
        frame = pd.DataFrame({"timestamp": timestamps, "value": df[numeric_col]}).dropna()
        frame = frame[~frame["value"].isin([float("inf"), float("-inf")])]
        if frame.empty:
            return _builder_result(
                "no_data", _empty_frame(columns), datetime=datetime_col, metric=numeric_col
            )
        grouped = frame.groupby("timestamp", sort=True)["value"].mean().reset_index()
        metric = numeric_col
    if len(grouped) < 2:
        return _builder_result(
            "insufficient_data",
            _empty_frame(columns),
            datetime=datetime_col,
            metric=metric,
            parse_ratio=round(parse_ratio, 4),
        )
    grouped["value"] = pd.to_numeric(grouped["value"], errors="coerce")
    return _builder_result(
        "ok",
        grouped.loc[:, columns],
        datetime=datetime_col,
        metric=metric,
        parse_ratio=round(parse_ratio, 4),
        points=int(len(grouped)),
        granularity=safe_granularity,
        missing_datetime=missing_datetime,
    )


_DATETIME_AGGREGATIONS = ("mean", "median", "sum", "count")


def _apply_time_aggregation(grouped: Any, aggregation: str) -> pd.Series:
    """Reduce a grouped numeric series by the requested aggregation."""
    if aggregation == "median":
        return grouped.median()
    if aggregation == "sum":
        return grouped.sum()
    if aggregation == "count":
        return grouped.count()
    return grouped.mean()


def _datetime_numeric_aggregation_data(
    df: pd.DataFrame,
    datetime_col: str,
    numeric_col: str,
    *,
    granularity: str = "day",
    aggregation: str = "mean",
    parse_threshold: float = DATETIME_PARSE_THRESHOLD,
) -> dict[str, Any]:
    """Aggregate a numeric column over datetime buckets (day/week/month).

    ``aggregation`` is one of mean/median/sum/count. Rows with unparseable
    datetimes or non-finite numeric values are dropped. Returns a safe status
    when parse confidence is too low, no usable rows remain, fewer than two
    buckets result, or the aggregation is unsupported. Never mutates; never raises.
    """
    columns = ["period", "value", "aggregation", "count"]
    if datetime_col not in df.columns or numeric_col not in df.columns:
        return _builder_result(
            "invalid_column", _empty_frame(columns), datetime=datetime_col, metric=numeric_col
        )
    if not pd.api.types.is_numeric_dtype(df[numeric_col]):
        return _builder_result(
            "invalid_type", _empty_frame(columns), datetime=datetime_col, metric=numeric_col
        )
    if aggregation not in _DATETIME_AGGREGATIONS:
        return _builder_result(
            "invalid_aggregation",
            _empty_frame(columns),
            datetime=datetime_col,
            metric=numeric_col,
            aggregation=aggregation,
        )
    parsed = pd.to_datetime(df[datetime_col], errors="coerce", utc=True, format="mixed")
    parse_ratio = float(parsed.notna().mean()) if len(parsed) else 0.0
    missing_datetime = int(parsed.isna().sum())
    threshold = max(0.0, min(float(parse_threshold), 1.0))
    if parse_ratio < threshold:
        return _builder_result(
            "low_parse_confidence",
            _empty_frame(columns),
            datetime=datetime_col,
            metric=numeric_col,
            aggregation=aggregation,
            parse_ratio=round(parse_ratio, 4),
            parse_threshold=threshold,
            missing_datetime=missing_datetime,
        )
    safe_granularity = granularity if granularity in _DATETIME_GRANULARITIES else "day"
    frame = pd.DataFrame(
        {"period": _floor_to_granularity(parsed, safe_granularity), "value": df[numeric_col]}
    )
    frame = frame[frame["period"].notna()]
    frame = frame[~frame["value"].isin([float("inf"), float("-inf")])].dropna(subset=["value"])
    rows_used = int(len(frame))
    meta = {
        "datetime": datetime_col,
        "metric": numeric_col,
        "granularity": safe_granularity,
        "aggregation": aggregation,
        "missing_datetime": missing_datetime,
        "rows_used": rows_used,
    }
    if frame.empty:
        return _builder_result("no_data", _empty_frame(columns), **meta)
    grouped = frame.groupby("period", sort=True)["value"]
    aggregated = _apply_time_aggregation(grouped, aggregation)
    data = pd.DataFrame(
        {
            "period": aggregated.index,
            "value": pd.to_numeric(aggregated.to_numpy(), errors="coerce").round(6),
            "aggregation": aggregation,
            "count": grouped.count().to_numpy(),
        }
    )
    if len(data) < 2:
        return _builder_result("insufficient_data", _empty_frame(columns), **meta)
    return _builder_result(
        "ok", data.loc[:, columns], parse_ratio=round(parse_ratio, 4), points=int(len(data)), **meta
    )


def _datetime_categorical_counts_data(
    df: pd.DataFrame,
    datetime_col: str,
    categorical_col: str,
    *,
    granularity: str = "day",
    top_n: int = MAX_GROUP_CATEGORIES,
    parse_threshold: float = DATETIME_PARSE_THRESHOLD,
) -> dict[str, Any]:
    """Count categorical values over datetime buckets (day/week/month), long-form.

    Missing category values are preserved as ``(missing)``; categories beyond the
    top ``top_n`` by overall frequency roll into ``(other)``. Rows with unparseable
    datetimes are dropped. Returns a safe status on low parse confidence or no
    usable data. Never mutates; never raises.
    """
    columns = ["period", "category", "count"]
    if datetime_col not in df.columns or categorical_col not in df.columns:
        return _builder_result(
            "invalid_column", _empty_frame(columns), datetime=datetime_col, category=categorical_col
        )
    if pd.api.types.is_numeric_dtype(df[categorical_col]):
        return _builder_result(
            "invalid_type", _empty_frame(columns), datetime=datetime_col, category=categorical_col
        )
    parsed = pd.to_datetime(df[datetime_col], errors="coerce", utc=True, format="mixed")
    parse_ratio = float(parsed.notna().mean()) if len(parsed) else 0.0
    missing_datetime = int(parsed.isna().sum())
    threshold = max(0.0, min(float(parse_threshold), 1.0))
    if parse_ratio < threshold:
        return _builder_result(
            "low_parse_confidence",
            _empty_frame(columns),
            datetime=datetime_col,
            category=categorical_col,
            parse_ratio=round(parse_ratio, 4),
            parse_threshold=threshold,
            missing_datetime=missing_datetime,
        )
    safe_granularity = granularity if granularity in _DATETIME_GRANULARITIES else "day"
    safe_top_n = _clamp_int(top_n, 1, MAX_GROUP_CATEGORIES)
    category = df[categorical_col].astype("object")
    category = category.where(~category.isna(), _MISSING_CATEGORY_LABEL)
    frame = pd.DataFrame(
        {"period": _floor_to_granularity(parsed, safe_granularity), "category": category}
    )
    frame = frame[frame["period"].notna()]
    rows_used = int(len(frame))
    if frame.empty:
        return _builder_result(
            "no_data",
            _empty_frame(columns),
            datetime=datetime_col,
            category=categorical_col,
            granularity=safe_granularity,
            missing_datetime=missing_datetime,
            rows_used=0,
        )
    overall = frame["category"].value_counts()
    kept = list(overall.head(safe_top_n).index)
    other_count = int(overall[~overall.index.isin(kept)].sum())
    frame["category"] = frame["category"].where(frame["category"].isin(kept), _OTHER_CATEGORY_LABEL)
    grouped = frame.groupby(["period", "category"], sort=True).size().reset_index(name="count")
    data = grouped.loc[:, columns]
    return _builder_result(
        "ok",
        data,
        datetime=datetime_col,
        category=categorical_col,
        granularity=safe_granularity,
        top_n=safe_top_n,
        missing_datetime=missing_datetime,
        categories_plotted=int(data["category"].nunique()),
        other_count=other_count,
        rows_used=rows_used,
        parse_ratio=round(parse_ratio, 4),
    )


def _datetime_candidate_columns(
    df: pd.DataFrame,
    *,
    max_columns: int = MAX_SUMMARY_COLUMNS,
    parse_threshold: float = DATETIME_PARSE_THRESHOLD,
) -> list[str]:
    """Return bounded columns that are already datetime-like or parse confidently."""
    threshold = max(0.0, min(float(parse_threshold), 1.0))
    candidates: list[str] = []
    for column in df.columns[: max(0, max_columns)]:
        series = df[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            candidates.append(str(column))
            continue
        if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
            continue
        if series.empty:
            continue
        parsed = pd.to_datetime(series, errors="coerce", utc=True, format="mixed")
        parse_ratio = float(parsed.notna().mean()) if len(parsed) else 0.0
        if parse_ratio >= threshold:
            candidates.append(str(column))
    return candidates


def _outlier_bar_data(df: pd.DataFrame, max_columns: int = MAX_OUTLIER_COLUMNS) -> dict[str, Any]:
    """Return bounded IQR outlier counts for a compact bar view."""
    columns = ["column", "outlier_count", "outlier_pct"]
    summary = _aggregate_iqr_outlier_summary(df, max_columns=max_columns)
    if summary.empty:
        return _builder_result("no_numeric", _empty_frame(columns))
    data = summary.loc[:, columns].copy()
    data["outlier_count"] = (
        pd.to_numeric(data["outlier_count"], errors="coerce").fillna(0).astype(int)
    )
    data["outlier_pct"] = pd.to_numeric(data["outlier_pct"], errors="coerce").fillna(0.0)
    return _builder_result(
        "ok",
        data,
        numeric_columns=int(len(data)),
        numeric_columns_total=int(df.select_dtypes(include="number").shape[1]),
        truncated=bool(df.select_dtypes(include="number").shape[1] > max_columns),
    )


_CROSSTAB_NORMALIZE_MODES = ("overall", "row", "column")


def _normalize_crosstab(ct: pd.DataFrame, mode: str) -> pd.DataFrame:
    """Return ``ct`` as overall/row/column percentages (zero divisors → 0), rounded."""
    if mode == "overall":
        total = float(ct.to_numpy().sum())
        result = ct / total * 100.0 if total else ct * 0.0
    elif mode == "row":
        row_sums = ct.sum(axis=1).replace(0, pd.NA)
        result = ct.div(row_sums, axis=0) * 100.0
    elif mode == "column":
        col_sums = ct.sum(axis=0).replace(0, pd.NA)
        result = ct.div(col_sums, axis=1) * 100.0
    else:
        return ct
    return result.fillna(0.0).round(3)


def _categorical_crosstab_data(
    df: pd.DataFrame,
    col1: str,
    col2: str,
    *,
    max_categories: int = MAX_CROSSTAB_CATEGORIES,
    normalize: str | None = None,
) -> dict[str, Any]:
    """Return a capped categorical-vs-categorical crosstab.

    ``normalize`` (``overall``/``row``/``column``) returns percentage cells;
    ``None``/unknown keeps raw counts (the default, unchanged behavior).
    """
    if col1 not in df.columns or col2 not in df.columns:
        return _builder_result("invalid_column", pd.DataFrame(), x=col1, y=col2)
    if pd.api.types.is_numeric_dtype(df[col1]) or pd.api.types.is_numeric_dtype(df[col2]):
        return _builder_result("invalid_type", pd.DataFrame(), x=col1, y=col2)
    pair = df[[col1, col2]].dropna()
    if pair.empty:
        return _builder_result("no_data", pd.DataFrame(), x=col1, y=col2)
    safe_max = _clamp_int(max_categories, 1, MAX_CROSSTAB_CATEGORIES)
    levels1 = pair[col1].value_counts().head(safe_max).index
    levels2 = pair[col2].value_counts().head(safe_max).index
    capped = pair[pair[col1].isin(levels1) & pair[col2].isin(levels2)]
    ct = pd.crosstab(capped[col1], capped[col2])
    if ct.empty:
        return _builder_result("no_data", pd.DataFrame(), x=col1, y=col2)
    safe_normalize = normalize if normalize in _CROSSTAB_NORMALIZE_MODES else None
    data = _normalize_crosstab(ct, safe_normalize) if safe_normalize else ct
    cells = int(ct.shape[0] * ct.shape[1])
    return _builder_result(
        "ok",
        data,
        x=col1,
        y=col2,
        normalize=safe_normalize or "none",
        x_categories_total=int(pair[col1].nunique(dropna=True)),
        y_categories_total=int(pair[col2].nunique(dropna=True)),
        x_categories_displayed=int(ct.shape[0]),
        y_categories_displayed=int(ct.shape[1]),
        cells=cells,
        truncated=bool(
            pair[col1].nunique(dropna=True) > safe_max
            or pair[col2].nunique(dropna=True) > safe_max
            or cells > MAX_PAIRWISE_CELLS
        ),
    )


def _categorical_crosstab_heatmap_data(
    df: pd.DataFrame,
    col1: str,
    col2: str,
    *,
    max_categories: int = MAX_CROSSTAB_CATEGORIES,
    normalize: str | None = None,
) -> dict[str, Any]:
    """Return long-form heatmap data for a categorical crosstab.

    Columns: ``feature_x``, ``feature_y``, ``value``, ``count``. ``value`` equals
    the raw count in raw mode, or the overall/row/column percentage when
    ``normalize`` is set. Respects the crosstab category caps and mirrors the base
    builder's status on insufficient data.
    """
    columns = ["feature_x", "feature_y", "value", "count"]
    base = _categorical_crosstab_data(df, col1, col2, max_categories=max_categories)
    if base["status"] != "ok":
        return _builder_result(base["status"], _empty_frame(columns), x=col1, y=col2)
    counts = cast(pd.DataFrame, base["data"])
    safe_normalize = normalize if normalize in _CROSSTAB_NORMALIZE_MODES else None
    values = _normalize_crosstab(counts, safe_normalize) if safe_normalize else counts
    records: list[dict[str, Any]] = []
    for x_value in counts.index:
        for y_value in counts.columns:
            records.append(
                {
                    "feature_x": str(x_value),
                    "feature_y": str(y_value),
                    "value": round(float(values.loc[x_value, y_value]), 3),
                    "count": int(counts.loc[x_value, y_value]),
                }
            )
    data = pd.DataFrame.from_records(records, columns=columns)
    return _builder_result(
        "ok", data, x=col1, y=col2, normalize=safe_normalize or "none", cells=int(len(data))
    )


# --- Visual discovery builders (P2) ------------------------------------------
#
# Every builder below is framework-free and deterministic: it reads only the
# DataFrame it is given, never mutates it, never touches Streamlit, session
# state, the filesystem or the network, and returns a structured status instead
# of raising. All of them are descriptive/exploratory — none performs a
# hypothesis test, reports a p-value, or claims statistical significance.


def _deterministic_row_positions(row_count: int, max_rows: int) -> np.ndarray:
    """Return bounded, evenly-spaced row positions (no random sampling).

    Positions are integer offsets into row order, not DataFrame index labels,
    so callers never surface a source index. Returns every position when the
    frame already fits inside ``max_rows``.
    """
    count = max(0, int(row_count))
    safe_max = max(1, int(max_rows))
    if count <= safe_max:
        return np.arange(count)
    spread = np.linspace(0, count - 1, safe_max).round().astype(int)
    return cast(np.ndarray, np.unique(spread))


def _robust_location_scale(values: np.ndarray) -> tuple[float, float] | None:
    """Return a ``(location, scale)`` pair for a normal reference line.

    Prefers the robust median / (IQR / 1.349) pair so a few extreme values do
    not tilt the reference; falls back to the sample mean/standard deviation
    when the IQR is degenerate. Returns None when no positive scale exists.
    """
    if values.size < 2:
        return None
    location = float(np.median(values))
    q1, q3 = (float(v) for v in np.quantile(values, [0.25, 0.75]))
    scale = (q3 - q1) / 1.349
    if not math.isfinite(scale) or scale <= 0:
        scale = float(np.std(values, ddof=1)) if values.size > 1 else 0.0
    if not (math.isfinite(location) and math.isfinite(scale)) or scale <= 0:
        return None
    return location, scale


def _qq_normal_data(
    series: pd.Series,
    *,
    max_points: int = QQ_MAX_POINTS,
    min_observations: int = QQ_MIN_OBSERVATIONS,
) -> dict[str, Any]:
    """Return normal Q-Q plotting data for one numeric-like Series.

    A *visual* distribution diagnostic only: it compares ordered observed
    values against theoretical standard-normal quantiles (Blom plotting
    positions) computed with the standard library's :class:`NormalDist`, so no
    SciPy dependency is introduced. It never computes or returns a normality
    test statistic or p-value — formal testing stays in Statistics Lab.

    Values are coerced safely; missing and non-finite values are dropped. Long
    inputs are downsampled deterministically to ``max_points`` by evenly-spaced
    *rank* selection, and the theoretical quantiles keep the original ranks so
    the plotted points stay faithful to the full sample. Never mutates the
    input; never raises.
    """
    columns = ["theoretical_quantile", "observed_value"]
    try:
        coerced = pd.to_numeric(series, errors="coerce")
    except (TypeError, ValueError):
        return _builder_result("invalid_type", _empty_frame(columns))
    if not pd.api.types.is_numeric_dtype(series) and int(coerced.notna().sum()) == 0:
        return _builder_result("invalid_type", _empty_frame(columns))
    finite = coerced.replace([np.inf, -np.inf], np.nan).dropna()
    usable = int(len(finite))
    if usable < max(2, int(min_observations)):
        return _builder_result(
            "insufficient_data", _empty_frame(columns), observations=usable, sampled=False
        )
    ordered = np.sort(finite.to_numpy(dtype=float))
    moments = _robust_location_scale(ordered)
    if moments is None:
        return _builder_result(
            "insufficient_variation", _empty_frame(columns), observations=usable, sampled=False
        )
    location, scale = moments
    positions = _deterministic_row_positions(usable, max_points)
    plotting = (positions + 1.0 - 0.375) / (usable + 0.25)
    normal = NormalDist()
    theoretical = np.array([normal.inv_cdf(float(p)) for p in plotting], dtype=float)
    observed = ordered[positions]
    data = pd.DataFrame(
        {
            "theoretical_quantile": np.round(theoretical, 6),
            "observed_value": np.round(observed, 6),
        }
    )
    reference = pd.DataFrame(
        {
            "theoretical_quantile": [
                round(float(theoretical[0]), 6),
                round(float(theoretical[-1]), 6),
            ],
            "observed_value": [
                round(location + scale * float(theoretical[0]), 6),
                round(location + scale * float(theoretical[-1]), 6),
            ],
        }
    )
    return _builder_result(
        "ok",
        data,
        observations=usable,
        source_observations=int(len(series)),
        points=int(len(data)),
        sampled=bool(len(data) < usable),
        location=round(location, 6),
        scale=round(scale, 6),
        reference=reference,
    )


def _pareto_category_data(
    df: pd.DataFrame,
    col: str,
    *,
    max_categories: int = PARETO_MAX_CATEGORIES,
    include_missing: bool = False,
    min_category_count: int = PARETO_MIN_CATEGORY_COUNT,
    missing_label: str = _MISSING_CATEGORY_LABEL,
    other_label: str = _OTHER_CATEGORY_LABEL,
) -> dict[str, Any]:
    """Return bounded Pareto (count + cumulative share) data for one column.

    Ordering is deterministic: count descending with a stable string tie-break.
    Categories rarer than ``min_category_count`` are aggregated into the
    explicit ``other_label`` bucket (small-cell suppression) together with the
    tail beyond ``max_categories``, so uncommon values are never displayed on
    their own. Identifier-like / near-unique columns are refused rather than
    charted. Never mutates the input; never raises.
    """
    columns = ["category", "count", "pct", "cumulative_pct"]
    if col not in df.columns:
        return _builder_result("invalid_column", _empty_frame(columns), column=col)
    series = df[col]
    if isinstance(series, pd.DataFrame) or pd.api.types.is_numeric_dtype(series):
        return _builder_result("invalid_type", _empty_frame(columns), column=col)
    prepared = _pareto_counts(series, include_missing=include_missing, missing_label=missing_label)
    if prepared is None:
        return _builder_result("invalid_data", _empty_frame(columns), column=col)
    counts, denominator = prepared
    if counts.empty or denominator <= 0:
        return _builder_result("no_data", _empty_frame(columns), column=col)
    total_categories = int(len(counts))
    if _is_near_unique(total_categories, denominator, max_categories):
        return _builder_result(
            "near_unique",
            _empty_frame(columns),
            column=col,
            total_categories=total_categories,
            total_count=denominator,
        )
    kept, tail = _pareto_partition(
        sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0]))),
        visible_cap=_clamp_int(max_categories, 1, PARETO_MAX_CATEGORIES),
        min_category_count=int(min_category_count),
        protected_label=missing_label if include_missing else None,
        other_label=other_label,
    )
    data = _pareto_records(kept, denominator, columns)
    return _builder_result(
        "ok",
        data,
        column=col,
        total_categories=total_categories,
        displayed_categories=int(len(data)),
        total_count=denominator,
        include_missing=include_missing,
        min_category_count=int(min_category_count),
        suppressed_categories=tail["suppressed"],
        grouped_categories=tail["grouped"],
        other_count=tail["other_count"],
        truncated=bool(tail["other_count"] > 0),
    )


def _pareto_counts(
    series: pd.Series, *, include_missing: bool, missing_label: str
) -> tuple[pd.Series, int] | None:
    """Return ``(value_counts, denominator)`` for a Pareto view, or None if unusable."""
    working = series.astype("object")
    if include_missing:
        working = working.where(~working.isna(), missing_label)
    try:
        counts = working.value_counts(dropna=not include_missing)
    except TypeError:
        return None
    return counts, int(series.size if include_missing else series.notna().sum())


def _is_near_unique(total_categories: int, denominator: int, max_categories: int) -> bool:
    """Return True for identifier-like columns a concentration view must refuse."""
    if denominator <= 0 or total_categories <= max(1, int(max_categories)):
        return False
    return total_categories / denominator >= NEAR_UNIQUE_RATIO


def _pareto_partition(
    ordered: list[tuple[Any, Any]],
    *,
    visible_cap: int,
    min_category_count: int,
    protected_label: str | None,
    other_label: str,
) -> tuple[list[tuple[Any, int]], dict[str, int]]:
    """Split ordered categories into displayed rows plus one aggregated tail row.

    Returns ``(kept, tail)`` where ``kept`` already carries the appended
    ``other_label`` bucket when anything was folded away, and ``tail`` counts
    how many categories were suppressed (below the small-cell floor) versus
    grouped (beyond the visible cap). ``protected_label`` — the explicit
    missing bucket — is never suppressed: it describes absence, not a value.
    """
    kept: list[tuple[Any, int]] = []
    tail = {"other_count": 0, "suppressed": 0, "grouped": 0}
    for label, raw_count in ordered:
        count = int(raw_count)
        protected = protected_label is not None and label == protected_label
        if not protected and count < max(0, min_category_count):
            tail["other_count"] += count
            tail["suppressed"] += 1
        elif len(kept) >= visible_cap:
            tail["other_count"] += count
            tail["grouped"] += 1
        else:
            kept.append((label, count))
    if tail["other_count"] > 0:
        kept.append((other_label, tail["other_count"]))
    return kept, tail


def _pareto_records(
    kept: list[tuple[Any, int]], denominator: int, columns: list[str]
) -> pd.DataFrame:
    """Return the Pareto frame: count, share, and running cumulative share."""
    records = []
    running = 0
    for label, count in kept:
        running += count
        records.append(
            {
                "category": str(label),
                "count": int(count),
                "pct": round(count / denominator * 100.0, 4),
                "cumulative_pct": round(running / denominator * 100.0, 4),
            }
        )
    return pd.DataFrame.from_records(records, columns=columns)


def _missing_column_positions(df: pd.DataFrame, *, require_variation: bool) -> list[int]:
    """Return positions of columns holding missing values, ranked deterministically.

    Ordering is missing share descending, then column name ascending, so the
    selection is stable across runs. ``require_variation`` additionally drops
    columns that are entirely missing (their missingness indicator is constant
    and carries no pairwise signal).
    """
    row_count = int(len(df))
    scored: list[tuple[float, str, int]] = []
    for position in range(df.shape[1]):
        column = df.iloc[:, position]
        missing = int(column.isna().sum())
        if missing == 0:
            continue
        if require_variation and missing == row_count:
            continue
        share = missing / row_count if row_count else 0.0
        scored.append((-share, str(df.columns[position]), position))
    scored.sort()
    return [position for _share, _name, position in scored]


def _missingness_pattern_data(
    df: pd.DataFrame,
    *,
    max_rows: int = MISSINGNESS_PATTERN_MAX_ROWS,
    max_columns: int = MISSINGNESS_PATTERN_MAX_COLUMNS,
) -> dict[str, Any]:
    """Return an anonymous present/missing pattern matrix in long form.

    Only columns that actually contain missing values are included, ranked by
    missing share then column name. Rows are selected by deterministic,
    evenly-spaced *position* and re-labelled ``0..n-1``: no source index label,
    identifier, or cell value ever reaches the output — the matrix carries the
    present/missing state and nothing else. Never mutates; never raises.
    """
    columns = ["row_position", "column", "missing"]
    row_count = int(len(df))
    positions = _missing_column_positions(df, require_variation=False)
    if not positions or row_count == 0:
        return _builder_result(
            "no_missing_values",
            _empty_frame(columns),
            columns_with_missing=len(positions),
            source_rows=row_count,
        )
    safe_columns = max(1, int(max_columns))
    selected = positions[:safe_columns]
    rows = _deterministic_row_positions(row_count, max_rows)
    records: list[dict[str, Any]] = []
    for position in selected:
        name = str(df.columns[position])
        flags = df.iloc[:, position].isna().to_numpy()[rows]
        for anonymous, flag in enumerate(flags):
            records.append(
                {"row_position": int(anonymous), "column": name, "missing": int(bool(flag))}
            )
    data = pd.DataFrame.from_records(records, columns=columns)
    return _builder_result(
        "ok",
        data,
        source_rows=row_count,
        plot_rows=int(len(rows)),
        row_sampled=bool(len(rows) < row_count),
        columns_with_missing=len(positions),
        columns_displayed=len(selected),
        column_truncated=bool(len(positions) > len(selected)),
    )


def _missingness_association_data(
    df: pd.DataFrame,
    *,
    max_rows: int = MISSINGNESS_ASSOC_MAX_ROWS,
    max_columns: int = MISSINGNESS_ASSOC_MAX_COLUMNS,
    top_n: int = TOP_RELATIONSHIP_PAIRS,
) -> dict[str, Any]:
    """Return signed pairwise association between column *missingness* indicators.

    Each selected column becomes a binary missing indicator; the matrix is the
    Pearson correlation of those indicators (the phi coefficient for two binary
    variables), so values stay in ``[-1, 1]`` and the matrix is symmetric.
    Columns whose missingness does not vary are dropped because their
    association is undefined. This describes columns that go missing together;
    it does not identify an MCAR/MAR/MNAR mechanism. Never mutates; never raises.
    """
    columns = ["x", "y", "association"]
    row_count = int(len(df))
    positions = _missing_column_positions(df, require_variation=True)
    if len(positions) < 2 or row_count == 0:
        return _builder_result(
            "insufficient_columns",
            _empty_frame(columns),
            columns_available=len(positions),
            source_rows=row_count,
        )
    selected = positions[: max(0, int(max_columns))]
    rows = _deterministic_row_positions(row_count, max_rows)
    indicators = pd.DataFrame(
        {
            str(df.columns[position]): df.iloc[:, position].isna().to_numpy()[rows].astype(float)
            for position in selected
        }
    )
    varying = [name for name in indicators.columns if float(indicators[name].std(ddof=0)) > 0.0]
    if len(varying) < 2:
        return _builder_result(
            "insufficient_variation",
            _empty_frame(columns),
            columns_available=len(varying),
            source_rows=row_count,
        )
    matrix = indicators.loc[:, varying].corr(method="pearson").round(6)
    long = _long_pair_frame(matrix, value_name="association")
    return _builder_result(
        "ok",
        long,
        matrix=matrix,
        pairs=_ranked_matrix_pairs(matrix, value_name="association", top_n=top_n),
        columns_available=len(positions),
        columns_displayed=len(varying),
        column_truncated=bool(len(positions) > len(selected)),
        source_rows=row_count,
        rows_used=int(len(rows)),
        row_sampled=bool(len(rows) < row_count),
    )


def _categorical_association_candidates(
    df: pd.DataFrame,
    selected_columns: Sequence[str] | None = None,
    *,
    max_columns: int = CATEGORICAL_ASSOC_MAX_COLUMNS,
    max_levels: int = CATEGORICAL_ASSOC_MAX_LEVELS,
) -> tuple[list[int], list[dict[str, str]]]:
    """Return usable categorical column positions plus structured refusals.

    A column is refused when it holds no non-missing values (``empty``), has a
    single level (``constant``), or is identifier-like (``near_unique``). The
    refusal list is returned so the UI can explain every excluded column
    instead of silently dropping it.
    """
    requested = {str(name) for name in selected_columns} if selected_columns else None
    usable: list[int] = []
    refused: list[dict[str, str]] = []
    for position in range(df.shape[1]):
        name = str(df.columns[position])
        if requested is not None and name not in requested:
            continue
        column = df.iloc[:, position]
        if isinstance(column, pd.DataFrame) or pd.api.types.is_numeric_dtype(column):
            continue
        reason = _categorical_column_refusal(column, max_levels=max_levels)
        if reason is not None:
            refused.append({"column": name, "reason": reason})
            continue
        usable.append(position)
    limit = max(0, int(max_columns))
    for position in usable[limit:]:
        refused.append({"column": str(df.columns[position]), "reason": "column_cap"})
    return usable[:limit], refused


def _categorical_column_refusal(column: pd.Series, *, max_levels: int) -> str | None:
    """Return a structured refusal reason for an unusable categorical column."""
    non_null = int(column.notna().sum())
    if non_null == 0:
        return "empty"
    levels = int(column.nunique(dropna=True))
    if levels < 2:
        return "constant"
    if levels > max(1, int(max_levels)) and levels / non_null >= NEAR_UNIQUE_RATIO:
        return "near_unique"
    return None


def _capped_levels(column: pd.Series, *, max_levels: int, missing_label: str) -> pd.Series:
    """Return a level-capped copy of a categorical column (deterministic tail).

    Missing values become an explicit bucket and every level beyond the top
    ``max_levels`` (count descending, stable string tie-break) is folded into
    ``(other)``, bounding each contingency table to ``max_levels**2`` cells.
    """
    working = column.astype("object").where(~column.isna(), missing_label).astype("string")
    counts = working.value_counts(dropna=False)
    ordered = sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))
    keep = {str(label) for label, _count in ordered[: max(1, int(max_levels))]}
    # Positional index so pairwise crosstabs align by row order, never by a
    # (possibly duplicated) source index label.
    return working.where(working.isin(keep), _OTHER_CATEGORY_LABEL).reset_index(drop=True)


def _cramers_v(left: pd.Series, right: pd.Series) -> float | None:
    """Return the bias-corrected Cramér's V for two capped categorical Series.

    Dependency-free (no SciPy): the chi-square statistic is computed directly
    from the contingency table and used *only* to derive an effect-strength
    value in ``[0, 1]``. No p-value, critical value, or significance decision is
    produced or implied. Returns None when the table carries no usable signal.
    """
    table = pd.crosstab(left, right)
    observed = table.to_numpy(dtype=float)
    total = float(observed.sum())
    if total <= 1 or observed.shape[0] < 2 or observed.shape[1] < 2:
        return None
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0)) / total
    with np.errstate(divide="ignore", invalid="ignore"):
        terms = np.where(expected > 0, (observed - expected) ** 2 / expected, 0.0)
    phi2 = float(terms.sum()) / total
    rows, cols = observed.shape
    phi2_corrected = max(0.0, phi2 - (cols - 1) * (rows - 1) / (total - 1))
    rows_corrected = rows - ((rows - 1) ** 2) / (total - 1)
    cols_corrected = cols - ((cols - 1) ** 2) / (total - 1)
    denominator = min(cols_corrected - 1, rows_corrected - 1)
    if denominator <= 0:
        return None
    value = math.sqrt(phi2_corrected / denominator)
    if not math.isfinite(value):
        return None
    return float(min(1.0, max(0.0, value)))


def _categorical_association_data(
    df: pd.DataFrame,
    selected_columns: Sequence[str] | None = None,
    *,
    max_columns: int = CATEGORICAL_ASSOC_MAX_COLUMNS,
    max_levels: int = CATEGORICAL_ASSOC_MAX_LEVELS,
    max_rows: int = CATEGORICAL_ASSOC_MAX_ROWS,
    top_n: int = TOP_RELATIONSHIP_PAIRS,
) -> dict[str, Any]:
    """Return a bounded categorical association matrix (corrected Cramér's V).

    Values are effect strengths in ``[0, 1]``: 0 means the categories vary
    independently in the analyzed rows, 1 means they move together completely.
    This is exploratory description, not a test — there is no p-value and no
    significance claim, and association never establishes causation.

    Bounded on every axis: at most ``max_columns`` columns, ``max_levels``
    levels per column (tail folded into ``(other)``) and ``max_rows``
    deterministically positioned rows. Never mutates the input; never raises.
    """
    columns = ["x", "y", "association"]
    row_count = int(len(df))
    positions, refused = _categorical_association_candidates(
        df, selected_columns, max_columns=max_columns, max_levels=max_levels
    )
    if len(positions) < 2 or row_count == 0:
        return _builder_result(
            "insufficient_columns",
            _empty_frame(columns),
            columns_displayed=len(positions),
            unavailable=refused,
            source_rows=row_count,
        )
    rows = _deterministic_row_positions(row_count, max_rows)
    capped = {
        str(df.columns[position]): _capped_levels(
            df.iloc[:, position].iloc[rows],
            max_levels=max_levels,
            missing_label=_MISSING_CATEGORY_LABEL,
        )
        for position in positions
    }
    names = list(capped)
    matrix = pd.DataFrame(np.eye(len(names)), index=names, columns=names)
    for left in range(len(names)):
        for right in range(left + 1, len(names)):
            value = _cramers_v(capped[names[left]], capped[names[right]])
            matrix.iat[left, right] = np.nan if value is None else round(value, 6)
            matrix.iat[right, left] = matrix.iat[left, right]
    return _builder_result(
        "ok",
        _long_pair_frame(matrix, value_name="association"),
        matrix=matrix,
        pairs=_ranked_matrix_pairs(matrix, value_name="association", top_n=top_n),
        columns_displayed=len(names),
        max_levels=int(max_levels),
        unavailable=refused,
        source_rows=row_count,
        rows_used=int(len(rows)),
        row_sampled=bool(len(rows) < row_count),
    )


def _numeric_distribution(df: pd.DataFrame, col: str, bins: int = 10) -> pd.DataFrame | None:
    """Return a histogram-like count DataFrame for st.bar_chart. None if not applicable."""
    result = _numeric_histogram_data(df, col, bins=bins)
    if result["status"] != "ok":
        return None
    data = cast(pd.DataFrame, result["data"])
    return data.set_index("bin")[["count"]]


def _categorical_top_values(df: pd.DataFrame, col: str, n: int = 20) -> pd.DataFrame | None:
    """Return top-N value counts DataFrame for st.bar_chart/st.dataframe. None if not applicable."""
    result = _categorical_top_frequency_data(df, col, n=n)
    if result["status"] != "ok":
        return None
    data = cast(pd.DataFrame, result["data"])
    return data.set_index("category")[["count"]]


def _bivariate_numeric_numeric(
    df: pd.DataFrame, col1: str, col2: str
) -> tuple[pd.DataFrame | None, float | None]:
    """Return (scatter DataFrame, Pearson r) for two numeric columns. None pair if not applicable."""
    result = _bounded_scatter_data(df, col1, col2)
    if result["status"] != "ok":
        return None, None
    return cast(pd.DataFrame, result["data"]), cast(float | None, result.get("pearson_r"))


def _bivariate_numeric_categorical(
    df: pd.DataFrame, numeric_col: str, categorical_col: str
) -> pd.DataFrame | None:
    """Return grouped stats (count/mean/median) of numeric_col by categorical_col. None if not applicable."""
    result = _numeric_by_category_summary_data(df, numeric_col, categorical_col)
    if result["status"] != "ok":
        return None
    data = cast(pd.DataFrame, result["data"])
    grouped = data.set_index("category")[["count", "mean", "median"]]
    return grouped if not grouped.empty else None


def _bivariate_categorical_categorical(
    df: pd.DataFrame, col1: str, col2: str
) -> pd.DataFrame | None:
    """Return a crosstab frequency table for two categorical columns. None if not applicable."""
    result = _categorical_crosstab_data(df, col1, col2)
    if result["status"] != "ok":
        return None
    ct = cast(pd.DataFrame, result["data"])
    return ct if not ct.empty else None
