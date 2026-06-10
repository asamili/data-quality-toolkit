"""Data Overview page: CSV profiling and quality assessment (full and large-data modes)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.components.downloads import csv_download_button
from data_quality_toolkit.adapters.ui.components.errors import show_error
from data_quality_toolkit.adapters.ui.eda import (
    _build_overview_table,
    _duplicate_row_count,
    _high_cardinality_flags,
    _load_df_and_assess,
    _numeric_summary,
)
from data_quality_toolkit.adapters.ui.services.assessment import _load_profile_chunked

_LARGE_MODE_BANNER: str = (
    "**Large-file mode (profile-only):** "
    "Approximate profile via chunked streaming — no full-DataFrame load. "
    "Assessment, EDA, export, preprocessing plan, unique counts, "
    "outlier detection, and correlation are disabled."
)


def _render_large_data_profile_overview(st: Any, envelope: dict[str, Any]) -> None:
    """Render profile-only view for large-data mode.

    No DataFrame, no EDA, no assessment, no preprocessing plan.
    Shows: persistent warning banner, row/col counts, null table, dtype table.
    """
    st.warning(_LARGE_MODE_BANNER)
    profile = envelope.get("profile") or {}
    st.write(
        f"**Dataset Profile (approximate):** "
        f"{profile.get('rows', '?')} rows × {profile.get('cols', '?')} columns"
    )
    overview = _build_overview_table(profile)
    if not overview:
        st.info("No column data available.")
        return
    st.subheader("Column Analysis")
    overview_df = pd.DataFrame(overview)
    st.dataframe(overview_df)
    csv_download_button(st, "Download column analysis as CSV", overview_df, "column_analysis.csv")
    null_df = pd.DataFrame(
        {"null_pct": [r["null_pct"] for r in overview]},
        index=[r["column"] for r in overview],
    )
    if null_df["null_pct"].sum() > 0:
        st.caption("Null % by column")
        st.bar_chart(null_df)
    unsupported = envelope.get("unsupported_metrics") or []
    if unsupported:
        st.caption(f"Metrics unavailable in large-file mode: {', '.join(unsupported)}")


def _render_data_overview_large_mode(st: Any, csv_path: str) -> None:
    """Large-data mode branch: chunked profile-only, no full-DataFrame load."""
    chunksize = int(
        st.number_input(
            "Chunk size (rows per chunk)",
            min_value=1_000,
            max_value=1_000_000,
            value=100_000,
            step=10_000,
        )
    )
    envelope, err = _load_profile_chunked(csv_path, chunksize)
    if err is not None:
        show_error(st, "Profile Error", err)
        return
    if envelope is None:
        return
    _render_large_data_profile_overview(st, envelope)


def _render_data_overview(st: Any) -> None:
    """Render the Data Overview section: shape, per-column table, stats, duplicates."""
    st.header("Data Overview")
    st.caption("Perform automated quality assessment on a CSV file.")
    overview_csv = st.text_input("CSV path", placeholder="e.g., ./data/my_dataset.csv")
    if not overview_csv:
        st.info("💡 Enter a CSV path above to start profiling.")
        return

    large_mode = st.checkbox(
        "Large-data mode (profile-only, chunked streaming)",
        help=(
            "Enable for files too large to load into memory. "
            "Uses chunked streaming — no full-DataFrame load. "
            "Assessment, EDA, export, and preprocessing plan are disabled."
        ),
    )
    if large_mode:
        _render_data_overview_large_mode(st, overview_csv)
        return

    df, out, err = _load_df_and_assess(overview_csv)
    if err is not None:
        show_error(st, "Assessment Error", err)
        return
    if df is None or out is None:
        return

    profile = out["profile"]
    assessment = out["assessment"]
    score = float(assessment["score"])
    issues = list(assessment.get("issues") or [])

    st.divider()
    metric_col1, metric_col2 = st.columns(2)
    with metric_col1:
        st.metric("Quality Score", f"{score:.2%}")
    with metric_col2:
        st.metric("Issues Flagged", len(issues))

    if issues:
        issues_df = pd.DataFrame(issues)
        with st.expander("View Flagged Issues"):
            st.dataframe(issues_df)
            csv_download_button(st, "Download issues as CSV", issues_df, "flagged_issues.csv")

    st.write(
        f"**Dataset Profile**: {profile['rows']} rows × {profile['cols']} columns | {profile['memory_mb']:.2f} MB"
    )

    st.subheader("Column Analysis")
    overview = _build_overview_table(profile)
    overview_df = pd.DataFrame(overview)
    st.dataframe(overview_df)
    csv_download_button(st, "Download column analysis as CSV", overview_df, "column_analysis.csv")
    null_df = pd.DataFrame(
        {"null_pct": [r["null_pct"] for r in overview]},
        index=[r["column"] for r in overview],
    )
    if null_df["null_pct"].sum() > 0:
        st.caption("Null % by column")
        st.bar_chart(null_df)
    numeric = _numeric_summary(df)
    if numeric is not None:
        st.subheader("Numeric Summary")
        st.dataframe(numeric)
    st.write(f"Duplicate rows: {_duplicate_row_count(df)}")
    flags = _high_cardinality_flags(profile)
    if flags:
        st.warning(f"High-cardinality columns: {', '.join(flags)}")


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_data_overview(st)
