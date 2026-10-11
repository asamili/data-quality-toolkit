"""Statistics Lab runner surfaces: the 14-TestKey execution-coverage contract plus
the loaded-dataset parametric paired t-test runner.

The coverage contract is internal private UI architecture metadata: it records,
for each first-wave statistical TestKey, how (or whether) the Statistics Lab can
execute it today and its v2.9.9 disposition. It is immutable and machine-tested;
it is not a public API.

The paired t-test runner renders page-local widgets and delegates computation to
the Streamlit-free service wrapper (``run_paired_t_test``), which routes through
the existing ``run_statistical_test`` public-API seam. This module never invokes
the domain statistics kernel directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.components.downloads import csv_download_button
from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_metric_cards,
    render_section_header,
)
from data_quality_toolkit.adapters.ui.components.states import (
    render_info_state,
    render_warning_state,
)
from data_quality_toolkit.adapters.ui.components.workspace_save_ui import (
    render_analysis_csv_save,
)
from data_quality_toolkit.adapters.ui.services.statistics import (
    group_category_options,
    outcome_category_options,
    run_one_proportion_z_test,
    run_paired_t_test,
    run_two_proportion_z_test,
)
from data_quality_toolkit.adapters.ui.services.statistics_eligibility import (
    NOT_BINARY,
    STATS_CATEGORICAL_MAX_LEVELS,
    STATS_LABEL_PREVIEW_MAX,
    ColumnEligibility,
    binary_outcome_candidates,
    categorical_candidates,
    classify_binary_outcome_column,
    classify_categorical_column,
    eligible_columns,
    exclusion_summary,
    summarize_labels,
)
from data_quality_toolkit.adapters.ui.services.statistics_guidance import (
    ResultGuidance,
    guidance_for_paired,
    guidance_for_proportion,
    guidance_sections,
)
from data_quality_toolkit.adapters.ui.services.statistics_visualization import (
    PAIRED_LINE_DISPLAY_MAX,
    PAIRED_PLOT_MAX_PAIRS,
    build_paired_evidence,
    build_proportion_evidence,
)

# ── TestKey execution-coverage contract (baseline reconciliation) ──────────
#
# Baseline classifications (evidence-based, per the baseline reconciliation):
#   already_runnable      — executable today from a loaded dataset in Statistics Lab.
#   equivalent_elsewhere  — executable through an equivalent specialized panel that
#                           does not go through the generic run_statistical_test runner.
#   confirmed_missing     — no loaded-dataset execution surface exists.
#   deferred              — reserved classification for keys parked by an explicit
#                           earlier decision (none at the v2.9.9 baseline).
BASELINE_ALREADY_RUNNABLE = "already_runnable"
BASELINE_EQUIVALENT_ELSEWHERE = "equivalent_elsewhere"
BASELINE_CONFIRMED_MISSING = "confirmed_missing"
BASELINE_DEFERRED = "deferred"
BASELINE_CLASSIFICATIONS = (
    BASELINE_ALREADY_RUNNABLE,
    BASELINE_EQUIVALENT_ELSEWHERE,
    BASELINE_CONFIRMED_MISSING,
    BASELINE_DEFERRED,
)

# v2.9.9 dispositions: what this release does (or deliberately does not do) per key.
DISPOSITION_UNCHANGED = "unchanged"
DISPOSITION_UNCHANGED_EQUIVALENT = "unchanged_equivalent_surface"
DISPOSITION_DEFERRED = "deferred"
DISPOSITION_IMPLEMENTED_PAIRED_T = "implemented_paired_t"
DISPOSITION_IMPLEMENTED_PROPORTION_Z = "implemented_proportion_z"
DISPOSITION_IMPLEMENTED_CHI_SQUARE = "implemented_chi_square"
DISPOSITIONS = (
    DISPOSITION_UNCHANGED,
    DISPOSITION_UNCHANGED_EQUIVALENT,
    DISPOSITION_DEFERRED,
    DISPOSITION_IMPLEMENTED_PAIRED_T,
    DISPOSITION_IMPLEMENTED_PROPORTION_Z,
    DISPOSITION_IMPLEMENTED_CHI_SQUARE,
)

# Marks the absence of an execution surface in a coverage entry.
NO_SURFACE = "none"


@dataclass(frozen=True)
class TestKeyCoverage:
    """One TestKey's baseline execution-coverage record (immutable)."""

    test_key: str
    baseline: str
    surface: str
    disposition: str


