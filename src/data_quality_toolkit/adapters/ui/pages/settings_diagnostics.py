import streamlit as st

from data_quality_toolkit.adapters.ui.services import diagnostics


def render() -> None:
    st.header("Settings & Diagnostics")
    _render_settings_diagnostics(st)


def _render_settings_diagnostics(st_container) -> None:
    st_container.subheader("Versions")
    versions = diagnostics._collect_versions()
    st_container.table(list(versions.items()))

    st_container.subheader("Settings Snapshot")
    snapshot = diagnostics._collect_settings_snapshot()
    st_container.json(snapshot)

    st_container.subheader("Project Config")
    config = diagnostics._load_project_config()
    st_container.json(config)

    st_container.subheader("Import Diagnostics")
    diag = diagnostics._collect_import_diagnostics()
    st_container.json(diag)

    if st_container.button("Run Writable Directory Probe"):
        # We need a path. Prompting for it isn't explicitly required, but needed.
        # As a placeholder, using CWD.
        path = st_container.text_input("Enter directory to probe", value=".")
        if st_container.button("Confirm Probe"):
            success, err = diagnostics._probe_writable_dir(path)
            if success:
                st_container.success(f"Writable: {path}")
            else:
                st_container.error(f"Not writable: {err}")
