"""Streamlit dashboard app for Data Quality Toolkit."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from data_quality_toolkit.api import assess_csv as _assess_csv
from data_quality_toolkit.storage.connection import StorageError
from data_quality_toolkit.storage.reader import read_run_history
from data_quality_toolkit.ui.eda import (
    _bivariate_categorical_categorical,
    _bivariate_numeric_categorical,
    _bivariate_numeric_numeric,
    _build_overview_table,
    _build_trend_df,
    _categorical_top_values,
    _duplicate_row_count,
    _extract_latest_issues,
    _extract_trend_data,
    _high_cardinality_flags,
    _iqr_outlier_summary,
    _load_df_and_assess,
    _numeric_distribution,
    _numeric_summary,
    _plan_preprocessing,
)


def _load_run_history(
    db_path_str: str, dataset_id: str
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Fetch run history records. Returns (records, None) or (None, error_message)."""
    try:
        records = read_run_history(Path(db_path_str.strip()), dataset_id.strip())
        return records, None
    except StorageError as exc:
        return None, str(exc)


def _run_assess_csv(path_str: str) -> tuple[dict[str, Any] | None, str | None]:
    """Call the public assess_csv API and return (result, None) or (None, error_message).

    Mirrors the _load_run_history pattern: thin wrapper that isolates exception
    handling so the Streamlit caller can stay free of bare try/except blocks.
    Routing through api.assess_csv gives the UI the same hardened load_csv path
    (row cap, max_rows_in_memory guard) that the CLI and Python API use.
    """
    try:
        result = _assess_csv(path_str.strip())
        return result, None
    except Exception as exc:
        return None, str(exc)


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


def _render_num_num(st: Any, df: pd.DataFrame, col1: str, col2: str) -> None:
    scatter_df, r = _bivariate_numeric_numeric(df, col1, col2)
    if scatter_df is None:
        st.info("Insufficient distinct values for scatter chart.")
        return
    st.caption(f"Scatter: {col1} vs {col2}")
    st.scatter_chart(scatter_df, x=col1, y=col2)
    if r is not None:
        st.caption(f"Pearson r: {r:.3f}")


def _render_num_cat(st: Any, df: pd.DataFrame, num_col: str, cat_col: str) -> None:
    grouped = _bivariate_numeric_categorical(df, num_col, cat_col)
    if grouped is None:
        st.info("No usable data for this column pair.")
        return
    st.caption(f"{num_col} by {cat_col}")
    st.dataframe(grouped)
    st.bar_chart(grouped[["mean"]].rename(columns={"mean": num_col}))


def _render_cat_cat(st: Any, df: pd.DataFrame, col1: str, col2: str) -> None:
    ct = _bivariate_categorical_categorical(df, col1, col2)
    if ct is None:
        st.info("No usable data for this column pair.")
        return
    st.caption(f"Crosstab: {col1} vs {col2}")
    st.dataframe(ct)


def _render_eda_bivariate(st: Any, df: pd.DataFrame) -> None:
    """Render EDA Bivariate Explorer: two-column selector, type-aware relationship view."""
    st.subheader("EDA — Bivariate Explorer")
    cols = df.columns.tolist()
    if len(cols) < 2:
        st.info("Need at least two columns for bivariate analysis.")
        return
    col1 = st.selectbox("First column", cols, key="biv_col1")
    col2 = st.selectbox("Second column", cols, key="biv_col2")
    if col1 == col2:
        st.info("Select two different columns.")
        return
    n1 = pd.api.types.is_numeric_dtype(df[col1])
    n2 = pd.api.types.is_numeric_dtype(df[col2])
    if n1 and n2:
        _render_num_num(st, df, col1, col2)
    elif n1:
        _render_num_cat(st, df, col1, col2)
    elif n2:
        _render_num_cat(st, df, col2, col1)
    else:
        _render_cat_cat(st, df, col1, col2)


def _render_preprocessing_plan(st: Any, df: pd.DataFrame) -> None:
    """Render Preprocessing Recommendations table: per-column issues and suggested transformations."""
    st.subheader("Preprocessing Recommendations")
    plan = _plan_preprocessing(df)
    if not plan:
        st.info("No columns to analyse.")
        return
    st.dataframe(pd.DataFrame(plan))


def _render_data_overview(st: Any) -> None:
    """Render the Data Overview section: shape, per-column table, stats, duplicates."""
    st.header("Data Overview")
    overview_csv = st.text_input("CSV path for data overview", placeholder="path/to/data.csv")
    if not overview_csv:
        st.info("Enter a CSV path to see a data overview.")
        return

    df, out, err = _load_df_and_assess(overview_csv)
    if err is not None:
        st.error(f"CSV error: {err}")
        return
    if df is None or out is None:
        return

    profile = out["profile"]
    assessment = out["assessment"]
    score = float(assessment["score"])
    issues = list(assessment.get("issues") or [])
    st.metric("Quality Score", f"{score:.2%}")
    st.caption(f"Issues flagged: {len(issues)}")
    if issues:
        st.dataframe(pd.DataFrame(issues))

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
    _render_eda_bivariate(st, df)
    _render_preprocessing_plan(st, df)


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
