from __future__ import annotations

from typing import Any

from data_quality_toolkit import create_manifest


def render_summary(manifest: dict[str, Any]) -> None:
    import streamlit as st

    st.subheader("Manifest Summary")
    st.json(manifest.get("summary", {}), expanded=False)


def render_datasets(manifest: dict[str, Any]) -> None:
    import streamlit as st

    st.subheader("Datasets")
    st.dataframe(manifest.get("datasets", []))


def render_artifacts(manifest: dict[str, Any]) -> None:
    import streamlit as st

    st.subheader("Artifacts")
    st.dataframe(manifest.get("artifacts", []))


def render_gate_failures(manifest: dict[str, Any]) -> None:
    import streamlit as st

    st.subheader("Gate Failures")
    failures = manifest.get("gates", {}).get("failures", [])
    if failures:
        st.dataframe(failures)
    else:
        st.info("No gate failures.")


def render_raw_json(manifest: dict[str, Any]) -> None:
    import streamlit as st

    st.subheader("Raw Manifest JSON")
    st.json(manifest, expanded=False)


def render_manifest_viewer() -> None:
    import streamlit as st

    st.header("Lineage Manifest Viewer")

    col1, col2 = st.columns(2)
    run_id = col1.text_input("Run ID")
    sessions_root = col2.text_input("Sessions Root", value=".")

    if st.button("Load Manifest"):
        if not run_id or not sessions_root:
            st.error("Please enter both Run ID and Sessions Root.")
            return

        try:
            manifest = create_manifest(run_id, sessions_root)
            render_summary(manifest)
            render_datasets(manifest)
            render_artifacts(manifest)
            render_gate_failures(manifest)
            render_raw_json(manifest)
        except Exception as e:
            st.error(f"Error loading manifest: {e}")
