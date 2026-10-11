"""Statistics Lab chi-square section: loaded-dataset goodness-of-fit, independence,
and homogeneity runners.

This is the dedicated page helper that owns all new chi-square Streamlit rendering:
the single "Chi-square tests" section, mode selection, page-local widget controls,
the goodness-of-fit expected-distribution input, observed/expected and
contingency-table presentation, metric cards, informational assumption warnings,
browser downloads, and workspace-save wiring. All data preparation, type-safe
collision-safe category identity, and public ``run_statistical_test`` orchestration
live in the Streamlit-free ``services.statistics`` layer. This module never imports a
private domain helper, never reimplements the statistical formula or the category
identity, never calls SciPy directly, and never performs durable filesystem writes.
"""

from __future__ import annotations

from collections.abc import Mapping
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
    chi_square_gof_options,
    run_chi_square_gof_test,
    run_chi_square_homogeneity_test,
    run_chi_square_independence_test,
)
from data_quality_toolkit.adapters.ui.services.statistics_eligibility import (
    CUSTOM_PROPORTION_BOUND_REASON,
    STATS_CATEGORICAL_MAX_LEVELS,
    ColumnEligibility,
    bounded_table_preview,
    categorical_candidates,
    classify_categorical_column,
    custom_proportions_available,
    eligible_columns,
    exclusion_summary,
    summarize_labels,
)
from data_quality_toolkit.adapters.ui.services.statistics_guidance import (
    ResultGuidance,
    guidance_for_contingency,
    guidance_for_goodness_of_fit,
    guidance_sections,
)
from data_quality_toolkit.adapters.ui.services.statistics_visualization import (
    CONTINGENCY_MAX_CELLS,
    CONTINGENCY_MAX_COLUMNS,
    CONTINGENCY_MAX_ROWS,
    GOF_MAX_CATEGORIES,
    build_contingency_evidence,
    build_gof_evidence,
)

# ── section modes ─────────────────────────────────────────────────────────────

_CHI_MODE_GOF = "Goodness of fit"
_CHI_MODE_IND = "Independence"
_CHI_MODE_HOMOG = "Homogeneity"
_CHI_MODES = (_CHI_MODE_GOF, _CHI_MODE_IND, _CHI_MODE_HOMOG)

_CHI_MODE_KEY = "stats_lab_chi_mode"

# Goodness-of-fit widget keys / expected-distribution modes.
_GOF_COLUMN = "stats_lab_chi_gof_column"
_GOF_EXPECTED_MODE = "stats_lab_chi_gof_expected_mode"
_GOF_PROP_PREFIX = "stats_lab_chi_gof_prop_"
_GOF_EXPECTED_EQUAL = "Equal proportions"
_GOF_EXPECTED_CUSTOM = "Custom proportions"
_GOF_EXPECTED_MODES = (_GOF_EXPECTED_EQUAL, _GOF_EXPECTED_CUSTOM)

_SAVE_GOF_BTN = "statistics_lab_save_chi_gof_btn"
_SAVE_GOF_COUNTS_BTN = "statistics_lab_save_chi_gof_counts_btn"
_STATISTICS_GOF_FILE = "statistics_chi_square_gof.csv"
_STATISTICS_GOF_COUNTS_FILE = "statistics_chi_square_gof_counts.csv"

# Independence widget keys / filenames / workspace artifacts.
_IND_FIRST_COLUMN = "stats_lab_chi_ind_first_column"
_IND_SECOND_COLUMN = "stats_lab_chi_ind_second_column"
_SAVE_IND_BTN = "statistics_lab_save_chi_independence_btn"
_SAVE_IND_TABLE_BTN = "statistics_lab_save_chi_independence_table_btn"
_STATISTICS_IND_FILE = "statistics_chi_square_independence.csv"
_STATISTICS_IND_TABLE_FILE = "statistics_chi_square_independence_table.csv"

