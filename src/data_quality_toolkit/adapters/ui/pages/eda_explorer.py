"""EDA Explorer page: univariate/bivariate exploration and preprocessing recommendations.

Split out of the Data Overview tab during the G1 UI restructure — render
functions are moved verbatim; the page-level CSV input reuses the same
hardened ``_load_df_and_assess`` path as Data Overview.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.components.dataset_context import (
    render_dataset_context_panel,
)
from data_quality_toolkit.adapters.ui.components.downloads import csv_download_button
from data_quality_toolkit.adapters.ui.components.errors import show_error
from data_quality_toolkit.adapters.ui.components.page_shell import render_page_header
from data_quality_toolkit.adapters.ui.components.states import render_warning_state
from data_quality_toolkit.adapters.ui.components.storylens import render_storylens_card
from data_quality_toolkit.adapters.ui.eda import (
    MAX_CORRELATION_COLUMNS,
    MAX_OUTLIER_COLUMNS,
    MAX_SUMMARY_COLUMNS,
    _aggregate_iqr_outlier_summary,
    _bivariate_categorical_categorical,
    _bivariate_numeric_categorical,
    _bivariate_numeric_numeric,
    _categorical_top_values,
    _correlation_matrix,
    _dataset_profile,
    _dtype_distribution,
    _duplicate_row_summary,
    _iqr_outlier_summary,
    _load_df_and_assess,
    _missingness_summary,
    _numeric_distribution,
    _plan_preprocessing,
)
from data_quality_toolkit.adapters.ui.state.context import get_dataset_context
from data_quality_toolkit.adapters.ui.state.keys import BIV_COL1, BIV_COL2
from data_quality_toolkit.application.explanation import (
    Explanation,
    explain_missing_value_issue,
    explain_quality_score,
)


def _eda_storylens(
    result: dict[str, Any] | None, profile: Mapping[str, Any] | None
) -> list[Explanation]:
    """Build bounded deterministic StoryLens cards from EDA assessment facts.

    Returns at most 2 cards (quality score + first missing-value issue).
    Returns [] on any unexpected error — never raises, never fabricates.
    """
    try:
        assessment = (result or {}).get("assessment") or {}
        score_raw = assessment.get("score")
        if score_raw is None or profile is None:
            return []
        score = float(score_raw)
        rows = int(profile["rows"])
        cols = int(profile["cols"])
        issues: list[dict[str, Any]] = list(assessment.get("issues") or [])
        cards: list[Explanation] = [
            explain_quality_score(
                score=score,
                rows=rows,
                columns=cols,
                issues_total=len(issues),
            )
        ]
        for issue in issues:
            if issue.get("type") == "missing":
                column = issue.get("column")
                pct = issue.get("pct")
                if column and isinstance(pct, int | float) and not isinstance(pct, bool):
                    cards.append(
                        explain_missing_value_issue(
                            column=str(column),
                            null_pct=float(pct),
                            severity_label=str(issue.get("severity", "medium")),
                        )
                    )
                    break
        return cards
    except Exception:
        return []


def _render_dataset_profile(
    st: Any, df: pd.DataFrame, profile: Mapping[str, Any] | None = None
) -> None:
    st.subheader("Dataset profile")
    facts = _dataset_profile(df, profile)
    cards = st.columns(4)
    cards[0].metric("Rows", f"{facts['rows']:,}")
    cards[1].metric("Columns", f"{facts['columns']:,}")
    cards[2].metric("Missing cells", f"{facts['missing_cells']:,}")
    cards[3].metric("Memory", f"{facts['memory_mb']:.2f} MB")


def _render_missingness(st: Any, df: pd.DataFrame) -> None:
    st.subheader("Missingness")
    summary = _missingness_summary(df)
    if summary.empty:
        st.info("No columns to summarize.")
        return
    st.dataframe(summary, hide_index=True)
    if df.shape[1] > MAX_SUMMARY_COLUMNS:
        st.caption(f"Showing the first {MAX_SUMMARY_COLUMNS} columns to keep the view responsive.")


def _render_duplicate_rows(st: Any, df: pd.DataFrame) -> None:
    st.subheader("Duplicate rows")
    summary = _duplicate_row_summary(df)
    cards = st.columns(3)
    cards[0].metric("Duplicate rows", f"{summary['duplicate_rows']:,}")
    cards[1].metric("Duplicate rate", f"{summary['duplicate_pct']:.2f}%")
    cards[2].metric("Unique rows", f"{summary['unique_rows']:,}")
    st.caption("Counts fully duplicated rows; source records are not displayed.")


def _render_dtype_distribution(st: Any, df: pd.DataFrame) -> None:
    st.subheader("Data types")
    summary = _dtype_distribution(df)
    if summary.empty:
        st.info("No data types to summarize.")
        return
    st.dataframe(summary, hide_index=True)
    st.bar_chart(summary.set_index("dtype")[["column_count"]])


def _render_eda_univariate(st: Any, df: pd.DataFrame) -> None:
    """Render bounded numeric distributions and categorical top values."""
    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    categorical_columns = [column for column in df.columns if column not in numeric_columns]

    st.subheader("Numeric distributions")
    if numeric_columns:
        col_name = st.selectbox("Select numeric column", numeric_columns)
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
        st.info("No numeric columns to explore.")

    st.subheader("Categorical top values")
    if categorical_columns:
        col_name = st.selectbox("Select categorical column", categorical_columns)
        if col_name is None:
            return
        top = _categorical_top_values(df, col_name)
        if top is not None:
            st.caption("Top values (up to 20)")
            st.dataframe(top)
            st.bar_chart(top)
        else:
            st.info("No usable values for this column.")
    else:
        st.info("No categorical columns to explore.")


def _render_correlation_matrix(st: Any, df: pd.DataFrame) -> None:
    st.subheader("Correlation matrix")
    matrix = _correlation_matrix(df)
    if matrix is None:
        st.info("Need at least two numeric columns for a correlation matrix.")
        return
    st.dataframe(matrix)
    numeric_count = df.select_dtypes(include="number").shape[1]
    if numeric_count > MAX_CORRELATION_COLUMNS:
        st.caption(
            f"Correlation is limited to the first {MAX_CORRELATION_COLUMNS} numeric columns."
        )


def _render_outlier_summary(st: Any, df: pd.DataFrame) -> None:
    st.subheader("Outlier summary")
    summary = _aggregate_iqr_outlier_summary(df)
    if summary.empty:
        st.info("No numeric columns to summarize.")
        return
    st.dataframe(summary, hide_index=True)
    numeric_count = df.select_dtypes(include="number").shape[1]
    if numeric_count > MAX_OUTLIER_COLUMNS:
        st.caption(
            f"Outlier summary is limited to the first {MAX_OUTLIER_COLUMNS} numeric columns."
        )


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


def _render_eda_explorer(st: Any, session_state: Mapping[str, Any] | None = None) -> None:
    """Render the EDA Explorer page: CSV input, then univariate/bivariate/preprocessing."""
    render_page_header(
        st,
        "EDA Explorer",
        "Explore column distributions, relationships, and preprocessing recommendations.",
        step_label="Step 3 of 11 — EDA Explorer",
    )
    context = get_dataset_context(session_state or {})
    if context is not None:
        render_dataset_context_panel(st, context)
        if context.large_file_mode:
            render_warning_state(
                st,
                "EDA is unavailable for the active large-file profile context. "
                "Return to Start and select full analysis mode to use EDA.",
            )
            return
        eda_csv = context.source_path
    else:
        eda_csv = st.text_input("CSV path", placeholder="e.g., ./data/my_dataset.csv")
    if not eda_csv:
        st.info("💡 Start with a dataset context or enter a CSV path above to begin exploring.")
        return

    df, result, err = _load_df_and_assess(eda_csv)
    if err is not None:
        show_error(st, "Load Error", err)
        return
    if df is None:
        return

    profile = result.get("profile") if result is not None else None
    render_storylens_card(st, _eda_storylens(result, profile))
    _render_dataset_profile(st, df, profile)
    _render_missingness(st, df)
    _render_duplicate_rows(st, df)
    _render_dtype_distribution(st, df)
    _render_eda_univariate(st, df)
    _render_correlation_matrix(st, df)
    _render_outlier_summary(st, df)
    _render_eda_bivariate(st, df)
    _render_preprocessing_plan(st, df)


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_eda_explorer(st, st.session_state)  # type: ignore[arg-type, unused-ignore]
