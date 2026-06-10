"""Run History page: score trend and latest-run issues from the DQT database."""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.ui.eda import (
    _build_trend_df,
    _extract_latest_issues,
    _extract_trend_data,
)
from data_quality_toolkit.adapters.ui.services.assessment import _load_run_history


def _render_run_history(st: Any) -> None:
    """Render the Run History section: trend chart and latest issues breakdown."""
    st.header("Run History")
    st.caption("Load historical audit data from the DQT database.")
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


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_run_history(st)