# Homogeneity widget keys / filenames / workspace artifacts.
_HOMOG_OUTCOME_COLUMN = "stats_lab_chi_homog_outcome_column"
_HOMOG_GROUP_COLUMN = "stats_lab_chi_homog_group_column"
_SAVE_HOMOG_BTN = "statistics_lab_save_chi_homogeneity_btn"
_SAVE_HOMOG_TABLE_BTN = "statistics_lab_save_chi_homogeneity_table_btn"
_STATISTICS_HOMOG_FILE = "statistics_chi_square_homogeneity.csv"
_STATISTICS_HOMOG_TABLE_FILE = "statistics_chi_square_homogeneity_table.csv"

_SAVE_ANALYSIS_CAPTION = (
    "Downloads stay in your browser. Optionally save this analysis under your "
    "Workspace Root / analysis; existing files are not overwritten."
)

# ── opt-in result evidence ────────────────────────────────────────────────────
#
# Each chi-square mode offers one clearly labelled checkbox that reveals a
# bounded, result-native evidence view beside the result that produced it. The
# evidence is built only from the completed result object already on screen: the
# statistic, p-value, degrees of freedom and decision are never recomputed and
# the test is never run a second time.

_GOF_SHOW_EVIDENCE = "stats_lab_chi_gof_show_evidence"
_IND_SHOW_EVIDENCE = "stats_lab_chi_independence_show_evidence"
_HOMOG_SHOW_EVIDENCE = "stats_lab_chi_homogeneity_show_evidence"

_EVIDENCE_CHECKBOX_LABEL = "Show evidence chart and interpretation guidance"

_GOF_CONTRIBUTION_CAVEAT = (
    "A chi-square cell contribution localises where observed and expected counts "
    "disagree. It does not explain why they disagree and carries no p-value of its own."
)
_RESIDUAL_DIRECTION_CAVEAT = (
    "A positive Pearson residual means the observed count is above its expected count "
    "and a negative one means it is below; the size is standardised by the expected count."
)
_ASSOCIATION_CAVEAT = (
    "A pattern in this table describes the analyzed rows only. It does not establish "
    "cause and performs no post-hoc comparison of individual cells."
)
_LOW_EXPECTED_CAVEAT = (
    "Cells with small expected counts make the chi-square approximation less reliable. "
    "This note is informational and does not change the test that ran."
)


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


def _proportion_input(st: Any, label: str, *, value: float, key: str) -> float:
    """Page-local bounded expected-proportion input (0–1); never raises upward."""
    raw = st.number_input(
        label,
        min_value=0.0,
        max_value=1.0,
        value=value,
        step=0.05,
        key=key,
    )
    if raw is None:
        return value
    try:
        return float(raw)
    except (TypeError, ValueError):
        return value


def _render_chi_status(st: Any, result: Mapping[str, Any]) -> bool:
    """Render a non-ok chi-square status safely; return True when the result is ok.

    A ``unavailable`` (SciPy absent) status renders a structured warning; every other
    non-ok status renders an informational callout. No raw traceback is ever shown.
    """
    status = str(result.get("status") or "unknown")
    if status == "ok":
        return True
    message = str(result.get("reason") or f"Status: {status}")
    if status == "unavailable":
        render_warning_state(st, message)
    else:
        render_info_state(st, message)
    return False


def _render_chi_decision_cards(st: Any, result: Mapping[str, Any], default_key: str) -> None:
    """Render the shared test / statistic / p-value / decision metric cards."""
    reject_null = result.get("reject_null")
    decision = "reject" if reject_null is True else "do not reject"
    render_metric_cards(
        st,
        [
            {"label": "Test", "value": result.get("test_key", default_key)},
            {"label": "Statistic (χ²)", "value": _format_number(result.get("statistic"))},
            {"label": "p-value", "value": _format_number(result.get("p_value"))},
            {"label": "Decision", "value": decision},
        ],
    )


