"""Pure UI-layer helper and compute functions for the Data Quality Toolkit dashboard."""

from __future__ import annotations

from typing import Any, cast

import pandas as pd

from data_quality_toolkit.shared.constants import DEFAULT_HIGH_CARDINALITY_THRESHOLD
from data_quality_toolkit.workflow.preprocessing import (  # noqa: F401
    iqr_outlier_summary as _iqr_outlier_summary,
)
from data_quality_toolkit.workflow.preprocessing import (  # noqa: F401
    plan_preprocessing as _plan_preprocessing,
)


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
    from data_quality_toolkit.assessment.quality_checker import assess as _assess
    from data_quality_toolkit.loaders.file.csv_loader import load_csv as _load_csv_h
    from data_quality_toolkit.profiling.profiling_orchestrator import run_profiling as _run_prof

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
    if not pd.api.types.is_numeric_dtype(series) or len(series) < 2 or series.nunique() < 2:
        return None
    try:
        counts = pd.cut(series, bins=bins, duplicates="drop").value_counts().sort_index()
    except (ValueError, TypeError):
        return None
    if counts.empty:
        return None
    return pd.DataFrame({"count": counts.values}, index=counts.index.astype(str))


def _categorical_top_values(df: pd.DataFrame, col: str, n: int = 20) -> pd.DataFrame | None:
    """Return top-N value counts DataFrame for st.bar_chart/st.dataframe. None if not applicable."""
    series = df[col]
    if pd.api.types.is_numeric_dtype(series):
        return None
    counts = series.value_counts().head(n)
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