TESTKEY_EXECUTION_COVERAGE: Mapping[str, TestKeyCoverage] = MappingProxyType(
    {
        "ONE_T": TestKeyCoverage(
            test_key="ONE_T",
            baseline=BASELINE_ALREADY_RUNNABLE,
            surface=(
                "Statistical tests tab — 'Run Statistical Test' one-sample mode "
                "(run_one_sample_numeric_test → public run_statistical_test)"
            ),
            disposition=DISPOSITION_UNCHANGED,
        ),
        "ONE_Z": TestKeyCoverage(
            test_key="ONE_Z",
            baseline=BASELINE_CONFIRMED_MISSING,
            surface=NO_SURFACE,
            disposition=DISPOSITION_DEFERRED,
        ),
        "TWO_T_EQ": TestKeyCoverage(
            test_key="TWO_T_EQ",
            baseline=BASELINE_ALREADY_RUNNABLE,
            surface=(
                "Statistical tests tab — 'Run Statistical Test' two-group pooled mode "
                "and A/B comparison (public run_statistical_test / compare_ab)"
            ),
            disposition=DISPOSITION_UNCHANGED,
        ),
        "TWO_T_WELCH": TestKeyCoverage(
            test_key="TWO_T_WELCH",
            baseline=BASELINE_ALREADY_RUNNABLE,
            surface=(
                "Statistical tests tab — 'Run Statistical Test' two-group Welch mode, "
                "A/B comparison, and two-level Group comparison"
            ),
            disposition=DISPOSITION_UNCHANGED,
        ),
        "TWO_Z": TestKeyCoverage(
            test_key="TWO_Z",
            baseline=BASELINE_CONFIRMED_MISSING,
            surface=NO_SURFACE,
            disposition=DISPOSITION_DEFERRED,
        ),
        "PAIRED_T": TestKeyCoverage(
            test_key="PAIRED_T",
            baseline=BASELINE_CONFIRMED_MISSING,
            surface=(
                "Statistical tests tab — 'Paired samples — parametric t-test' runner "
                "added in 2.10.0 (run_paired_t_test → public run_statistical_test); the "
                "pre-existing Wilcoxon signed-rank panel is paired but nonparametric, "
                "not an equivalent parametric surface"
            ),
            disposition=DISPOSITION_IMPLEMENTED_PAIRED_T,
        ),
        "ANOVA": TestKeyCoverage(
            test_key="ANOVA",
            baseline=BASELINE_EQUIVALENT_ELSEWHERE,
            surface=(
                "Statistical tests tab — Group comparison multi-group panel runs "
                "one-way ANOVA alongside Kruskal-Wallis via "
                "domain inferential.compare_multi_group (two-sided only; not routed "
                "through the generic run_statistical_test runner)"
            ),
            disposition=DISPOSITION_UNCHANGED_EQUIVALENT,
        ),
        "ONE_PROP_Z": TestKeyCoverage(
            test_key="ONE_PROP_Z",
            baseline=BASELINE_CONFIRMED_MISSING,
            surface=(
                "Statistical tests tab — 'Proportion tests' one-proportion runner "
                "added in 2.10.0 (run_one_proportion_z_test → public run_statistical_test); "
                "tests one binary outcome column's success proportion against a null "
                "proportion from the loaded dataset"
            ),
            disposition=DISPOSITION_IMPLEMENTED_PROPORTION_Z,
        ),
        "TWO_PROP_Z": TestKeyCoverage(
            test_key="TWO_PROP_Z",
            baseline=BASELINE_CONFIRMED_MISSING,
            surface=(
                "Statistical tests tab — 'Proportion tests' two-proportion runner "
                "added in 2.10.0 (run_two_proportion_z_test → public run_statistical_test); "
                "compares a binary outcome's success proportion between two selected "
                "groups (first minus second) from the loaded dataset"
            ),
            disposition=DISPOSITION_IMPLEMENTED_PROPORTION_Z,
        ),
        "ONE_VAR_CHI": TestKeyCoverage(
            test_key="ONE_VAR_CHI",
            baseline=BASELINE_CONFIRMED_MISSING,
            surface=NO_SURFACE,
            disposition=DISPOSITION_DEFERRED,
        ),
        "F_VAR": TestKeyCoverage(
            test_key="F_VAR",
            baseline=BASELINE_CONFIRMED_MISSING,
            surface=NO_SURFACE,
            disposition=DISPOSITION_DEFERRED,
        ),
        "CHI_GOF": TestKeyCoverage(
            test_key="CHI_GOF",
            baseline=BASELINE_CONFIRMED_MISSING,
            surface=(
                "Statistical tests tab — 'Chi-square tests' Goodness of fit runner "
                "added in 2.10.0 (run_chi_square_gof_test → public run_statistical_test); "
                "compares one categorical column's observed distribution against equal "
                "or custom expected proportions from the loaded dataset"
            ),
            disposition=DISPOSITION_IMPLEMENTED_CHI_SQUARE,
        ),
        "CHI_IND": TestKeyCoverage(
            test_key="CHI_IND",
            baseline=BASELINE_CONFIRMED_MISSING,
            surface=(
                "Statistical tests tab — 'Chi-square tests' Independence runner added in "
                "2.10.0 (run_chi_square_independence_test → public run_statistical_test); builds "
                "a contingency table from two categorical columns of the loaded dataset and "
                "tests whether they are associated. The pre-existing Cramér's V categorical "
                "association panel is a ranking diagnostic, not an equivalent alpha-decision "
                "runner"
            ),
            disposition=DISPOSITION_IMPLEMENTED_CHI_SQUARE,
        ),
        "CHI_HOMOG": TestKeyCoverage(
            test_key="CHI_HOMOG",
            baseline=BASELINE_CONFIRMED_MISSING,
            surface=(
                "Statistical tests tab — 'Chi-square tests' Homogeneity runner added in "
                "2.10.0 (run_chi_square_homogeneity_test → public run_statistical_test); reuses "
                "the shared contingency-table primitive (populations on rows, outcome "
                "categories on columns) and routes through the distinct CHI_HOMOG key to "
                "test whether an outcome distribution is the same across selected groups"
            ),
            disposition=DISPOSITION_IMPLEMENTED_CHI_SQUARE,
        ),
    }
)

# ── paired t-test runner (page-local widgets; computation via the service) ──

_PAIRED_T_ALTERNATIVES = ("two-sided", "greater", "less")
_PAIRED_T_COL_A = "stats_lab_paired_t_column_a"
_PAIRED_T_COL_B = "stats_lab_paired_t_column_b"
_PAIRED_T_ALTERNATIVE = "stats_lab_paired_t_alternative"
_PAIRED_T_NULL_DIFF = "stats_lab_paired_t_null_difference"
_SAVE_PAIRED_T_BTN = "statistics_lab_save_paired_t_btn"
_STATISTICS_PAIRED_T_FILE = "statistics_paired_t.csv"
_SAVE_ANALYSIS_CAPTION = (
    "Downloads stay in your browser. Optionally save this analysis under your "
    "Workspace Root / analysis; existing files are not overwritten."
)

