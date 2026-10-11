"""Dim Time page: generate and download a time dimension CSV in memory."""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.ui import journey
from data_quality_toolkit.adapters.ui.components.downloads import MIME_CSV
from data_quality_toolkit.adapters.ui.components.errors import show_error
from data_quality_toolkit.adapters.ui.components.page_guidance import render_page_guidance
from data_quality_toolkit.adapters.ui.components.page_shell import render_page_header
from data_quality_toolkit.adapters.ui.components.workspace_save_ui import (
    WORKSPACE_ROOT_EMPTY_STATE,
    _workspace_root_value,
)
from data_quality_toolkit.adapters.ui.services.kpi import _generate_dim_time_csv
from data_quality_toolkit.adapters.ui.services.workspace_save import (
    WorkspaceSaveResult,
    build_workspace_filename,
    save_to_workspace,
)

# Workspace subfolder and widget key for the opt-in dim_time Save-to-Workspace action.
# Defined locally (not in state/keys.py); this gate does not add shared source keys.
_EXPORTS_SUBFOLDER = "exports"
_SAVE_DIM_TIME_BTN = "dim_time_save_btn"


def _render_dim_time(st: Any) -> None:
    """Render the Dim Time tab — generate and download time dimension CSV in memory."""
    render_page_header(
        st,
        "Dim Time",
        "Generate a time dimension table and download as CSV.",
        step_label=journey.step_label("dim_time"),
    )
    render_page_guidance(
        st,
        purpose="Generate a date/time dimension table for BI models.",
        inputs="A date range and calendar options.",
        workflow="Configure the range, generate, then download the CSV.",
        next_step="Export or the Power BI package flow",
    )

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
    _render_dim_time_workspace_save(st, csv_str or "")


def _render_dim_time_workspace_save(st: Any, csv_content: str) -> None:
    """Offer opt-in Save-to-Workspace for dim_time.csv (additive; browser download stays)."""
    st.caption(
        "Optionally save dim_time.csv under your Workspace Root / exports. "
        "Existing files are not overwritten."
    )
    if not st.button("Save dim_time.csv to workspace", key=_SAVE_DIM_TIME_BTN):
        return

    workspace_root = _workspace_root_value(st)
    if not workspace_root.strip():
        st.info(WORKSPACE_ROOT_EMPTY_STATE)
        return
    # Save the exact same CSV content served by the browser download above.
    filename = build_workspace_filename(artifact="dim_time", extension="csv")
    result = save_to_workspace(workspace_root, _EXPORTS_SUBFOLDER, filename, csv_content)
    _render_save_result(st, result)


def _render_save_result(st: Any, result: WorkspaceSaveResult) -> None:
    """Render the save outcome using basename / workspace-relative fields only."""
    if result.status == "saved":
        st.success(f"Saved to workspace: {result.relative_path}")
    elif result.status == "invalid":
        st.info(result.message)
    else:
        st.error(result.message or "Could not save dim_time.csv.")


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_dim_time(st)