def _render_downloadable(
    st: Any,
    dataframe: pd.DataFrame,
    *,
    download_label: str,
    file_name: str,
    save_label: str,
    save_key: str,
    artifact: str,
    dataset_name: str | None,
) -> None:
    """Render a visible table with matching browser download and workspace save.

    Only the browser table is bounded: the download button and the workspace save
    always receive the complete, unmodified result frame, and a bound that actually
    withheld rows is disclosed rather than applied silently.
    """
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


def _render_guidance(st: Any, guidance: ResultGuidance) -> None:
    """Render one result's interpretation guidance as bounded caption lines."""
    for heading, text in guidance_sections(guidance):
        st.caption(f"{heading}: {text}")


def _evidence_requested(st: Any, key: str) -> bool:
    """Render the single opt-in evidence toggle for a mode (default off)."""
    return bool(st.checkbox(_EVIDENCE_CHECKBOX_LABEL, key=key))


# ── L1 semantic eligibility (page tier) ───────────────────────────────────────
#
# Categorical selectors are built from the shared eligibility policy instead of
# every dataframe column, so a pathological high-cardinality field never reaches
# option construction from the normal page path. When nothing qualifies the page
# states why, with a bounded summary rather than a hidden failure.

_ELIGIBILITY_HINT = (
    "A categorical analysis needs a field with at least two distinct non-missing "
    f"categories and at most {STATS_CATEGORICAL_MAX_LEVELS} distinct values."
)


def _eligible_categorical(df: pd.DataFrame) -> tuple[list[str], list[ColumnEligibility]]:
    """Eligible categorical column names plus every column's classification."""
    classifications = categorical_candidates(df)
    return eligible_columns(classifications), classifications


def _render_no_eligible_columns(
    st: Any, classifications: list[ColumnEligibility], *, purpose: str
) -> None:
    """Explain, concisely and without enumerating categories, why nothing qualified."""
    summary = exclusion_summary(classifications)
    message = f"{purpose} {_ELIGIBILITY_HINT} No column in this dataset qualifies."
    render_info_state(st, f"{message} {summary}".strip())


def _confirm_eligible(st: Any, df: pd.DataFrame, columns: tuple[str, ...]) -> bool:
    """Re-check a selected column before it reaches option construction.

    The selector already excludes unsafe columns; this is the defensive layer for a
    stale session-state selection, and it keeps a pathological field away from typed
    category construction rather than relying on the widget alone.
    """
    for column in columns:
        verdict = classify_categorical_column(df, column)
        if not verdict.eligible:
            render_info_state(st, f"{verdict.reason} {_ELIGIBILITY_HINT}".strip())
            return False
    return True


# ── goodness of fit ───────────────────────────────────────────────────────────


def _gof_summary_dataframe(result: Mapping[str, Any]) -> pd.DataFrame:
    """Build the one-row goodness-of-fit result summary table."""
    reject_null = result.get("reject_null")
    decision = "reject" if reject_null is True else "do not reject"
    row = {
        "source": "chi-square goodness of fit",
        "test": result.get("test_key"),
        "method": result.get("method"),
        "column": result.get("column"),
        "expected_mode": result.get("expected_mode"),
        "category_count": result.get("category_count"),
        "total_rows": result.get("total_rows"),
        "valid_rows": result.get("valid_rows"),
        "excluded_rows": result.get("excluded_rows"),
        "statistic": result.get("statistic"),
        "p_value": result.get("p_value"),
        "degrees_of_freedom": result.get("degrees_of_freedom"),
        "alpha": result.get("alpha"),
        "reject_null": reject_null,
        "decision": decision,
        "status": result.get("status"),
    }
    return pd.DataFrame([row])


def _gof_counts_dataframe(result: Mapping[str, Any]) -> pd.DataFrame:
    """Build the long-form observed/expected category evidence table."""
    rows = [
        {
            "category": entry.get("category"),
            "observed_count": entry.get("observed"),
            "expected_proportion": entry.get("expected_proportion"),
            "expected_count": entry.get("expected_count"),
        }
        for entry in result.get("categories") or []
    ]
    return pd.DataFrame(
        rows,
        columns=["category", "observed_count", "expected_proportion", "expected_count"],
    )