# ── opt-in result evidence ────────────────────────────────────────────────────
#
# Each runner offers one clearly labelled checkbox that reveals a bounded,
# result-native evidence view beside the result that produced it. Evidence is
# built from the completed result object and the exact analyzed inputs the runner
# already holds: no test is executed a second time and no statistic, p-value,
# alternative or paired direction is recomputed.

_EVIDENCE_CHECKBOX_LABEL = "Show evidence chart and interpretation guidance"
_PAIRED_T_SHOW_EVIDENCE = "stats_lab_paired_t_show_evidence"
_ONE_PROP_SHOW_EVIDENCE = "stats_lab_one_prop_show_evidence"
_TWO_PROP_SHOW_EVIDENCE = "stats_lab_two_prop_show_evidence"

_PAIRED_CAUSE_CAVEAT = (
    "Movement within pairs is described here, not explained. Without a controlled "
    "design, a shift between the two measurements does not establish cause."
)
_PAIRED_ANONYMOUS_CAVEAT = (
    "Pairs are shown at anonymous positions only; no row identifier, index or source "
    "location is displayed."
)
_PROPORTION_IMPORTANCE_CAVEAT = (
    "The chart shows observed shares and their denominators. Whether a gap of this size "
    "matters is a domain judgement, not something the test measures."
)
_PROPORTION_NO_INTERVAL_CAVEAT = (
    "This result exposes counts and proportions but no interval, so no uncertainty "
    "whiskers are drawn; none are invented."
)

_PAIRED_LINE_SPEC: dict[str, Any] = {
    "mark": {"type": "line", "point": True, "opacity": 0.5},
    "encoding": {
        "x": {"field": "measurement", "type": "nominal", "title": "Measurement", "sort": None},
        "y": {"field": "value", "type": "quantitative", "title": "Value"},
        "detail": {"field": "pair", "type": "nominal"},
        "tooltip": [
            {"field": "pair", "type": "quantitative", "title": "Pair position"},
            {"field": "measurement", "type": "nominal"},
            {"field": "value", "type": "quantitative"},
        ],
    },
}

_PAIRED_DIFFERENCE_SPEC: dict[str, Any] = {
    "layer": [
        {"mark": {"type": "rule", "color": "red"}, "encoding": {"y": {"datum": 0}}},
        {
            "mark": {"type": "point", "filled": True, "opacity": 0.6},
            "encoding": {
                "x": {
                    "field": "pair",
                    "type": "quantitative",
                    "title": "Anonymous pair position",
                },
                "y": {"field": "difference", "type": "quantitative", "title": "Difference"},
                "tooltip": [
                    {"field": "pair", "type": "quantitative", "title": "Pair position"},
                    {"field": "difference", "type": "quantitative"},
                ],
            },
        },
    ]
}


def _format_number(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.4g}"
    except (TypeError, ValueError):
        return str(value)


def _format_int(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _number_input_float(st: Any, label: str, *, value: float, key: str) -> float:
    raw = st.number_input(label, value=value, step=0.1, key=key)
    if raw is None:
        return value
    try:
        return float(raw)
    except (TypeError, ValueError):
        return value


def _render_guidance(st: Any, guidance: ResultGuidance) -> None:
    """Render one result's interpretation guidance as bounded caption lines."""
    for heading, text in guidance_sections(guidance):
        st.caption(f"{heading}: {text}")


def _evidence_requested(st: Any, key: str) -> bool:
    """Render the single opt-in evidence toggle for a runner (default off)."""
    return bool(st.checkbox(_EVIDENCE_CHECKBOX_LABEL, key=key))


def _paired_t_result_dataframe(result: Mapping[str, Any]) -> pd.DataFrame:
    """Build a one-row export table for a paired t-test result."""
    reject_null = result.get("reject_null")
    decision = "reject" if reject_null is True else "do not reject"
    row = {
        "source": "paired t-test",
        "test": result.get("test_key"),
        "method": result.get("method"),
        "column_a": result.get("column_a"),
        "column_b": result.get("column_b"),
        "n_pairs": result.get("n_pairs"),
        "n_excluded_rows": result.get("n_excluded_rows"),
        "statistic": result.get("statistic"),
        "p_value": result.get("p_value"),
        "alpha": result.get("alpha"),
        "alternative": result.get("alternative"),
        "reject_null": reject_null,
        "decision": decision,
    }
    return pd.DataFrame([{key: value for key, value in row.items() if value is not None}])


def render_paired_evidence(
    st: Any,
    result: Mapping[str, Any],
    *,
    frame: pd.DataFrame,
    column_a: str,
    column_b: str,
) -> None:
    """Render the opt-in paired evidence view beside an existing paired result.

    The pairs come from the exact analyzed columns the runner already used, with
    the same pairwise exclusion rule, so the displayed complete-pair count agrees
    with the computed result. The difference keeps the contract direction (first
    minus second) and is never reversed; the test is not run again.
    """
    evidence = build_paired_evidence(
        frame[column_a].tolist(),
        frame[column_b].tolist(),
        total_rows=int(len(frame)),
    )
    guidance = guidance_for_paired(
        result,
        first=str(column_a),
        second=str(column_b),
        evidence=evidence if evidence["status"] == "ok" else None,
    )
    if evidence["status"] != "ok":
        render_info_state(st, f"Evidence view unavailable: {evidence['reason']}.")
        _render_guidance(st, guidance)
        return
    st.caption(
        f"Before/after values for up to {PAIRED_LINE_DISPLAY_MAX} anonymous pairs "
        f"({evidence['displayed_lines']:,} shown of {evidence['complete_pairs']:,} "
        "complete pairs)."
    )
    st.vega_lite_chart(evidence["lines_long"], _PAIRED_LINE_SPEC, use_container_width=True)
    st.caption(
        f"Paired differences ({column_a} minus {column_b}) against a zero reference, "
        f"bounded at {PAIRED_PLOT_MAX_PAIRS} pairs "
        f"({evidence['displayed_pairs']:,} plotted)."
    )
    st.vega_lite_chart(evidence["data"], _PAIRED_DIFFERENCE_SPEC, use_container_width=True)
    if evidence["excluded_rows"]:
        st.caption(
            f"{evidence['excluded_rows']:,} row(s) were excluded because one side of the "
            "pair was missing or non-finite."
        )
    st.caption(_PAIRED_ANONYMOUS_CAVEAT)
    st.caption(_PAIRED_CAUSE_CAVEAT)
    _render_guidance(st, guidance)


def _render_paired_t_result(
    st: Any,
    result: Mapping[str, Any],
    *,
    dataset_name: str | None = None,
    frame: pd.DataFrame | None = None,
    column_a: str | None = None,
    column_b: str | None = None,
) -> None:
    """Render a paired t-test result safely from its status dict."""
    status = str(result.get("status") or "unknown")
    if status != "ok":
        message = str(result.get("reason") or f"Status: {status}")
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
            {"label": "Test", "value": result.get("test_key", "PAIRED_T")},
            {"label": "Statistic", "value": _format_number(result.get("statistic"))},
            {"label": "p-value", "value": _format_number(result.get("p_value"))},
            {"label": "Decision", "value": decision},
        ],
    )
    pair_cards = [{"label": "Complete pairs", "value": _format_int(result.get("n_pairs"))}]
    n_excluded_rows = result.get("n_excluded_rows")
    if n_excluded_rows:
        pair_cards.append(
            {"label": "Excluded rows (incomplete pairs)", "value": _format_int(n_excluded_rows)}
        )
    render_metric_cards(st, pair_cards)
    st.caption(
        f"{result.get('method', 'paired_t')} at alpha={_format_number(result.get('alpha'))}; "
        f"alternative={result.get('alternative', 'two-sided')}."
    )
    table = _paired_t_result_dataframe(result)
    st.dataframe(table, hide_index=True)
    csv_download_button(st, "Download paired t-test result (CSV)", table, _STATISTICS_PAIRED_T_FILE)
    render_analysis_csv_save(
        st,
        button_label="Save paired t-test result to Workspace",
        key=_SAVE_PAIRED_T_BTN,
        artifact="statistics_paired_t",
        dataframe=table,
        dataset_name=dataset_name,
        caption=_SAVE_ANALYSIS_CAPTION,
    )
    for warning in result.get("warnings") or []:
        st.caption(str(warning))
    if frame is None or column_a is None or column_b is None:
        return
    if _evidence_requested(st, _PAIRED_T_SHOW_EVIDENCE):
        render_paired_evidence(st, result, frame=frame, column_a=column_a, column_b=column_b)


