"""Tests for the Preprocess Studio page (render + recipe-state helpers)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pandas as pd

from data_quality_toolkit.adapters.ui.pages.preprocess_studio import (
    _append_step,
    _current_steps,
    _render_preprocess_studio,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT, PREP_RECIPE_STEPS
from data_quality_toolkit.application.workflow.preprocessing import make_recipe_step

_PATCH_LOAD = "data_quality_toolkit.adapters.ui.pages.preprocess_studio._load_df_and_assess"

_DF = pd.DataFrame({"n": [1.0, 2.0, 2.0, 3.0], "c": ["a", "a", "a", "b"]})
_RESULT: dict[str, Any] = {"profile": {"rows": 4, "cols": 2}, "assessment": {"score": 1.0}}


class FakeSt:
    """Minimal Streamlit recorder supporting columns/selectbox/multiselect/button."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.text_values: dict[str, str] = {}

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
        return self.text_values.get(label, str(k.get("value", "")))

    def selectbox(self, label: str, options: Any = (), **k: Any) -> Any:
        self._rec("selectbox", label, options, **k)
        return options[0] if options else None

    def multiselect(self, label: str, options: Any = (), **k: Any) -> list[Any]:
        self._rec("multiselect", label, options, **k)
        return []

    def button(self, label: str, **k: Any) -> bool:
        self._rec("button", label, **k)
        return False

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))


# ── recipe-state helpers ─────────────────────────────────────────────────────


def test_append_step_grows_recipe() -> None:
    state: dict[str, Any] = {}
    _append_step(state, "scaling", ["n"], {"strategy": "minmax"})
    _append_step(state, "drop_duplicates", [], {})
    assert len(_current_steps(state)) == 2


def test_append_step_ignores_empty_operation() -> None:
    state: dict[str, Any] = {}
    _append_step(state, "", ["n"], {})
    assert _current_steps(state) == []


def test_current_steps_ignores_malformed_state() -> None:
    assert _current_steps({PREP_RECIPE_STEPS: "not-a-list"}) == []


# ── page render ──────────────────────────────────────────────────────────────


def test_render_empty_path_shows_info() -> None:
    st = FakeSt()
    _render_preprocess_studio(st, {})
    assert st.called("header")
    assert st.called("info")
    assert not st.called("dataframe")


def test_render_load_error_shows_error() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "bad.csv"
    with patch(_PATCH_LOAD, return_value=(None, None, "file not found")):
        _render_preprocess_studio(st, {})
    assert st.called("error")
    assert not st.called("metric")


def test_render_large_file_context_blocks_without_loading() -> None:
    st = FakeSt()
    context = DatasetContext(
        source_path="C:/safe/data.csv",
        display_name="data.csv",
        size_bytes=10,
        modified_ns=1,
        large_file_mode=True,
    )
    with patch(_PATCH_LOAD) as load:
        _render_preprocess_studio(st, {DATASET_CONTEXT: context})
    load.assert_not_called()
    assert st.called("warning")


def test_render_shows_recommendations_without_steps() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_preprocess_studio(st, {})
    assert st.called("dataframe")  # recommendations table
    text = st.texts()
    assert "Recommended actions" in text
    assert "Build recipe" in text
    assert "Export recipe" in text


def test_render_with_seeded_recipe_shows_before_after_and_export() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    state: dict[str, Any] = {PREP_RECIPE_STEPS: [make_recipe_step("drop_duplicates", [], {})]}
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_preprocess_studio(st, state)
    assert st.called("metric")  # before/after summary cards
    assert st.called("download_button")  # recipe export
    text = st.texts()
    assert "Preview & before/after validation" in text
    assert "Transformed preview" in text


def test_render_does_not_draw_charts() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    state: dict[str, Any] = {
        PREP_RECIPE_STEPS: [make_recipe_step("scaling", ["n"], {"strategy": "minmax"})]
    }
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_preprocess_studio(st, state)
    assert not st.called("bar_chart")
    assert not st.called("scatter_chart")
    assert not st.called("line_chart")