_GOF_BAR_SPEC: dict[str, Any] = {
    "mark": {"type": "bar"},
    "encoding": {
        "x": {"field": "category", "type": "nominal", "title": "Category"},
        "xOffset": {"field": "measure", "type": "nominal"},
        "y": {"field": "count", "type": "quantitative", "title": "Count"},
        "color": {"field": "measure", "type": "nominal", "title": "Count type"},
        "tooltip": [
            {"field": "category", "type": "nominal"},
            {"field": "measure", "type": "nominal"},
            {"field": "count", "type": "quantitative"},
        ],
    },
}


def _render_gof_evidence(st: Any, result: Mapping[str, Any]) -> None:
    """Render the opt-in goodness-of-fit evidence view beside its existing result.

    Built entirely from the completed result's own ``categories`` contract: the
    test is not re-run and no statistic, p-value or decision is recomputed.
    """
    evidence = build_gof_evidence(result)
    if evidence["status"] != "ok":
        render_info_state(st, f"Evidence view unavailable: {evidence['reason']}.")
        _render_guidance(st, guidance_for_goodness_of_fit(result))
        return
    st.caption(
        "Observed against expected counts for the same categories the test used "
        f"(bounded at {GOF_MAX_CATEGORIES} categories)."
    )
    st.vega_lite_chart(evidence["comparison"], _GOF_BAR_SPEC, use_container_width=True)
    if evidence["contribution_available"]:
        st.caption(
            "Chi-square contribution per category, with each category's share of the "
            "total contribution."
        )
    else:
        render_info_state(
            st,
            "Cell contributions are unavailable because at least one expected count is "
            "not usable; no value is substituted for the missing contribution.",
        )
    st.dataframe(evidence["data"], hide_index=True)
    if evidence["truncated"]:
        st.caption(
            f"Showing the first {evidence['displayed_categories']:,} of "
            f"{evidence['category_count']:,} categories."
        )
    st.caption(_GOF_CONTRIBUTION_CAVEAT)
    _render_guidance(st, guidance_for_goodness_of_fit(result, evidence=evidence))


def _render_gof_result(
    st: Any,
    result: Mapping[str, Any],
    *,
    dataset_name: str | None = None,
) -> None:
    """Render a goodness-of-fit result safely from its status dict."""
    if not _render_chi_status(st, result):
        return
    _render_chi_decision_cards(st, result, "CHI_GOF")
    render_metric_cards(
        st,
        [
            {"label": "Categories", "value": _format_int(result.get("category_count"))},
            {
                "label": "Degrees of freedom",
                "value": _format_int(result.get("degrees_of_freedom")),
            },
            {"label": "Valid rows", "value": _format_int(result.get("valid_rows"))},
            {"label": "Excluded rows", "value": _format_int(result.get("excluded_rows"))},
        ],
    )
    st.caption(
        f"{result.get('method', 'chi_square_goodness_of_fit')} at "
        f"alpha={_format_number(result.get('alpha'))} (right-tail chi-square). "
        f"Expected distribution: {result.get('expected_mode', 'equal')}."
    )
    _render_downloadable(
        st,
        _gof_summary_dataframe(result),
        download_label="Download goodness-of-fit result (CSV)",
        file_name=_STATISTICS_GOF_FILE,
        save_label="Save goodness-of-fit result to Workspace",
        save_key=_SAVE_GOF_BTN,
        artifact="statistics_chi_square_gof",
        dataset_name=dataset_name,
    )
    _render_downloadable(
        st,
        _gof_counts_dataframe(result),
        download_label="Download goodness-of-fit category counts (CSV)",
        file_name=_STATISTICS_GOF_COUNTS_FILE,
        save_label="Save goodness-of-fit category counts to Workspace",
        save_key=_SAVE_GOF_COUNTS_BTN,
        artifact="statistics_chi_square_gof_counts",
        dataset_name=dataset_name,
    )
    for warning in result.get("warnings") or []:
        st.caption(str(warning))
    if _evidence_requested(st, _GOF_SHOW_EVIDENCE):
        _render_gof_evidence(st, result)