def render_paired_t_runner(
    st: Any,
    df: pd.DataFrame,
    alpha: float,
    *,
    dataset_name: str | None = None,
) -> None:
    """Paired/dependent-samples parametric t-test runner (user-selected option).

    Parametric counterpart to the nonparametric Wilcoxon signed-rank panel; it is
    offered as an explicit paired test and does not change any automatic test
    recommendation or verdict threshold.
    """
    render_section_header(
        st,
        "Paired samples — parametric t-test",
        "Parametric test on the mean of paired differences. Does not change "
        "automatic test recommendations.",
    )
    st.caption(
        "For paired/dependent numeric columns (e.g., before/after on the same rows). "
        "Assumes the paired differences are approximately normal; the Wilcoxon "
        "signed-rank panel below is the nonparametric alternative. Rows are excluded "
        "only when either selected column is missing for that row."
    )
    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    if len(numeric_columns) < 2:
        st.info("Need at least two numeric columns for a paired t-test.")
        return
    column_a = st.selectbox("First paired measurement", numeric_columns, key=_PAIRED_T_COL_A)
    if column_a is None:
        return
    b_options = [column for column in numeric_columns if column != column_a]
    if not b_options:
        st.info("Need a second distinct numeric column for a paired t-test.")
        return
    column_b = st.selectbox("Second paired measurement", b_options, key=_PAIRED_T_COL_B)
    alternative = st.selectbox("Alternative", _PAIRED_T_ALTERNATIVES, key=_PAIRED_T_ALTERNATIVE)
    if column_b is None or alternative is None:
        return
    null_difference = _number_input_float(
        st,
        "Null difference (mean of pair differences)",
        value=0.0,
        key=_PAIRED_T_NULL_DIFF,
    )
    result = run_paired_t_test(
        df,
        str(column_a),
        str(column_b),
        null_difference=null_difference,
        alpha=alpha,
        alternative=str(alternative),
    )
    _render_paired_t_result(
        st,
        result,
        dataset_name=dataset_name,
        frame=df,
        column_a=str(column_a),
        column_b=str(column_b),
    )


# ── proportion z-test runners (page-local widgets; computation via the service) ──

_PROPORTION_ALTERNATIVES = ("two-sided", "greater", "less")
_PROP_MODE_ONE = "One proportion"
_PROP_MODE_TWO = "Two proportions"
_PROP_MODES = (_PROP_MODE_ONE, _PROP_MODE_TWO)

_PROP_MODE_KEY = "stats_lab_prop_mode"
_ONE_PROP_OUTCOME = "stats_lab_one_prop_outcome"
_ONE_PROP_SUCCESS = "stats_lab_one_prop_success"
_ONE_PROP_NULL = "stats_lab_one_prop_null"
_ONE_PROP_ALTERNATIVE = "stats_lab_one_prop_alternative"
_TWO_PROP_OUTCOME = "stats_lab_two_prop_outcome"
_TWO_PROP_SUCCESS = "stats_lab_two_prop_success"
_TWO_PROP_GROUP_COLUMN = "stats_lab_two_prop_group_column"
_TWO_PROP_GROUP_A = "stats_lab_two_prop_group_a"
_TWO_PROP_GROUP_B = "stats_lab_two_prop_group_b"
_TWO_PROP_ALTERNATIVE = "stats_lab_two_prop_alternative"

