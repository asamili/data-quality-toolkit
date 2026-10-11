"""Workspace Root propagation: Start / Load Dataset → Save-to-Workspace helpers.

Regression tests for the multipage state-lifecycle bug where the Workspace Root
text input was bound directly to the canonical ``SRC_WORKSPACE_ROOT`` key:
Streamlit deletes widget-backed session-state keys whenever their widget is not
rendered, so navigating off Start erased the saved root and every downstream
Save-to-Workspace helper fell back to the empty-state message.

The fix binds the Start input to a page-local widget key
(``SRC_WORKSPACE_ROOT_INPUT``) and mirrors its value into the canonical key,
which is never widget-backed and therefore survives navigation. These tests
model the Streamlit cleanup by deleting the widget key between page renders.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.components.workspace_save_ui import (
    WORKSPACE_ROOT_EMPTY_STATE,
    render_analysis_csv_save,
)
from data_quality_toolkit.adapters.ui.pages.dim_time import (
    _SAVE_DIM_TIME_BTN,
    _render_dim_time_workspace_save,
)
from data_quality_toolkit.adapters.ui.pages.start import _render_start
from data_quality_toolkit.adapters.ui.state.keys import (
    SRC_WORKSPACE_ROOT,
    SRC_WORKSPACE_ROOT_INPUT,
)

_DF = pd.DataFrame({"a": [1, 2]})
_SAVE_BTN = "ws_prop_save_btn"


class FakeSt:
    """Records render calls and mimics keyed widget values from session state."""

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

    def download_button(self, *args: Any, **kwargs: Any) -> None:
        self._record("download_button", *args, **kwargs)

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

    def texts(self) -> str:
        return " ".join(str(x) for _, args, _ in self.calls for x in args if isinstance(x, str))

    def texts_named(self, name: str) -> str:
        return " ".join(str(x) for kind, args, _ in self.calls for x in args if kind == name)


def _render_start_with_typed_root(state: dict[str, Any], root: str) -> FakeSt:
    """Render Start as if the user just typed ``root`` into the widget."""
    state[SRC_WORKSPACE_ROOT_INPUT] = root
    st = FakeSt(state)
    _render_start(st, state)
    return st


def _simulate_navigation_away(state: dict[str, Any]) -> None:
    """Model Streamlit's widget cleanup when the Start page stops rendering."""
    state.pop(SRC_WORKSPACE_ROOT_INPUT, None)


def test_start_saves_typed_root_into_canonical_helper_key(tmp_path) -> None:
    root = str(tmp_path / "workspace")
    state: dict[str, Any] = {}

    _render_start_with_typed_root(state, root)

    assert state[SRC_WORKSPACE_ROOT] == root


def test_saved_root_survives_widget_cleanup_and_helper_saves(tmp_path) -> None:
    root = tmp_path / "workspace"
    state: dict[str, Any] = {}
    _render_start_with_typed_root(state, str(root))
    _simulate_navigation_away(state)

    st = FakeSt(state)
    st.button_clicks[_SAVE_BTN] = True
    render_analysis_csv_save(
        st,
        button_label="Save to workspace",
        key=_SAVE_BTN,
        artifact="profile",
        dataframe=_DF,
        dataset_name="demo.csv",
    )

    assert WORKSPACE_ROOT_EMPTY_STATE not in st.texts()
    saved = list((root / "analysis").glob("*.csv"))
    # save_to_workspace re-sanitizes the built name, collapsing "__" to "_".
    assert [file.name for file in saved] == ["demo_profile.csv"]
    assert "Saved to workspace: analysis/demo_profile.csv" in st.texts_named("success")


def test_downstream_page_saves_after_root_saved_on_start(tmp_path) -> None:
    root = tmp_path / "workspace"
    state: dict[str, Any] = {}
    _render_start_with_typed_root(state, str(root))
    _simulate_navigation_away(state)

    st = FakeSt(state)
    st.button_clicks[_SAVE_DIM_TIME_BTN] = True
    _render_dim_time_workspace_save(st, "date\n2025-01-01\n")

    assert WORKSPACE_ROOT_EMPTY_STATE not in st.texts()
    saved = list((root / "exports").glob("*.csv"))
    assert [file.name for file in saved] == ["dim_time.csv"]


def test_empty_state_still_shown_when_root_never_set(tmp_path) -> None:
    state: dict[str, Any] = {}
    _render_start(FakeSt(state), state)  # Start rendered, root left blank
    _simulate_navigation_away(state)

    st = FakeSt(state)
    st.button_clicks[_SAVE_BTN] = True
    render_analysis_csv_save(
        st,
        button_label="Save to workspace",
        key=_SAVE_BTN,
        artifact="profile",
        dataframe=_DF,
    )

    assert WORKSPACE_ROOT_EMPTY_STATE in st.texts()
    assert not list(tmp_path.rglob("*.csv"))


def test_clearing_root_on_start_restores_empty_state(tmp_path) -> None:
    root = str(tmp_path / "workspace")
    state: dict[str, Any] = {}
    _render_start_with_typed_root(state, root)
    _render_start_with_typed_root(state, "")  # user clears the input

    assert state[SRC_WORKSPACE_ROOT] == ""

    st = FakeSt(state)
    st.button_clicks[_SAVE_BTN] = True
    render_analysis_csv_save(
        st,
        button_label="Save to workspace",
        key=_SAVE_BTN,
        artifact="profile",
        dataframe=_DF,
    )
    assert WORKSPACE_ROOT_EMPTY_STATE in st.texts()


def test_returning_to_start_reseeds_widget_from_canonical(tmp_path) -> None:
    root = str(tmp_path / "workspace")
    state: dict[str, Any] = {}
    _render_start_with_typed_root(state, root)
    _simulate_navigation_away(state)

    st = FakeSt(state)
    _render_start(st, state)  # back to Start: widget key was cleaned up

    assert state[SRC_WORKSPACE_ROOT_INPUT] == root
    assert state[SRC_WORKSPACE_ROOT] == root
    assert "Workspace Root saved" in st.texts_named("caption")


def test_save_messages_never_leak_absolute_root(tmp_path) -> None:
    root = tmp_path / "workspace"
    state: dict[str, Any] = {}
    _render_start_with_typed_root(state, str(root))
    _simulate_navigation_away(state)

    st = FakeSt(state)
    st.button_clicks[_SAVE_BTN] = True
    render_analysis_csv_save(
        st,
        button_label="Save to workspace",
        key=_SAVE_BTN,
        artifact="profile",
        dataframe=_DF,
        dataset_name="demo.csv",
    )

    assert str(root) not in st.texts()
    assert str(tmp_path) not in st.texts()