def _render_gof_runner(
    st: Any,
    df: pd.DataFrame,
    alpha: float,
    *,
    dataset_name: str | None = None,
) -> None:
    """Goodness-of-fit runner: compare one column's distribution to an expected one."""
    st.caption(
        "Null: the observed category distribution matches the expected distribution. "
        "Alternative: it differs from the expected distribution. Right-tail chi-square; "
        "missing and non-finite values are excluded."
    )
    if not df.columns.tolist():
        st.info("Load a dataset with at least one column to run a goodness-of-fit test.")
        return
    columns, classifications = _eligible_categorical(df)
    if not columns:
        _render_no_eligible_columns(st, classifications, purpose="Goodness of fit:")
        return
    column = st.selectbox("Categorical column", columns, key=_GOF_COLUMN)
    if column is None:
        return
    if not _confirm_eligible(st, df, (str(column),)):
        return
    options, options_error = chi_square_gof_options(df, str(column))
    if options_error is not None:
        render_warning_state(st, options_error)
        return
    if len(options) < 2:
        labels = [option.label for option in options]
        render_info_state(
            st,
            "Goodness of fit needs a column with at least two distinct non-missing categories. "
            f"Observed distinct values in {column!r}: {summarize_labels(labels)}. Values of "
            "different types (e.g. 1 [int] and 1 [str]) are kept distinct.",
        )
        return
    labels = [option.label for option in options]
    st.caption(f"Observed categories in {column!r}: {summarize_labels(labels)}.")
    custom_available = custom_proportions_available(len(options))
    if not custom_available:
        render_info_state(st, CUSTOM_PROPORTION_BOUND_REASON)
    expected_modes = _GOF_EXPECTED_MODES if custom_available else (_GOF_EXPECTED_EQUAL,)
    expected_mode = st.selectbox("Expected distribution", expected_modes, key=_GOF_EXPECTED_MODE)
    if expected_mode is None:
        return
    expected_proportions: dict[Any, float] | None = None
    # ``custom_available`` is re-tested rather than trusted from the selector alone:
    # a stale session-state selection must never instantiate one widget per category.
    if custom_available and expected_mode == _GOF_EXPECTED_CUSTOM:
        st.caption(
            "Enter one expected proportion per category. Each must be greater than zero and "
            "the proportions must sum to 1; inputs are not silently normalized."
        )
        default = 1.0 / len(options)
        expected_proportions = {
            option.identity: _proportion_input(
                st,
                f"Expected proportion — {option.label}",
                value=default,
                key=f"{_GOF_PROP_PREFIX}{index}",
            )
            for index, option in enumerate(options)
        }
    result = run_chi_square_gof_test(
        df,
        str(column),
        expected_proportions=expected_proportions,
        alpha=alpha,
    )
    _render_gof_result(st, result, dataset_name=dataset_name)


# ── contingency-based tests (independence + homogeneity share rendering) ──────


def _contingency_summary_dataframe(
    result: Mapping[str, Any],
    *,
    source: str,
    label_columns: dict[str, str],
) -> pd.DataFrame:
    """Build the one-row summary table for a contingency chi-square result."""
    reject_null = result.get("reject_null")
    decision = "reject" if reject_null is True else "do not reject"
    row: dict[str, Any] = {
        "source": source,
        "test": result.get("test_key"),
        "method": result.get("method"),
    }
    for header, key in label_columns.items():
        row[header] = result.get(key)
    row.update(
        {
            "row_categories": result.get("row_category_count"),
            "column_categories": result.get("col_category_count"),
            "total_rows": result.get("total_rows"),
            "valid_rows": result.get("valid_rows"),
            "excluded_rows": result.get("excluded_rows"),
            "statistic": result.get("statistic"),
            "p_value": result.get("p_value"),
            "degrees_of_freedom": result.get("degrees_of_freedom"),
            "alpha": result.get("alpha"),
            "reject_null": reject_null,
            "decision": decision,
            "status": result.get("status"),
        }
    )
    return pd.DataFrame([row])


