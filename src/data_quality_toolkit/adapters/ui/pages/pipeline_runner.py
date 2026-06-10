import streamlit as st

from data_quality_toolkit.adapters.ui.services.pipeline import (
    _load_pipeline_config_file,
    _run_elt_pipeline,
)
from data_quality_toolkit.adapters.ui.state import keys


def render() -> None:
    st.header("Pipeline Runner")
    st.markdown("""
    ELTPipeline is currently a declarative scaffold. Extract, transform, load, and assess steps are recorded; manifest reads existing lineage/session artifacts.
    """)
    _render_pipeline_runner(st)


def _render_pipeline_runner(st_container) -> None:
    run_id = st_container.text_input("Run ID", key=keys.PIPE_RUN_ID)
    sessions_root = st_container.text_input("Sessions Root", key=keys.PIPE_SESSIONS_ROOT)
    config_path = st_container.text_input(
        "Pipeline YAML Config Path (optional)", key=keys.PIPE_CONFIG_PATH
    )

    extract = st_container.checkbox("Extract", key=keys.PIPE_EXTRACT)
    transform = st_container.checkbox("Transform", key=keys.PIPE_TRANSFORM)
    load = st_container.checkbox("Load", key=keys.PIPE_LOAD)
    assess = st_container.checkbox("Assess", key=keys.PIPE_ASSESS)
    manifest = st_container.checkbox("Manifest", key=keys.PIPE_MANIFEST)

    if st_container.button("Run Pipeline", key=keys.PIPE_RUN_BTN):
        _execute_pipeline(
            st_container,
            run_id,
            sessions_root,
            config_path,
            extract,
            transform,
            load,
            assess,
            manifest,
        )


def _execute_pipeline(
    st_container, run_id, sessions_root, config_path, extract, transform, load, assess, manifest
) -> None:
    if not run_id or not sessions_root:
        st_container.error("Run ID and Sessions Root are required.")
        return

    if config_path:
        _, err = _load_pipeline_config_file(config_path)
        if err:
            st_container.error(f"Error loading config: {err}")
            return

    steps = []
    if extract:
        steps.append({"type": "extract"})
    if transform:
        steps.append({"type": "transform"})
    if load:
        steps.append({"type": "load"})
    if assess:
        steps.append({"type": "assess"})
    if manifest:
        steps.append({"type": "manifest"})

    result, err = _run_elt_pipeline(run_id, sessions_root, steps)
    if err:
        st_container.error(f"Pipeline error: {err}")
    else:
        st_container.success("Pipeline executed successfully.")
        st_container.json(result)
        st_container.markdown("### CLI Equivalence Snippet")
        st_container.code(f"dqt run --run-id {run_id} --root {sessions_root} ...")
