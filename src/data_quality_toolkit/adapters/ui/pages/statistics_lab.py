"""Statistics Lab page: descriptive statistics plus a scipy-guarded inferential tier.

Statistics Lab is the *numbers* surface — descriptive calculations, frequency
tables, correlation tables, and an inferential tier (normality, group comparison,
A/B). Visual exploration (charts, scatter, bivariate plots) lives on the EDA
Explorer page. Sections are organized into task-oriented tabs (Overview,
Descriptive statistics, Relationships, Categories & groups, Statistical tests,
Distributions, Power & Sample size), mirroring the EDA Explorer tab model. The
descriptive tier uses only
pandas/numpy (core dependencies); the inferential tier requires the optional
``[stats]`` extra (scipy) and degrades to a clear unavailable message when
scipy is not installed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from typing import Any, cast

import pandas as pd

from data_quality_toolkit.adapters.ui import journey
from data_quality_toolkit.adapters.ui.components.dataset_context import (
    render_dataset_context_panel,
)
from data_quality_toolkit.adapters.ui.components.downloads import csv_download_button
from data_quality_toolkit.adapters.ui.components.errors import show_error
from data_quality_toolkit.adapters.ui.components.page_guidance import render_page_guidance
from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_metric_cards,
    render_page_header,
    render_section_header,
)
from data_quality_toolkit.adapters.ui.components.source_hub import render_dataset_source_callout
from data_quality_toolkit.adapters.ui.components.states import (
    render_info_state,
    render_warning_state,
)
from data_quality_toolkit.adapters.ui.components.workspace_save_ui import (
    render_analysis_csv_save,
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
from data_quality_toolkit.adapters.ui.pages.statistics_lab_chi_square import (
    render_chi_square_tests_runner,
)
from data_quality_toolkit.adapters.ui.pages.statistics_lab_runners import (
    render_paired_evidence,
    render_paired_t_runner,
    render_proportion_tests_runner,
)
from data_quality_toolkit.adapters.ui.services.managed_frame_loader import (
    ManagedFrameLoadError,
    get_managed_frame,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    ManagedTrustRoot,
    TrustAuthority,
    resolve_trust_authority,
)
from data_quality_toolkit.adapters.ui.services.statistics import (
    assumption_checks_dataframe,
    assumption_checks_grouped,
    assumption_checks_one_sample,
    bootstrap_mean_confidence_interval,
    compare_numeric_ab,
    confidence_interval_choices,
    distribution_calculation_choices,
    distribution_choices,
    group_summary_dataframe,
    inferential_available,
    mean_confidence_interval,
    multi_group_comparison,
    multivariate_categorical_associations,
    multivariate_covariance_matrix,
    multivariate_grouped_summary,
    multivariate_top_correlations,
    multivariate_vif_table,
    nonparametric_effect_sizes,
    normality_check,
    numeric_descriptive_stats,
    paired_wilcoxon_test,
    power_mean,
    power_prop,
    power_target_choices,
    profile_numeric_summary_dataframe,
    required_n_cohend,
    required_n_mean,
    required_n_prop,
    required_n_variance,
    run_one_sample_numeric_test,
    run_two_sample_numeric_test,
    select_hypothesis_test,
    statistics_profile,
    theoretical_distribution_result,
    two_group_comparison,
)
from data_quality_toolkit.adapters.ui.services.statistics_eligibility import (
    STATS_CATEGORICAL_MAX_LEVELS,
    bounded_table_preview,
)
from data_quality_toolkit.adapters.ui.services.statistics_guidance import (
    ResultGuidance,
    guidance_for_assumptions,
    guidance_for_distribution,
    guidance_for_effect_sizes,
    guidance_for_interval,
    guidance_for_multi_group,
    guidance_for_power,
    guidance_for_two_group,
    guidance_sections,
)
from data_quality_toolkit.adapters.ui.services.statistics_visualization import (
    CI_PLOT_MAX_ESTIMATES,
    DISTRIBUTION_CURVE_MAX_POINTS,
    POWER_CURVE_MAX_POINTS,
    build_distribution_curve,
    build_estimate_interval_evidence,
    build_group_comparison_evidence,
    build_parameter_grid,
    build_power_curve,
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
_STATS_ASSUMPTION_METRIC = "stats_lab_assumption_metric"
_STATS_ASSUMPTION_GROUP = "stats_lab_assumption_group"
_STATS_WILCOXON_COL_A = "stats_lab_wilcoxon_column_a"
_STATS_WILCOXON_COL_B = "stats_lab_wilcoxon_column_b"
_STATS_WILCOXON_ALTERNATIVE = "stats_lab_wilcoxon_alternative"
_STATS_WIZARD_VARIABLE_TYPE = "stats_lab_wizard_variable_type"
_STATS_WIZARD_GROUP_STRUCTURE = "stats_lab_wizard_group_structure"
_STATS_WIZARD_SIGMA = "stats_lab_wizard_sigma"
_STATS_WIZARD_EQUAL_VARIANCE = "stats_lab_wizard_equal_variance"
_STATS_WIZARD_ALTERNATIVE = "stats_lab_wizard_alternative"
_STATS_RUN_MODE = "stats_lab_run_mode"
_STATS_RUN_METRIC = "stats_lab_run_metric"
_STATS_RUN_GROUP = "stats_lab_run_group"
_STATS_RUN_A = "stats_lab_run_a_value"
_STATS_RUN_B = "stats_lab_run_b_value"
_STATS_RUN_NULL_MEAN = "stats_lab_run_null_mean"
_STATS_RUN_NULL_DIFF = "stats_lab_run_null_difference"
_STATS_RUN_EQUAL_VARIANCE = "stats_lab_run_equal_variance"
_STATS_RUN_ALTERNATIVE = "stats_lab_run_alternative"
_STATS_AB_EQUAL_VARIANCE = "stats_lab_ab_equal_variance"
_STATS_AB_ALTERNATIVE = "stats_lab_ab_alternative"
_STATS_CI_COLUMN = "stats_lab_ci_column"
_STATS_CI_METHOD = "stats_lab_ci_method"
_STATS_CI_CONFIDENCE = "stats_lab_ci_confidence"
_STATS_CI_RESAMPLES = "stats_lab_ci_resamples"
_STATS_POWER_ANALYSIS = "stats_lab_power_analysis"
_STATS_POWER_ALPHA = "stats_lab_power_alpha"
_STATS_POWER_TARGET = "stats_lab_power_target"
_STATS_POWER_N = "stats_lab_power_n"
_STATS_POWER_DELTA = "stats_lab_power_delta"
_STATS_POWER_SIGMA = "stats_lab_power_sigma"
_STATS_POWER_P1 = "stats_lab_power_p1"
_STATS_POWER_P2 = "stats_lab_power_p2"
_STATS_POWER_ALTERNATIVE = "stats_lab_power_alternative"
_STATS_POWER_RATIO = "stats_lab_power_variance_ratio"
_STATS_DIST_DISTRIBUTION = "stats_lab_distribution_family"
_STATS_DIST_CALCULATION = "stats_lab_distribution_calculation"
_STATS_DIST_X = "stats_lab_distribution_x"
_STATS_DIST_K = "stats_lab_distribution_k"
_STATS_DIST_MU = "stats_lab_distribution_mu"
_STATS_DIST_SIGMA = "stats_lab_distribution_sigma"
_STATS_DIST_DF = "stats_lab_distribution_df"
_STATS_DIST_DF1 = "stats_lab_distribution_df1"
_STATS_DIST_DF2 = "stats_lab_distribution_df2"
_STATS_DIST_N = "stats_lab_distribution_n"
_STATS_DIST_P = "stats_lab_distribution_p"
_STATS_DIST_LAM = "stats_lab_distribution_lam"
_STATS_DIST_ALPHA = "stats_lab_distribution_alpha"
_SAVE_DESCRIPTIVE_STATISTICS_BTN = "statistics_lab_save_descriptive_statistics_btn"
_SAVE_COVARIANCE_MATRIX_BTN = "statistics_lab_save_covariance_matrix_btn"
_SAVE_VIF_MULTICOLLINEARITY_BTN = "statistics_lab_save_vif_multicollinearity_btn"
_SAVE_TOP_CORRELATIONS_BTN = "statistics_lab_save_top_correlations_btn"
_SAVE_CATEGORICAL_ASSOCIATIONS_BTN = "statistics_lab_save_categorical_associations_btn"
_SAVE_GROUPED_NUMERIC_BY_CATEGORY_BTN = "statistics_lab_save_grouped_numeric_by_category_btn"
_SAVE_GROUP_TEST_RESULTS_BTN = "statistics_lab_save_group_test_results_btn"
_SAVE_STATISTICAL_TEST_RESULTS_BTN = "statistics_lab_save_test_results_btn"
_SAVE_AB_TEST_RESULTS_BTN = "statistics_lab_save_ab_test_results_btn"
_SAVE_CONFIDENCE_INTERVALS_BTN = "statistics_lab_save_confidence_intervals_btn"
_SAVE_EFFECT_SIZES_BTN = "statistics_lab_save_effect_sizes_btn"
_SAVE_DISTRIBUTIONS_BTN = "statistics_lab_save_distributions_btn"
_SAVE_POWER_SAMPLE_SIZE_BTN = "statistics_lab_save_power_sample_size_btn"
_SAVE_ASSUMPTION_CHECKS_BTN = "statistics_lab_save_assumption_checks_btn"
_SAVE_WILCOXON_BTN = "statistics_lab_save_wilcoxon_btn"

_STATISTICS_TEST_RESULTS_FILE = "statistics_test_results.csv"
_STATISTICS_ASSUMPTIONS_FILE = "statistics_assumption_checks.csv"
_STATISTICS_WILCOXON_FILE = "statistics_wilcoxon.csv"
_STATISTICS_INTERVALS_FILE = "statistics_intervals.csv"
_STATISTICS_EFFECT_SIZES_FILE = "statistics_effect_sizes.csv"
_STATISTICS_DISTRIBUTIONS_FILE = "statistics_distributions.csv"
_STATISTICS_POWER_SAMPLE_SIZE_FILE = "statistics_power_sample_size.csv"

# Bound how wide a column may be before we treat it as a grouping candidate. The
# value is owned by the shared Statistics Lab eligibility policy so the page and the
# statistics service cannot drift apart; the accepted 2..50 rule is unchanged.
_MAX_GROUP_CARDINALITY = STATS_CATEGORICAL_MAX_LEVELS
_STATS_TAB_LABELS = [
    "Overview",
    "Descriptive statistics",
    "Relationships",
    "Categories & groups",
    "Statistical tests",
    "Distributions",
    "Power & Sample size",
]
_SAVE_ANALYSIS_CAPTION = (
    "Downloads stay in your browser. Optionally save this analysis under your "
    "Workspace Root / analysis; existing files are not overwritten."
)

# Fixed, privacy-safe refusal shown when a managed-looking dataset context has
# no valid managed trust root (root-first authority, fail-closed).
_MANAGED_FAIL_CLOSED_MESSAGE = (
    "The managed dataset context is not backed by a valid managed trust root. "
    "Reopen the managed version explicitly to continue."
)

_MANAGED_LARGE_STATS_MESSAGE = (
    "Statistics Lab needs full analysis mode. Reopen a full-analysis managed "
    "version to compute descriptive statistics."
)
_ALPHA_CHOICES = [0.05, 0.01, 0.10]
_ALTERNATIVE_CHOICES = ["two-sided", "greater", "less"]
_VARIABLE_TYPES = ["numeric", "proportion", "categorical", "variance"]
_GROUP_STRUCTURES = [
    "one_sample",
    "two_independent",
    "paired",
    "multi_group",
    "goodness_of_fit",
    "contingency",
]
_SIGMA_OPTIONS = {
    "Unknown sigma (t-test)": False,
    "Known sigma (z-test)": True,
}
_EQUAL_VARIANCE_OPTIONS = {
    "Unequal variances (Welch)": False,
    "Equal variances (pooled)": True,
}
# Confidence-interval methods: label → (kind, bootstrap method). Mean is the
# closed-form t-interval; the bootstrap options resample the mean.
_CI_METHODS = {
    "Mean (t-interval)": ("mean", "percentile"),
    "Bootstrap mean (percentile)": ("bootstrap", "percentile"),
    "Bootstrap mean (BCA)": ("bootstrap", "bca"),
}
# Bounded resample counts keep bootstrap compute predictable and deterministic.
_CI_RESAMPLE_CHOICES = [2000, 5000, 10000]
# Power & sample-size analyses: label → kind. Each kind selects one closed-form
# domain function; controls are bounded to avoid free-text math entry.
_POWER_ANALYSES = {
    "Power — one-sample mean": "power_mean",
    "Power — two proportions": "power_prop",
    "Required n — mean": "n_mean",
    "Required n — two proportions": "n_prop",
    "Required n — variance ratio": "n_variance",
    "Required n — Cohen's d (two-sample t)": "n_cohend",
}


# ── opt-in result evidence ────────────────────────────────────────────────────
#
# Every workflow that produces a result offers one clearly labelled checkbox that
# reveals a bounded, result-native evidence view immediately after that result.
# Evidence is derived only from the completed result object and the analyzed
# inputs the workflow already holds: nothing here re-runs a statistical service,
# reloads a dataset, or recomputes a statistic, p-value, alpha decision,
# alternative or paired direction.

_EVIDENCE_CHECKBOX_LABEL = "Show evidence chart and interpretation guidance"
_GUIDANCE_CHECKBOX_LABEL = "Show interpretation guidance"
_CURVE_CHECKBOX_LABEL = "Show bounded curve and interpretation guidance"

_STATS_CI_SHOW_EVIDENCE = "stats_lab_ci_show_evidence"
_STATS_EFFECT_SHOW_EVIDENCE = "stats_lab_effect_show_evidence"
_STATS_TWO_GROUP_SHOW_EVIDENCE = "stats_lab_two_group_show_evidence"
_STATS_MULTI_GROUP_SHOW_EVIDENCE = "stats_lab_multi_group_show_evidence"
_STATS_WILCOXON_SHOW_EVIDENCE = "stats_lab_wilcoxon_show_evidence"
_STATS_DIST_SHOW_CURVE = "stats_lab_distribution_show_curve"
_STATS_POWER_SHOW_CURVE = "stats_lab_power_show_curve"
_STATS_ASSUMPTION_SHOW_GUIDANCE = "stats_lab_assumption_show_guidance"

_INTERVAL_CAVEAT = (
    "The bar spans the interval and the marker is the point estimate. An interval "
    "covering a reference value means the data are compatible with it, not that the "
    "reference is the true value."
)
_GROUP_CENTER_CAVEAT = (
    "Group centres and sizes come from the result already computed above; no individual "
    "rows are plotted and no pairwise comparison is performed here."
)
_OMNIBUS_CAVEAT = (
    "This omnibus result asks only whether some group differs. It does not identify "
    "which groups differ, and no post-hoc comparison is run."
)
_DISTRIBUTION_CAVEAT = (
    "This is the theoretical distribution for the parameters entered. It makes no claim "
    "that the active dataset follows this distribution and runs no goodness-of-fit test."
)
_POWER_CURVE_CAVEAT = (
    "The curve varies one planning input while every other input stays fixed. Points "
    "where the calculation is undefined are skipped rather than plotted as zero, and no "
    "sample size is recommended for you."
)

_ESTIMATE_SPEC: dict[str, Any] = {
    "layer": [
        {
            "mark": {"type": "rule", "size": 3},
            "encoding": {
                "y": {"field": "label", "type": "nominal", "title": "Estimate"},
                "x": {"field": "lower", "type": "quantitative", "title": "Value"},
                "x2": {"field": "upper"},
            },
        },
        {
            "mark": {"type": "point", "filled": True, "size": 90},
            "encoding": {
                "y": {"field": "label", "type": "nominal"},
                "x": {"field": "estimate", "type": "quantitative"},
                "tooltip": [
                    {"field": "label", "type": "nominal"},
                    {"field": "estimate", "type": "quantitative"},
                    {"field": "lower", "type": "quantitative"},
                    {"field": "upper", "type": "quantitative"},
                    {"field": "n", "type": "quantitative"},
                ],
            },
        },
    ]
}

_GROUP_SPEC: dict[str, Any] = {
    "mark": {"type": "bar"},
    "encoding": {
        "x": {"field": "group", "type": "nominal", "title": "Group"},
        "y": {"field": "center", "type": "quantitative", "title": "Group centre"},
        "tooltip": [
            {"field": "group", "type": "nominal"},
            {"field": "n", "type": "quantitative"},
            {"field": "center", "type": "quantitative"},
        ],
    },
}


def _render_guidance(st: Any, guidance: ResultGuidance) -> None:
    """Render one result's interpretation guidance as bounded caption lines."""
    for heading, text in guidance_sections(guidance):
        st.caption(f"{heading}: {text}")


