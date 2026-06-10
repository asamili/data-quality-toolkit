"""EDA Explorer page: univariate/bivariate exploration and preprocessing recommendations.

Split out of the Data Overview tab during the G1 UI restructure — render
functions are moved verbatim; the page-level CSV input reuses the same
hardened ``_load_df_and_assess`` path as Data Overview.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.components.downloads import csv_download_button
from data_quality_toolkit.adapters.ui.components.errors import show_error
from data_quality_toolkit.adapters.ui.eda import (
    _bivariate_categorical_categorical,
    _bivariate_numeric_categorical,
    _bivariate_numeric_numeric,
    _categorical_top_values,
    _iqr_outlier_summary,
    _load_df_and_assess,
    _numeric_distribution,
    _plan_preprocessing,
)
from data_quality_toolkit.adapters.ui.state.keys import BIV_COL1, BIV_COL2


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
    col1 = st.selectbox("First column", cols, key=BIV_COL1)
    col2 = st.selectbox("Second column", cols, key=BIV_COL2)
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
    plan_df = pd.DataFrame(plan)
    st.dataframe(plan_df)
    csv_download_button(
        st,
        "Download recommendations as CSV",
        plan_df,
        "preprocessing_recommendations.csv",
    )


def _render_eda_explorer(st: Any) -> None:
    """Render the EDA Explorer page: CSV input, then univariate/bivariate/preprocessing."""
    st.header("EDA Explorer")
    st.caption("Explore column distributions, relationships, and preprocessing recommendations.")
    eda_csv = st.text_input("CSV path", placeholder="e.g., ./data/my_dataset.csv")
    if not eda_csv:
        st.info("💡 Enter a CSV path above to start exploring.")
        return

    df, _, err = _load_df_and_assess(eda_csv)
    if err is not None:
        show_error(st, "Load Error", err)
        return
    if df is None:
        return

    _render_eda_univariate(st, df)
    _render_eda_bivariate(st, df)
    _render_preprocessing_plan(st, df)


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_eda_explorer(st)
