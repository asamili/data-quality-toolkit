"""Reusable opt-in Save-to-Workspace UI helper for analysis CSV outputs.

This is the thin Streamlit-facing wrapper around the framework-agnostic
``services.workspace_save`` foundation. It renders an *additive* save button next
to an existing browser download: the browser download stays the primary path,
and a server-side copy is written only when the user explicitly clicks the
button. Nothing is written on render. A blank Workspace Root is a no-op with
guidance. Existing files are never overwritten (the foundation appends a numeric
suffix). Only basename / workspace-relative paths are shown — never an absolute
local path.

Analysis CSV outputs are saved under ``<Workspace Root>/analysis/``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.services.workspace_save import (
    WorkspaceSaveResult,
    build_workspace_filename,
    save_to_workspace,
)
from data_quality_toolkit.adapters.ui.state.keys import SRC_WORKSPACE_ROOT

# Workspace subfolder for analysis CSV outputs. Distinct from exports/recipes/kpi.
ANALYSIS_SUBFOLDER = "analysis"

# Shared empty-state copy shown (only on an explicit save click) when Workspace Root
# is blank. Reused by every opt-in Save-to-Workspace helper so the message reads
# consistently and never implies a browser download failed or that analysis needs a
# workspace. Browser downloads stay available regardless of Workspace Root.
WORKSPACE_ROOT_EMPTY_STATE = (
    "Browser downloads are available. To also save outputs inside your workspace, "
    "set Workspace Root on Start / Load Dataset."
)


def render_analysis_csv_save(
    st: Any,
    *,
    button_label: str,
    key: str,
    artifact: str,
    dataframe: pd.DataFrame,
    dataset_name: str | None = None,
    caption: str | None = None,
) -> None:
    """Render an opt-in Save-to-Workspace button for one analysis CSV output.

    The saved payload is the exact content served by the sibling browser download
    (``dataframe.to_csv(index=False)``). Saving happens only when ``button_label``
    is clicked — never on render. A blank Workspace Root shows guidance and writes
    nothing. The filename is ``<dataset>__<artifact>.csv`` (or ``<artifact>.csv``
    when no dataset is known), sanitized by the foundation; existing files are not
    overwritten. The result is displayed as basename / workspace-relative only.
    """
    if caption:
        st.caption(caption)
    if not st.button(button_label, key=key):
        return

    workspace_root = _workspace_root_value(st)
    if not workspace_root.strip():
        st.info(WORKSPACE_ROOT_EMPTY_STATE)
        return

    filename = build_workspace_filename(artifact=artifact, extension="csv", dataset=dataset_name)
    result = save_to_workspace(
        workspace_root, ANALYSIS_SUBFOLDER, filename, dataframe.to_csv(index=False)
    )
    _render_save_result(st, result)


def _render_save_result(st: Any, result: WorkspaceSaveResult) -> None:
    """Render the save outcome using basename / workspace-relative fields only."""
    if result.status == "saved":
        st.success(f"Saved to workspace: {result.relative_path}")
    elif result.status == "invalid":
        st.info(result.message)
    else:
        st.error(result.message or "Could not save analysis output.")


def _workspace_root_value(source: Any) -> str:
    """Read the shared Workspace Root string from session state (never raises).

    Accepts either a Streamlit-like object exposing ``.session_state`` or a
    session-state mapping directly, so every page can share one reader.
    """
    try:
        state = getattr(source, "session_state", source)
        value = state.get(SRC_WORKSPACE_ROOT, "")
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


__all__ = [
    "ANALYSIS_SUBFOLDER",
    "WORKSPACE_ROOT_EMPTY_STATE",
    "render_analysis_csv_save",
]