def _evidence_requested(st: Any, key: str, label: str = _EVIDENCE_CHECKBOX_LABEL) -> bool:
    """Render one clearly labelled opt-in evidence toggle (default off)."""
    return bool(st.checkbox(label, key=key))


def _render_estimate_evidence(
    st: Any,
    estimates: list[Mapping[str, Any]],
    guidance: ResultGuidance,
    *,
    reference: Any = None,
    caption: str,
) -> None:
    """Render a bounded point-and-interval evidence view, then its guidance.

    Numeric values stay visible in the table beside the chart so the estimate and
    its interval are never conveyed by geometry alone.
    """
    evidence = build_estimate_interval_evidence(estimates, reference=reference)
    if evidence["status"] != "ok":
        render_info_state(st, f"Evidence view unavailable: {evidence['reason']}.")
        _render_guidance(st, guidance)
        return
    st.caption(f"{caption} (bounded at {CI_PLOT_MAX_ESTIMATES} estimates).")
    spec = dict(_ESTIMATE_SPEC)
    if evidence["reference_available"]:
        spec = {
            "layer": [
                *_ESTIMATE_SPEC["layer"],
                {
                    "mark": {"type": "rule", "color": "red", "strokeDash": [4, 4]},
                    "encoding": {"x": {"datum": evidence["reference"]}},
                },
            ]
        }
    st.vega_lite_chart(evidence["data"], spec, use_container_width=True)
    st.dataframe(evidence["data"], hide_index=True)
    if not evidence["intervals_available"]:
        render_info_state(
            st,
            "No interval is available for this estimate, so none is drawn; an absent "
            "interval is never replaced with zero.",
        )
    st.caption(_INTERVAL_CAVEAT)
    _render_guidance(st, guidance)


def _render_group_evidence(
    st: Any,
    groups: list[Mapping[str, Any]],
    guidance: ResultGuidance,
    *,
    caption: str,
    omnibus: bool = False,
) -> None:
    """Render a bounded per-group centre comparison, then its guidance."""
    evidence = build_group_comparison_evidence(groups)
    if evidence["status"] != "ok":
        render_info_state(st, f"Evidence view unavailable: {evidence['reason']}.")
        _render_guidance(st, guidance)
        return
    st.caption(caption)
    st.vega_lite_chart(evidence["data"], _GROUP_SPEC, use_container_width=True)
    st.dataframe(evidence["data"], hide_index=True)
    if evidence["truncated"]:
        st.caption(
            f"Showing {evidence['displayed_groups']:,} of {evidence['group_count']:,} groups."
        )
    st.caption(_GROUP_CENTER_CAVEAT)
    if omnibus:
        st.caption(_OMNIBUS_CAVEAT)
    _render_guidance(st, guidance)


def _format_number(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.4g}"
    except (TypeError, ValueError):
        return str(value)


