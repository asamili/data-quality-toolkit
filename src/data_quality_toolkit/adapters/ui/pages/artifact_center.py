"""Artifact Center page: a standalone, path-safe view of generated artifacts.

Reuses the existing safe artifact component/service. Artifacts are produced by
the Export page (server-side write) and by pipeline/lineage runs; this page only
*presents* them, redacted to basenames. It creates no files on render and never
shows full local paths as primary display.
"""

from __future__ import annotations

from typing import Any

from data_quality_toolkit import create_manifest
from data_quality_toolkit.adapters.ui.components.artifacts import render_artifact_center
from data_quality_toolkit.adapters.ui.components.errors import show_error
from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_page_header,
    render_section_header,
)
from data_quality_toolkit.adapters.ui.services.artifacts import artifact_rows_from_manifest
from data_quality_toolkit.shared.error_contract import to_error_info

_RUN_ID = "artifact_center_run_id"
_SESSIONS_ROOT = "artifact_center_sessions_root"
_LOAD_BTN = "artifact_center_load_btn"


def _render_artifact_center(st: Any) -> None:
    """Render the standalone Artifact Center page body."""
    render_page_header(
        st,
        "Artifact Center",
        "Review generated artifacts by name, type, and status — basenames only, never full paths.",
        step_label="Step 9 of 11 — Artifact Center",
    )
    st.info(
        "Artifacts are produced by the **Export** page (server-side write) and by pipeline/"
        "lineage runs. This page presents them safely — no files are created here."
    )

    render_section_header(st, "Load artifacts from a lineage manifest")
    run_id = st.text_input("Run ID", key=_RUN_ID)
    sessions_root = st.text_input("Sessions Root", value=".", key=_SESSIONS_ROOT)

    if st.button("Load artifacts", key=_LOAD_BTN):
        if not run_id or not sessions_root:
            st.error("Please enter both Run ID and Sessions Root.")
            return
        try:
            manifest = create_manifest(run_id, sessions_root)
        except Exception as exc:
            show_error(st, "Manifest load failed", to_error_info(exc)["message"])
            return
        render_artifact_center(
            st, artifact_rows_from_manifest(manifest), title="Artifact Center (Safe View)"
        )
    else:
        render_artifact_center(st, [], title="Artifact Center")


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_artifact_center(st)
