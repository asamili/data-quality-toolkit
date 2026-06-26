"""Statistics Lab page: descriptive statistics plus a scipy-guarded inferential tier.

Statistics Lab is the *numbers* surface — descriptive calculations, frequency
tables, correlation tables, and an inferential tier (normality, group comparison,
A/B). Visual exploration (charts, scatter, bivariate plots) lives on the EDA
Explorer page. The descriptive tier uses only pandas/numpy (core dependencies);
the inferential tier requires the optional ``[stats]`` extra (scipy) and degrades
to a clear unavailable message when scipy is not installed.
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
from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_metric_cards,
    render_page_header,
    render_section_header,
)
from data_quality_toolkit.adapters.ui.components.states import (
    render_info_state,
    render_warning_state,
)
from data_quality_toolkit.adapters.ui.eda import (
    _categorical_top_values,
    _correlation_matrix,
    _dataset_profile,
    _dtype_distribution,
    _duplicate_row_summary,
    _load_df_and_assess,
    _missingness_summary,
)
from data_quality_toolkit.adapters.ui.services.statistics import (
    ab_comparison,
    group_summary_dataframe,
    inferential_available,
    multi_group_comparison,
    normality_check,
    numeric_descriptive_stats,
    two_group_comparison,
)
from data_quality_toolkit.adapters.ui.state.context import get_dataset_context

_STATS_CAT_COLUMN = "stats_lab_categorical_column"
_STATS_NORMALITY_COLUMN = "stats_lab_normality_column"
_STATS_GROUP_METRIC = "stats_lab_group_metric"
_STATS_GROUP_COLUMN = "stats_lab_group_column"
_STATS_AB_GROUP = "stats_lab_ab_group_column"
_STATS_AB_A = "stats_lab_ab_a_value"
_STATS_AB_B = "stats_lab_ab_b_value"
_STATS_AB_METRIC = "stats_lab_ab_metric"
_STATS_ALPHA = "stats_lab_alpha"

# Bound how wide a column may be before we treat it as a grouping candidate.
_MAX_GROUP_CARDINALITY = 50
_ALPHA_CHOICES = [0.05, 0.01, 0.10]


def _render_dimensions(st: Any, df: pd.DataFrame, profile: Mapping[str, Any] | None) -> None:
    facts = _dataset_profile(df, profile)
    render_metric_cards(
        st,
        [
            {"label": "Rows", "value": f"{facts['rows']:,}"},
            {"label": "Columns", "value": f"{facts['columns']:,}"},
            {"label": "Missing cells", "value": f"{facts['missing_cells']:,}"},
            {"label": "Memory", "value": f"{facts['memory_mb']:.2f} MB"},
        ],
    )


def _render_type_summary(st: Any, df: pd.DataFrame) -> None:
    render_section_header(st, "Column type summary")
    summary = _dtype_distribution(df)
    if summary.empty:
        st.info("No columns to summarize.")
        return
    st.dataframe(summary, hide_index=True)


def _render_numeric_stats(st: Any, df: pd.DataFrame) -> None:
    render_section_header(
        st,
        "Numeric descriptive statistics",
        "count · mean · median · std · min · max · skew · kurtosis",
    )
    stats = numeric_descriptive_stats(df)
    if stats is None:
        st.info("No numeric columns to summarize.")
        return
    st.dataframe(stats)
    csv_download_button(
        st,
        "Download descriptive statistics as CSV",
        stats.reset_index(names="column"),
        "descriptive_statistics.csv",
    )


def _render_missingness(st: Any, df: pd.DataFrame) -> None:
    render_section_header(st, "Missingness")
    summary = _missingness_summary(df)
    if summary.empty:
        st.info("No columns to summarize.")
        return
    st.dataframe(summary, hide_index=True)


def _render_duplicates(st: Any, df: pd.DataFrame) -> None:
    render_section_header(st, "Duplicate rows")
    summary = _duplicate_row_summary(df)
    render_metric_cards(
        st,
        [
            {"label": "Duplicate rows", "value": f"{summary['duplicate_rows']:,}"},
            {"label": "Duplicate rate", "value": f"{summary['duplicate_pct']:.2f}%"},
            {"label": "Unique rows", "value": f"{summary['unique_rows']:,}"},
        ],
    )
    st.caption("Counts fully duplicated rows; source records are not displayed.")


def _render_categorical_frequencies(st: Any, df: pd.DataFrame) -> None:
    render_section_header(st, "Categorical frequencies", "Top values for a selected column.")
    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    categorical_columns = [column for column in df.columns if column not in numeric_columns]
    if not categorical_columns:
        st.info("No categorical columns to summarize.")
        return
    col_name = st.selectbox("Select categorical column", categorical_columns, key=_STATS_CAT_COLUMN)
    if col_name is None:
        return
    top = _categorical_top_values(df, col_name)
    if top is None:
        st.info("No usable values for this column.")
        return
    st.dataframe(top)


def _render_correlation(st: Any, df: pd.DataFrame) -> None:
    render_section_header(st, "Correlation table", "Pearson correlation across numeric columns.")
    matrix = _correlation_matrix(df)
    if matrix is None:
        st.info("Need at least two numeric columns for a correlation table.")
        return
    st.dataframe(matrix)


def _group_candidate_columns(df: pd.DataFrame) -> list[str]:
    """Columns usable as a grouping key: bounded cardinality, at least two levels."""
    candidates: list[str] = []
    for column in df.columns:
        levels = int(df[column].nunique(dropna=True))
        if 2 <= levels <= _MAX_GROUP_CARDINALITY:
            candidates.append(column)
    return candidates


def _render_two_sample_result(st: Any, result: Mapping[str, Any]) -> None:
    """Render a two-group / A-B comparison result safely from its status dict."""
    if result.get("status") != "ok":
        render_info_state(st, str(result.get("reason") or result.get("interpretation")))
        return
    render_metric_cards(
        st,
        [
            {"label": f"n · {result['group_a']}", "value": f"{result['n_a']:,}"},
            {"label": f"n · {result['group_b']}", "value": f"{result['n_b']:,}"},
            {"label": "Δ mean (A−B)", "value": f"{result['delta_mean']:.4g}"},
            {
                "label": "Percent lift",
                "value": (
                    "—" if result["percent_lift"] is None else f"{result['percent_lift']:.2f}%"
                ),
            },
            {
                "label": "Cohen's d",
                "value": f"{result['cohens_d']:.4g}",
                "help": result["effect_size_label"],
            },
        ],
    )
    tests = pd.DataFrame(
        [
            {
                "test": "Welch t-test",
                "statistic": round(result["welch"]["statistic"], 4),
                "p_value": round(result["welch"]["p_value"], 4),
                "significant": result["welch"]["significant"],
            },
            {
                "test": "Mann-Whitney U",
                "statistic": round(result["mann_whitney"]["statistic"], 4),
                "p_value": round(result["mann_whitney"]["p_value"], 4),
                "significant": result["mann_whitney"]["significant"],
            },
        ]
    )
    st.dataframe(tests, hide_index=True)
    st.caption(result["interpretation"])


def _render_normality(st: Any, df: pd.DataFrame, alpha: float) -> None:
    render_section_header(st, "Normality check", "Shapiro-Wilk on a selected numeric column.")
    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    if not numeric_columns:
        st.info("No numeric columns to check.")
        return
    column = st.selectbox(
        "Numeric column for normality", numeric_columns, key=_STATS_NORMALITY_COLUMN
    )
    if column is None:
        return
    result = normality_check(df[column], alpha=alpha)
    if result.get("status") != "ok":
        render_info_state(st, str(result.get("reason") or result.get("interpretation")))
        return
    render_metric_cards(
        st,
        [
            {"label": "Statistic (W)", "value": f"{result['statistic']:.4g}"},
            {"label": "p-value", "value": f"{result['p_value']:.4g}"},
            {"label": "Sample size", "value": f"{result['sample_size']:,}"},
        ],
    )
    st.caption(result["interpretation"])


def _render_group_comparison(st: Any, df: pd.DataFrame, alpha: float) -> None:
    render_section_header(
        st,
        "Group comparison",
        "Two groups → Welch t-test + Mann-Whitney U. More groups → ANOVA + Kruskal-Wallis.",
    )
    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    group_columns = _group_candidate_columns(df)
    if not numeric_columns or not group_columns:
        st.info("Need at least one numeric metric and one grouping column.")
        return
    metric = st.selectbox("Numeric metric", numeric_columns, key=_STATS_GROUP_METRIC)
    group_col = st.selectbox("Group by", group_columns, key=_STATS_GROUP_COLUMN)
    if metric is None or group_col is None:
        return
    levels = int(df[group_col].nunique(dropna=True))
    if levels == 2:
        _render_two_sample_result(st, two_group_comparison(df, metric, group_col, alpha=alpha))
        return
    result = multi_group_comparison(df, metric, group_col, alpha=alpha)
    summary = group_summary_dataframe(result)
    if summary is not None:
        st.dataframe(summary, hide_index=True)
    if result.get("status") != "ok":
        render_info_state(st, str(result.get("reason") or result.get("interpretation")))
        return
    tests = pd.DataFrame(
        [
            {
                "test": "ANOVA",
                "statistic": round(result["anova"]["statistic"], 4),
                "p_value": round(result["anova"]["p_value"], 4),
                "significant": result["anova"]["significant"],
            },
            {
                "test": "Kruskal-Wallis",
                "statistic": round(result["kruskal"]["statistic"], 4),
                "p_value": round(result["kruskal"]["p_value"], 4),
                "significant": result["kruskal"]["significant"],
            },
        ]
    )
    st.dataframe(tests, hide_index=True)
    st.caption(result["interpretation"])


def _render_ab_comparison(st: Any, df: pd.DataFrame, alpha: float) -> None:
    render_section_header(
        st,
        "A/B comparison",
        "Pick two group values and compare a numeric metric (A vs B).",
    )
    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    group_columns = _group_candidate_columns(df)
    if not numeric_columns or not group_columns:
        st.info("Need at least one numeric metric and one grouping column.")
        return
    group_col = st.selectbox("Group column", group_columns, key=_STATS_AB_GROUP)
    if group_col is None:
        return
    values = [str(v) for v in df[group_col].dropna().unique().tolist()]
    if len(values) < 2:
        st.info("Selected column needs at least two distinct values for A/B.")
        return
    a_value = st.selectbox("A value", values, key=_STATS_AB_A)
    b_value = st.selectbox("B value", values, key=_STATS_AB_B)
    metric = st.selectbox("Numeric metric", numeric_columns, key=_STATS_AB_METRIC)
    if a_value is None or b_value is None or metric is None:
        return
    _render_two_sample_result(
        st, ab_comparison(df, group_col, a_value, b_value, metric, alpha=alpha)
    )


def _render_inferential(st: Any, df: pd.DataFrame) -> None:
    st.divider()
    render_section_header(
        st,
        "Inferential Tests / A-B Comparison",
        "Normality, group comparison, and A/B testing. p-values are uncorrected for "
        "multiple testing; interpret as guidance, not proof.",
    )
    if not inferential_available():
        render_warning_state(
            st,
            "Inferential statistics unavailable — install the [stats] extra "
            "(pip install data-quality-toolkit[stats]) to enable normality checks, "
            "group comparison, and A/B testing. Descriptive statistics above still work.",
        )
        return
    alpha = st.selectbox("Significance level (alpha)", _ALPHA_CHOICES, key=_STATS_ALPHA)
    if alpha is None:
        alpha = _ALPHA_CHOICES[0]
    _render_normality(st, df, alpha)
    _render_group_comparison(st, df, alpha)
    _render_ab_comparison(st, df, alpha)


def _render_statistics_lab(st: Any, session_state: Mapping[str, Any] | None = None) -> None:
    """Render the Statistics Lab page body."""
    render_page_header(
        st,
        "Statistics Lab",
        "Descriptive statistics and tables. For charts and visual exploration, use EDA Explorer.",
        step_label="Step 4 of 11 — Statistics Lab",
    )
    context = get_dataset_context(session_state or {})
    if context is not None:
        render_dataset_context_panel(st, context)
        if context.large_file_mode:
            render_warning_state(
                st,
                "Statistics Lab needs full analysis mode. Return to Start and select full "
                "analysis to compute descriptive statistics.",
            )
            return
        csv_path = context.source_path
    else:
        csv_path = st.text_input("CSV path", placeholder="e.g., ./data/my_dataset.csv")
    if not csv_path:
        st.info("💡 Start with a dataset context or enter a CSV path above to compute statistics.")
        return

    df, result, err = _load_df_and_assess(csv_path)
    if err is not None:
        show_error(st, "Load Error", err)
        return
    if df is None:
        return

    profile = result.get("profile") if result is not None else None
    _render_dimensions(st, df, profile)
    _render_type_summary(st, df)
    _render_numeric_stats(st, df)
    _render_missingness(st, df)
    _render_duplicates(st, df)
    _render_categorical_frequencies(st, df)
    _render_correlation(st, df)
    _render_inferential(st, df)


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_statistics_lab(st, st.session_state)  # type: ignore[arg-type, unused-ignore]
