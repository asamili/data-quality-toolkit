from __future__ import annotations

from typing import Any

from data_quality_toolkit import create_manifest
from data_quality_toolkit.adapters.ui import journey
from data_quality_toolkit.adapters.ui.components.artifacts import render_artifact_center
from data_quality_toolkit.adapters.ui.components.errors import show_error
from data_quality_toolkit.adapters.ui.components.page_guidance import render_page_guidance
from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_page_header,
    render_section_header,
)
from data_quality_toolkit.adapters.ui.components.source_context import (
    render_session_run_id_input,
    render_sessions_root_input,
)
from data_quality_toolkit.adapters.ui.components.source_hub import render_source_hub_source_summary
from data_quality_toolkit.adapters.ui.services.artifacts import (
    artifact_rows_from_manifest,
    dataset_rows_from_manifest,
    load_manifest_dict,
    manifest_file_name,
    session_directory_exists,
    session_manifest_path,
)
from data_quality_toolkit.shared.error_contract import to_error_info

_REBUILD_CONFIRM = "manifest_viewer_rebuild_confirm"
_REBUILD_BTN = "manifest_viewer_rebuild_btn"


def _read_only_note(manifest_name: str) -> str:
    return (
        f"Read-only: loading opens the session's existing `{manifest_name}` and never "
        "writes. The Session Run ID names a session folder under Sessions Root; it is "
        "not the Export run ID."
    )


def _rebuild_disclosure(manifest_name: str) -> str:
    return (
        "**Server-side write:** rebuilding scans the selected existing session "
        f"directory and writes or overwrites its `{manifest_name}`. This is different "
        "from the read-only load above, which never writes."
    )


def _coerce_st(st: Any | None) -> Any:
    if st is not None:
        return st
    import streamlit as streamlit

    return streamlit


def render_summary(manifest: dict[str, Any], st: Any | None = None) -> None:
    st = _coerce_st(st)
    st.subheader("Manifest Summary")
    st.json(manifest.get("summary", {}), expanded=False)


def render_datasets(manifest: dict[str, Any], st: Any | None = None) -> None:
    st = _coerce_st(st)
    st.subheader("Datasets (Safe View)")
    rows = dataset_rows_from_manifest(manifest)
    st.caption("Dataset paths are shown as basenames only. Review raw evidence before sharing.")
    if rows:
        st.dataframe(rows, use_container_width=True)
    else:
        st.info("No dataset entries available in this manifest.")


def render_artifacts(manifest: dict[str, Any], st: Any | None = None) -> None:
    st = _coerce_st(st)
    render_artifact_center(
        st,
        artifact_rows_from_manifest(manifest),
        title="Artifact Center (Safe View)",
    )


def render_gate_failures(manifest: dict[str, Any], st: Any | None = None) -> None:
    st = _coerce_st(st)
    st.subheader("Gate Failures")
    failures = manifest.get("gates", {}).get("failures", [])
    if failures:
        st.dataframe(failures)
    else:
        st.info("No gate failures.")


def render_raw_json(manifest: dict[str, Any], st: Any | None = None) -> None:
    st = _coerce_st(st)
    st.subheader("Raw Manifest JSON")
    st.warning(
        "Local/private evidence: raw manifest JSON may include full local paths or run "
        "metadata. Review and redact before sharing."
    )
    st.json(manifest, expanded=False)


def _render_loaded_manifest(st: Any, manifest: dict[str, Any]) -> None:
    """Render the safe projections for a loaded manifest."""
    render_summary(manifest, st)
    render_datasets(manifest, st)
    render_artifacts(manifest, st)
    render_gate_failures(manifest, st)
    render_raw_json(manifest, st)


def _load_existing_manifest(st: Any, sessions_root: str, run_id: str) -> None:
    """Read-only load of the session's existing manifest; never writes."""
    manifest_path = session_manifest_path(sessions_root, run_id)
    if manifest_path is None:
        st.error("Please enter both Session Run ID and Sessions Root.")
        return
    manifest, err = load_manifest_dict(manifest_path)
    if err is not None:
        show_error(st, "Manifest load failed", err)
        return
    if manifest is None:
        manifest_name = manifest_file_name()
        st.info(
            f"No existing `{manifest_name}` was found for this session. Nothing was "
            f"created by this check. Use **Rebuild {manifest_name}** below to scan the "
            "existing session directory and write one, or run a manifest-emitting "
            "workflow first."
        )
        return
    _render_loaded_manifest(st, manifest)


def _render_rebuild_action(st: Any, sessions_root: str, run_id: str) -> None:
    """Render the separately confirmed, write-capable manifest rebuild action."""
    manifest_name = manifest_file_name()
    st.divider()
    render_section_header(
        st,
        f"Rebuild {manifest_name}",
        "Scan an existing session directory and rewrite its lineage manifest.",
    )
    st.warning(_rebuild_disclosure(manifest_name))
    confirmed = st.checkbox(
        f"I confirm: scan the existing session directory and write {manifest_name}",
        key=_REBUILD_CONFIRM,
    )
    if not st.button(f"Rebuild {manifest_name}", key=_REBUILD_BTN):
        return
    if not run_id or not sessions_root:
        st.error("Please enter both Session Run ID and Sessions Root.")
        return
    if not confirmed:
        st.error("Check the rebuild confirmation box to enable this server-side write.")
        return
    if not session_directory_exists(sessions_root, run_id):
        st.error(
            "Session directory not found under Sessions Root. Rebuild only works on an "
            "existing session and never creates a new directory."
        )
        return
    try:
        create_manifest(run_id, sessions_root)
    except Exception as exc:
        show_error(st, "Manifest rebuild failed", to_error_info(exc)["message"])
        return
    st.success(f"{manifest_name} was rebuilt for this session.")
    _load_existing_manifest(st, sessions_root, run_id)


def _render_manifest_viewer(st: Any) -> None:
    """Testable render logic for the Manifest Viewer page."""
    render_page_header(
        st,
        "Lineage Manifest Viewer",
        "Inspect a lineage manifest's summary, datasets, artifacts, and gate failures — "
        "basenames only.",
        step_label=journey.step_label("manifest_viewer"),
    )
    render_page_guidance(
        st,
        purpose="Inspect a run's lineage manifest: summary, datasets, artifacts, and gate failures.",
        inputs="A Sessions Root and Session Run ID.",
        workflow="Load the existing manifest read-only and review the safe projections; "
        "open raw JSON only if needed.",
        safety="Paths are shown basename-first; raw JSON may include local paths and is warned.",
        next_step="Artifact Center or Settings / Governance",
    )

    run_id = render_session_run_id_input(st)
    sessions_root = render_sessions_root_input(st)
    st.caption(_read_only_note(manifest_file_name()))
    render_source_hub_source_summary(
        st,
        (("Sessions Root", sessions_root), ("Session Run ID", run_id)),
        present_text="Using manifest source from Start",
        missing_text="Set Sessions Root and Session Run ID in Start / Load Dataset",
    )

    if st.button("Load Manifest"):
        _load_existing_manifest(st, sessions_root, run_id)

    _render_rebuild_action(st, sessions_root, run_id)


def render_manifest_viewer() -> None:
    import streamlit as st

    _render_manifest_viewer(st)
