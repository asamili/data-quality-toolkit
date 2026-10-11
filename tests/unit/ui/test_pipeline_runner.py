"""Tests for the Pipeline Runner page (dry-run render + gated execution)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from data_quality_toolkit.adapters.ui.pages.pipeline_runner import (
    _render_pipeline_runner,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import (
    DATASET_CONTEXT,
    PIPE_CONFIRM_EXEC,
    PIPE_RUN_BTN,
    SRC_EXPORT_RUN_ID,
    SRC_SESSION_RUN_ID,
)

_PATCH_EXEC = "data_quality_toolkit.adapters.ui.pages.pipeline_runner._run_elt_pipeline"

_CTX = DatasetContext(
    source_path="C:\\Users\\example_user\\data\\sales.csv",
    display_name="sales.csv",
    size_bytes=4096,
    modified_ns=1,
)


class FakeSt:
    """Minimal Streamlit recorder with seedable checkbox/button/text values."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.text_values: dict[str, str] = {}
        self.checkbox_values: dict[str, bool] = {}
        self.button_values: dict[str, bool] = {}

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def _rec(self, name: str, *a: Any, **k: Any) -> None:
        self.calls.append((name, a, k))

    def __getattr__(self, name: str) -> Any:
        def recorder(*a: Any, **k: Any) -> None:
            self._rec(name, *a, **k)

        return recorder

    def columns(self, n: int) -> list[FakeSt]:
        self._rec("columns", n)
        return [FakeSt() for _ in range(n)]

    def text_input(self, label: str, **k: Any) -> str:
        self._rec("text_input", label, **k)
        return self.text_values.get(k.get("key", label), "")

    def checkbox(self, label: str, **k: Any) -> bool:
        self._rec("checkbox", label, **k)
        key = k.get("key", label)
        return self.checkbox_values.get(key, bool(k.get("value", False)))

    def button(self, label: str, **k: Any) -> bool:
        self._rec("button", label, **k)
        return self.button_values.get(k.get("key", label), False)

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))


def test_render_without_context_shows_blocked_and_runs_nothing() -> None:
    st = FakeSt()
    with patch(_PATCH_EXEC) as mock_exec:
        _render_pipeline_runner(st, {})
    mock_exec.assert_not_called()
    assert st.called("header")
    assert st.called("dataframe")  # plan table still rendered
    assert "blocked" in st.texts()


def test_render_with_context_previews_plan_and_does_not_execute() -> None:
    st = FakeSt()
    state: dict[str, Any] = {DATASET_CONTEXT: _CTX}
    with patch(_PATCH_EXEC) as mock_exec:
        _render_pipeline_runner(st, state)
    mock_exec.assert_not_called()
    assert st.called("dataframe")  # dry-run plan table
    assert st.called("code")  # CLI equivalence
    assert st.called("download_button")  # JSON plan download
    text = st.texts()
    assert "sales.csv" in text
    assert "dqt pipeline run" in text


def test_render_does_not_leak_absolute_paths() -> None:
    st = FakeSt()
    with patch(_PATCH_EXEC):
        _render_pipeline_runner(st, {DATASET_CONTEXT: _CTX})
    assert "C:\\Users" not in st.texts()


# ── operator-flow structure (flow map + numbered stages + guidance) ──────────


def test_render_shows_flow_map_caption() -> None:
    st = FakeSt()
    with patch(_PATCH_EXEC):
        _render_pipeline_runner(st, {DATASET_CONTEXT: _CTX})
    text = st.texts()
    assert "Flow: 1 Check dataset readiness" in text
    assert "5 Run legacy scaffold (optional, gated)" in text


def test_render_shows_numbered_stages_in_order() -> None:
    st = FakeSt()
    with patch(_PATCH_EXEC):
        _render_pipeline_runner(st, {DATASET_CONTEXT: _CTX})
    text = st.texts()
    stages = [
        "1 · Dataset readiness",
        "2 · Run configuration",
        "3 · Step selection",
        "4 · Dry-run preview",
        "5 · Existing execution scaffold (advanced)",
    ]
    positions = [text.index(stage) for stage in stages]
    assert positions == sorted(positions)