_SAVE_ONE_PROP_BTN = "statistics_lab_save_one_prop_z_btn"
_SAVE_TWO_PROP_BTN = "statistics_lab_save_two_prop_z_btn"
_STATISTICS_ONE_PROP_FILE = "statistics_one_proportion_z.csv"
_STATISTICS_TWO_PROP_FILE = "statistics_two_proportion_z.csv"


def _category_option_label(option: Any) -> str:
    """Render a type-safe category option's display label (Streamlit ``format_func``).

    Display text only; the option's native ``value`` (not this label) is what the
    service uses for computation.
    """
    return str(getattr(option, "label", option))


def _one_proportion_result_dataframe(result: Mapping[str, Any]) -> pd.DataFrame:
    """Build the one-row export table for a one-proportion z-test result."""
    reject_null = result.get("reject_null")
    decision = "reject" if reject_null is True else "do not reject"
    row = {
        "source": "one-proportion z-test",
        "test": result.get("test_key"),
        "method": result.get("method"),
        "outcome_column": result.get("outcome_column"),
        "success_value": result.get("success_label"),
        "total_rows": result.get("total_rows"),
        "valid_rows": result.get("valid_rows"),
        "excluded_rows": result.get("excluded_rows"),
        "success_count": result.get("success_count"),
        "failure_count": result.get("failure_count"),
        "observed_proportion": result.get("observed_proportion"),
        "null_proportion": result.get("null_proportion"),
        "statistic": result.get("statistic"),
        "p_value": result.get("p_value"),
        "alpha": result.get("alpha"),
        "alternative": result.get("alternative"),
        "reject_null": reject_null,
        "decision": decision,
        "status": result.get("status"),
    }
    return pd.DataFrame([row])


def _two_proportion_result_dataframe(result: Mapping[str, Any]) -> pd.DataFrame:
    """Build the one-row export table for a two-proportion z-test result."""
    reject_null = result.get("reject_null")
    decision = "reject" if reject_null is True else "do not reject"
    row = {
        "source": "two-proportion z-test",
        "test": result.get("test_key"),
        "method": result.get("method"),
        "outcome_column": result.get("outcome_column"),
        "success_value": result.get("success_label"),
        "group_column": result.get("group_column"),
        "first_group": result.get("group_a_label"),
        "second_group": result.get("group_b_label"),
        "total_rows": result.get("total_rows"),
        "invalid_or_missing_rows": result.get("invalid_or_missing_rows"),
        "rows_outside_groups": result.get("rows_outside_groups"),
        "n_first_group": result.get("n_a"),
        "n_second_group": result.get("n_b"),
        "successes_first_group": result.get("successes_a"),
        "successes_second_group": result.get("successes_b"),
        "proportion_first_group": result.get("proportion_a"),
        "proportion_second_group": result.get("proportion_b"),
        "proportion_difference": result.get("proportion_difference"),
        "statistic": result.get("statistic"),
        "p_value": result.get("p_value"),
        "alpha": result.get("alpha"),
        "alternative": result.get("alternative"),
        "reject_null": reject_null,
        "decision": decision,
        "status": result.get("status"),
    }
    return pd.DataFrame([row])


def _proportion_spec(*, reference: float | None, intervals: bool) -> dict[str, Any]:
    """Vega-Lite spec for bounded proportion evidence with optional whiskers/reference."""
    layers: list[dict[str, Any]] = [
        {
            "mark": {"type": "bar"},
            "encoding": {
                "x": {"field": "label", "type": "nominal", "title": "Category"},
                "y": {
                    "field": "proportion",
                    "type": "quantitative",
                    "title": "Observed proportion",
                    "scale": {"domain": [0, 1]},
                },
                "tooltip": [
                    {"field": "label", "type": "nominal"},
                    {"field": "successes", "type": "quantitative"},
                    {"field": "total", "type": "quantitative"},
                    {"field": "proportion", "type": "quantitative"},
                ],
            },
        }
    ]
    if intervals:
        layers.append(
            {
                "mark": {"type": "rule"},
                "encoding": {
                    "x": {"field": "label", "type": "nominal"},
                    "y": {"field": "lower", "type": "quantitative"},
                    "y2": {"field": "upper"},
                },
            }
        )
    if reference is not None:
        layers.append(
            {
                "mark": {"type": "rule", "color": "red", "strokeDash": [4, 4]},
                "encoding": {"y": {"datum": reference}},
            }
        )
    return {"layer": layers}


def _render_proportion_evidence(
    st: Any,
    evidence: Mapping[str, Any],
    guidance: ResultGuidance,
    *,
    caption: str,
) -> None:
    """Render prepared proportion evidence, then its interpretation guidance."""
    if evidence["status"] != "ok":
        render_info_state(st, f"Evidence view unavailable: {evidence['reason']}.")
        _render_guidance(st, guidance)
        return
    st.caption(caption)
    st.vega_lite_chart(
        evidence["data"],
        _proportion_spec(
            reference=evidence["reference"] if evidence["reference_available"] else None,
            intervals=bool(evidence["intervals_available"]),
        ),
        use_container_width=True,
    )
    st.dataframe(evidence["data"], hide_index=True)
    if evidence["difference_available"]:
        st.caption(f"Observed difference (first minus second): {evidence['difference']}.")
    if not evidence["intervals_available"]:
        st.caption(_PROPORTION_NO_INTERVAL_CAVEAT)
    st.caption(_PROPORTION_IMPORTANCE_CAVEAT)
    _render_guidance(st, guidance)


