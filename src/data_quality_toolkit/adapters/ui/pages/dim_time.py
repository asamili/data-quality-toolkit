"""Dim Time page: generate and download a time dimension CSV in memory."""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.ui.components.downloads import MIME_CSV
from data_quality_toolkit.adapters.ui.components.errors import show_error
from data_quality_toolkit.adapters.ui.services.kpi import _generate_dim_time_csv


def _render_dim_time(st: Any) -> None:
    """Render the Dim Time tab — generate and download time dimension CSV in memory."""
    st.header("Dim Time")
    st.caption("Generate a time dimension table and download as CSV.")

    start_date = st.text_input("Start date (YYYY-MM-DD)", value="2018-01-01")
    end_date = st.text_input("End date (YYYY-MM-DD)", value="2030-12-31")
    week_start = st.number_input(
        "Week start day (1=Mon … 7=Sun)", min_value=1, max_value=7, value=1, step=1
    )

    use_fiscal = st.checkbox("Custom fiscal year start month")
    fiscal_year_start: int | None = None
    if use_fiscal:
        fiscal_year_start = st.number_input(
            "Fiscal year start month (1–12)", min_value=1, max_value=12, value=7, step=1
        )

    if not start_date or not end_date:
        st.info("💡 Enter start and end dates above.")
        return

    csv_str, row_count, err = _generate_dim_time_csv(
        start_date=start_date,
        end_date=end_date,
        week_start=int(week_start),
        fiscal_year_start=int(fiscal_year_start) if fiscal_year_start is not None else None,
    )
    if err:
        show_error(st, "Generation error", err)
        return

    st.success(f"✓ {row_count:,} rows — {start_date} to {end_date}")
    st.download_button(
        "Download dim_time.csv",
        data=(csv_str or "").encode(),
        file_name="dim_time.csv",
        mime=MIME_CSV,
    )


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_dim_time(st)
