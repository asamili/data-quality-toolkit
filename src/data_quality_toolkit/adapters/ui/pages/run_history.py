"""Quality History page: score trend, latest-run issues, and run comparison."""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.ui import journey
from data_quality_toolkit.adapters.ui.components.errors import redact_message_paths
from data_quality_toolkit.adapters.ui.components.page_guidance import render_page_guidance
from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_page_header,
    render_section_header,
)
from data_quality_toolkit.adapters.ui.components.source_context import (
    export_run_id_evidence,
    render_dataset_id_input,
    render_quality_history_db_input,
)
from data_quality_toolkit.adapters.ui.components.source_hub import (
    render_source_hub_source_summary,
    render_use_current_dataset_id,
)
from data_quality_toolkit.adapters.ui.components.storylens import render_storylens_card
from data_quality_toolkit.adapters.ui.eda import (
    _build_trend_df,
    _extract_latest_issues,
    _extract_trend_data,
)
from data_quality_toolkit.adapters.ui.services.assessment import _load_run_history
from data_quality_toolkit.adapters.ui.services.compare import _run_compare
from data_quality_toolkit.application.explanation import explain_not_enough_runs

# One-line operator flow map shown under the page guidance so the numbered stage
# headers below read as a single guided sequence.
_FLOW_MAP = (
    "Flow: 1 Choose history source and dataset → 2 Review score trend → "
    "3 Inspect latest issues → 4 Compare runs"
)


def _render_export_run_evidence(st: Any) -> None:
    """Show the latest successful Export's run ID as read-only evidence.

    This page queries history by database and Dataset ID only; there is no Run ID
    control, and this value is not one. It is shown so the operator can tell which
    Export produced the newest history, and it is deliberately not editable and
    not a query filter.
    """
    try:
        run_id = export_run_id_evidence(st.session_state)
    except Exception:
        return
    if not run_id:
        return
    st.caption(
        f"Latest successful Export run ID: `{run_id}`. Shown as export evidence only — "
        "this page filters history by database and Dataset ID, not by run ID."
    )


def _render_compare_section(st: Any, db_path_str: str, dataset_id: str) -> None:
    """Render the run-to-run delta below the trend section."""
    st.divider()
    render_section_header(st, "4 · Run-to-run comparison")
    result, err = _run_compare(db_path_str, dataset_id)
    if err is not None:
        st.info(f"Compare unavailable: {redact_message_paths(err)}")
        return

    if result is None:
        return

    score_delta = result.get("score_delta")
    issues_delta = result.get("issues_delta")

    col1, col2 = st.columns(2)
    with col1:
        delta_str = f"{score_delta:+.4f}" if score_delta is not None else None
        st.metric("Score (current)", f"{result.get('current_score', 0):.2f}", delta=delta_str)
    with col2:
        issues_delta_str = str(int(issues_delta)) if issues_delta is not None else None
        st.metric(
            "Issues (current)", str(result.get("current_issues_total", 0)), delta=issues_delta_str
        )

    sev_delta = result.get("issues_by_severity_delta")
    cat_delta = result.get("issues_by_category_delta")
    if sev_delta or cat_delta:
        col3, col4 = st.columns(2)
        if sev_delta:
            with col3:
                st.caption("Issues delta by severity")
                st.table(sev_delta)
        if cat_delta:
            with col4:
                st.caption("Issues delta by category")
                st.table(cat_delta)


def _render_run_history(st: Any) -> None:
    """Render the Run History section: trend chart, latest issues breakdown, and run comparison."""
    render_page_header(
        st,
        "Quality History",
        "Load historical quality-audit data (separate from drift monitoring history).",
        step_label=journey.step_label("run_history"),
    )
    render_page_guidance(
        st,
        purpose="Review quality-run history and run-to-run comparison from the quality-history "
        "database.",
        inputs="A quality-history database and a Dataset ID.",
        workflow="Enter the database and Dataset ID, then inspect the score trend and issue "
        "changes.",
        next_step="Artifact Center — manifest-backed artifact review "
        "(requires a manifest-producing session/pipeline run)",
    )
    st.caption(_FLOW_MAP)

    render_section_header(st, "1 · Choose history source and dataset")
    st.caption(
        "This page is read-only: entering a database and Dataset ID only reads "
        "quality history. Nothing is written."
    )
    st.info(
        "**Reuse your loaded dataset:** click **Use current dataset** below to fill the "
        "Dataset ID automatically — no need to paste it. "
        "**To create run history:** run Export at least once. A successful Export "
        "prefills the Quality-history database and Dataset ID here when those "
        "fields are blank; values you entered yourself are kept. Run Export again to "
        "accumulate trend data. Opening historical or external results manually still "
        "works: enter a `dqt.db` path and the `dataset_id` field from "
        "`quality_report.json`."
    )
    db_path_str = render_quality_history_db_input(st)
    render_use_current_dataset_id(st)
    dataset_id = render_dataset_id_input(st)
    _render_export_run_evidence(st)
    render_source_hub_source_summary(
        st,
        (
            ("Quality-history database", db_path_str),
            ("Dataset ID", dataset_id),
        ),
        present_text="Using Quality History sources from Start",
        missing_text="Set Quality History source values in Start / Load Dataset",
    )

    if not db_path_str or not dataset_id:
        st.info("💡 Enter a database path and dataset ID above to load run history.")
        return

    records, err = _load_run_history(db_path_str, dataset_id)
    if err is not None:
        st.error(f"Storage error: {redact_message_paths(err)}")
        return

    if not records:
        st.warning(
            "No run history found for this dataset. Run `dqt export` on it at least "
            "once to record a first run."
        )
        return

    if len(records) == 1:
        try:
            render_storylens_card(st, [explain_not_enough_runs(run_count=1)])
        except Exception:  # noqa: S110
            pass

    trend = _extract_trend_data(records)
    if len(trend) >= 2:
        render_section_header(st, "2 · Score trend")
        df = _build_trend_df(trend)
        if df is not None:
            st.line_chart(df[["Score"]])
        else:
            st.line_chart({"Score": [r["score"] for r in trend]})

    sev, cat = _extract_latest_issues(records)
    if sev or cat:
        render_section_header(st, "3 · Latest run — issues breakdown")
        col1, col2 = st.columns(2)
        with col1:
            st.caption("By severity")
            st.table(sev)
        with col2:
            st.caption("By category")
            st.table(cat)

    st.caption("All recorded runs")
    st.dataframe(records)

    if len(records) >= 2:
        _render_compare_section(st, db_path_str, dataset_id)


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_run_history(st)