def _contingency_cells_dataframe(
    result: Mapping[str, Any],
    *,
    row_header: str,
    col_header: str,
) -> pd.DataFrame:
    """Build the long-form observed/expected contingency evidence table."""
    rows = [
        {
            row_header: entry.get("row_category"),
            col_header: entry.get("col_category"),
            "observed_count": entry.get("observed"),
            "expected_count": entry.get("expected"),
        }
        for entry in result.get("cells") or []
    ]
    return pd.DataFrame(
        rows,
        columns=[row_header, col_header, "observed_count", "expected_count"],
    )


def _contingency_heatmap_spec(row_header: str, col_header: str) -> dict[str, Any]:
    """Vega-Lite spec for the signed Pearson-residual heatmap."""
    return {
        "mark": {"type": "rect"},
        "encoding": {
            "x": {"field": "col_category", "type": "nominal", "title": col_header},
            "y": {"field": "row_category", "type": "nominal", "title": row_header},
            "color": {
                "field": "residual",
                "type": "quantitative",
                "title": "Pearson residual",
                "scale": {"scheme": "blueorange", "domainMid": 0},
            },
            "tooltip": [
                {"field": "row_category", "type": "nominal", "title": row_header},
                {"field": "col_category", "type": "nominal", "title": col_header},
                {"field": "observed", "type": "quantitative"},
                {"field": "expected", "type": "quantitative"},
                {"field": "residual", "type": "quantitative"},
                {"field": "direction", "type": "nominal"},
            ],
        },
    }


def _render_contingency_evidence(
    st: Any,
    result: Mapping[str, Any],
    *,
    family: str,
    row_header: str,
    col_header: str,
) -> None:
    """Render the opt-in contingency evidence view beside its existing result.

    Uses the completed result's own ``cells``, ``row_labels`` and ``col_labels``.
    Only the Pearson residual and the chi-square cell contribution are derived;
    the chi-square statistic, p-value and decision are never recomputed.
    """
    evidence = build_contingency_evidence(result)
    if evidence["status"] != "ok":
        render_info_state(st, f"Evidence view unavailable: {evidence['reason']}.")
        _render_guidance(st, guidance_for_contingency(result, family=family))
        return
    st.caption(
        "Signed Pearson residual per cell: observed minus expected, standardised by the "
        f"expected count (bounded at {CONTINGENCY_MAX_ROWS} x {CONTINGENCY_MAX_COLUMNS} "
        f"categories and {CONTINGENCY_MAX_CELLS} cells)."
    )
    st.vega_lite_chart(
        evidence["data"],
        _contingency_heatmap_spec(row_header, col_header),
        use_container_width=True,
    )
    st.caption("Cells ranked by the size of their departure from the expected count.")
    st.dataframe(evidence["ranked"], hide_index=True)
    st.caption(_RESIDUAL_DIRECTION_CAVEAT)
    if evidence["sparse_expected"]:
        st.caption(
            f"{evidence['low_expected_cells']} cell(s) have an expected count below 5. "
            f"{_LOW_EXPECTED_CAVEAT}"
        )
    st.caption(_ASSOCIATION_CAVEAT)
    _render_guidance(st, guidance_for_contingency(result, family=family, evidence=evidence))


