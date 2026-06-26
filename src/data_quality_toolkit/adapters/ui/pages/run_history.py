"""Quality History page: score trend, latest-run issues, and run comparison."""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.ui.components.storylens import render_storylens_card
from data_quality_toolkit.adapters.ui.eda import (
    _build_trend_df,
    _extract_latest_issues,
    _extract_trend_data,
)
from data_quality_toolkit.adapters.ui.services.assessment import _load_run_history
from data_quality_toolkit.adapters.ui.services.compare import _run_compare
from data_quality_toolkit.application.explanation import explain_not_enough_runs


def _render_compare_section(st: Any, db_path_str: str, dataset_id: str) -> None:
    """Render the run-to-run delta below the trend section."""
    st.divider()
    st.subheader("Run-to-Run Comparison")
    result, err = _run_compare(db_path_str, dataset_id)
    if err is not None:
        st.info(f"Compare unavailable: {err}")
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
    st.header("Quality History")
    st.caption("Load historical quality-audit data (separate from drift monitoring history).")
    st.info(
        "**How to generate run history:** run `dqt export <file.csv> --outdir <dir>` at least once. "
        "This writes `<dir>/dqt.db` and `<dir>/star/quality_report.json`. "
        "The **Dataset ID** is the `dataset_id` field inside `quality_report.json` "
        "(example: `sha1:a3f2...`). Run export again to accumulate trend data."
    )
    db_path_str = st.text_input("Database path", placeholder="e.g., ./dist/dqt.db")
    dataset_id = st.text_input(
        "Dataset ID",
        placeholder="e.g., sha1:a3f2… (from dist/star/quality_report.json)",
    )

    if not db_path_str or not dataset_id:
        st.info("💡 Enter a database path and dataset ID above to load run history.")
        return

    records, err = _load_run_history(db_path_str, dataset_id)
    if err is not None:
        st.error(f"Storage error: {err}")
        return

    if not records:
        st.warning("No run history found for this dataset.")
        return

    if len(records) == 1:
        try:
            render_storylens_card(st, [explain_not_enough_runs(run_count=1)])
        except Exception:  # noqa: S110
            pass

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

    if len(records) >= 2:
        _render_compare_section(st, db_path_str, dataset_id)


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_run_history(st)
