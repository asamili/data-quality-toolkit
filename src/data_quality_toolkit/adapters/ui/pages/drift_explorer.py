"""Privacy-safe, read-only Drift Explorer for monitoring history and evidence."""

from __future__ import annotations

import os
from typing import Any

from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_metric_cards,
    render_page_header,
    render_section_header,
)
from data_quality_toolkit.adapters.ui.components.storylens import render_storylens_card
from data_quality_toolkit.adapters.ui.services.monitoring import (
    build_drift_storylens_cards,
    columns_to_display_dicts,
    compact_identifier,
    distributions_to_display_dicts,
    evaluate_drift_rate_for_display,
    evaluate_psi_for_display,
    format_drift_state,
    format_optional,
    load_distribution_series,
    load_monitoring_overview,
    load_run_detail,
    redact_path_to_basename,
    runs_to_display_dicts,
)
from data_quality_toolkit.adapters.ui.state import keys
from data_quality_toolkit.application.explanation import (
    Explanation,
    explain_no_drift,
    explain_not_enough_runs,
)

_DB_ENV_VAR = "DQT_UI_DB"
_METRIC_FIELDS: dict[str, str] = {
    "PSI": "psi",
    "Jensen-Shannon": "js_distance",
    "Wasserstein": "wasserstein",
    "Statistic": "statistic",
    "p-value": "p_value",
}
_DASHBOARD_CMD = "dqt drift-history dashboard --db monitoring.db --output dashboard.html"
_UI_CMD = "dqt ui --db monitoring.db"


def _drift_summary_storylens(summary: Any) -> list[Explanation]:
    """Compatibility helper retained for deterministic StoryLens wiring tests."""
    try:
        total = int(summary.total_runs)
        if total < 2:
            return [explain_not_enough_runs(run_count=total)]
        if int(summary.drifted_runs) == 0:
            return [
                explain_no_drift(
                    drift_detected=False,
                    run_id=summary.latest_run_id or None,
                )
            ]
        return []
    except Exception:
        return []


def _render_cli_help(st: Any) -> None:
    st.caption("Generate a static HTML dashboard, or relaunch this explorer:")
    st.code(_DASHBOARD_CMD, language="bash")
    st.code(_UI_CMD, language="bash")


def _latest_run(overview: Any) -> Any | None:
    """Return the summary's latest run when present in the loaded window."""
    latest_id = overview.summary.latest_run_id
    return next((run for run in overview.runs if run.run_id == latest_id), None) or (
        overview.runs[0] if overview.runs else None
    )


def _render_summary(st: Any, overview: Any) -> None:
    """Render monitoring status without collapsing unknown drift into no drift."""
    summary = overview.summary
    latest = _latest_run(overview)
    render_section_header(st, "Monitoring status summary")

    render_metric_cards(
        st,
        [
            {"label": "Total runs", "value": str(summary.total_runs)},
            {"label": "Drifted runs", "value": str(summary.drifted_runs)},
            {"label": "Drift rate", "value": f"{summary.drift_rate:.2%}"},
            {
                "label": "Latest drift state",
                "value": format_drift_state(summary.latest_drift_detected),
            },
        ],
    )

    counts = (
        f"{format_optional(latest.columns_tested)} / "
        f"{format_optional(latest.columns_drifted)} / "
        f"{format_optional(latest.columns_skipped)}"
        if latest
        else "unavailable"
    )
    render_metric_cards(
        st,
        [
            {"label": "Latest run", "value": compact_identifier(summary.latest_run_id)},
            {
                "label": "Latest status",
                "value": format_optional(latest.status if latest else None),
            },
            {"label": "Latest time", "value": format_optional(summary.latest_created_at)},
            {"label": "Tested / drifted / skipped", "value": counts},
        ],
    )


def _render_drift_rate_threshold(st: Any, overview: Any) -> float:
    """Render an informational threshold using authoritative evaluator semantics."""
    render_section_header(st, "Drift-rate threshold guidance")
    threshold = float(
        st.number_input(
            "Maximum acceptable drift rate",
            min_value=0.0,
            max_value=1.0,
            value=0.20,
            step=0.05,
            key=keys.DRIFT_RATE_THRESHOLD,
            help="A breach occurs only when drift rate is strictly greater than this value.",
        )
    )
    result = evaluate_drift_rate_for_display(overview, threshold=threshold)
    message = (
        f"Observed {result['drift_rate']:.2%}; threshold {result['threshold']:.2%}. "
        "This is informational guidance, not validation approval."
    )
    if result["breached"]:
        st.warning(f"Threshold breached. {message}")
    else:
        st.info(f"Threshold not breached. {message}")
    return threshold


