"""Focused tests for the explicit, confirmation-gated Initialize Workspace action.

The helper creates only the four admitted standard folders and never creates
database files, manifests, exports, Power BI packages, or pipeline artifacts, and
never runs export/Power BI/pipeline logic. The Start-page wiring gates creation on
both an explicit confirmation checkbox and an explicit button click.
"""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.ui.components.source_hub import (
    WORKSPACE_INIT_FOLDERS,
    initialize_workspace_folders,
)
from data_quality_toolkit.adapters.ui.pages.start import (
    _WORKSPACE_INIT_BTN,
    _WORKSPACE_INIT_CONFIRM,
    _render_start,
)
from data_quality_toolkit.adapters.ui.state.keys import (
    SRC_DATASET_ID,
    SRC_MONITORING_DB,
    SRC_QUALITY_HISTORY_DB,
    SRC_SESSION_RUN_ID,
    SRC_WORKSPACE_ROOT,
)


class FakeSt:
    """Records Start render calls and mimics keyed widget values."""

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

    def text_named(self, name: str) -> str:
        return " ".join(str(args[0]) for args, _ in self.calls_named(name) if args)


# --- helper-level tests -------------------------------------------------------


def test_initialize_workspace_folders_creates_only_admitted_folders(tmp_path) -> None:
    workspace_root = tmp_path / "station-workspace"

    result = initialize_workspace_folders(str(workspace_root))

    assert result.created == WORKSPACE_INIT_FOLDERS
    assert result.existing == ()
    assert result.failed == ()
    assert result.message == ""

    for name in WORKSPACE_INIT_FOLDERS:
        assert (workspace_root / name).is_dir()

    # No database files or other artifacts are ever created.
    assert not (workspace_root / "monitoring.db").exists()
    assert not (workspace_root / "dqt.db").exists()
    assert not (workspace_root / "manifests").exists()
    assert not (workspace_root / "reports").exists()
    assert not (workspace_root / "star").exists()

    children = sorted(child.name for child in workspace_root.iterdir())
    assert children == sorted(WORKSPACE_INIT_FOLDERS)
    # Every created entry is a directory — no export/PBI/pipeline artifact files.
    assert all(child.is_dir() for child in workspace_root.iterdir())


def test_initialize_workspace_folders_treats_existing_as_success(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    (workspace_root / "inputs").mkdir(parents=True)
    (workspace_root / "exports").mkdir(parents=True)

    result = initialize_workspace_folders(str(workspace_root))

    assert set(result.existing) == {"inputs", "exports"}
    assert set(result.created) == {"powerbi", "sessions"}
    assert result.failed == ()
    for name in WORKSPACE_INIT_FOLDERS:
        assert (workspace_root / name).is_dir()


def test_initialize_workspace_folders_blank_root_is_noop() -> None:
    result = initialize_workspace_folders("   ")

    assert result.created == ()
    assert result.existing == ()
    assert result.failed == ()
    assert result.message


def test_initialize_workspace_folders_normalizes_relative_root(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = initialize_workspace_folders("station-workspace")

    expected_root = tmp_path / "station-workspace"
    assert result.created == WORKSPACE_INIT_FOLDERS
    for name in WORKSPACE_INIT_FOLDERS:
        folder = expected_root / name
        assert folder.is_dir()
        assert folder.is_absolute()


def test_initialize_workspace_folders_reports_non_dir_collision_as_failed(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "inputs").write_text("", encoding="utf-8")

    result = initialize_workspace_folders(str(workspace_root))

    assert "inputs" in result.failed
    assert set(result.created) == {"exports", "powerbi", "sessions"}
    # The pre-existing non-dir entry is left untouched (not overwritten).
    assert (workspace_root / "inputs").is_file()


# --- Start-page integration tests --------------------------------------------


def test_start_initialize_workspace_creates_folders_on_confirm_and_click(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    state: dict[str, Any] = {
        SRC_WORKSPACE_ROOT: str(workspace_root),
        _WORKSPACE_INIT_CONFIRM: True,
    }
    st = FakeSt(state)
    st.button_clicks[_WORKSPACE_INIT_BTN] = True

    _render_start(st, state)

    for name in WORKSPACE_INIT_FOLDERS:
        assert (workspace_root / name).is_dir()
    assert not (workspace_root / "monitoring.db").exists()
    assert not (workspace_root / "dqt.db").exists()

    assert "Created folders" in st.text_named("success")


def test_start_initialize_workspace_requires_confirmation(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(workspace_root)}
    st = FakeSt(state)
    st.button_clicks[_WORKSPACE_INIT_BTN] = True

    _render_start(st, state)

    assert not workspace_root.exists()
    assert "Confirm the checkbox" in st.text_named("info")
    assert st.text_named("success") == ""


def test_start_initialize_workspace_requires_button(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    state: dict[str, Any] = {
        SRC_WORKSPACE_ROOT: str(workspace_root),
        _WORKSPACE_INIT_CONFIRM: True,
    }
    st = FakeSt(state)  # button intentionally not clicked

    _render_start(st, state)

    assert not workspace_root.exists()
    assert st.text_named("success") == ""


def test_start_initialize_workspace_blank_root_reports_and_creates_nothing(tmp_path) -> None:
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: "", _WORKSPACE_INIT_CONFIRM: True}
    st = FakeSt(state)
    st.button_clicks[_WORKSPACE_INIT_BTN] = True

    _render_start(st, state)

    assert "Enter a Workspace Root" in st.text_named("info")
    assert st.text_named("success") == ""


def test_start_initialize_workspace_preserves_explicit_source_values(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    state: dict[str, Any] = {
        SRC_WORKSPACE_ROOT: str(workspace_root),
        SRC_MONITORING_DB: "/explicit/monitoring.db",
        SRC_QUALITY_HISTORY_DB: "/explicit/dqt.db",
        _WORKSPACE_INIT_CONFIRM: True,
    }
    st = FakeSt(state)
    st.button_clicks[_WORKSPACE_INIT_BTN] = True

    _render_start(st, state)

    # Explicit source values are never overwritten by the action.
    assert state[SRC_MONITORING_DB] == "/explicit/monitoring.db"
    assert state[SRC_QUALITY_HISTORY_DB] == "/explicit/dqt.db"
    # Folders created, but no database files and no Run ID / Dataset ID seeding.
    for name in WORKSPACE_INIT_FOLDERS:
        assert (workspace_root / name).is_dir()
    assert not (workspace_root / "monitoring.db").exists()
    assert not (workspace_root / "dqt.db").exists()
    assert SRC_SESSION_RUN_ID not in state
    assert SRC_DATASET_ID not in state