def test_step_selection_caption_explains_preview_scope() -> None:
    st = FakeSt()
    with patch(_PATCH_EXEC):
        _render_pipeline_runner(st, {DATASET_CONTEXT: _CTX})
    text = st.texts()
    assert "Checkboxes control which steps appear in the dry-run plan below" in text
    assert "nothing runs and nothing is written" in text


def test_stage_captions_state_nothing_runs_until_click() -> None:
    st = FakeSt()
    with patch(_PATCH_EXEC):
        _render_pipeline_runner(st, {DATASET_CONTEXT: _CTX})
    text = st.texts()
    assert "previewing is always safe" in text
    assert "Nothing runs until you tick the confirmation box and click the run button" in text


def test_execution_gated_until_confirmed() -> None:
    st = FakeSt()
    st.text_values["src_session_run_id"] = "run-1"
    st.text_values["src_sessions_root"] = "sessions"
    st.button_values[PIPE_RUN_BTN] = True  # user clicks run
    # confirm checkbox stays unchecked (defaults to value=False)
    with patch(_PATCH_EXEC) as mock_exec:
        _render_pipeline_runner(st, {DATASET_CONTEXT: _CTX})
    mock_exec.assert_not_called()
    assert st.called("warning")  # confirmation reminder shown


def test_execution_runs_only_when_confirmed_and_clicked() -> None:
    st = FakeSt()
    st.text_values["src_session_run_id"] = "run-1"
    st.text_values["src_sessions_root"] = "sessions"
    st.button_values[PIPE_RUN_BTN] = True
    st.checkbox_values["pipe_confirm_exec"] = True
    with patch(_PATCH_EXEC, return_value=({"status": "success"}, None)) as mock_exec:
        _render_pipeline_runner(st, {DATASET_CONTEXT: _CTX})
    mock_exec.assert_called_once()
    assert st.called("success")


# ── P5B: session-run identity, never export-run identity ────────────────────


def test_scaffold_reads_the_session_run_id_as_the_session_folder() -> None:
    st = FakeSt()
    st.text_values[SRC_SESSION_RUN_ID] = "session-folder-1"
    st.text_values["src_sessions_root"] = "sessions"
    st.button_values[PIPE_RUN_BTN] = True
    st.checkbox_values[PIPE_CONFIRM_EXEC] = True

    with patch(_PATCH_EXEC, return_value=({"status": "success"}, None)) as mock_exec:
        _render_pipeline_runner(st, {DATASET_CONTEXT: _CTX})

    mock_exec.assert_called_once_with("session-folder-1", "sessions")


def test_scaffold_never_uses_the_export_run_id_as_a_session_folder() -> None:
    st = FakeSt()
    # An export-run ID present in shared state must be invisible to this page.
    st.text_values["src_sessions_root"] = "sessions"
    st.button_values[PIPE_RUN_BTN] = True
    st.checkbox_values[PIPE_CONFIRM_EXEC] = True
    state: dict[str, Any] = {
        DATASET_CONTEXT: _CTX,
        SRC_EXPORT_RUN_ID: "run-from-an-export",
    }

    with patch(_PATCH_EXEC) as mock_exec:
        _render_pipeline_runner(st, state)

    # No Session Run ID was entered, so the run is refused rather than silently
    # falling back to the export-run ID as a folder name.
    mock_exec.assert_not_called()
    assert st.called("error")


def test_session_run_input_is_the_only_run_id_control() -> None:
    st = FakeSt()
    _render_pipeline_runner(st, {DATASET_CONTEXT: _CTX})

    run_id_keys = [
        call[2].get("key")
        for call in st.calls
        if call[0] == "text_input" and "run" in str(call[2].get("key", ""))
    ]
    assert run_id_keys == [SRC_SESSION_RUN_ID]