def _format_power(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _format_int(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _result_dataframe(row: Mapping[str, Any]) -> pd.DataFrame:
    """Build a one-row table for exporting visible structured result values."""
    return pd.DataFrame([{key: value for key, value in row.items() if value is not None}])


def _render_downloadable_result_table(
    st: Any,
    dataframe: pd.DataFrame,
    *,
    download_label: str,
    file_name: str,
    save_label: str,
    save_key: str,
    artifact: str,
    dataset_name: str | None = None,
) -> None:
    """Render a visible result table with matching browser download and workspace save.

    Only the browser table is bounded: the download button and the workspace save
    always receive the complete, unmodified result frame, and a bound that actually
    withheld rows is disclosed rather than applied silently.
    """
    if dataframe.empty:
        return
    preview = bounded_table_preview(dataframe)
    st.dataframe(preview.frame, hide_index=True)
    if preview.truncated:
        st.caption(preview.disclosure)
    csv_download_button(st, download_label, dataframe, file_name)
    render_analysis_csv_save(
        st,
        button_label=save_label,
        key=save_key,
        artifact=artifact,
        dataframe=dataframe,
        dataset_name=dataset_name,
        caption=_SAVE_ANALYSIS_CAPTION,
    )


def _public_test_result_dataframe(result: Mapping[str, Any], *, source: str) -> pd.DataFrame:
    reject_null = result.get("reject_null")
    decision = "reject" if reject_null is True else "do not reject"
    assumptions = result.get("assumptions") or {}
    return _result_dataframe(
        {
            "source": source,
            "test": result.get("test_key"),
            "method": result.get("method"),
            "metric": result.get("metric"),
            "group_column": result.get("group_col"),
            "group_a": result.get("group_a"),
            "group_b": result.get("group_b"),
            "n_a": result.get("n_a") or assumptions.get("n_a"),
            "n_b": result.get("n_b") or assumptions.get("n_b"),
            "statistic": result.get("statistic"),
            "p_value": result.get("p_value"),
            "alpha": result.get("alpha"),
            "alternative": result.get("alternative"),
            "reject_null": reject_null,
            "decision": decision,
        }
    )


def _two_group_tests_dataframe(result: Mapping[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
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


def _multi_group_tests_dataframe(result: Mapping[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
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


def _effect_size_result_dataframe(result: Mapping[str, Any]) -> pd.DataFrame:
    hodges_lehmann = result.get("hodges_lehmann") or {}
    return _result_dataframe(
        {
            "group_a": result.get("group_a"),
            "group_b": result.get("group_b"),
            "n_a": result.get("n_a"),
            "n_b": result.get("n_b"),
            "confidence": result.get("confidence"),
            "cliffs_delta": result.get("cliffs_delta"),
            "cliffs_interpretation": result.get("cliffs_interpretation"),
            "hodges_lehmann_estimate": hodges_lehmann.get("estimate"),
            "hodges_lehmann_lower": hodges_lehmann.get("lower"),
            "hodges_lehmann_upper": hodges_lehmann.get("upper"),
            "hodges_lehmann_method": hodges_lehmann.get("method"),
        }
    )


def _confidence_interval_result_dataframe(result: Mapping[str, Any]) -> pd.DataFrame:
    return _result_dataframe(
        {
            "method": result.get("method"),
            "confidence": result.get("confidence"),
            "n": result.get("n"),
            "estimate": result.get("point"),
            "lower_bound": result.get("lower"),
            "upper_bound": result.get("upper"),
        }
    )


def _distribution_result_dataframe(result: Mapping[str, Any]) -> pd.DataFrame:
    parameters = result.get("parameters") or {}
    row: dict[str, Any] = {
        "distribution": result.get("distribution"),
        "calculation": result.get("calculation"),
        "method": result.get("method"),
        "tail": result.get("tail"),
        "value": result.get("value"),
    }
    row.update({f"parameter_{name}": value for name, value in parameters.items()})
    return _result_dataframe(row)


def _number_input_float(st: Any, label: str, *, value: float, key: str) -> float:
    raw = st.number_input(label, value=value, step=0.1, key=key)
    if raw is None:
        return value
    try:
        return float(raw)
    except (TypeError, ValueError):
        return value


def _bounded_number_input_float(
    st: Any,
    label: str,
    *,
    value: float,
    min_value: float,
    max_value: float,
    step: float,
    key: str,
) -> float:
    raw = st.number_input(
        label,
        min_value=min_value,
        max_value=max_value,
        value=value,
        step=step,
        key=key,
    )
    if raw is None:
        return value
    try:
        return float(raw)
    except (TypeError, ValueError):
        return value


def _bounded_number_input_int(
    st: Any,
    label: str,
    *,
    value: int,
    min_value: int,
    max_value: int,
    step: int,
    key: str,
) -> int:
    raw = st.number_input(
        label,
        min_value=min_value,
        max_value=max_value,
        value=value,
        step=step,
        key=key,
    )
    if raw is None:
        return value
    try:
        return int(raw)
    except (TypeError, ValueError):
        return value


def _select_equal_variance(st: Any, *, key: str) -> bool:
    options = list(_EQUAL_VARIANCE_OPTIONS)
    selected = st.selectbox("Variance assumption", options, key=key)
    return bool(_EQUAL_VARIANCE_OPTIONS.get(str(selected), False))


def _select_distinct_pair(
    st: Any,
    values: list[str],
    *,
    a_key: str,
    b_key: str,
) -> tuple[str | None, str | None]:
    if len(values) < 2:
        return None, None
    a_value = st.selectbox("A value", values, key=a_key)
    if a_value is None:
        return None, None
    b_options = [value for value in values if value != str(a_value)]
    if not b_options:
        return str(a_value), None
    b_value = st.selectbox("B value", b_options, key=b_key)
    if b_value is None:
        return str(a_value), None
    return str(a_value), str(b_value)


def _render_statistics_profile(st: Any, csv_path: str, df: pd.DataFrame) -> dict[str, Any] | None:
    render_section_header(
        st,
        "Descriptive Statistics / Profile",
        "DQT-native profile summary for the selected CSV.",
    )
    result = statistics_profile(csv_path)
    if result.get("status") != "ok":
        render_info_state(
            st,
            "Statistics profile unavailable for the selected CSV; continuing with "
            "the loaded DataFrame summary.",
        )
        _render_dimensions(st, df, None)
        return result

    profile = result.get("profile") or {}
    numeric_summary = result.get("numeric_summary") or []
    render_metric_cards(
        st,
        [
            {"label": "Rows", "value": f"{int(profile.get('n_rows', 0)):,}"},
            {"label": "Columns", "value": f"{int(profile.get('n_columns', 0)):,}"},
            {"label": "Numeric columns", "value": f"{len(numeric_summary):,}"},
            {"label": "Memory", "value": f"{float(profile.get('memory_mb', 0.0)):.2f} MB"},
        ],
    )
    return result


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


def _render_numeric_stats(
    st: Any,
    df: pd.DataFrame,
    profile_result: Mapping[str, Any] | None = None,
    *,
    dataset_name: str | None = None,
) -> None:
    render_section_header(
        st,
        "Numeric descriptive statistics",
        "count · mean · median · std · min · max · skew · kurtosis",
    )
    stats = (
        profile_numeric_summary_dataframe(dict(profile_result))
        if profile_result is not None
        else None
    )
    if stats is None:
        stats = numeric_descriptive_stats(df)
        if stats is None:
            st.info("No numeric columns to summarize.")
            return
        st.dataframe(stats)
        csv_data = stats.reset_index(names="column")
    else:
        st.dataframe(stats, hide_index=True)
        csv_data = stats
    csv_download_button(
        st,
        "Download descriptive statistics as CSV",
        csv_data,
        "descriptive_statistics.csv",
    )
    render_analysis_csv_save(
        st,
        button_label="Save descriptive statistics to Workspace",
        key=_SAVE_DESCRIPTIVE_STATISTICS_BTN,
        artifact="descriptive_statistics",
        dataframe=csv_data,
        dataset_name=dataset_name,
        caption=_SAVE_ANALYSIS_CAPTION,
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


def _render_multivariate(st: Any, df: pd.DataFrame, *, dataset_name: str | None = None) -> None:
    """Render dependency-free multivariate numeric diagnostics with CSV downloads."""
    render_section_header(
        st,
        "Multivariate diagnostics",
        "Covariance, multicollinearity (VIF), and strongest numeric relationships.",
    )
    covariance = multivariate_covariance_matrix(df)
    if covariance is None:
        st.info("Need at least two numeric columns for a covariance matrix.")
    else:
        st.caption("Covariance across numeric columns (first 20).")
        st.dataframe(covariance)
        csv_download_button(
            st,
            "Download covariance matrix as CSV",
            covariance.reset_index(names="column"),
            "covariance_matrix.csv",
        )
        render_analysis_csv_save(
            st,
            button_label="Save covariance matrix to Workspace",
            key=_SAVE_COVARIANCE_MATRIX_BTN,
            artifact="covariance_matrix",
            dataframe=covariance.reset_index(names="column"),
            dataset_name=dataset_name,
            caption=_SAVE_ANALYSIS_CAPTION,
        )
    vif = multivariate_vif_table(df)
    if vif is None:
        st.info("Need at least two non-constant numeric columns to estimate VIF.")
    else:
        st.caption("Variance inflation factors estimate multicollinearity among numeric columns.")
        st.dataframe(vif, hide_index=True)
        csv_download_button(st, "Download VIF table as CSV", vif, "vif_multicollinearity.csv")
        render_analysis_csv_save(
            st,
            button_label="Save VIF table to Workspace",
            key=_SAVE_VIF_MULTICOLLINEARITY_BTN,
            artifact="vif_multicollinearity",
            dataframe=vif,
            dataset_name=dataset_name,
            caption=_SAVE_ANALYSIS_CAPTION,
        )
    top = multivariate_top_correlations(df)
    if top is None:
        st.info("Need at least two numeric columns to rank pairwise correlations.")
    else:
        st.caption("Strongest numeric relationships ranked by absolute correlation.")
        st.dataframe(top, hide_index=True)
        csv_download_button(st, "Download top correlations as CSV", top, "top_correlations.csv")
        render_analysis_csv_save(
            st,
            button_label="Save top correlations to Workspace",
            key=_SAVE_TOP_CORRELATIONS_BTN,
            artifact="top_correlations",
            dataframe=top,
            dataset_name=dataset_name,
            caption=_SAVE_ANALYSIS_CAPTION,
        )


def _render_categorical_mixed(
    st: Any, df: pd.DataFrame, *, dataset_name: str | None = None
) -> None:
    """Render dependency-free categorical/mixed diagnostics with CSV downloads."""
    render_section_header(
        st,
        "Categorical and mixed diagnostics",
        "Cramér's V associations and numeric summaries grouped by category.",
    )
    associations = multivariate_categorical_associations(df)
    if associations is None:
        st.info("Need at least two categorical columns for association analysis.")
    else:
        st.caption(
            "Categorical associations ranked by Cramér's V; "
            "p-values are shown only when scipy is available."
        )
        st.dataframe(associations, hide_index=True)
        csv_download_button(
            st,
            "Download categorical associations as CSV",
            associations,
            "categorical_associations.csv",
        )
        render_analysis_csv_save(
            st,
            button_label="Save categorical associations to Workspace",
            key=_SAVE_CATEGORICAL_ASSOCIATIONS_BTN,
            artifact="categorical_associations",
            dataframe=associations,
            dataset_name=dataset_name,
            caption=_SAVE_ANALYSIS_CAPTION,
        )
    grouped = multivariate_grouped_summary(df)
    if grouped is None:
        st.info(
            "Need at least one categorical column and one numeric column for grouped summaries."
        )
    else:
        st.caption("Numeric summaries grouped by the first categorical column.")
        st.dataframe(grouped, hide_index=True)
        csv_download_button(
            st,
            "Download grouped numeric summary as CSV",
            grouped,
            "grouped_numeric_by_category.csv",
        )
        render_analysis_csv_save(
            st,
            button_label="Save grouped numeric summary to Workspace",
            key=_SAVE_GROUPED_NUMERIC_BY_CATEGORY_BTN,
            artifact="grouped_numeric_by_category",
            dataframe=grouped,
            dataset_name=dataset_name,
            caption=_SAVE_ANALYSIS_CAPTION,
        )


def _group_candidate_columns(df: pd.DataFrame) -> list[str]:
    """Columns usable as a grouping key: bounded cardinality, at least two levels."""
    candidates: list[str] = []
    for column in df.columns:
        levels = int(df[column].nunique(dropna=True))
        if 2 <= levels <= _MAX_GROUP_CARDINALITY:
            candidates.append(column)
    return candidates


def _render_selection_result(st: Any, result: Mapping[str, Any]) -> None:
    if result.get("status") == "ok":
        render_metric_cards(
            st,
            [
                {"label": "Selected test", "value": result.get("test_key", "UNKNOWN")},
                {"label": "Alpha", "value": _format_number(result.get("alpha"))},
                {"label": "Alternative", "value": result.get("alternative", "two-sided")},
            ],
        )
        st.caption(str(result.get("explanation") or "Selection complete."))
    else:
        render_info_state(
            st,
            str(
                result.get("explanation")
                or result.get("reason")
                or "No supported first-wave test matched this setup."
            ),
        )
    for message in result.get("messages") or []:
        st.caption(str(message))
    for warning in result.get("warnings") or []:
        st.caption(str(warning))


def _render_public_test_result(
    st: Any,
    result: Mapping[str, Any],
    *,
    source: str,
    save_key: str,
    save_label: str,
    dataset_name: str | None = None,
) -> None:
    status = str(result.get("status") or "unknown")
    if status != "ok":
        message = str(result.get("reason") or result.get("explanation") or f"Status: {status}")
        if status == "unavailable":
            render_warning_state(st, message)
        else:
            render_info_state(st, message)
        return

    reject_null = result.get("reject_null")
    decision = "reject" if reject_null is True else "do not reject"
    render_metric_cards(
        st,
        [
            {"label": "Test", "value": result.get("test_key", "UNKNOWN")},
            {"label": "Statistic", "value": _format_number(result.get("statistic"))},
            {"label": "p-value", "value": _format_number(result.get("p_value"))},
            {"label": "Decision", "value": decision},
        ],
    )
    assumptions = result.get("assumptions") or {}
    n_a = result.get("n_a") or assumptions.get("n_a")
    n_b = result.get("n_b") or assumptions.get("n_b")
    if n_a is not None and n_b is not None:
        render_metric_cards(
            st,
            [
                {"label": f"n · {result.get('group_a', 'A')}", "value": f"{int(n_a):,}"},
                {"label": f"n · {result.get('group_b', 'B')}", "value": f"{int(n_b):,}"},
            ],
        )
    st.caption(
        f"{result.get('method', 'hypothesis_test')} at alpha={_format_number(result.get('alpha'))}; "
        f"alternative={result.get('alternative', 'two-sided')}."
    )
    _render_downloadable_result_table(
        st,
        _public_test_result_dataframe(result, source=source),
        download_label=f"Download {source.lower()} result (CSV)",
        file_name=_STATISTICS_TEST_RESULTS_FILE,
        save_label=save_label,
        save_key=save_key,
        artifact="statistics_test_results",
        dataset_name=dataset_name,
    )
    for warning in result.get("warnings") or []:
        st.caption(str(warning))


def _render_hypothesis_wizard(st: Any, alpha: float) -> None:
    render_section_header(
        st,
        "Hypothesis Test Selection",
        "Choose a typed hypothesis setup and let DQT select the first-wave test.",
    )
    variable_type = st.selectbox(
        "Variable type",
        _VARIABLE_TYPES,
        key=_STATS_WIZARD_VARIABLE_TYPE,
    )
    group_structure = st.selectbox(
        "Group structure",
        _GROUP_STRUCTURES,
        key=_STATS_WIZARD_GROUP_STRUCTURE,
    )
    sigma_choice = st.selectbox(
        "Sigma",
        list(_SIGMA_OPTIONS),
        key=_STATS_WIZARD_SIGMA,
    )
    equal_variance = _select_equal_variance(st, key=_STATS_WIZARD_EQUAL_VARIANCE)
    alternative = st.selectbox(
        "Selection alternative",
        _ALTERNATIVE_CHOICES,
        key=_STATS_WIZARD_ALTERNATIVE,
    )
    if variable_type is None or group_structure is None or alternative is None:
        return
    result = select_hypothesis_test(
        str(variable_type),
        str(group_structure),
        sigma_known=_SIGMA_OPTIONS.get(str(sigma_choice)),
        equal_variance_assumed=equal_variance,
        paired=str(group_structure) == "paired",
        alternative=str(alternative),
        alpha=alpha,
    )
    _render_selection_result(st, result)


def _render_statistical_test_runner(
    st: Any,
    df: pd.DataFrame,
    alpha: float,
    *,
    dataset_name: str | None = None,
) -> None:
    render_section_header(
        st,
        "Run Statistical Test",
        "Run a narrow numeric one-sample or two-group test against selected columns.",
    )
    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    if not numeric_columns:
        st.info("Need at least one numeric column to run a statistical test.")
        return

    mode = st.selectbox(
        "Test mode",
        ["One-sample numeric t-test", "Two-group numeric t-test"],
        key=_STATS_RUN_MODE,
    )
    alternative = st.selectbox(
        "Test alternative",
        _ALTERNATIVE_CHOICES,
        key=_STATS_RUN_ALTERNATIVE,
    )
    if mode is None or alternative is None:
        return

    metric = st.selectbox("Test metric", numeric_columns, key=_STATS_RUN_METRIC)
    if metric is None:
        return

    if str(mode).startswith("One-sample"):
        null_mean = _number_input_float(st, "Null mean", value=0.0, key=_STATS_RUN_NULL_MEAN)
        result = run_one_sample_numeric_test(
            df,
            str(metric),
            null_mean=null_mean,
            alpha=alpha,
            alternative=str(alternative),
        )
        _render_public_test_result(
            st,
            result,
            source="statistical test",
            save_key=_SAVE_STATISTICAL_TEST_RESULTS_BTN,
            save_label="Save statistical test result to Workspace",
            dataset_name=dataset_name,
        )
        return

    group_columns = _group_candidate_columns(df)
    if not group_columns:
        st.info("Need a grouping column with at least two values for a two-group test.")
        return
    group_col = st.selectbox("Test group column", group_columns, key=_STATS_RUN_GROUP)
    if group_col is None:
        return
    values = [str(v) for v in df[str(group_col)].dropna().unique().tolist()]
    a_value, b_value = _select_distinct_pair(
        st,
        values,
        a_key=_STATS_RUN_A,
        b_key=_STATS_RUN_B,
    )
    if a_value is None or b_value is None:
        st.info("Selected group column needs at least two distinct values.")
        return
    null_difference = _number_input_float(
        st,
        "Null difference",
        value=0.0,
        key=_STATS_RUN_NULL_DIFF,
    )
    equal_variance = _select_equal_variance(st, key=_STATS_RUN_EQUAL_VARIANCE)
    result = run_two_sample_numeric_test(
        df,
        str(metric),
        str(group_col),
        a_value,
        b_value,
        equal_variance_assumed=equal_variance,
        null_difference=null_difference,
        alpha=alpha,
        alternative=str(alternative),
    )
    _render_public_test_result(
        st,
        result,
        source="statistical test",
        save_key=_SAVE_STATISTICAL_TEST_RESULTS_BTN,
        save_label="Save statistical test result to Workspace",
        dataset_name=dataset_name,
    )


def _render_two_sample_result(
    st: Any,
    result: Mapping[str, Any],
    *,
    dataset_name: str | None = None,
) -> None:
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
    _render_downloadable_result_table(
        st,
        _two_group_tests_dataframe(result),
        download_label="Download group comparison tests (CSV)",
        file_name=_STATISTICS_TEST_RESULTS_FILE,
        save_label="Save group comparison tests to Workspace",
        save_key=_SAVE_GROUP_TEST_RESULTS_BTN,
        artifact="statistics_test_results",
        dataset_name=dataset_name,
    )
    st.caption(result["interpretation"])
    if not _evidence_requested(st, _STATS_TWO_GROUP_SHOW_EVIDENCE):
        return
    _render_group_evidence(
        st,
        [
            {"group": result["group_a"], "n": result.get("n_a"), "center": result.get("mean_a")},
            {"group": result["group_b"], "n": result.get("n_b"), "center": result.get("mean_b")},
        ],
        guidance_for_two_group(result),
        caption="Group means and sizes from the comparison already computed above.",
    )


def _render_nonparametric_effect_sizes(
    st: Any,
    df: pd.DataFrame,
    metric: str,
    group_col: str,
    alpha: float,
    *,
    dataset_name: str | None = None,
) -> None:
    """Surface Cliff's delta + Hodges-Lehmann shift for the two-group split.

    Additive to the existing two-group result; uses ``confidence = 1 - alpha`` so
    the band tracks the panel's significance level without a new control.
    """
    render_section_header(
        st,
        "Nonparametric effect sizes",
        "Cliff's delta and the Hodges-Lehmann location shift for the two groups.",
    )
    result = nonparametric_effect_sizes(df, metric, group_col, confidence=1.0 - alpha)
    if result.get("status") != "ok":
        render_info_state(st, str(result.get("reason")))
        return
    hodges_lehmann = result["hodges_lehmann"]
    cards = [
        {"label": "Cliff's delta", "value": _format_number(result["cliffs_delta"])},
        {"label": "Effect size interpretation", "value": str(result["cliffs_interpretation"])},
        {"label": "Sample sizes", "value": f"{result['n_a']:,} · {result['n_b']:,}"},
        {
            "label": "Hodges-Lehmann estimate",
            "value": _format_number(hodges_lehmann.get("estimate")),
        },
    ]
    if hodges_lehmann.get("status") == "ok":
        cards.extend(
            [
                {"label": "Lower bound", "value": _format_number(hodges_lehmann.get("lower"))},
                {"label": "Upper bound", "value": _format_number(hodges_lehmann.get("upper"))},
                {"label": "Method", "value": str(hodges_lehmann.get("method") or "—")},
            ]
        )
    render_metric_cards(st, cards)
    _render_downloadable_result_table(
        st,
        _effect_size_result_dataframe(result),
        download_label="Download effect sizes (CSV)",
        file_name=_STATISTICS_EFFECT_SIZES_FILE,
        save_label="Save effect sizes to Workspace",
        save_key=_SAVE_EFFECT_SIZES_BTN,
        artifact="statistics_effect_sizes",
        dataset_name=dataset_name,
    )
    confidence_pct = float(result.get("confidence") or 0.0) * 100.0
    st.caption(
        f"Cliff's delta and Hodges-Lehmann orient as {result['group_a']} vs "
        f"{result['group_b']} (positive favors {result['group_a']}); "
        f"{confidence_pct:.0f}% Hodges-Lehmann interval."
    )
    if hodges_lehmann.get("status") != "ok":
        render_info_state(
            st,
            f"Hodges-Lehmann confidence interval unavailable: " f"{hodges_lehmann.get('reason')}",
        )
    if not _evidence_requested(st, _STATS_EFFECT_SHOW_EVIDENCE):
        return
    _render_estimate_evidence(
        st,
        [
            {
                "label": "Hodges-Lehmann shift",
                "estimate": hodges_lehmann.get("estimate"),
                "lower": hodges_lehmann.get("lower"),
                "upper": hodges_lehmann.get("upper"),
                "confidence": result.get("confidence"),
                "n": None,
            }
        ],
        guidance_for_effect_sizes(result),
        reference=0.0,
        caption=(
            f"Hodges-Lehmann location shift for {result['group_a']} versus "
            f"{result['group_b']}, against a zero-shift reference"
        ),
    )


_ASSUMPTION_NONE_GROUP = "— none (single column) —"


def _render_assumption_checks(
    st: Any,
    df: pd.DataFrame,
    alpha: float,
    *,
    dataset_name: str | None = None,
) -> None:
    """Display informational assumption checks near the statistical-test workflows.

    Helps operators interpret tests (normality, equal variance, sample size,
    missingness). Informational only: these checks never change which test is
    selected or any p-value verdict.
    """
    render_section_header(
        st,
        "Assumption checks",
        "Informational normality, equal-variance, and sample-size checks for "
        "interpreting statistical tests.",
    )
    st.caption(
        "These checks are informational: they do not automatically change the selected "
        "test or any p-value verdict. Interpret them alongside your domain context."
    )
    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    if not numeric_columns:
        st.info("Need at least one numeric column to check assumptions.")
        return
    metric = st.selectbox(
        "Numeric column for assumption checks",
        numeric_columns,
        key=_STATS_ASSUMPTION_METRIC,
    )
    if metric is None:
        return
    group_options = [
        _ASSUMPTION_NONE_GROUP,
        *[column for column in _group_candidate_columns(df) if column != metric],
    ]
    group_choice = st.selectbox("Group by (optional)", group_options, key=_STATS_ASSUMPTION_GROUP)
    if group_choice is None or group_choice == _ASSUMPTION_NONE_GROUP:
        result = assumption_checks_one_sample(df, str(metric), alpha=alpha)
    else:
        result = assumption_checks_grouped(df, str(metric), str(group_choice), alpha=alpha)
    if result.get("status") != "ok":
        render_info_state(st, str(result.get("reason") or "Assumption checks unavailable."))
        return
    table = assumption_checks_dataframe(result)
    if table is None:
        render_info_state(st, "No assumption checks to display for this selection.")
        return
    _render_downloadable_result_table(
        st,
        table,
        download_label="Download assumption checks (CSV)",
        file_name=_STATISTICS_ASSUMPTIONS_FILE,
        save_label="Save assumption checks to Workspace",
        save_key=_SAVE_ASSUMPTION_CHECKS_BTN,
        artifact="statistics_assumption_checks",
        dataset_name=dataset_name,
    )
    for warning in result.get("warnings") or []:
        st.caption(str(warning))
    for check in result.get("checks") or []:
        interpretation = str(check.get("interpretation") or "")
        caveat = check.get("caveat")
        suffix = f" ({caveat})" if caveat else ""
        st.caption(f"{check.get('name')}: {check.get('status')} — {interpretation}{suffix}")
    if _evidence_requested(st, _STATS_ASSUMPTION_SHOW_GUIDANCE, _GUIDANCE_CHECKBOX_LABEL):
        _render_guidance(st, guidance_for_assumptions(result))


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


def _render_group_comparison(
    st: Any,
    df: pd.DataFrame,
    alpha: float,
    *,
    dataset_name: str | None = None,
) -> None:
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
        _render_two_sample_result(
            st,
            two_group_comparison(df, metric, group_col, alpha=alpha),
            dataset_name=dataset_name,
        )
        _render_nonparametric_effect_sizes(
            st,
            df,
            metric,
            group_col,
            alpha,
            dataset_name=dataset_name,
        )
        return
    result = multi_group_comparison(df, metric, group_col, alpha=alpha)
    summary = group_summary_dataframe(result)
    if summary is not None:
        st.dataframe(summary, hide_index=True)
    if result.get("status") != "ok":
        render_info_state(st, str(result.get("reason") or result.get("interpretation")))
        return
    _render_downloadable_result_table(
        st,
        _multi_group_tests_dataframe(result),
        download_label="Download group comparison tests (CSV)",
        file_name=_STATISTICS_TEST_RESULTS_FILE,
        save_label="Save group comparison tests to Workspace",
        save_key=_SAVE_GROUP_TEST_RESULTS_BTN,
        artifact="statistics_test_results",
        dataset_name=dataset_name,
    )
    st.caption(result["interpretation"])
    if not _evidence_requested(st, _STATS_MULTI_GROUP_SHOW_EVIDENCE):
        return
    _render_group_evidence(
        st,
        [
            {"group": group.get("group"), "n": group.get("n"), "center": group.get("mean")}
            for group in result.get("groups") or []
        ],
        guidance_for_multi_group(result),
        caption="Group means and sizes from the omnibus comparison already computed above.",
        omnibus=True,
    )


def _render_ab_comparison(
    st: Any,
    df: pd.DataFrame,
    alpha: float,
    *,
    dataset_name: str | None = None,
) -> None:
    render_section_header(
        st,
        "A/B Comparison",
        "A/B comparison for two selected group values on a numeric metric.",
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
    a_value, b_value = _select_distinct_pair(
        st,
        values,
        a_key=_STATS_AB_A,
        b_key=_STATS_AB_B,
    )
    metric = st.selectbox("Numeric metric", numeric_columns, key=_STATS_AB_METRIC)
    if a_value is None or b_value is None or metric is None:
        return
    equal_variance = _select_equal_variance(st, key=_STATS_AB_EQUAL_VARIANCE)
    alternative = st.selectbox(
        "A/B alternative",
        _ALTERNATIVE_CHOICES,
        key=_STATS_AB_ALTERNATIVE,
    )
    if alternative is None:
        return
    _render_public_test_result(
        st,
        compare_numeric_ab(
            df,
            str(group_col),
            a_value,
            b_value,
            str(metric),
            equal_variance_assumed=equal_variance,
            alpha=alpha,
            alternative=str(alternative),
        ),
        source="A/B comparison",
        save_key=_SAVE_AB_TEST_RESULTS_BTN,
        save_label="Save A/B test result to Workspace",
        dataset_name=dataset_name,
    )


def _wilcoxon_result_dataframe(result: Mapping[str, Any]) -> pd.DataFrame:
    """Build a one-row export table for a Wilcoxon signed-rank result."""
    return _result_dataframe(
        {
            "test": result.get("test_name"),
            "method": result.get("method"),
            "column_a": result.get("column_a"),
            "column_b": result.get("column_b"),
            "alternative": result.get("alternative"),
            "n_pairs": result.get("n_pairs"),
            "n_nonzero_differences": result.get("n_nonzero_differences"),
            "statistic": result.get("statistic"),
            "p_value": result.get("p_value"),
            "alpha": result.get("alpha"),
            "significant": result.get("significant"),
        }
    )


def _render_wilcoxon(
    st: Any,
    df: pd.DataFrame,
    alpha: float,
    *,
    dataset_name: str | None = None,
) -> None:
    """Paired/dependent-samples Wilcoxon signed-rank test (user-selected option).

    Informational and user-driven: it is offered as an explicit paired test and
    does not change any automatic test recommendation or verdict threshold.
    """
    render_section_header(
        st,
        "Paired samples — Wilcoxon signed-rank",
        "Nonparametric test for paired/dependent observations. Does not change "
        "automatic test recommendations.",
    )
    st.caption(
        "For paired/dependent numeric columns (e.g., before/after on the same rows). "
        "Tests whether the paired differences are centered at zero; it is not the same "
        "as Mann-Whitney U, which is for independent samples."
    )
    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    if len(numeric_columns) < 2:
        st.info("Need at least two numeric columns for a paired Wilcoxon test.")
        return
    column_a = st.selectbox("First numeric column", numeric_columns, key=_STATS_WILCOXON_COL_A)
    if column_a is None:
        return
    b_options = [column for column in numeric_columns if column != column_a]
    if not b_options:
        st.info("Need a second distinct numeric column for a paired test.")
        return
    column_b = st.selectbox("Second numeric column", b_options, key=_STATS_WILCOXON_COL_B)
    alternative = st.selectbox("Alternative", _ALTERNATIVE_CHOICES, key=_STATS_WILCOXON_ALTERNATIVE)
    if column_b is None or alternative is None:
        return
    result = paired_wilcoxon_test(
        df, str(column_a), str(column_b), alpha=alpha, alternative=str(alternative)
    )
    status = str(result.get("status") or "unknown")
    if status != "ok":
        message = str(result.get("reason") or result.get("interpretation") or f"Status: {status}")
        if status == "unavailable":
            render_warning_state(st, message)
        else:
            render_info_state(st, message)
        return
    significant = result.get("significant")
    decision = "reject null (differences ≠ 0)" if significant else "do not reject null"
    render_metric_cards(
        st,
        [
            {"label": "Statistic (W)", "value": _format_number(result.get("statistic"))},
            {"label": "p-value", "value": _format_number(result.get("p_value"))},
            {"label": "Pairs", "value": _format_int(result.get("n_pairs"))},
            {"label": "Non-zero diffs", "value": _format_int(result.get("n_nonzero_differences"))},
            {"label": "Decision", "value": decision},
        ],
    )
    _render_downloadable_result_table(
        st,
        _wilcoxon_result_dataframe(result),
        download_label="Download Wilcoxon result (CSV)",
        file_name=_STATISTICS_WILCOXON_FILE,
        save_label="Save Wilcoxon result to Workspace",
        save_key=_SAVE_WILCOXON_BTN,
        artifact="statistics_wilcoxon",
        dataset_name=dataset_name,
    )
    st.caption(f"{result.get('interpretation', '')} (alternative={result.get('alternative')})")
    if result.get("caveat"):
        st.caption(str(result["caveat"]))
    if _evidence_requested(st, _STATS_WILCOXON_SHOW_EVIDENCE):
        render_paired_evidence(
            st,
            result,
            frame=df,
            column_a=str(column_a),
            column_b=str(column_b),
        )


def _render_confidence_interval_result(
    st: Any,
    result: Mapping[str, Any],
    *,
    dataset_name: str | None = None,
    label: str = "Mean",
) -> None:
    """Render a confidence-interval result safely from its status dict."""
    status = str(result.get("status") or "unknown")
    if status != "ok":
        message = str(
            result.get("reason") or f"Confidence interval unavailable (status: {status})."
        )
        if status == "unavailable":
            render_warning_state(st, message)
        else:
            render_info_state(st, message)
        return
    render_metric_cards(
        st,
        [
            {"label": "Estimate", "value": _format_number(result.get("point"))},
            {"label": "Lower bound", "value": _format_number(result.get("lower"))},
            {"label": "Upper bound", "value": _format_number(result.get("upper"))},
            {"label": "Method", "value": str(result.get("method") or "—")},
        ],
    )
    _render_downloadable_result_table(
        st,
        _confidence_interval_result_dataframe(result),
        download_label="Download confidence interval (CSV)",
        file_name=_STATISTICS_INTERVALS_FILE,
        save_label="Save confidence interval to Workspace",
        save_key=_SAVE_CONFIDENCE_INTERVALS_BTN,
        artifact="statistics_intervals",
        dataset_name=dataset_name,
    )
    confidence_pct = float(result.get("confidence") or 0.0) * 100.0
    st.caption(
        f"{confidence_pct:.0f}% confidence interval; n={result.get('n')}. "
        f"{result.get('interpretation') or ''}".strip()
    )
    if not _evidence_requested(st, _STATS_CI_SHOW_EVIDENCE):
        return
    _render_estimate_evidence(
        st,
        [
            {
                "label": label,
                "estimate": result.get("point"),
                "lower": result.get("lower"),
                "upper": result.get("upper"),
                "confidence": result.get("confidence"),
                "n": result.get("n"),
            }
        ],
        guidance_for_interval(result, label=label),
        caption="Point estimate with its interval",
    )


def _render_confidence_intervals(
    st: Any,
    df: pd.DataFrame,
    *,
    dataset_name: str | None = None,
) -> None:
    render_section_header(
        st,
        "Confidence interval",
        "Estimate a numeric column's mean with lower/upper bounds at a chosen confidence level.",
    )
    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    if not numeric_columns:
        st.info("Need at least one numeric column to estimate a confidence interval.")
        return
    column = st.selectbox("Confidence interval column", numeric_columns, key=_STATS_CI_COLUMN)
    method_label = st.selectbox("Method", list(_CI_METHODS), key=_STATS_CI_METHOD)
    confidence = st.selectbox(
        "Confidence level", list(confidence_interval_choices()), key=_STATS_CI_CONFIDENCE
    )
    if column is None or method_label is None or confidence is None:
        return
    kind, boot_method = _CI_METHODS[str(method_label)]
    if kind == "mean":
        result = mean_confidence_interval(df, str(column), confidence=float(confidence))
    else:
        resamples = st.selectbox(
            "Bootstrap resamples", _CI_RESAMPLE_CHOICES, key=_STATS_CI_RESAMPLES
        )
        result = bootstrap_mean_confidence_interval(
            df,
            str(column),
            confidence=float(confidence),
            n_bootstrap=int(resamples or _CI_RESAMPLE_CHOICES[0]),
            method=boot_method,
        )
    _render_confidence_interval_result(st, result, dataset_name=dataset_name)


def _render_inferential(
    st: Any,
    df: pd.DataFrame,
    *,
    dataset_name: str | None = None,
) -> None:
    render_section_header(
        st,
        "Inferential Tests / A-B Comparison",
        "Normality, group comparison, and A/B testing. p-values are uncorrected for "
        "multiple testing; interpret as guidance, not proof.",
    )
    alpha = st.selectbox("Significance level (alpha)", _ALPHA_CHOICES, key=_STATS_ALPHA)
    if alpha is None:
        alpha = _ALPHA_CHOICES[0]
    _render_hypothesis_wizard(st, float(alpha))
    _render_assumption_checks(st, df, float(alpha), dataset_name=dataset_name)
    if not inferential_available():
        render_warning_state(
            st,
            "Inferential statistics unavailable — install the [stats] extra "
            "(pip install data-quality-toolkit[stats]) to enable normality checks, "
            "group comparison, and A/B testing. Descriptive statistics above still work.",
        )
        _render_statistical_test_runner(st, df, float(alpha), dataset_name=dataset_name)
        _render_ab_comparison(st, df, float(alpha), dataset_name=dataset_name)
        render_paired_t_runner(st, df, float(alpha), dataset_name=dataset_name)
        _render_wilcoxon(st, df, float(alpha), dataset_name=dataset_name)
        render_proportion_tests_runner(st, df, float(alpha), dataset_name=dataset_name)
        render_chi_square_tests_runner(st, df, float(alpha), dataset_name=dataset_name)
        _render_confidence_intervals(st, df, dataset_name=dataset_name)
        return
    _render_normality(st, df, float(alpha))
    _render_group_comparison(st, df, float(alpha), dataset_name=dataset_name)
    _render_statistical_test_runner(st, df, float(alpha), dataset_name=dataset_name)
    _render_ab_comparison(st, df, float(alpha), dataset_name=dataset_name)
    render_paired_t_runner(st, df, float(alpha), dataset_name=dataset_name)
    _render_wilcoxon(st, df, float(alpha), dataset_name=dataset_name)
    render_proportion_tests_runner(st, df, float(alpha), dataset_name=dataset_name)
    render_chi_square_tests_runner(st, df, float(alpha), dataset_name=dataset_name)
    _render_confidence_intervals(st, df, dataset_name=dataset_name)


def _render_distribution_result(st: Any, result: Mapping[str, Any]) -> None:
    """Render a theoretical distribution result from the service status dict."""
    status = str(result.get("status") or "unknown")
    if status != "ok":
        message = str(result.get("reason") or f"Distribution lookup unavailable ({status}).")
        if status == "unavailable":
            render_warning_state(st, message)
        else:
            render_info_state(st, message)
        return

    cards = [
        {"label": "Value", "value": _format_number(result.get("value"))},
        {"label": "Distribution", "value": str(result.get("distribution") or "—")},
        {"label": "Calculation", "value": str(result.get("calculation") or "—")},
        {"label": "Method", "value": str(result.get("method") or "—")},
    ]
    if result.get("tail"):
        cards.append({"label": "Tail", "value": str(result.get("tail"))})
    render_metric_cards(st, cards)
    _render_downloadable_result_table(
        st,
        _distribution_result_dataframe(result),
        download_label="Download distribution result (CSV)",
        file_name=_STATISTICS_DISTRIBUTIONS_FILE,
        save_label="Save distribution result to Workspace",
        save_key=_SAVE_DISTRIBUTIONS_BTN,
        artifact="statistics_distributions",
    )

    parameters = result.get("parameters") or {}
    if parameters:
        st.dataframe(
            pd.DataFrame(
                [
                    {"parameter": str(name), "value": _format_number(value)}
                    for name, value in parameters.items()
                ]
            ),
            hide_index=True,
        )
    if result.get("explanation"):
        st.caption(str(result["explanation"]))


def _distribution_parameter_inputs(
    st: Any,
    distribution: str,
    calculation: str,
) -> dict[str, Any]:
    """Collect bounded distribution parameters from the UI controls."""
    params: dict[str, Any] = {}
    is_critical = calculation == "Critical value (two-tail)"

    if distribution == "Normal":
        if not is_critical:
            params["x"] = _bounded_number_input_float(
                st,
                "x value",
                value=0.0,
                min_value=-1_000_000.0,
                max_value=1_000_000.0,
                step=0.1,
                key=_STATS_DIST_X,
            )
            params["mu"] = _bounded_number_input_float(
                st,
                "Mean (mu)",
                value=0.0,
                min_value=-1_000_000.0,
                max_value=1_000_000.0,
                step=0.1,
                key=_STATS_DIST_MU,
            )
            params["sigma"] = _bounded_number_input_float(
                st,
                "Standard deviation (sigma)",
                value=1.0,
                min_value=0.000001,
                max_value=1_000_000.0,
                step=0.1,
                key=_STATS_DIST_SIGMA,
            )

    elif distribution == "Student t":
        if not is_critical:
            params["x"] = _bounded_number_input_float(
                st,
                "x value",
                value=0.0,
                min_value=-1_000_000.0,
                max_value=1_000_000.0,
                step=0.1,
                key=_STATS_DIST_X,
            )
        params["df"] = _bounded_number_input_float(
            st,
            "Degrees of freedom",
            value=10.0,
            min_value=0.000001,
            max_value=1_000_000.0,
            step=1.0,
            key=_STATS_DIST_DF,
        )

    elif distribution == "Chi-square":
        params["x"] = _bounded_number_input_float(
            st,
            "x value",
            value=1.0,
            min_value=0.0,
            max_value=1_000_000.0,
            step=0.1,
            key=_STATS_DIST_X,
        )
        params["df"] = _bounded_number_input_float(
            st,
            "Degrees of freedom",
            value=5.0,
            min_value=0.000001,
            max_value=1_000_000.0,
            step=1.0,
            key=_STATS_DIST_DF,
        )

    elif distribution == "F":
        params["x"] = _bounded_number_input_float(
            st,
            "x value",
            value=1.0,
            min_value=0.0,
            max_value=1_000_000.0,
            step=0.1,
            key=_STATS_DIST_X,
        )
        params["df1"] = _bounded_number_input_float(
            st,
            "Numerator degrees of freedom",
            value=5.0,
            min_value=0.000001,
            max_value=1_000_000.0,
            step=1.0,
            key=_STATS_DIST_DF1,
        )
        params["df2"] = _bounded_number_input_float(
            st,
            "Denominator degrees of freedom",
            value=20.0,
            min_value=0.000001,
            max_value=1_000_000.0,
            step=1.0,
            key=_STATS_DIST_DF2,
        )

    elif distribution == "Binomial":
        n = _bounded_number_input_int(
            st,
            "Trials (n)",
            value=10,
            min_value=0,
            max_value=100_000,
            step=1,
            key=_STATS_DIST_N,
        )
        params["n"] = n
        params["k"] = _bounded_number_input_int(
            st,
            "Count (k)",
            value=min(3, n),
            min_value=0,
            max_value=max(0, n),
            step=1,
            key=_STATS_DIST_K,
        )
        params["p"] = _bounded_number_input_float(
            st,
            "Success probability (p)",
            value=0.5,
            min_value=0.0,
            max_value=1.0,
            step=0.01,
            key=_STATS_DIST_P,
        )

    elif distribution == "Poisson":
        params["k"] = _bounded_number_input_int(
            st,
            "Count (k)",
            value=3,
            min_value=0,
            max_value=100_000,
            step=1,
            key=_STATS_DIST_K,
        )
        params["lam"] = _bounded_number_input_float(
            st,
            "Rate (lambda)",
            value=3.0,
            min_value=0.000001,
            max_value=1_000_000.0,
            step=0.1,
            key=_STATS_DIST_LAM,
        )

    if is_critical:
        params["alpha"] = float(
            st.selectbox("Two-tail alpha", _ALPHA_CHOICES, key=_STATS_DIST_ALPHA)
            or _ALPHA_CHOICES[0]
        )

    return params


# The axis a bounded distribution curve varies for each supported family. A
# calculation without a value axis (a two-tail critical value) has no curve.
_DISTRIBUTION_AXIS: dict[str, str] = {
    "Normal": "x",
    "Student t": "x",
    "Chi-square": "x",
    "F": "x",
    "Binomial": "k",
    "Poisson": "k",
}


def _distribution_axis_range(
    distribution: str, params: Mapping[str, Any]
) -> tuple[float, float] | None:
    """Return the bounded plotting range for a supported distribution's value axis."""
    if distribution == "Normal":
        mu = float(params.get("mu", 0.0))
        sigma = float(params.get("sigma", 1.0))
        x = float(params.get("x", mu))
        return min(mu - 4.0 * sigma, x), max(mu + 4.0 * sigma, x)
    if distribution == "Student t":
        x = float(params.get("x", 0.0))
        return min(-4.0, x - 1.0), max(4.0, x + 1.0)
    if distribution in {"Chi-square", "F"}:
        x = float(params.get("x", 1.0))
        return 0.0, max(5.0, x * 2.0)
    if distribution == "Binomial":
        return 0.0, max(0.0, float(params.get("n", 0)))
    if distribution == "Poisson":
        k = float(params.get("k", 0))
        lam = float(params.get("lam", 1.0))
        return 0.0, max(k + 5.0, lam * 3.0 + 5.0)
    return None


def _distribution_shading(calculation: str, selected: float) -> tuple[float | None, float | None]:
    """Return the region the existing calculation covers, or no region for a density."""
    if calculation == "CDF":
        return None, selected
    if calculation == "PMF":
        return selected, selected
    return None, None


def _distribution_evaluator(
    distribution: str,
    calculation: str,
    params: Mapping[str, Any],
    axis: str,
    *,
    discrete: bool,
) -> Callable[[float], Mapping[str, Any]]:
    """Bind the existing distribution lookup to one varying axis value."""

    def evaluate(value: float) -> Mapping[str, Any]:
        merged = dict(params)
        merged[axis] = int(round(value)) if discrete else float(value)
        return theoretical_distribution_result(distribution, calculation, **merged)

    return evaluate


def _distribution_spec(*, discrete: bool, marker: float | None) -> dict[str, Any]:
    """Vega-Lite spec for the bounded curve, its shaded region and the selected point."""
    encoding: dict[str, Any] = {
        "x": {"field": "x", "type": "quantitative", "title": "Value"},
        "y": {"field": "value", "type": "quantitative", "title": "Probability / density"},
        "tooltip": [
            {"field": "x", "type": "quantitative"},
            {"field": "value", "type": "quantitative"},
            {"field": "shaded", "type": "nominal", "title": "In calculated region"},
        ],
    }
    layers: list[dict[str, Any]] = []
    if discrete:
        bar_encoding = dict(encoding)
        bar_encoding["color"] = {
            "field": "shaded",
            "type": "nominal",
            "title": "In calculated region",
        }
        layers.append({"mark": {"type": "bar"}, "encoding": bar_encoding})
    else:
        layers.append(
            {
                "transform": [{"filter": "datum.shaded"}],
                "mark": {"type": "area", "opacity": 0.3},
                "encoding": encoding,
            }
        )
        layers.append({"mark": {"type": "line"}, "encoding": encoding})
    if marker is not None:
        layers.append(
            {
                "mark": {"type": "rule", "color": "red", "strokeDash": [4, 4]},
                "encoding": {"x": {"datum": marker}},
            }
        )
    return {"layer": layers}


def _render_distribution_curve(
    st: Any,
    distribution: str,
    calculation: str,
    params: Mapping[str, Any],
    result: Mapping[str, Any],
) -> None:
    """Render the opt-in bounded curve beside an existing distribution lookup."""
    guidance = guidance_for_distribution(result)
    axis = _DISTRIBUTION_AXIS.get(distribution)
    bounds: tuple[float, float] | None = None
    selected: float | None = None
    if axis is not None and axis in params:
        try:
            bounds = _distribution_axis_range(distribution, params)
            selected = float(params[axis])
        except (TypeError, ValueError):
            bounds, selected = None, None
    if axis is None or bounds is None or selected is None:
        render_info_state(
            st,
            "A bounded curve is not available for this calculation; the value above is a "
            "single lookup against the same distribution.",
        )
        _render_guidance(st, guidance)
        return
    discrete = axis == "k"
    grid = build_parameter_grid(
        bounds[0],
        bounds[1],
        points=DISTRIBUTION_CURVE_MAX_POINTS,
        maximum=DISTRIBUTION_CURVE_MAX_POINTS,
        integer=discrete,
    )
    shade_lower, shade_upper = _distribution_shading(calculation, selected)
    evidence = build_distribution_curve(
        _distribution_evaluator(distribution, calculation, params, axis, discrete=discrete),
        grid,
        marker=selected,
        shade_lower=shade_lower,
        shade_upper=shade_upper,
    )
    if evidence["status"] != "ok":
        render_info_state(st, f"Curve unavailable: {evidence['reason']}.")
        _render_guidance(st, guidance)
        return
    st.caption(
        f"{distribution} {calculation} across {evidence['points']:,} bounded points "
        f"(capped at {DISTRIBUTION_CURVE_MAX_POINTS}); the marker is the selected value."
    )
    st.vega_lite_chart(
        evidence["data"],
        _distribution_spec(
            discrete=discrete,
            marker=evidence["marker"] if evidence["marker_available"] else None,
        ),
        use_container_width=True,
    )
    if evidence["invalid_points"]:
        st.caption(
            f"{evidence['invalid_points']:,} point(s) were skipped because the lookup was "
            "undefined there; no value was substituted."
        )
    st.caption(_DISTRIBUTION_CAVEAT)
    _render_guidance(st, guidance)


def _render_distribution_lookup(st: Any) -> None:
    """Render the theoretical Distributions planning tab."""
    render_section_header(
        st,
        "Theoretical distributions",
        "Lookup PMF/PDF/CDF values and available two-tail critical values.",
    )
    distribution = st.selectbox(
        "Distribution",
        list(distribution_choices()),
        key=_STATS_DIST_DISTRIBUTION,
    )
    if distribution is None:
        return
    calculations = list(distribution_calculation_choices(str(distribution)))
    calculation = st.selectbox(
        "Calculation",
        calculations,
        key=_STATS_DIST_CALCULATION,
    )
    if calculation is None:
        return

    params = _distribution_parameter_inputs(st, str(distribution), str(calculation))
    result = theoretical_distribution_result(str(distribution), str(calculation), **params)
    _render_distribution_result(st, result)
    if _evidence_requested(st, _STATS_DIST_SHOW_CURVE, _CURVE_CHECKBOX_LABEL):
        _render_distribution_curve(st, str(distribution), str(calculation), params, result)


def _render_power_result(
    st: Any,
    result: Mapping[str, Any],
    *,
    cards: list[dict[str, Any]],
    interpretation: str,
    table: pd.DataFrame,
) -> None:
    """Render a power/sample-size result safely from its status dict."""
    status = str(result.get("status") or "unknown")
    if status != "ok":
        message = str(result.get("reason") or f"Power analysis unavailable (status: {status}).")
        if status == "unavailable":
            render_warning_state(st, message)
        else:
            render_info_state(st, message)
        return
    render_metric_cards(st, cards)
    _render_downloadable_result_table(
        st,
        table,
        download_label="Download power/sample-size result (CSV)",
        file_name=_STATISTICS_POWER_SAMPLE_SIZE_FILE,
        save_label="Save power/sample-size result to Workspace",
        save_key=_SAVE_POWER_SAMPLE_SIZE_BTN,
        artifact="statistics_power_sample_size",
    )
    if interpretation:
        st.caption(interpretation)


def _power_sample_size_grid(selected: int) -> list[float]:
    """Bounded integer sample-size grid around the entered sample size."""
    return build_parameter_grid(
        2.0,
        max(10.0, float(selected) * 3.0),
        points=POWER_CURVE_MAX_POINTS,
        maximum=POWER_CURVE_MAX_POINTS,
        integer=True,
    )


def _effect_size_grid(selected: float) -> list[float]:
    """Bounded effect-size grid around the entered effect, keeping its sign."""
    low, high = sorted((selected / 4.0, selected * 3.0))
    return build_parameter_grid(
        low,
        high,
        points=POWER_CURVE_MAX_POINTS,
        maximum=POWER_CURVE_MAX_POINTS,
    )


def _power_curve_plan(
    kind: str,
    *,
    alpha: float,
    alternative: str,
    power_target: float | None,
    inputs: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Bind one existing power calculator to a single varying planning parameter.

    Returns None for an analysis type that has no supported varying axis; no new
    power formula is introduced for any branch.
    """
    if kind == "power_mean":
        n = int(inputs["n"])
        delta = float(inputs["delta"])
        sigma = float(inputs["sigma"])
        return {
            "evaluate": lambda value: power_mean(
                int(value), delta, sigma, alpha=alpha, alternative=alternative
            ),
            "grid": _power_sample_size_grid(n),
            "value_field": "power",
            "selected": float(n),
            "x_title": "Sample size (n)",
            "y_title": "Power",
        }
    if kind == "power_prop":
        n = int(inputs["n"])
        p1 = float(inputs["p1"])
        p2 = float(inputs["p2"])
        return {
            "evaluate": lambda value: power_prop(
                int(value), p1, p2, alpha=alpha, alternative=alternative
            ),
            "grid": _power_sample_size_grid(n),
            "value_field": "power",
            "selected": float(n),
            "x_title": "Sample size per group (n)",
            "y_title": "Power",
        }
    if kind == "n_mean" and power_target is not None:
        delta = float(inputs["delta"])
        sigma = float(inputs["sigma"])
        return {
            "evaluate": lambda value: required_n_mean(
                float(value), sigma, alpha=alpha, power=power_target, alternative=alternative
            ),
            "grid": _effect_size_grid(delta),
            "value_field": "n",
            "selected": delta,
            "x_title": "Effect size (mean difference)",
            "y_title": "Required sample size",
        }
    if kind == "n_cohend" and power_target is not None:
        delta = float(inputs["delta"])
        return {
            "evaluate": lambda value: required_n_cohend(
                float(value), alpha=alpha, power=power_target
            ),
            "grid": _effect_size_grid(delta),
            "value_field": "n_per_group",
            "selected": delta,
            "x_title": "Effect size (Cohen's d)",
            "y_title": "Required sample size per group",
        }
    return None


def _power_curve_spec(plan: Mapping[str, Any], selected: float | None) -> dict[str, Any]:
    """Vega-Lite spec for a bounded planning curve with the selected point marked."""
    layers: list[dict[str, Any]] = [
        {
            "mark": {"type": "line", "point": True},
            "encoding": {
                "x": {"field": "parameter", "type": "quantitative", "title": plan["x_title"]},
                "y": {"field": "value", "type": "quantitative", "title": plan["y_title"]},
                "tooltip": [
                    {"field": "parameter", "type": "quantitative", "title": plan["x_title"]},
                    {"field": "value", "type": "quantitative", "title": plan["y_title"]},
                ],
            },
        }
    ]
    if selected is not None:
        layers.append(
            {
                "mark": {"type": "rule", "color": "red", "strokeDash": [4, 4]},
                "encoding": {"x": {"datum": selected}},
            }
        )
    return {"layer": layers}


def _render_power_curve(
    st: Any,
    result: Mapping[str, Any],
    *,
    kind: str,
    analysis_label: str,
    alpha: float,
    alternative: str = "two-sided",
    power_target: float | None = None,
    inputs: Mapping[str, Any],
) -> None:
    """Render the opt-in bounded planning curve beside an existing power result.

    The curve is offered only once a completed result exists and only for the
    analysis types the existing calculators already support.
    """
    if str(result.get("status") or "") != "ok":
        return
    if not _evidence_requested(st, _STATS_POWER_SHOW_CURVE, _CURVE_CHECKBOX_LABEL):
        return
    guidance = guidance_for_power(
        result, analysis=analysis_label, alpha=alpha, alternative=alternative
    )
    plan = _power_curve_plan(
        kind,
        alpha=alpha,
        alternative=alternative,
        power_target=power_target,
        inputs=inputs,
    )
    if plan is None:
        render_info_state(st, "A bounded curve is not offered for this analysis type.")
        _render_guidance(st, guidance)
        return
    evidence = build_power_curve(
        plan["evaluate"],
        plan["grid"],
        value_field=str(plan["value_field"]),
        selected=plan["selected"],
    )
    if evidence["status"] != "ok":
        render_info_state(st, f"Curve unavailable: {evidence['reason']}.")
        _render_guidance(st, guidance)
        return
    st.caption(
        f"{plan['y_title']} against {plan['x_title'].lower()} across "
        f"{evidence['points']:,} bounded points (capped at {POWER_CURVE_MAX_POINTS}), "
        f"at alpha={_format_number(alpha)} with a {alternative} alternative."
    )
    st.vega_lite_chart(
        evidence["data"],
        _power_curve_spec(plan, evidence["selected"] if evidence["selected_available"] else None),
        use_container_width=True,
    )
    if evidence["invalid_points"]:
        st.caption(
            f"{evidence['invalid_points']:,} point(s) were skipped because the calculation "
            "is undefined there; no value was substituted."
        )
    st.caption(_POWER_CURVE_CAVEAT)
    _render_guidance(st, guidance)


def _render_power_analysis(st: Any) -> None:
    """Render the Power & Sample size planning tab (dataset-independent)."""
    render_section_header(
        st,
        "Power & sample size",
        "Plan a study: estimate statistical power or the sample size needed to detect an "
        "effect. This is a planning tool and does not require a dataset.",
    )
    analysis_label = st.selectbox("Analysis type", list(_POWER_ANALYSES), key=_STATS_POWER_ANALYSIS)
    if analysis_label is None:
        return
    kind = _POWER_ANALYSES[str(analysis_label)]
    alpha = float(
        st.selectbox("Alpha (significance level)", _ALPHA_CHOICES, key=_STATS_POWER_ALPHA)
        or _ALPHA_CHOICES[0]
    )

    if kind == "power_mean":
        n = int(_number_input_float(st, "Sample size (n)", value=50.0, key=_STATS_POWER_N))
        delta = _number_input_float(
            st, "Effect size (mean difference)", value=0.5, key=_STATS_POWER_DELTA
        )
        sigma = _number_input_float(st, "Standard deviation", value=1.0, key=_STATS_POWER_SIGMA)
        alternative = str(
            st.selectbox("Alternative", _ALTERNATIVE_CHOICES, key=_STATS_POWER_ALTERNATIVE)
            or _ALTERNATIVE_CHOICES[0]
        )
        result = power_mean(n, delta, sigma, alpha=alpha, alternative=alternative)
        cards = [
            {"label": "Power", "value": _format_power(result.get("power"))},
            {"label": "Alpha", "value": _format_number(alpha)},
            {"label": "Effect size", "value": _format_number(delta)},
            {"label": "Method", "value": str(result.get("method") or "—")},
        ]
        interpretation = (
            f"At α={_format_number(alpha)} with n={n}, this design has "
            f"{_format_power(result.get('power'))} power to detect a mean difference of "
            f"{_format_number(delta)} (sd={_format_number(sigma)}, {alternative})."
        )
        _render_power_result(
            st,
            result,
            cards=cards,
            interpretation=interpretation,
            table=_result_dataframe(
                {
                    "analysis": analysis_label,
                    "method": result.get("method"),
                    "n": n,
                    "delta": delta,
                    "sigma": sigma,
                    "alpha": alpha,
                    "alternative": alternative,
                    "power": result.get("power"),
                }
            ),
        )
        _render_power_curve(
            st,
            result,
            kind=kind,
            analysis_label=str(analysis_label),
            alpha=alpha,
            alternative=alternative,
            inputs={"n": n, "delta": delta, "sigma": sigma},
        )

    elif kind == "power_prop":
        n = int(
            _number_input_float(st, "Sample size per group (n)", value=100.0, key=_STATS_POWER_N)
        )
        p1 = _number_input_float(st, "Baseline proportion (p1)", value=0.5, key=_STATS_POWER_P1)
        p2 = _number_input_float(st, "Comparison proportion (p2)", value=0.6, key=_STATS_POWER_P2)
        alternative = str(
            st.selectbox("Alternative", _ALTERNATIVE_CHOICES, key=_STATS_POWER_ALTERNATIVE)
            or _ALTERNATIVE_CHOICES[0]
        )
        result = power_prop(n, p1, p2, alpha=alpha, alternative=alternative)
        cards = [
            {"label": "Power", "value": _format_power(result.get("power"))},
            {"label": "Alpha", "value": _format_number(alpha)},
            {
                "label": "Effect size",
                "value": f"{_format_number(p1)} → {_format_number(p2)}",
            },
            {"label": "Method", "value": str(result.get("method") or "—")},
        ]
        interpretation = (
            f"At α={_format_number(alpha)} with n={n} per group, this design has "
            f"{_format_power(result.get('power'))} power to detect a shift from "
            f"{_format_number(p1)} to {_format_number(p2)} ({alternative})."
        )
        _render_power_result(
            st,
            result,
            cards=cards,
            interpretation=interpretation,
            table=_result_dataframe(
                {
                    "analysis": analysis_label,
                    "method": result.get("method"),
                    "n_per_group": n,
                    "p1": p1,
                    "p2": p2,
                    "alpha": alpha,
                    "alternative": alternative,
                    "power": result.get("power"),
                }
            ),
        )
        _render_power_curve(
            st,
            result,
            kind=kind,
            analysis_label=str(analysis_label),
            alpha=alpha,
            alternative=alternative,
            inputs={"n": n, "p1": p1, "p2": p2},
        )

    elif kind == "n_mean":
        power_target = float(
            st.selectbox("Target power", list(power_target_choices()), key=_STATS_POWER_TARGET)
            or power_target_choices()[0]
        )
        delta = _number_input_float(
            st, "Effect size (mean difference)", value=0.5, key=_STATS_POWER_DELTA
        )
        sigma = _number_input_float(st, "Standard deviation", value=1.0, key=_STATS_POWER_SIGMA)
        alternative = str(
            st.selectbox("Alternative", _ALTERNATIVE_CHOICES, key=_STATS_POWER_ALTERNATIVE)
            or _ALTERNATIVE_CHOICES[0]
        )
        result = required_n_mean(
            delta, sigma, alpha=alpha, power=power_target, alternative=alternative
        )
        cards = [
            {"label": "Required sample size", "value": _format_int(result.get("n"))},
            {"label": "Alpha", "value": _format_number(alpha)},
            {"label": "Target power", "value": _format_power(power_target)},
            {"label": "Effect size", "value": _format_number(delta)},
            {"label": "Method", "value": str(result.get("method") or "—")},
        ]
        interpretation = (
            f"To reach {_format_power(power_target)} power at α={_format_number(alpha)}, you "
            f"need about n={_format_int(result.get('n'))} to detect a mean difference of "
            f"{_format_number(delta)} (sd={_format_number(sigma)}, {alternative})."
        )
        _render_power_result(
            st,
            result,
            cards=cards,
            interpretation=interpretation,
            table=_result_dataframe(
                {
                    "analysis": analysis_label,
                    "method": result.get("method"),
                    "target_power": power_target,
                    "delta": delta,
                    "sigma": sigma,
                    "alpha": alpha,
                    "alternative": alternative,
                    "required_n": result.get("n"),
                }
            ),
        )
        _render_power_curve(
            st,
            result,
            kind=kind,
            analysis_label=str(analysis_label),
            alpha=alpha,
            alternative=alternative,
            power_target=power_target,
            inputs={"delta": delta, "sigma": sigma},
        )

    elif kind == "n_prop":
        power_target = float(
            st.selectbox("Target power", list(power_target_choices()), key=_STATS_POWER_TARGET)
            or power_target_choices()[0]
        )
        p1 = _number_input_float(st, "Baseline proportion (p1)", value=0.5, key=_STATS_POWER_P1)
        p2 = _number_input_float(st, "Comparison proportion (p2)", value=0.6, key=_STATS_POWER_P2)
        alternative = str(
            st.selectbox("Alternative", _ALTERNATIVE_CHOICES, key=_STATS_POWER_ALTERNATIVE)
            or _ALTERNATIVE_CHOICES[0]
        )
        result = required_n_prop(p1, p2, alpha=alpha, power=power_target, alternative=alternative)
        cards = [
            {
                "label": "Required sample size",
                "value": (
                    f"{_format_int(result.get('n1'))} / {_format_int(result.get('n2'))} "
                    "(per group)"
                ),
            },
            {"label": "Alpha", "value": _format_number(alpha)},
            {"label": "Target power", "value": _format_power(power_target)},
            {
                "label": "Effect size",
                "value": f"{_format_number(p1)} → {_format_number(p2)}",
            },
            {"label": "Method", "value": str(result.get("method") or "—")},
        ]
        interpretation = (
            f"To reach {_format_power(power_target)} power at α={_format_number(alpha)}, you "
            f"need about n={_format_int(result.get('n1'))} and "
            f"n={_format_int(result.get('n2'))} per group to detect a shift from "
            f"{_format_number(p1)} to {_format_number(p2)} ({alternative})."
        )
        _render_power_result(
            st,
            result,
            cards=cards,
            interpretation=interpretation,
            table=_result_dataframe(
                {
                    "analysis": analysis_label,
                    "method": result.get("method"),
                    "target_power": power_target,
                    "p1": p1,
                    "p2": p2,
                    "alpha": alpha,
                    "alternative": alternative,
                    "required_n1": result.get("n1"),
                    "required_n2": result.get("n2"),
                }
            ),
        )
        _render_power_curve(
            st,
            result,
            kind=kind,
            analysis_label=str(analysis_label),
            alpha=alpha,
            alternative=alternative,
            power_target=power_target,
            inputs={"p1": p1, "p2": p2},
        )

    elif kind == "n_variance":
        power_target = float(
            st.selectbox("Target power", list(power_target_choices()), key=_STATS_POWER_TARGET)
            or power_target_choices()[0]
        )
        ratio = _number_input_float(
            st, "Variance ratio to detect", value=2.0, key=_STATS_POWER_RATIO
        )
        result = required_n_variance(ratio, alpha=alpha, power=power_target)
        cards = [
            {"label": "Required sample size", "value": _format_int(result.get("n"))},
            {"label": "Alpha", "value": _format_number(alpha)},
            {"label": "Target power", "value": _format_power(power_target)},
            {"label": "Effect size", "value": f"variance ratio {_format_number(ratio)}"},
            {"label": "Method", "value": str(result.get("method") or "—")},
        ]
        interpretation = (
            f"To reach {_format_power(power_target)} power at α={_format_number(alpha)}, you "
            f"need about n={_format_int(result.get('n'))} to detect a variance ratio of "
            f"{_format_number(ratio)} (two-sided)."
        )
        _render_power_result(
            st,
            result,
            cards=cards,
            interpretation=interpretation,
            table=_result_dataframe(
                {
                    "analysis": analysis_label,
                    "method": result.get("method"),
                    "target_power": power_target,
                    "variance_ratio": ratio,
                    "alpha": alpha,
                    "required_n": result.get("n"),
                }
            ),
        )
        _render_power_curve(
            st,
            result,
            kind=kind,
            analysis_label=str(analysis_label),
            alpha=alpha,
            power_target=power_target,
            inputs={"ratio": ratio},
        )

    elif kind == "n_cohend":
        power_target = float(
            st.selectbox("Target power", list(power_target_choices()), key=_STATS_POWER_TARGET)
            or power_target_choices()[0]
        )
        delta = _number_input_float(
            st, "Effect size (Cohen's d)", value=0.5, key=_STATS_POWER_DELTA
        )
        result = required_n_cohend(delta, alpha=alpha, power=power_target)
        cards = [
            {
                "label": "Required sample size",
                "value": f"{_format_int(result.get('n_per_group'))} (per group)",
            },
            {"label": "Alpha", "value": _format_number(alpha)},
            {"label": "Target power", "value": _format_power(power_target)},
            {"label": "Effect size", "value": f"Cohen's d {_format_number(delta)}"},
            {"label": "Method", "value": str(result.get("method") or "—")},
        ]
        interpretation = (
            f"To reach {_format_power(power_target)} power at α={_format_number(alpha)}, you "
            f"need about n={_format_int(result.get('n_per_group'))} per group to detect a "
            f"Cohen's d of {_format_number(delta)} (two-sided)."
        )
        _render_power_result(
            st,
            result,
            cards=cards,
            interpretation=interpretation,
            table=_result_dataframe(
                {
                    "analysis": analysis_label,
                    "method": result.get("method"),
                    "target_power": power_target,
                    "cohens_d": delta,
                    "alpha": alpha,
                    "required_n_per_group": result.get("n_per_group"),
                }
            ),
        )
        _render_power_curve(
            st,
            result,
            kind=kind,
            analysis_label=str(analysis_label),
            alpha=alpha,
            power_target=power_target,
            inputs={"delta": delta},
        )


def _render_statistics_tabs(
    st: Any, df: pd.DataFrame, csv_path: str, dataset_name: str | None
) -> None:
    """Render the seven Statistics Lab tabs from a loaded frame.

    Shared verbatim by the legacy path-based flow and the managed root-first
    flow so the statistics surface is identical for both.
    """
    (
        overview_tab,
        descriptive_tab,
        relationships_tab,
        categories_tab,
        tests_tab,
        distributions_tab,
        power_tab,
    ) = st.tabs(_STATS_TAB_LABELS)
    with overview_tab:
        st.caption(
            "What this helps answer: is this dataset complete and healthy enough to analyze?"
        )
        stats_profile_result = _render_statistics_profile(st, csv_path, df)
        _render_type_summary(st, df)
        _render_missingness(st, df)
        _render_duplicates(st, df)
    with descriptive_tab:
        st.caption("What this helps answer: what does each column look like on its own?")
        _render_numeric_stats(st, df, stats_profile_result, dataset_name=dataset_name)
        _render_categorical_frequencies(st, df)
    with relationships_tab:
        st.caption(
            "What this helps answer: how do numeric columns move together, "
            "and is anything redundant?"
        )
        _render_correlation(st, df)
        _render_multivariate(st, df, dataset_name=dataset_name)
    with categories_tab:
        st.caption(
            "What this helps answer: how do categories relate, and how do "
            "numeric values differ across groups?"
        )
        _render_categorical_mixed(st, df, dataset_name=dataset_name)
    with tests_tab:
        st.caption("What this helps answer: is a difference between groups real or likely noise?")
        _render_inferential(st, df, dataset_name=dataset_name)
    with distributions_tab:
        st.caption(
            "What this helps answer: what probability, density, or cutoff does a "
            "theoretical distribution imply?"
        )
        _render_distribution_lookup(st)
    with power_tab:
        st.caption(
            "What this helps answer: how big a sample do I need, and how much power "
            "will a given sample size give me?"
        )
        _render_power_analysis(st)


def _render_managed_statistics_lab(
    st: Any, session_state: MutableMapping[str, Any], root: ManagedTrustRoot
) -> None:
    """Render Statistics Lab for a trusted managed version (root-first).

    The frame comes from the managed loader under exact canonical cache
    identity; the DQT-native profile reads the same trusted locator the loader
    just revalidated, never an operator-supplied path.
    """
    if root.large_file_mode:
        render_warning_state(st, _MANAGED_LARGE_STATS_MESSAGE)
        return
    try:
        df = get_managed_frame(session_state)
    except ManagedFrameLoadError as exc:
        show_error(st, "Managed Dataset Error", str(exc))
        return
    _render_statistics_tabs(st, df, root.locator.absolute_path, root.locator.display_name)


def _render_statistics_lab(st: Any, session_state: Mapping[str, Any] | None = None) -> None:
    """Render the Statistics Lab page body."""
    render_page_header(
        st,
        "Statistics Lab",
        "Descriptive statistics and tables. For charts and visual exploration, use EDA Explorer.",
        step_label=journey.step_label("statistics_lab"),
    )
    render_page_guidance(
        st,
        purpose=(
            "Compute descriptive statistics, run guided statistical tests, and look up "
            "bounded theoretical distributions."
        ),
        inputs="The dataset and the columns or groups you select.",
        workflow="Profile columns, select a test or distribution, and interpret the result.",
        outputs="Descriptive tables, statistical-test results, and distribution lookup values.",
        next_step="EDA Explorer or Preprocess Studio",
    )
    session = cast(MutableMapping[str, Any], session_state if session_state is not None else {})
    context = get_dataset_context(session)
    decision = resolve_trust_authority(session)

    # The shared identity callout always renders exactly once (accepted discovery/history
    # contract). Trust governs data dispatch and provenance below it, never the
    # identity surface itself.
    if decision.managed and decision.root is not None:
        # Root-first: valid managed trust governs even over a stale mirror or
        # a manually entered path.
        render_dataset_source_callout(st, context, session_state=session)
        _render_managed_statistics_lab(st, session, decision.root)
        return
    render_dataset_source_callout(st, context)
    if decision.authority is TrustAuthority.FAIL_CLOSED:
        show_error(st, "Managed Dataset Error", _MANAGED_FAIL_CLOSED_MESSAGE)
        return

    dataset_name = None
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
        dataset_name = context.display_name
    else:
        st.caption("Advanced/manual CSV path override.")
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

    _render_statistics_tabs(st, df, str(csv_path), dataset_name)


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_statistics_lab(st, st.session_state)  # type: ignore[arg-type, unused-ignore]