def _render_contingency_result(
    st: Any,
    result: Mapping[str, Any],
    *,
    default_key: str,
    source: str,
    family: str,
    show_key: str,
    label_columns: dict[str, str],
    row_header: str,
    col_header: str,
    summary_file: str,
    table_file: str,
    summary_artifact: str,
    table_artifact: str,
    summary_save_key: str,
    table_save_key: str,
    dataset_name: str | None = None,
) -> None:
    """Render a contingency chi-square result (shared by independence and homogeneity)."""
    if not _render_chi_status(st, result):
        return
    _render_chi_decision_cards(st, result, default_key)
    dimensions = (
        f"{_format_int(result.get('row_category_count'))}"
        f" × {_format_int(result.get('col_category_count'))}"
    )
    render_metric_cards(
        st,
        [
            {"label": "Rows × columns", "value": dimensions},
            {
                "label": "Degrees of freedom",
                "value": _format_int(result.get("degrees_of_freedom")),
            },
            {"label": "Valid rows", "value": _format_int(result.get("valid_rows"))},
            {"label": "Excluded rows", "value": _format_int(result.get("excluded_rows"))},
        ],
    )
    st.caption(
        f"{result.get('method', 'chi_square')} at alpha={_format_number(result.get('alpha'))} "
        "(right-tail chi-square)."
    )
    row_summary = summarize_labels(result.get("row_labels"), total=result.get("row_category_count"))
    col_summary = summarize_labels(result.get("col_labels"), total=result.get("col_category_count"))
    st.caption(f"{row_header} categories: {row_summary}. {col_header} categories: {col_summary}.")
    _render_downloadable(
        st,
        _contingency_summary_dataframe(result, source=source, label_columns=label_columns),
        download_label=f"Download {source} result (CSV)",
        file_name=summary_file,
        save_label=f"Save {source} result to Workspace",
        save_key=summary_save_key,
        artifact=summary_artifact,
        dataset_name=dataset_name,
    )
    _render_downloadable(
        st,
        _contingency_cells_dataframe(result, row_header=row_header, col_header=col_header),
        download_label=f"Download {source} table (CSV)",
        file_name=table_file,
        save_label=f"Save {source} table to Workspace",
        save_key=table_save_key,
        artifact=table_artifact,
        dataset_name=dataset_name,
    )
    for warning in result.get("warnings") or []:
        st.caption(str(warning))
    if _evidence_requested(st, show_key):
        _render_contingency_evidence(
            st,
            result,
            family=family,
            row_header=row_header,
            col_header=col_header,
        )


def _select_distinct_columns(
    st: Any,
    columns: list[str],
    *,
    first_label: str,
    second_label: str,
    first_key: str,
    second_key: str,
) -> tuple[str, str] | None:
    """Render two column selectors, forcing the second to differ from the first."""
    first = st.selectbox(first_label, columns, key=first_key)
    if first is None:
        return None
    second_options = [column for column in columns if column != str(first)]
    if not second_options:
        st.info("Need a second distinct column.")
        return None
    second = st.selectbox(second_label, second_options, key=second_key)
    if second is None:
        return None
    return str(first), str(second)


def _render_independence_runner(
    st: Any,
    df: pd.DataFrame,
    alpha: float,
    *,
    dataset_name: str | None = None,
) -> None:
    """Independence runner: test whether two categorical variables are associated."""
    st.caption(
        "Null: the two variables are independent. Alternative: the two variables are "
        "associated. Right-tail chi-square on a contingency table; a row is excluded when "
        "either selected value is missing or non-finite."
    )
    if len(df.columns.tolist()) < 2:
        st.info("Need at least two columns to test independence.")
        return
    columns, classifications = _eligible_categorical(df)
    if len(columns) < 2:
        _render_no_eligible_columns(
            st, classifications, purpose="Independence needs two categorical columns:"
        )
        return
    selection = _select_distinct_columns(
        st,
        columns,
        first_label="First categorical column",
        second_label="Second categorical column",
        first_key=_IND_FIRST_COLUMN,
        second_key=_IND_SECOND_COLUMN,
    )
    if selection is None:
        return
    first_column, second_column = selection
    if not _confirm_eligible(st, df, (first_column, second_column)):
        return
    result = run_chi_square_independence_test(df, first_column, second_column, alpha=alpha)
    _render_contingency_result(
        st,
        result,
        default_key="CHI_IND",
        source="independence",
        family="independence",
        show_key=_IND_SHOW_EVIDENCE,
        label_columns={"first_column": "first_column", "second_column": "second_column"},
        row_header="first_category",
        col_header="second_category",
        summary_file=_STATISTICS_IND_FILE,
        table_file=_STATISTICS_IND_TABLE_FILE,
        summary_artifact="statistics_chi_square_independence",
        table_artifact="statistics_chi_square_independence_table",
        summary_save_key=_SAVE_IND_BTN,
        table_save_key=_SAVE_IND_TABLE_BTN,
        dataset_name=dataset_name,
    )