def _trend_rows(overview: Any) -> list[dict[str, Any]]:
    """Build oldest-to-newest run-series rows for the history view."""
    return [
        {
            "Run": compact_identifier(run.run_id),
            "Created at": format_optional(run.created_at),
            "Drift state": (
                1.0 if run.drift_detected is True else 0.0 if run.drift_detected is False else None
            ),
        }
        for run in reversed(overview.runs)
    ]


def _render_history(st: Any, overview: Any) -> None:
    """Render run-series context, with raw-ish history kept as secondary evidence."""
    render_section_header(st, "Monitoring history")
    if len(overview.runs) < 2:
        st.info(
            "Insufficient trend history: at least two monitoring runs are needed for a "
            "run-series view. A single run can still contain reference/current drift evidence."
        )
    else:
        rows = _trend_rows(overview)
        st.line_chart(rows, x="Created at", y="Drift state")
        st.caption(
            "Oldest to newest; drift state uses 1 for yes and 0 for no. "
            "Unknown states remain unavailable and are not converted to no drift."
        )

    with st.expander("View run history evidence"):
        st.dataframe(runs_to_display_dicts(overview), use_container_width=True)


def _render_psi_threshold(st: Any, columns: list[Any]) -> None:
    """Offer PSI guidance only when the selected run has authoritative PSI values."""
    observed = [column.psi for column in columns if column.psi is not None]
    if not observed:
        st.caption("PSI threshold guidance is unavailable: this run has no recorded PSI values.")
        return

    threshold = float(
        st.number_input(
            "Maximum acceptable PSI",
            min_value=0.0,
            value=0.20,
            step=0.05,
            key=keys.DRIFT_PSI_THRESHOLD,
            help="Evaluated only against recorded per-column PSI values for this run.",
        )
    )
    result = evaluate_psi_for_display(columns, threshold=threshold)
    max_observed = max(observed)
    message = (
        f"Maximum recorded PSI {max_observed:.4f}; threshold {threshold:.4f}. "
        "This is informational guidance, not validation approval."
    )
    if result["breached"]:
        st.warning(f"PSI threshold breached by {len(result['offenders'])} column(s). {message}")
    else:
        st.info(f"PSI threshold not breached. {message}")


def _render_distribution_section(
    st: Any, db_path_str: str, run_id: str, col_names: list[str]
) -> None:
    render_section_header(st, "Distribution evidence")
    if not col_names:
        st.info("No columns are available for distribution inspection.")
        return

    dist_column = st.selectbox(
        "Distribution column", options=col_names, key=keys.DRIFT_DISTRIBUTION_COLUMN
    )
    bins, err = load_distribution_series(db_path_str, run_id, dist_column)
    if err is not None:
        st.error(f"Could not load distribution evidence: {err}")
        return
    if not bins:
        st.info("No distribution bins were recorded for this column.")
        return

    display_rows = distributions_to_display_dicts(bins)
    chart_rows = [
        {
            "Bin": item.bin_label or str(item.bin_index),
            "Reference": item.reference_prob if item.reference_prob is not None else 0.0,
            "Current": item.current_prob if item.current_prob is not None else 0.0,
        }
        for item in bins
    ]
    st.bar_chart(chart_rows, x="Bin", y=["Reference", "Current"])
    st.caption(
        "Chart-only note: unavailable probabilities are zero-filled solely so Streamlit can "
        "draw the bars. The evidence table below preserves them as unavailable."
    )
    st.dataframe(display_rows, use_container_width=True)


