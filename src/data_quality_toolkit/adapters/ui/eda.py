"""Pure UI-layer helper and compute functions for the Data Quality Toolkit dashboard."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pandas as pd

from data_quality_toolkit.application.workflow.preprocessing import (  # noqa: F401
    iqr_outlier_summary as _iqr_outlier_summary,
)
from data_quality_toolkit.application.workflow.preprocessing import (  # noqa: F401
    plan_preprocessing as _plan_preprocessing,
)
from data_quality_toolkit.shared.constants import DEFAULT_HIGH_CARDINALITY_THRESHOLD

MAX_SUMMARY_COLUMNS = 100
MAX_CORRELATION_COLUMNS = 20
MAX_OUTLIER_COLUMNS = 50
MAX_HISTOGRAM_BINS = 50


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


def _load_df_and_assess(
    path_str: str,
) -> tuple[pd.DataFrame | None, dict[str, Any] | None, str | None]:
    """Single-read path for _render_data_overview.

    Loads the CSV once via the hardened csv_loader (max_rows guard, sha1 dataset_id,
    SAMPLE_SIZE env support), then runs profiling and assessment over the in-memory
    DataFrame.  Returns (df, result_dict, None) on success or (None, None, error_msg)
    on failure.
    """
    from data_quality_toolkit.adapters.loaders.file.csv_loader import load_csv as _load_csv_h
    from data_quality_toolkit.domain.assessment.quality_checker import assess as _assess
    from data_quality_toolkit.domain.profiling.profiling_orchestrator import (
        run_profiling as _run_prof,
    )

    path = path_str.strip()
    try:
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


def _correlation_matrix(
    df: pd.DataFrame, max_columns: int = MAX_CORRELATION_COLUMNS
) -> pd.DataFrame | None:
    """Return a bounded Pearson correlation matrix for numeric columns."""
    numeric = df.select_dtypes(include="number")
    numeric = numeric.iloc[:, : max(0, max_columns)]
    if numeric.shape[1] < 2:
        return None
    finite = numeric.mask(numeric.isin([float("inf"), float("-inf")]))
    return finite.corr(min_periods=2).round(3)


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


def _numeric_distribution(df: pd.DataFrame, col: str, bins: int = 10) -> pd.DataFrame | None:
    """Return a histogram-like count DataFrame for st.bar_chart. None if not applicable."""
    series = df[col].dropna()
    if not pd.api.types.is_numeric_dtype(series):
        return None
    series = series[~series.isin([float("inf"), float("-inf")])]
    if len(series) < 2 or series.nunique() < 2:
        return None
    bins = min(max(int(bins), 2), MAX_HISTOGRAM_BINS)
    try:
        counts = pd.cut(series, bins=bins, duplicates="drop").value_counts().sort_index()
    except (OverflowError, ValueError, TypeError):
        return None
    if counts.empty:
        return None
    return pd.DataFrame({"count": counts.values}, index=counts.index.astype(str))


def _categorical_top_values(df: pd.DataFrame, col: str, n: int = 20) -> pd.DataFrame | None:
    """Return top-N value counts DataFrame for st.bar_chart/st.dataframe. None if not applicable."""
    series = df[col]
    if pd.api.types.is_numeric_dtype(series) or n <= 0:
        return None
    try:
        counts = series.value_counts().head(n)
    except TypeError:
        return None
    if counts.empty:
        return None
    return counts.to_frame("count")


def _bivariate_numeric_numeric(
    df: pd.DataFrame, col1: str, col2: str
) -> tuple[pd.DataFrame | None, float | None]:
    """Return (scatter DataFrame, Pearson r) for two numeric columns. None pair if not applicable."""
    if not pd.api.types.is_numeric_dtype(df[col1]) or not pd.api.types.is_numeric_dtype(df[col2]):
        return None, None
    pair = df[[col1, col2]].dropna()
    if len(pair) < 2 or pair[col1].nunique() < 2 or pair[col2].nunique() < 2:
        return None, None
    try:
        r_val = pair.corr().iloc[0, 1]
        r = None if pd.isna(r_val) else float(r_val)
    except (ValueError, TypeError):
        r = None
    return pair, r


def _bivariate_numeric_categorical(
    df: pd.DataFrame, numeric_col: str, categorical_col: str
) -> pd.DataFrame | None:
    """Return grouped stats (count/mean/median) of numeric_col by categorical_col. None if not applicable."""
    if not pd.api.types.is_numeric_dtype(df[numeric_col]):
        return None
    if pd.api.types.is_numeric_dtype(df[categorical_col]):
        return None
    grouped = df.groupby(categorical_col)[numeric_col].agg(["count", "mean", "median"])
    return grouped if not grouped.empty else None


def _bivariate_categorical_categorical(
    df: pd.DataFrame, col1: str, col2: str
) -> pd.DataFrame | None:
    """Return a crosstab frequency table for two categorical columns. None if not applicable."""
    if pd.api.types.is_numeric_dtype(df[col1]) or pd.api.types.is_numeric_dtype(df[col2]):
        return None
    ct = pd.crosstab(df[col1], df[col2])
    return ct if not ct.empty else None