def _render_homogeneity_runner(
    st: Any,
    df: pd.DataFrame,
    alpha: float,
    *,
    dataset_name: str | None = None,
) -> None:
    """Homogeneity runner: test whether an outcome distribution is equal across groups."""
    st.caption(
        "Null: every population/group has the same outcome distribution. Alternative: at "
        "least one population/group has a different outcome distribution. Right-tail "
        "chi-square on a contingency table (populations on the rows, outcome categories on "
        "the columns); a row is excluded when either selected value is missing or "
        "non-finite. This does not imply causation and performs no post-hoc group comparison."
    )
    if len(df.columns.tolist()) < 2:
        st.info("Need at least two columns to test homogeneity.")
        return
    columns, classifications = _eligible_categorical(df)
    if len(columns) < 2:
        _render_no_eligible_columns(
            st, classifications, purpose="Homogeneity needs two categorical columns:"
        )
        return
    selection = _select_distinct_columns(
        st,
        columns,
        first_label="Outcome / category column",
        second_label="Population / group column",
        first_key=_HOMOG_OUTCOME_COLUMN,
        second_key=_HOMOG_GROUP_COLUMN,
    )
    if selection is None:
        return
    outcome_column, group_column = selection
    if not _confirm_eligible(st, df, (outcome_column, group_column)):
        return
    result = run_chi_square_homogeneity_test(df, group_column, outcome_column, alpha=alpha)
    _render_contingency_result(
        st,
        result,
        default_key="CHI_HOMOG",
        source="homogeneity",
        family="homogeneity",
        show_key=_HOMOG_SHOW_EVIDENCE,
        label_columns={"group_column": "group_column", "outcome_column": "outcome_column"},
        row_header="group",
        col_header="outcome",
        summary_file=_STATISTICS_HOMOG_FILE,
        table_file=_STATISTICS_HOMOG_TABLE_FILE,
        summary_artifact="statistics_chi_square_homogeneity",
        table_artifact="statistics_chi_square_homogeneity_table",
        summary_save_key=_SAVE_HOMOG_BTN,
        table_save_key=_SAVE_HOMOG_TABLE_BTN,
        dataset_name=dataset_name,
    )


# ── section entry point ───────────────────────────────────────────────────────


def render_chi_square_tests_runner(
    st: Any,
    df: pd.DataFrame,
    alpha: float,
    *,
    dataset_name: str | None = None,
) -> None:
    """Chi-square tests section (user-selected mode).

    A single bounded inferential section offering the loaded-dataset chi-square tests.
    Every mode is right-tail chi-square and routes through the public
    ``run_statistical_test`` seam; the section adds no new formula or TestKey and does
    not change any automatic test recommendation or verdict threshold.
    """
    render_section_header(
        st,
        "Chi-square tests",
        "Right-tail chi-square tests for categorical distributions. Does not change "
        "automatic test recommendations.",
    )
    st.caption(
        "Categorical hypothesis tests on the loaded dataset. Missing values are excluded; "
        "non-finite numeric values are excluded. Expected-frequency notes are informational "
        "and never switch the test."
    )
    mode = st.selectbox("Chi-square test", _CHI_MODES, key=_CHI_MODE_KEY)
    if mode == _CHI_MODE_IND:
        _render_independence_runner(st, df, alpha, dataset_name=dataset_name)
    elif mode == _CHI_MODE_HOMOG:
        _render_homogeneity_runner(st, df, alpha, dataset_name=dataset_name)
    else:
        _render_gof_runner(st, df, alpha, dataset_name=dataset_name)
