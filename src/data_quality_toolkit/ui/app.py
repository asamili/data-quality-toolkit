"""Streamlit dashboard app for Data Quality Toolkit."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from data_quality_toolkit.profiling.profiling_orchestrator import run_profiling
from data_quality_toolkit.storage.connection import StorageError
from data_quality_toolkit.storage.reader import read_run_history


def _load_run_history(
    db_path_str: str, dataset_id: str
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Fetch run history records. Returns (records, None) or (None, error_message)."""
    try:
        records = read_run_history(Path(db_path_str.strip()), dataset_id.strip())
        return records, None
    except StorageError as exc:
        return None, str(exc)


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


def _load_csv(path_str: str) -> tuple[pd.DataFrame | None, str | None]:
    """Load a CSV into a DataFrame. Returns (df, None) or (None, error_message)."""
    p = Path(path_str.strip())
    if not p.exists():
        return None, f"File not found: {p}"
    try:
        df = pd.read_csv(p)
    except (OSError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        return None, str(exc)
    return df, None


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


def _high_cardinality_flags(profile: Any, threshold: float = 0.9) -> list[str]:
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


def _iqr_outlier_summary(df: pd.DataFrame, col: str) -> dict[str, Any] | None:
    """Return IQR-based outlier stats. None if non-numeric or fewer than 4 non-null values."""
    series = df[col].dropna()
    if not pd.api.types.is_numeric_dtype(series) or len(series) < 4:
        return None
    q1 = float(series.quantile(0.25))
    q3 = float(series.quantile(0.75))
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    outliers = int(((series < lower) | (series > upper)).sum())
    return {
        "q1": q1,
        "q3": q3,
        "iqr": iqr,
        "lower_fence": lower,
        "upper_fence": upper,
        "outlier_count": outliers,
    }


def _render_eda_univariate(st: Any, df: pd.DataFrame) -> None:
    """Render EDA Univariate Explorer: column selector, distribution chart, IQR outlier hint."""
    st.subheader("EDA — Univariate Explorer")
    cols = df.columns.tolist()
    if not cols:
        st.info("No columns to explore.")
        return
    col_name = st.selectbox("Select column", cols)
    if col_name is None:
        return
    is_numeric = pd.api.types.is_numeric_dtype(df[col_name])
    if is_numeric:
        dist = _numeric_distribution(df, col_name)
        if dist is not None:
            st.caption("Distribution")
            st.bar_chart(dist)
        else:
            st.info("Insufficient distinct values for distribution chart.")
        outlier_stats = _iqr_outlier_summary(df, col_name)
        if outlier_stats is not None:
            caption = (
                f"IQR: {outlier_stats['iqr']:.2f} | "
                f"Fences: [{outlier_stats['lower_fence']:.2f}, "
                f"{outlier_stats['upper_fence']:.2f}] | "
                f"Outliers: {outlier_stats['outlier_count']}"
            )
            st.caption(caption)
    else:
        top = _categorical_top_values(df, col_name)
        if top is not None:
            st.caption("Top values (up to 20)")
            st.dataframe(top)
            st.bar_chart(top)
        else:
            st.info("No usable values for this column.")


def _render_data_overview(st: Any) -> None:
    """Render the Data Overview section: shape, per-column table, stats, duplicates."""
    st.header("Data Overview")
    overview_csv = st.text_input("CSV path for data overview", placeholder="path/to/data.csv")
    if not overview_csv:
        st.info("Enter a CSV path to see a data overview.")
        return

    df, csv_err = _load_csv(overview_csv)
    if csv_err is not None:
        st.error(f"CSV error: {csv_err}")
        return
    if df is None:
        return

    profile = run_profiling(df, "dashboard_overview")
    st.write(f"Shape: {profile['rows']} rows x {profile['cols']} columns")
    st.write(f"Memory: {profile['memory_mb']:.2f} MB")
    st.subheader("Columns")
    overview = _build_overview_table(profile)
    st.table(overview)
    null_df = pd.DataFrame(
        {"null_pct": [r["null_pct"] for r in overview]},
        index=[r["column"] for r in overview],
    )
    if null_df["null_pct"].sum() > 0:
        st.caption("Null % by column")
        st.bar_chart(null_df)
    numeric = _numeric_summary(df)
    if numeric is not None:
        st.subheader("Numeric Summary")
        st.dataframe(numeric)
    st.write(f"Duplicate rows: {_duplicate_row_count(df)}")
    flags = _high_cardinality_flags(profile)
    if flags:
        st.warning(f"High-cardinality columns: {', '.join(flags)}")
    _render_eda_univariate(st, df)


def main() -> None:
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError(
            "Streamlit is not installed. "
            "Install the UI extra when available: pip install data-quality-toolkit[ui]"
        ) from exc

    st.title("Data Quality Toolkit Dashboard")
    st.caption("Phase 4 dashboard")

    _render_data_overview(st)

    st.header("Run History")
    db_path_str = st.text_input("Database path", placeholder="path/to/dqt.db")
    dataset_id = st.text_input("Dataset ID", placeholder="my_dataset")

    if not db_path_str or not dataset_id:
        st.info("Enter a database path and dataset ID to load run history.")
        return

    records, err = _load_run_history(db_path_str, dataset_id)
    if err is not None:
        st.error(f"Storage error: {err}")
        return

    if not records:
        st.warning("No run history found for this dataset.")
        return

    trend = _extract_trend_data(records)
    if len(trend) >= 2:
        st.subheader("Score Trend")
        df = _build_trend_df(trend)
        if df is not None:
            st.line_chart(df[["Score"]])
        else:
            st.line_chart({"Score": [r["score"] for r in trend]})

    sev, cat = _extract_latest_issues(records)
    if sev or cat:
        st.subheader("Latest Run — Issues Breakdown")
        col1, col2 = st.columns(2)
        with col1:
            st.caption("By severity")
            st.table(sev)
        with col2:
            st.caption("By category")
            st.table(cat)

    st.dataframe(records)


if __name__ == "__main__":
    main()
