from __future__ import annotations

from typing import Any

from data_quality_toolkit import create_manifest
from data_quality_toolkit.adapters.ui.components.artifacts import render_artifact_center
from data_quality_toolkit.adapters.ui.components.errors import show_error
from data_quality_toolkit.adapters.ui.services.artifacts import (
    artifact_rows_from_manifest,
    dataset_rows_from_manifest,
)
from data_quality_toolkit.shared.error_contract import to_error_info


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


def _render_manifest_viewer(st: Any) -> None:
    """Testable render logic for the Manifest Viewer page."""
    st.header("Lineage Manifest Viewer")

    run_id = st.text_input("Run ID")
    sessions_root = st.text_input("Sessions Root", value=".")

    if st.button("Load Manifest"):
        if not run_id or not sessions_root:
            st.error("Please enter both Run ID and Sessions Root.")
            return

        try:
            manifest = create_manifest(run_id, sessions_root)
            render_summary(manifest, st)
            render_datasets(manifest, st)
            render_artifacts(manifest, st)
            render_gate_failures(manifest, st)
            render_raw_json(manifest, st)
        except Exception as exc:
            show_error(st, "Manifest load failed", to_error_info(exc)["message"])


def render_manifest_viewer() -> None:
    import streamlit as st

    _render_manifest_viewer(st)