def render_one_proportion_evidence(st: Any, result: Mapping[str, Any]) -> None:
    """Render the opt-in one-proportion evidence view beside its existing result."""
    evidence = build_proportion_evidence(
        [
            {
                "label": result.get("success_label"),
                "successes": result.get("success_count"),
                "total": result.get("valid_rows"),
                "proportion": result.get("observed_proportion"),
            }
        ],
        reference=result.get("null_proportion"),
    )
    _render_proportion_evidence(
        st,
        evidence,
        guidance_for_proportion(result, mode="one"),
        caption=(
            "Observed success share against the null proportion, with the counts and "
            "denominator the test used."
        ),
    )


def render_two_proportion_evidence(st: Any, result: Mapping[str, Any]) -> None:
    """Render the opt-in two-proportion evidence view beside its existing result."""
    evidence = build_proportion_evidence(
        [
            {
                "label": result.get("group_a_label"),
                "successes": result.get("successes_a"),
                "total": result.get("n_a"),
                "proportion": result.get("proportion_a"),
            },
            {
                "label": result.get("group_b_label"),
                "successes": result.get("successes_b"),
                "total": result.get("n_b"),
                "proportion": result.get("proportion_b"),
            },
        ],
        difference=result.get("proportion_difference"),
    )
    _render_proportion_evidence(
        st,
        evidence,
        guidance_for_proportion(result, mode="two"),
        caption=(
            "Observed success share per selected group, with the successes and denominator "
            "the test used. Group labels keep their typed identity."
        ),
    )


def _render_proportion_status(st: Any, result: Mapping[str, Any]) -> bool:
    """Render a non-ok proportion status safely; return True when the result is ok."""
    status = str(result.get("status") or "unknown")
    if status == "ok":
        return True
    message = str(result.get("reason") or f"Status: {status}")
    if status == "unavailable":
        render_warning_state(st, message)
    else:
        render_info_state(st, message)
    return False


def _render_one_proportion_result(
    st: Any,
    result: Mapping[str, Any],
    *,
    dataset_name: str | None = None,
) -> None:
    """Render a one-proportion z-test result safely from its status dict."""
    if not _render_proportion_status(st, result):
        return
    reject_null = result.get("reject_null")
    decision = "reject" if reject_null is True else "do not reject"
    render_metric_cards(
        st,
        [
            {"label": "Test", "value": result.get("test_key", "ONE_PROP_Z")},
            {"label": "Statistic (z)", "value": _format_number(result.get("statistic"))},
            {"label": "p-value", "value": _format_number(result.get("p_value"))},
            {"label": "Decision", "value": decision},
        ],
    )
    render_metric_cards(
        st,
        [
            {
                "label": "Observed proportion",
                "value": _format_number(result.get("observed_proportion")),
            },
            {"label": "Null proportion", "value": _format_number(result.get("null_proportion"))},
            {"label": "Successes", "value": _format_int(result.get("success_count"))},
            {"label": "Valid rows", "value": _format_int(result.get("valid_rows"))},
        ],
    )
    st.caption(
        f"{result.get('method', 'one_proportion_z')} at "
        f"alpha={_format_number(result.get('alpha'))}; "
        f"alternative={result.get('alternative', 'two-sided')}. "
        f"Successes={_format_int(result.get('success_count'))}, "
        f"failures={_format_int(result.get('failure_count'))}, "
        f"excluded rows={_format_int(result.get('excluded_rows'))}."
    )
    table = _one_proportion_result_dataframe(result)
    st.dataframe(table, hide_index=True)
    csv_download_button(
        st, "Download one-proportion z-test result (CSV)", table, _STATISTICS_ONE_PROP_FILE
    )
    render_analysis_csv_save(
        st,
        button_label="Save one-proportion z-test result to Workspace",
        key=_SAVE_ONE_PROP_BTN,
        artifact="statistics_one_proportion_z",
        dataframe=table,
        dataset_name=dataset_name,
        caption=_SAVE_ANALYSIS_CAPTION,
    )
    for warning in result.get("warnings") or []:
        st.caption(str(warning))
    if _evidence_requested(st, _ONE_PROP_SHOW_EVIDENCE):
        render_one_proportion_evidence(st, result)


def _render_two_proportion_result(
    st: Any,
    result: Mapping[str, Any],
    *,
    dataset_name: str | None = None,
) -> None:
    """Render a two-proportion z-test result safely from its status dict."""
    if not _render_proportion_status(st, result):
        return
    reject_null = result.get("reject_null")
    decision = "reject" if reject_null is True else "do not reject"
    group_a = result.get("group_a_label", "A")
    group_b = result.get("group_b_label", "B")
    render_metric_cards(
        st,
        [
            {"label": "Test", "value": result.get("test_key", "TWO_PROP_Z")},
            {"label": "Statistic (z)", "value": _format_number(result.get("statistic"))},
            {"label": "p-value", "value": _format_number(result.get("p_value"))},
            {"label": "Decision", "value": decision},
        ],
    )
    render_metric_cards(
        st,
        [
            {"label": f"p · {group_a}", "value": _format_number(result.get("proportion_a"))},
            {"label": f"p · {group_b}", "value": _format_number(result.get("proportion_b"))},
            {
                "label": "Difference (first − second)",
                "value": _format_number(result.get("proportion_difference")),
            },
        ],
    )
    render_metric_cards(
        st,
        [
            {"label": f"n · {group_a}", "value": _format_int(result.get("n_a"))},
            {"label": f"n · {group_b}", "value": _format_int(result.get("n_b"))},
            {
                "label": "Rows outside groups",
                "value": _format_int(result.get("rows_outside_groups")),
            },
            {
                "label": "Invalid/missing rows",
                "value": _format_int(result.get("invalid_or_missing_rows")),
            },
        ],
    )
    st.caption(
        f"{result.get('method', 'two_proportion_z')} at "
        f"alpha={_format_number(result.get('alpha'))}; "
        f"alternative={result.get('alternative', 'two-sided')}. "
        f"Successes {group_a}={_format_int(result.get('successes_a'))}, "
        f"{group_b}={_format_int(result.get('successes_b'))}."
    )
    table = _two_proportion_result_dataframe(result)
    st.dataframe(table, hide_index=True)
    csv_download_button(
        st, "Download two-proportion z-test result (CSV)", table, _STATISTICS_TWO_PROP_FILE
    )
    render_analysis_csv_save(
        st,
        button_label="Save two-proportion z-test result to Workspace",
        key=_SAVE_TWO_PROP_BTN,
        artifact="statistics_two_proportion_z",
        dataframe=table,
        dataset_name=dataset_name,
        caption=_SAVE_ANALYSIS_CAPTION,
    )
    for warning in result.get("warnings") or []:
        st.caption(str(warning))
    if _evidence_requested(st, _TWO_PROP_SHOW_EVIDENCE):
        render_two_proportion_evidence(st, result)


