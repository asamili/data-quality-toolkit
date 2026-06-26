"""Start page: establish and inspect the shared local dataset context."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from data_quality_toolkit.adapters.ui.components.dataset_context import (
    render_dataset_context_panel,
)
from data_quality_toolkit.adapters.ui.components.page_shell import render_page_header
from data_quality_toolkit.adapters.ui.components.states import (
    render_empty_state,
    render_info_state,
)
from data_quality_toolkit.adapters.ui.services.dataset import build_dataset_context
from data_quality_toolkit.adapters.ui.state.context import (
    clear_dataset_context,
    get_dataset_context,
    set_dataset_context,
)
from data_quality_toolkit.adapters.ui.state.keys import (
    DATASET_ACTIVATE_BTN,
    DATASET_CLEAR_BTN,
    DATASET_LARGE_FILE_MODE,
    DATASET_PATH_INPUT,
)


def _render_start(st: Any, session_state: MutableMapping[str, Any]) -> None:
    """Render the testable Start / Load Dataset page body."""
    render_page_header(
        st,
        "Start / Load Dataset",
        "Choose a local CSV once, then continue to Data Overview and EDA Explorer.",
        step_label="Step 1 of 11 — Start / Load Dataset",
    )
    render_info_state(
        st,
        "DQT uses a local path for this foundation release. No file is uploaded, copied, "
        "or sent to an external service.",
    )

    current = get_dataset_context(session_state)
    if DATASET_PATH_INPUT not in session_state:
        session_state[DATASET_PATH_INPUT] = current.source_path if current else ""
    if DATASET_LARGE_FILE_MODE not in session_state:
        session_state[DATASET_LARGE_FILE_MODE] = (
            current.large_file_mode if current is not None else False
        )

    path = st.text_input("CSV path", key=DATASET_PATH_INPUT)
    large_mode = st.checkbox(
        "Large-data mode (profile-only, chunked streaming)",
        key=DATASET_LARGE_FILE_MODE,
        help="Use chunked profiling for datasets that should not be fully loaded into memory.",
    )

    if st.button("Use dataset", key=DATASET_ACTIVATE_BTN, type="primary"):
        context, err = build_dataset_context(path, large_file_mode=large_mode)
        if err is not None:
            st.error(f"Dataset context error: {err}")
        elif context is not None:
            set_dataset_context(session_state, context)
            current = context
            st.success(f"Dataset context ready: {context.display_name}")

    if st.button("Clear dataset", key=DATASET_CLEAR_BTN, disabled=current is None):
        clear_dataset_context(session_state)
        current = None
        st.success("Dataset context cleared.")

    if current is None:
        render_empty_state(
            st,
            "No dataset selected",
            "Enter a local CSV path above. For a deterministic demo, try `examples/demo.csv`.",
        )
    else:
        render_dataset_context_panel(st, current)
        st.caption("Continue with Data Overview, then EDA Explorer.")


def render() -> None:
    """Streamlit navigation entry point."""
    import streamlit as st

    _render_start(st, st.session_state)  # type: ignore[arg-type, unused-ignore]