def _render_columns_section(st: Any, db_path_str: str, run_id: str) -> None:
    """Render selected-run status, thresholds, column evidence, and distributions."""
    detail, err = load_run_detail(db_path_str, run_id)
    if err is not None:
        st.error(f"Could not load selected-run detail: {err}")
        return
    if detail is None:
        st.warning("Selected-run detail is unavailable.")
        return

    run = detail.run
    render_section_header(st, "Selected-run detail")
    render_metric_cards(
        st,
        [
            {"label": "Drift detected", "value": format_drift_state(run.drift_detected)},
            {"label": "Status", "value": format_optional(run.status)},
            {"label": "Alpha", "value": format_optional(run.alpha)},
            {
                "label": "Tested / drifted / skipped",
                "value": (
                    f"{format_optional(run.columns_tested)} / "
                    f"{format_optional(run.columns_drifted)} / "
                    f"{format_optional(run.columns_skipped)}"
                ),
            },
        ],
    )

    if not detail.columns:
        st.info("No column-level drift results were recorded for this run.")
        return

    _render_psi_threshold(st, detail.columns)
    render_section_header(st, "Column-level evidence")
    col_names = sorted({column.column_name for column in detail.columns if column.column_name})
    kinds = sorted({column.kind for column in detail.columns if column.kind})

    fcol1, fcol2, fcol3, fcol4 = st.columns(4)
    with fcol1:
        column_filter = st.selectbox(
            "Column", options=["(all)", *col_names], key=keys.DRIFT_COLUMN_FILTER
        )
    with fcol2:
        drift_filter = st.selectbox(
            "Drift detected",
            options=["(all)", "Yes", "No", "Unknown"],
            key=keys.DRIFT_STATUS_FILTER,
        )
    with fcol3:
        kind_filter = st.selectbox(
            "Column type", options=["(all)", *kinds], key=keys.DRIFT_KIND_FILTER
        )
    with fcol4:
        metric_label = st.selectbox(
            "Sort by metric", options=list(_METRIC_FIELDS), key=keys.DRIFT_METRIC_SORT
        )

    filtered = list(detail.columns)
    if column_filter != "(all)":
        filtered = [column for column in filtered if column.column_name == column_filter]
    if drift_filter != "(all)":
        filtered = [
            column
            for column in filtered
            if format_drift_state(column.drift_detected) == drift_filter
        ]
    if kind_filter != "(all)":
        filtered = [column for column in filtered if column.kind == kind_filter]

    metric_field = _METRIC_FIELDS[metric_label]
    filtered.sort(
        key=lambda column: (
            getattr(column, metric_field) is None,
            -(getattr(column, metric_field) or 0.0),
        )
    )
    if not filtered:
        st.info("No columns match the current filters.")
    else:
        st.dataframe(columns_to_display_dicts(filtered, alpha=run.alpha), use_container_width=True)

    _render_distribution_section(st, db_path_str, run_id, col_names)


def _render_drift_explorer(st: Any) -> None:
    """Render the Drift Explorer page body."""
    render_page_header(
        st,
        "Drift Monitoring",
        "Inspect monitoring status, deterministic explanations, run history, and drift "
        "evidence from a local monitoring database.",
        step_label="Step 8 of 11 — Drift Monitoring",
    )

    render_section_header(st, "Monitoring source and filters")
    initial_db = os.environ.get(_DB_ENV_VAR, "")
    db_path_str = st.text_input(
        "Local monitoring database",
        value=initial_db,
        placeholder="e.g., ./monitoring.db",
        key=keys.DRIFT_DB_PATH,
    )
    if not db_path_str.strip():
        st.info(
            "Enter a local SQLite monitoring database path. This page is read-only and "
            "does not run drift calculations."
        )
        _render_cli_help(st)
        return

    safe_name = redact_path_to_basename(db_path_str) or "selected database"
    st.caption(f"Local-only source selected: {safe_name}")
    dataset_filter = st.text_input(
        "Current dataset ID filter",
        placeholder="Optional: exact current_dataset_id",
        key=keys.DRIFT_DATASET_FILTER,
    ).strip()
    limit = int(
        st.number_input(
            "Maximum monitoring runs",
            min_value=1,
            max_value=1000,
            value=100,
            step=1,
            key=keys.DRIFT_LIMIT,
        )
    )
    if dataset_filter:
        st.caption(f"Scoped to dataset: {compact_identifier(dataset_filter)}")
    else:
        st.warning(
            "No dataset filter is selected. The summary may aggregate monitoring runs from "
            "multiple current_dataset_id values."
        )

    overview, err = load_monitoring_overview(
        db_path_str,
        current_dataset_id=dataset_filter or None,
        limit=limit,
    )
    if err is not None:
        st.error(f"Could not load monitoring data from {safe_name}: {err}")
        return
    if overview is None:
        st.warning("Monitoring data is unavailable.")
        return

    _render_summary(st, overview)
    threshold = _render_drift_rate_threshold(st, overview)

    render_section_header(st, "Deterministic monitoring explanation")
    render_storylens_card(
        st,
        build_drift_storylens_cards(
            overview,
            threshold_metric="drift_rate",
            threshold_value=threshold,
        ),
    )

    if not overview.runs:
        st.warning("No monitoring runs were found for the selected filters.")
        _render_cli_help(st)
        return

    _render_history(st, overview)
    run_ids = [run.run_id for run in overview.runs if run.run_id]
    if not run_ids:
        st.info("Runs are present, but none have a run ID available for inspection.")
        return

    render_section_header(st, "Run-level inspection")
    selected_run = st.selectbox(
        "Select a monitoring run",
        options=run_ids,
        format_func=compact_identifier,
        key=keys.DRIFT_RUN_SELECTOR,
    )
    if selected_run:
        _render_columns_section(st, db_path_str, selected_run)

    st.divider()
    _render_cli_help(st)


def render() -> None:
    """Streamlit navigation entry point."""
    import streamlit as st

    _render_drift_explorer(st)