# ── L1 semantic eligibility (page tier) ───────────────────────────────────────
#
# The normal selection pathway offers only columns with exactly two valid levels,
# so a pathological high-cardinality field never reaches option construction. The
# defensive non-binary path stays in place for a stale session-state selection or a
# direct service call, and its text is bounded by the shared label-summary policy.

_BINARY_RULE = "Select a binary outcome column with exactly two distinct non-missing values."
_TYPED_VALUE_NOTE = "Values of different types (e.g. 1 [int] and 1 [str]) are kept distinct."
_GROUPING_RULE = (
    "Select a grouping column with at least two and at most "
    f"{STATS_CATEGORICAL_MAX_LEVELS} distinct non-missing values."
)


def _render_no_binary_outcome(st: Any, classifications: list[ColumnEligibility]) -> None:
    """Explain, concisely and without enumerating categories, why nothing qualified."""
    summary = exclusion_summary(classifications)
    message = f"{_BINARY_RULE} No column in this dataset qualifies."
    render_info_state(st, f"{message} {summary}".strip())


def _render_non_binary_outcome(
    st: Any, df: pd.DataFrame, classification: ColumnEligibility
) -> None:
    """Bounded defensive message for a selected column that is not binary.

    Observed labels are read only for a small category set; above the label-preview
    bound the message stays a count, so a very wide field can never produce an
    oversized alert.
    """
    parts = [classification.reason or _BINARY_RULE, _BINARY_RULE]
    if (
        classification.status == NOT_BINARY
        and classification.level_count <= STATS_LABEL_PREVIEW_MAX
    ):
        options, options_error = outcome_category_options(df, classification.column)
        if options_error is None and options:
            labels = [option.label for option in options]
            parts.append(
                f"Observed distinct values in {classification.column!r}: "
                f"{summarize_labels(labels)}. {_TYPED_VALUE_NOTE}"
            )
    render_info_state(st, " ".join(parts))


def _render_ineligible_grouping(st: Any, classification: ColumnEligibility) -> None:
    """Bounded refusal for a grouping column the eligible list never offered.

    Reached only through a stale or session-injected selection. The text is the shared
    eligibility policy's own count-only reason, so a near-unique field can never
    enumerate its labels here.
    """
    render_info_state(st, f"{classification.reason or _GROUPING_RULE} {_GROUPING_RULE}".strip())


def _select_outcome_and_success(
    st: Any,
    df: pd.DataFrame,
    columns: list[str],
    *,
    outcome_key: str,
    success_key: str,
) -> tuple[str, Any] | None:
    """Render the outcome column + success value selectors (shared by both runners).

    Returns (outcome column, selected success option) or None after rendering an
    actionable warning (ambiguous/unsafe category set) or info state (non-binary
    column). Collision-safe labels come from the service; the page never re-derives them.
    """
    classifications = binary_outcome_candidates(df, columns)
    eligible = eligible_columns(classifications)
    if not eligible:
        _render_no_binary_outcome(st, classifications)
        return None
    outcome = st.selectbox("Binary outcome column", eligible, key=outcome_key)
    if outcome is None:
        return None
    selected = classify_binary_outcome_column(df, str(outcome))
    if not selected.eligible:
        _render_non_binary_outcome(st, df, selected)
        return None
    options, options_error = outcome_category_options(df, str(outcome))
    if options_error is not None:
        render_warning_state(st, options_error)
        return None
    if len(options) != 2:
        labels = [option.label for option in options]
        render_info_state(
            st,
            f"{_BINARY_RULE} Observed distinct values in {outcome!r}: "
            f"{summarize_labels(labels)}. {_TYPED_VALUE_NOTE}",
        )
        return None
    st.caption(f"Observed values in {outcome!r}: {options[0].label}, {options[1].label}.")
    success = st.selectbox(
        "Value representing success",
        options,
        key=success_key,
        format_func=_category_option_label,
    )
    if success is None:
        return None
    return str(outcome), success


def _select_two_groups(
    st: Any,
    df: pd.DataFrame,
    group_column: str,
    *,
    key_a: str,
    key_b: str,
) -> tuple[Any, Any] | None:
    """Render the two group selectors; return (group A option, group B option) or None.

    Renders a warning for an ambiguous/unsafe group set and an info state when fewer
    than two distinct groups remain. Group B excludes group A by typed identity.
    """
    groups, groups_error = group_category_options(df, group_column)
    if groups_error is not None:
        render_warning_state(st, groups_error)
        return None
    if len(groups) < 2:
        render_info_state(
            st,
            f"Grouping column {group_column!r} needs at least two distinct non-missing values. "
            "Non-finite numeric values (±inf) are excluded and cannot be selected as groups.",
        )
        return None
    group_a = st.selectbox("First group", groups, key=key_a, format_func=_category_option_label)
    if group_a is None:
        return None
    b_options = [group for group in groups if group.identity != group_a.identity]
    if not b_options:
        st.info("Need a second distinct group value.")
        return None
    group_b = st.selectbox("Second group", b_options, key=key_b, format_func=_category_option_label)
    if group_b is None:
        return None
    return group_a, group_b


