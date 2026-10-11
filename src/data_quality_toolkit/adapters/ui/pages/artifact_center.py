"""Artifact Center page: a standalone, path-safe view of generated artifacts.

Reuses the existing safe artifact component/service. This page loads artifacts
referenced by a run's lineage manifest (Sessions Root + Session Run ID) produced by
manifest-emitting session/pipeline workflows; it only *presents* them, redacted
to basenames. It creates no files on render and never shows full local paths as
primary display.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from data_quality_toolkit import create_manifest
from data_quality_toolkit.adapters.ui import journey
from data_quality_toolkit.adapters.ui.components.artifacts import render_artifact_center
from data_quality_toolkit.adapters.ui.components.errors import redact_message_paths, show_error
from data_quality_toolkit.adapters.ui.components.page_guidance import render_page_guidance
from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_page_header,
    render_section_header,
    render_status_chip,
)
from data_quality_toolkit.adapters.ui.components.source_context import (
    render_session_run_id_input,
    render_sessions_root_input,
)
from data_quality_toolkit.adapters.ui.components.source_hub import render_source_hub_source_summary
from data_quality_toolkit.adapters.ui.services.artifact_previews import (
    file_size,
    human_size,
    preview_file,
    read_bounded_bytes,
)
from data_quality_toolkit.adapters.ui.services.artifacts import (
    artifact_rows_from_manifest,
    artifact_rows_from_mapping,
    load_manifest_dict,
    manifest_file_name,
    redact_path_to_basename,
    resolve_manifest_artifact_path,
    session_directory_exists,
    session_manifest_path,
)
from data_quality_toolkit.adapters.ui.services.export_alignment import (
    LatestExportMatch,
    compare_latest_export,
    latest_export_match_label,
)
from data_quality_toolkit.adapters.ui.state.context import get_dataset_context
from data_quality_toolkit.adapters.ui.state.export_context import (
    ExportArtifactContext,
    get_export_artifact_context,
)
from data_quality_toolkit.shared.error_contract import to_error_info

_LOAD_BTN = "artifact_center_load_btn"
_REBUILD_CONFIRM = "artifact_center_rebuild_confirm"
_REBUILD_BTN = "artifact_center_rebuild_btn"

_SESSION_RUN_ID_NOTE = (
    "The Session Run ID names a session folder under Sessions Root. It is not "
    "the Export run ID shown in the Latest Export section above."
)


def _rebuild_disclosure(manifest_name: str) -> str:
    return (
        "**Server-side write:** rebuilding scans the selected existing session "
        f"directory and writes or overwrites its `{manifest_name}`. This is different "
        "from the read-only load above, which never writes."
    )


# A mismatch is normal history, not a fault: the export stays exactly as it was
# recorded and is only labelled, so "warn" is the strongest tone used here.
_MATCH_TONES: dict[LatestExportMatch, str] = {
    LatestExportMatch.MATCHES_ACTIVE_MANAGED: "ok",
    LatestExportMatch.MATCHES_ACTIVE_LEGACY: "ok",
    LatestExportMatch.OTHER_DATASET: "warn",
    LatestExportMatch.NO_ACTIVE_DATASET: "info",
    LatestExportMatch.INSUFFICIENT_LINKAGE: "info",
}


def _render_one_preview(st: Any, preview: dict[str, Any]) -> None:
    """Render a single bounded artifact preview by kind."""
    kind = preview.get("kind")
    if kind == "csv" and preview.get("error") is None:
        st.dataframe(preview["data"], use_container_width=True)
    elif kind == "json":
        st.json(preview["data"])
    elif kind == "text":
        st.code(preview["text"])
    elif kind == "binary":
        st.caption(f"Binary file ({human_size(preview.get('size'))}) — download only.")
    else:
        st.caption(redact_message_paths(preview.get("error")) or "preview unavailable")


def _render_preview_expander(st: Any, path: str, *, key_prefix: str, missing_text: str) -> None:
    """Render one bounded preview/download expander for a local artifact path.

    The full path is used for local reads only; display stays basename-first.
    """
    basename = redact_path_to_basename(path) or "artifact"
    with st.expander(basename):
        preview = preview_file(path)
        if preview.get("kind") == "missing":
            render_status_chip(st, missing_text, tone="warn")
            return
        render_status_chip(
            st,
            f"Status: local evidence · {human_size(file_size(path))} · review before sharing",
            tone="info",
        )
        _render_one_preview(st, preview)
        data, derr = read_bounded_bytes(path)
        if data is not None:
            st.download_button(
                f"Download {basename}",
                data=data,
                file_name=basename,
                key=f"{key_prefix}{basename}",
            )
        elif derr is not None:
            st.caption(derr)


def _render_artifact_previews(st: Any, manifest: Mapping[str, Any], manifest_path: str) -> None:
    """Render bounded previews and downloads for manifest artifacts (basenames only).

    Relative artifact paths resolve against the manifest file's directory; a
    path escaping that directory is marked unavailable instead of being read.
    """
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return
    previewable = [item for item in artifacts if isinstance(item, Mapping) and item.get("path")]
    if not previewable:
        return
    render_section_header(
        st, "Artifact previews & downloads", "Bounded, local previews — basenames only."
    )
    for item in previewable:
        raw_path = str(item.get("path"))
        resolved = resolve_manifest_artifact_path(manifest_path, raw_path)
        if resolved is None:
            with st.expander(redact_path_to_basename(raw_path) or "artifact"):
                render_status_chip(
                    st,
                    "Status: artifact path is outside the manifest directory — unavailable",
                    tone="warn",
                )
            continue
        _render_preview_expander(
            st,
            resolved,
            key_prefix="ac_dl_",
            missing_text="Status: referenced by manifest, file not available locally",
        )


def _latest_export_summary(context: ExportArtifactContext) -> str:
    """Build the path-safe one-line summary for the Latest Export section."""
    outdir_name = redact_path_to_basename(context.output_dir) or "output directory"
    details = [
        f"Export run ID `{context.run_id or '—'}`",
        f"Dataset ID `{context.dataset_id or '—'}`",
        f"Output folder `{outdir_name}`",
    ]
    if context.exported_at:
        details.append(f"Exported at {context.exported_at}")
    if context.quality_db_status:
        details.append(f"Quality-history DB {context.quality_db_status}")
    return " · ".join(details)


def _render_latest_export_match(st: Any, context: ExportArtifactContext) -> None:
    """Report whether this historical export came from the currently active dataset.

    Comparison only: the stored export context is session evidence and is never
    cleared, overwritten, or relabelled as belonging to the active version. The
    status text is a fixed phrase — no path, version id, or hash reaches it.
    """
    try:
        active = get_dataset_context(st.session_state)
    except Exception:
        active = None
    match = compare_latest_export(context, active)
    render_status_chip(
        st, f"Source match: {latest_export_match_label(match)}", tone=_MATCH_TONES[match]
    )


def _render_latest_export(st: Any) -> None:
    """Render the Latest Export section from the typed session context only.

    Sources its artifacts from ``ExportArtifactContext`` alone — never Sessions
    Root or the shared run-ID input — and reads ``DATASET_CONTEXT`` read-only to
    label the export as matching or mismatching the active dataset. Performs
    local reads only (no file is created).
    """
    render_section_header(
        st,
        "Latest Export",
        "The most recent successful Export from this session — no Sessions Root or "
        "Session Run ID entry needed.",
    )
    try:
        context = get_export_artifact_context(st.session_state)
    except Exception:
        context = None
    if context is None:
        st.info(
            "No successful Export in this session yet. Run a confirmed Export on the "
            "Export page, or load a session manifest below."
        )
        return
    st.caption(_latest_export_summary(context))
    _render_latest_export_match(st, context)
    rows = artifact_rows_from_mapping(
        context.export_paths, source="Latest Export", write_mode="server-side write"
    )
    render_artifact_center(st, rows, title="Latest Export artifacts")
    previewable = sorted(path for path in context.export_paths.values() if path)
    for path in previewable:
        _render_preview_expander(
            st,
            path,
            key_prefix="le_dl_",
            missing_text="Status: recorded by Export, file not available locally",
        )


def _render_artifact_center(st: Any) -> None:
    """Render the standalone Artifact Center page body."""
    render_page_header(
        st,
        "Artifact Center",
        "Review generated artifacts by name, type, and status — basenames only, never full paths.",
        step_label=journey.step_label("artifact_center"),
    )
    render_page_guidance(
        st,
        purpose="Review the latest Export and session artifacts referenced by a lineage manifest.",
        inputs="None for Latest Export; a Sessions Root and Session Run ID for manifest mode.",
        workflow="Review the latest Export below, or load a session manifest, then preview "
        "or download safe artifacts.",
        safety="Basenames only; full local paths are never shown as primary output.",
        next_step="KPI Catalog or Manifest Viewer",
    )
    st.info(
        "The **Export** page previews its generated artifacts directly after a run. "
        "The Latest Export section below shows the most recent successful Export with "
        "no manual inputs. Separately, this page can load artifacts referenced by a "
        "run's lineage manifest, produced by manifest-emitting session/pipeline "
        "workflows (Sessions Root + Session Run ID). No files are created here."
    )

    _render_latest_export(st)

    st.divider()
    render_section_header(
        st,
        "Load artifacts from a lineage manifest",
        f"Read-only: loads an existing `{manifest_file_name()}` for a session run "
        "without writing. The separate Rebuild action below is the only write on "
        "this page and requires explicit confirmation.",
    )
    run_id = render_session_run_id_input(st)
    sessions_root = render_sessions_root_input(st)
    st.caption(_SESSION_RUN_ID_NOTE)
    render_source_hub_source_summary(
        st,
        (("Sessions Root", sessions_root), ("Session Run ID", run_id)),
        present_text="Using session source from Start",
        missing_text="Set Sessions Root and Session Run ID in Start / Load Dataset",
    )

    if st.button("Load existing manifest", key=_LOAD_BTN):
        _load_and_render_existing_manifest(st, sessions_root, run_id)
    else:
        render_artifact_center(st, [], title="Artifact Center")

    _render_rebuild_action(st, sessions_root, run_id)


def _load_and_render_existing_manifest(st: Any, sessions_root: str, run_id: str) -> None:
    """Read-only load of ``artifacts.json`` for the selected session; never writes."""
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
    render_artifact_center(
        st, artifact_rows_from_manifest(manifest), title="Artifact Center (Safe View)"
    )
    _render_artifact_previews(st, manifest, manifest_path)


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
    _load_and_render_existing_manifest(st, sessions_root, run_id)


_TITLE = "Artifact Center"
_URL_PATH = "artifact-center"


def artifact_center_page(st: Any) -> Any:
    """Canonical StreamlitPage for Artifact Center.

    Shared by app.py's navigation registration and export.py's Open Artifact
    Center action so the two never drift.
    """
    return st.Page(render, title=_TITLE, url_path=_URL_PATH)


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_artifact_center(st)
