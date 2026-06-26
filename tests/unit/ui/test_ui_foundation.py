"""Focused tests for the G27E shared UI foundation."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from data_quality_toolkit.adapters.ui.components.dataset_context import (
    format_file_size,
    render_dataset_context_panel,
)
from data_quality_toolkit.adapters.ui.components.page_shell import render_page_header
from data_quality_toolkit.adapters.ui.pages.data_overview import _render_data_overview
from data_quality_toolkit.adapters.ui.pages.eda_explorer import _render_eda_explorer
from data_quality_toolkit.adapters.ui.pages.start import _render_start
from data_quality_toolkit.adapters.ui.services.dataset import build_dataset_context
from data_quality_toolkit.adapters.ui.state.context import (
    DatasetContext,
    clear_dataset_context,
    get_dataset_context,
    set_dataset_context,
)
from data_quality_toolkit.adapters.ui.state.keys import (
    BIV_COL1,
    DATASET_CONTEXT,
    DATASET_LARGE_FILE_MODE,
    DATASET_PATH_INPUT,
)


class FakeSt:
    """Small Streamlit recorder for foundation render tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.text_values: dict[str, str] = {}
        self.checkbox_values: dict[str, bool] = {}
        self.clicked: set[str] = set()

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def header(self, *args: Any, **kwargs: Any) -> None:
        self._record("header", *args, **kwargs)

    def caption(self, *args: Any, **kwargs: Any) -> None:
        self._record("caption", *args, **kwargs)

    def info(self, *args: Any, **kwargs: Any) -> None:
        self._record("info", *args, **kwargs)

    def warning(self, *args: Any, **kwargs: Any) -> None:
        self._record("warning", *args, **kwargs)

    def error(self, *args: Any, **kwargs: Any) -> None:
        self._record("error", *args, **kwargs)

    def success(self, *args: Any, **kwargs: Any) -> None:
        self._record("success", *args, **kwargs)

    def text_input(self, label: str, **kwargs: Any) -> str:
        self._record("text_input", label, **kwargs)
        return self.text_values.get(label, "")

    def checkbox(self, label: str, **kwargs: Any) -> bool:
        self._record("checkbox", label, **kwargs)
        return self.checkbox_values.get(label, False)

    def button(self, label: str, **kwargs: Any) -> bool:
        self._record("button", label, **kwargs)
        return label in self.clicked

    def called(self, name: str) -> bool:
        return any(call[0] == name for call in self.calls)


def _context(path: str = "C:/safe/orders.csv", *, large: bool = False) -> DatasetContext:
    return DatasetContext(
        source_path=path,
        display_name="orders.csv",
        size_bytes=2048,
        modified_ns=10,
        large_file_mode=large,
    )


def test_build_dataset_context_success(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("id,value\n1,2\n", encoding="utf-8")

    context, err = build_dataset_context(f"  {csv_path}  ", large_file_mode=True)

    assert err is None
    assert context is not None
    assert context.display_name == "orders.csv"
    assert context.source_path == str(csv_path.resolve())
    assert context.size_bytes == csv_path.stat().st_size
    assert context.large_file_mode is True


def test_build_dataset_context_rejects_empty_missing_and_non_csv(tmp_path: Path) -> None:
    assert build_dataset_context("")[1] == "Enter a CSV path."
    assert build_dataset_context(str(tmp_path / "missing.csv"))[0] is None
    assert build_dataset_context(str(tmp_path / "data.txt"))[1] == "Dataset must be a .csv file."


def test_set_context_invalidates_derived_state_only_when_changed() -> None:
    state: dict[str, Any] = {BIV_COL1: "a"}
    context = _context()

    assert set_dataset_context(state, context) is True
    assert BIV_COL1 not in state
    state[BIV_COL1] = "b"
    assert set_dataset_context(state, context) is False
    assert state[BIV_COL1] == "b"


def test_clear_context_removes_context_and_derived_state() -> None:
    state: dict[str, Any] = {DATASET_CONTEXT: _context(), BIV_COL1: "a"}

    assert clear_dataset_context(state) is True
    assert get_dataset_context(state) is None
    assert BIV_COL1 not in state


def test_get_context_ignores_malformed_value() -> None:
    assert get_dataset_context({DATASET_CONTEXT: {"source_path": "unsafe"}}) is None


def test_shared_components_render_safe_metadata() -> None:
    st = FakeSt()
    context = _context("C:/private/location/orders.csv")

    render_page_header(st, "Title", "Caption", step_label="Step 1")
    render_dataset_context_panel(st, context)

    rendered = " ".join(str(args) for _, args, _ in st.calls)
    assert st.called("header")
    assert format_file_size(2048) == "2.0 KB"
    assert "orders.csv" in rendered
    assert context.source_path not in rendered


def test_start_activates_valid_dataset(tmp_path: Path) -> None:
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("id\n1\n", encoding="utf-8")
    st = FakeSt()
    st.text_values["CSV path"] = str(csv_path)
    st.clicked.add("Use dataset")
    state: dict[str, Any] = {}

    _render_start(st, state)

    context = get_dataset_context(state)
    assert context is not None
    assert context.display_name == "orders.csv"
    assert st.called("success")


def test_start_clear_removes_active_context() -> None:
    st = FakeSt()
    st.clicked.add("Clear dataset")
    state: dict[str, Any] = {
        DATASET_CONTEXT: _context(),
        DATASET_PATH_INPUT: "C:/safe/orders.csv",
        DATASET_LARGE_FILE_MODE: False,
    }

    _render_start(st, state)

    assert get_dataset_context(state) is None


def test_data_overview_reuses_active_context_path() -> None:
    st = FakeSt()
    context = _context()
    with patch(
        "data_quality_toolkit.adapters.ui.pages.data_overview._load_df_and_assess",
        return_value=(None, None, None),
    ) as load:
        _render_data_overview(st, {DATASET_CONTEXT: context})

    load.assert_called_once_with(context.source_path)
    assert not st.called("text_input")


def test_eda_reuses_active_context_path() -> None:
    st = FakeSt()
    context = _context()
    with patch(
        "data_quality_toolkit.adapters.ui.pages.eda_explorer._load_df_and_assess",
        return_value=(None, None, None),
    ) as load:
        _render_eda_explorer(st, {DATASET_CONTEXT: context})

    load.assert_called_once_with(context.source_path)
    assert not st.called("text_input")


def test_eda_blocks_large_file_context_without_loading() -> None:
    st = FakeSt()
    with patch("data_quality_toolkit.adapters.ui.pages.eda_explorer._load_df_and_assess") as load:
        _render_eda_explorer(st, {DATASET_CONTEXT: _context(large=True)})

    load.assert_not_called()
    assert st.called("warning")
