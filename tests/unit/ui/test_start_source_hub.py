"""Focused tests for Start / Load Dataset Source Hub wiring."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from data_quality_toolkit.adapters.ui.pages.start import _WORKSPACE_INIT_BTN, _render_start
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import (
    DATASET_ACTIVATE_BTN,
    DATASET_CLEAR_BTN,
    DATASET_CONTEXT,
    DATASET_LARGE_FILE_MODE,
    DATASET_PATH_INPUT,
    DRIFT_DATASET_FILTER,
    SRC_DATASET_ID,
    SRC_EXPORT_OUT_DIR,
    SRC_MONITORING_DB,
    SRC_PBI_OUT_DIR,
    SRC_QUALITY_HISTORY_DB,
    SRC_SESSION_RUN_ID,
    SRC_SESSIONS_ROOT,
    SRC_WORKSPACE_ROOT,
    SRC_WORKSPACE_ROOT_INPUT,
)


class FakeSt:
    """Records Start page render calls and mimics keyed widget values."""

    def __init__(self, session_state: dict[str, Any]) -> None:
        self.session_state = session_state
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.button_clicks: dict[str, bool] = {}

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def header(self, *args: Any, **kwargs: Any) -> None:
        self._record("header", *args, **kwargs)

    def subheader(self, *args: Any, **kwargs: Any) -> None:
        self._record("subheader", *args, **kwargs)

    def caption(self, *args: Any, **kwargs: Any) -> None:
        self._record("caption", *args, **kwargs)

    def info(self, *args: Any, **kwargs: Any) -> None:
        self._record("info", *args, **kwargs)

    def error(self, *args: Any, **kwargs: Any) -> None:
        self._record("error", *args, **kwargs)

    def success(self, *args: Any, **kwargs: Any) -> None:
        self._record("success", *args, **kwargs)

    def divider(self, *args: Any, **kwargs: Any) -> None:
        self._record("divider", *args, **kwargs)

    def write(self, *args: Any, **kwargs: Any) -> None:
        self._record("write", *args, **kwargs)

    def text_input(self, label: str, **kwargs: Any) -> str:
        self._record("text_input", label, **kwargs)
        key = kwargs.get("key")
        if isinstance(key, str):
            return str(self.session_state.get(key, ""))
        return ""

    def checkbox(self, label: str, **kwargs: Any) -> bool:
        self._record("checkbox", label, **kwargs)
        key = kwargs.get("key")
        return bool(self.session_state.get(key, False)) if isinstance(key, str) else False

    def button(self, label: str, **kwargs: Any) -> bool:
        self._record("button", label, **kwargs)
        lookup = kwargs.get("key", label)
        return self.button_clicks.get(str(lookup), False)

    def expander(self, label: str, **kwargs: Any) -> FakeSt:
        self._record("expander", label, **kwargs)
        return self

    def calls_named(self, name: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        return [(args, kwargs) for kind, args, kwargs in self.calls if kind == name]


def test_start_keeps_dataset_flow_before_collapsed_source_hub() -> None:
    state: dict[str, Any] = {}
    st = FakeSt(state)

    _render_start(st, state)

    text_inputs = st.calls_named("text_input")
    assert text_inputs[0][0][0] == "CSV path"
    assert text_inputs[0][1]["key"] == DATASET_PATH_INPUT

    buttons = st.calls_named("button")
    assert [(args[0], kwargs["key"]) for args, kwargs in buttons] == [
        ("Use dataset", DATASET_ACTIVATE_BTN),
        ("Clear dataset", DATASET_CLEAR_BTN),
        ("Initialize Workspace", _WORKSPACE_INIT_BTN),
    ]

    expander_calls = st.calls_named("expander")
    assert [args[0] for args, _ in expander_calls] == [
        "Workspace",
        "Monitoring & History",
        "Sessions & Runs",
        "Output locations",
        "Source summary",
    ]
    assert all(kwargs["expanded"] is False for _, kwargs in expander_calls)

    first_expander_index = next(
        index for index, call in enumerate(st.calls) if call[0] == "expander"
    )
    first_text_input_index = next(
        index for index, call in enumerate(st.calls) if call[0] == "text_input"
    )
    assert first_text_input_index < first_expander_index


def test_start_source_hub_wires_all_shared_source_keys() -> None:
    state: dict[str, Any] = {}
    st = FakeSt(state)

    _render_start(st, state)

    text_input_keys = [
        kwargs["key"]
        for _, kwargs in st.calls_named("text_input")
        if kwargs.get("key") != DATASET_PATH_INPUT
    ]
    assert text_input_keys == [
        SRC_WORKSPACE_ROOT_INPUT,
        SRC_MONITORING_DB,
        SRC_QUALITY_HISTORY_DB,
        SRC_SESSIONS_ROOT,
        SRC_SESSION_RUN_ID,
        SRC_DATASET_ID,
        SRC_EXPORT_OUT_DIR,
        SRC_PBI_OUT_DIR,
    ]

    info_text = " ".join(str(args[0]) for args, _ in st.calls_named("info"))
    assert "dataset source is required" in info_text
    assert "Monitoring DB" in info_text
    assert "Quality-history DB and Dataset ID" in info_text
    assert "Output locations are defaults only" in info_text


def test_workspace_root_seeds_blank_defaults_only_without_creating_paths(tmp_path) -> None:
    workspace_root = tmp_path / "station-workspace"
    state: dict[str, Any] = {
        SRC_WORKSPACE_ROOT: str(workspace_root),
        SRC_MONITORING_DB: "/explicit/monitoring.db",
        SRC_QUALITY_HISTORY_DB: "",
        SRC_SESSIONS_ROOT: "   ",
    }
    st = FakeSt(state)

    _render_start(st, state)

    assert state[SRC_WORKSPACE_ROOT] == str(workspace_root)
    # Explicit monitoring DB preserved; blank quality-history DB stays blank (never derived).
    assert state[SRC_MONITORING_DB] == "/explicit/monitoring.db"
    assert state[SRC_QUALITY_HISTORY_DB] == ""
    assert state[SRC_SESSIONS_ROOT] == str(workspace_root / "sessions")
    assert state[SRC_EXPORT_OUT_DIR] == str(workspace_root / "exports")
    assert state[SRC_PBI_OUT_DIR] == str(workspace_root / "powerbi")
    assert SRC_SESSION_RUN_ID not in state
    assert SRC_DATASET_ID not in state
    assert DRIFT_DATASET_FILTER not in state
    assert not workspace_root.exists()

    caption_text = " ".join(str(args[0]) for args, _ in st.calls_named("caption"))
    assert "Derived defaults filled for blank fields" in caption_text
    assert "Defaults only" in caption_text
    assert "no folders or files are created" in caption_text


def test_workspace_root_change_or_clear_preserves_existing_source_values() -> None:
    state: dict[str, Any] = {
        SRC_WORKSPACE_ROOT: "/workspace-b",
        SRC_MONITORING_DB: "/workspace-a/monitoring.db",
        SRC_QUALITY_HISTORY_DB: "/workspace-a/dqt.db",
        SRC_SESSIONS_ROOT: "/workspace-a/sessions",
        SRC_EXPORT_OUT_DIR: "/workspace-a/exports",
        SRC_PBI_OUT_DIR: "/workspace-a/powerbi",
    }

    _render_start(FakeSt(state), state)

    assert state[SRC_MONITORING_DB] == "/workspace-a/monitoring.db"
    assert state[SRC_QUALITY_HISTORY_DB] == "/workspace-a/dqt.db"
    assert state[SRC_SESSIONS_ROOT] == "/workspace-a/sessions"
    assert state[SRC_EXPORT_OUT_DIR] == "/workspace-a/exports"
    assert state[SRC_PBI_OUT_DIR] == "/workspace-a/powerbi"

    state[SRC_WORKSPACE_ROOT] = ""
    _render_start(FakeSt(state), state)

    assert state[SRC_MONITORING_DB] == "/workspace-a/monitoring.db"
    assert state[SRC_QUALITY_HISTORY_DB] == "/workspace-a/dqt.db"
    assert state[SRC_SESSIONS_ROOT] == "/workspace-a/sessions"
    assert state[SRC_EXPORT_OUT_DIR] == "/workspace-a/exports"
    assert state[SRC_PBI_OUT_DIR] == "/workspace-a/powerbi"


def test_start_source_summary_is_basename_first() -> None:
    state: dict[str, Any] = {
        DATASET_CONTEXT: DatasetContext(
            source_path=r"C:\Users\example_user\private\customers.csv",
            display_name="customers.csv",
            size_bytes=100,
            modified_ns=1,
        ),
        SRC_MONITORING_DB: r"C:\Users\example_user\private\monitoring.db",
        SRC_QUALITY_HISTORY_DB: r"C:\Users\example_user\private\dqt.db",
        SRC_SESSIONS_ROOT: r"C:\Users\example_user\private\sessions",
        SRC_SESSION_RUN_ID: "run-123",
        SRC_DATASET_ID: "sha1:any-value",
        SRC_EXPORT_OUT_DIR: r"C:\Users\example_user\private\dist",
        SRC_PBI_OUT_DIR: r"C:\Users\example_user\private\powerbi",
    }
    st = FakeSt(state)

    _render_start(st, state)

    summary_text = " ".join(str(args[0]) for args, _ in st.calls_named("write"))
    assert "customers.csv" in summary_text
    assert "monitoring.db" in summary_text
    assert "dqt.db" in summary_text
    assert "sessions" in summary_text
    assert "powerbi" in summary_text
    assert r"C:\Users\example_user\private" not in summary_text


def test_start_use_dataset_flow_still_sets_dataset_context() -> None:
    state: dict[str, Any] = {
        DATASET_PATH_INPUT: "data.csv",
        DATASET_LARGE_FILE_MODE: True,
    }
    st = FakeSt(state)
    st.button_clicks[DATASET_ACTIVATE_BTN] = True
    context = DatasetContext(
        source_path="data.csv",
        display_name="data.csv",
        size_bytes=123,
        modified_ns=456,
        large_file_mode=True,
    )

    with patch(
        "data_quality_toolkit.adapters.ui.pages.start.build_dataset_context",
        return_value=(context, None),
    ) as build_context:
        _render_start(st, state)

    build_context.assert_called_once_with("data.csv", large_file_mode=True)
    assert state[DATASET_CONTEXT] == context
    assert any(
        "Dataset context ready: data.csv" in str(args[0]) for args, _ in st.calls_named("success")
    )