def _render_one_proportion_runner(
    st: Any,
    df: pd.DataFrame,
    alpha: float,
    *,
    dataset_name: str | None = None,
) -> None:
    """One-proportion z-test runner: one binary outcome column vs a null proportion."""
    st.caption(
        "Tests one binary (two-value) outcome column against a null proportion. "
        "Direction: 'greater' means the observed success proportion is greater than the "
        "null proportion; 'less' means it is less than the null proportion."
    )
    columns = [str(column) for column in df.columns.tolist()]
    if not columns:
        st.info("Load a dataset with at least one column to run a proportion test.")
        return
    selection = _select_outcome_and_success(
        st, df, columns, outcome_key=_ONE_PROP_OUTCOME, success_key=_ONE_PROP_SUCCESS
    )
    if selection is None:
        return
    outcome, success = selection
    null_proportion = _number_input_float(
        st, "Null proportion (0–1)", value=0.5, key=_ONE_PROP_NULL
    )
    alternative = st.selectbox("Alternative", _PROPORTION_ALTERNATIVES, key=_ONE_PROP_ALTERNATIVE)
    if alternative is None:
        return
    result = run_one_proportion_z_test(
        df,
        outcome,
        success.value,
        null_proportion=null_proportion,
        alpha=alpha,
        alternative=str(alternative),
    )
    _render_one_proportion_result(st, result, dataset_name=dataset_name)


def _render_two_proportion_runner(
    st: Any,
    df: pd.DataFrame,
    alpha: float,
    *,
    dataset_name: str | None = None,
) -> None:
    """Two-proportion z-test runner: compare a binary success proportion across two groups."""
    st.caption(
        "Compares a binary outcome's success proportion between two selected groups. "
        "Comparison direction is the first selected group minus the second: 'greater' means "
        "the proportion in the first group is greater than in the second; 'less' means it is "
        "less than in the second."
    )
    columns = [str(column) for column in df.columns.tolist()]
    if len(columns) < 2:
        st.info("Need at least two columns (one binary outcome and one grouping column).")
        return
    selection = _select_outcome_and_success(
        st, df, columns, outcome_key=_TWO_PROP_OUTCOME, success_key=_TWO_PROP_SUCCESS
    )
    if selection is None:
        return
    outcome, success = selection
    candidate_columns = [column for column in columns if column != outcome]
    # Reuse the shared 2..STATS_CATEGORICAL_MAX_LEVELS group-cardinality policy rather
    # than offering every remaining column: the grouping selector must not become a
    # second, unbounded way into type-safe option construction.
    group_classifications = categorical_candidates(df, candidate_columns)
    group_columns = eligible_columns(group_classifications)
    if not group_columns:
        render_info_state(
            st,
            f"{_GROUPING_RULE} No remaining column qualifies. "
            f"{exclusion_summary(group_classifications)}".strip(),
        )
        return
    group_column = st.selectbox("Grouping column", group_columns, key=_TWO_PROP_GROUP_COLUMN)
    if group_column is None:
        return
    # A stale or session-injected widget key can name a column the eligible list above
    # never offered. Re-check the selection against the same classifier here, before any
    # option construction: the verdict comes from a level count alone, so a refused
    # grouping column builds no typed category, no group option object, and no group
    # widget, and no statistical run is reached.
    selected_group = classify_categorical_column(df, str(group_column))
    if not selected_group.eligible:
        _render_ineligible_grouping(st, selected_group)
        return
    selected_groups = _select_two_groups(
        st, df, str(group_column), key_a=_TWO_PROP_GROUP_A, key_b=_TWO_PROP_GROUP_B
    )
    if selected_groups is None:
        return
    group_a, group_b = selected_groups
    alternative = st.selectbox("Alternative", _PROPORTION_ALTERNATIVES, key=_TWO_PROP_ALTERNATIVE)
    if alternative is None:
        return
    st.caption(f"Comparison direction: {group_a.label} − {group_b.label} (first minus second).")
    result = run_two_proportion_z_test(
        df,
        outcome,
        success.value,
        str(group_column),
        group_a.value,
        group_b.value,
        alpha=alpha,
        alternative=str(alternative),
    )
    _render_two_proportion_result(st, result, dataset_name=dataset_name)


def render_proportion_tests_runner(
    st: Any,
    df: pd.DataFrame,
    alpha: float,
    *,
    dataset_name: str | None = None,
) -> None:
    """Proportion z-test section (user-selected option).

    A single bounded inferential section offering the one-proportion and
    two-proportion z-tests for binary success proportions. It does not change any
    automatic test recommendation or verdict threshold and adds no new formula.
    """
    render_section_header(
        st,
        "Proportion tests",
        "z-tests for binary success proportions. Does not change automatic test "
        "recommendations.",
    )
    st.caption(
        "One-proportion and two-proportion z-tests for a binary (two-value) outcome column. "
        "Missing values are excluded; non-finite numeric values are excluded."
    )
    mode = st.selectbox("Proportion test", _PROP_MODES, key=_PROP_MODE_KEY)
    if mode == _PROP_MODE_TWO:
        _render_two_proportion_runner(st, df, alpha, dataset_name=dataset_name)
    else:
        _render_one_proportion_runner(st, df, alpha, dataset_name=dataset_name)
