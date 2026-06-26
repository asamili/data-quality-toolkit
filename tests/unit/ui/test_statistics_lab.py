"""Tests for the Statistics Lab descriptive tier (page + service)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pandas as pd

from data_quality_toolkit.adapters.ui.pages.statistics_lab import _render_statistics_lab
from data_quality_toolkit.adapters.ui.services.statistics import (
    column_type_overview,
    numeric_descriptive_stats,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT

_PATCH_LOAD = "data_quality_toolkit.adapters.ui.pages.statistics_lab._load_df_and_assess"

_DF = pd.DataFrame(
    {
        "n": [1.0, 2.0, 3.0, 4.0, 5.0],
        "m": [10.0, 9.0, 8.0, 7.0, 6.0],
        "c": ["a", "b", "a", "c", "a"],
    }
)
_RESULT: dict[str, Any] = {"profile": {"rows": 5, "cols": 3}, "assessment": {"score": 1.0}}


class FakeSt:
    """Minimal Streamlit recorder supporting columns/selectbox/context use."""

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

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))


# ── service ─────────────────────────────────────────────────────────────────


def test_numeric_descriptive_stats_has_expected_columns() -> None:
    stats = numeric_descriptive_stats(_DF)
    assert stats is not None
    assert set(stats.columns) == {
        "count",
        "mean",
        "median",
        "std",
        "min",
        "max",
        "skew",
        "kurtosis",
    }
    assert "n" in stats.index
    assert "c" not in stats.index  # categorical excluded


def test_numeric_descriptive_stats_none_without_numeric() -> None:
    assert numeric_descriptive_stats(pd.DataFrame({"c": ["a", "b"]})) is None


def test_column_type_overview_counts() -> None:
    overview = column_type_overview(_DF)
    assert overview["total_columns"] == 3
    assert overview["numeric_columns"] == 2
    assert overview["categorical_or_other_columns"] == 1


# ── page render ────────────────────────────────────────────────────────────


def test_render_empty_path_shows_info() -> None:
    st = FakeSt()
    _render_statistics_lab(st, {})
    assert st.called("header")
    assert st.called("info")
    assert not st.called("dataframe")


def test_render_load_error_shows_error() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "bad.csv"
    with patch(_PATCH_LOAD, return_value=(None, None, "file not found")):
        _render_statistics_lab(st, {})
    assert st.called("error")
    assert not st.called("dataframe")


def test_render_happy_path_shows_descriptive_tables() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_statistics_lab(st, {})
    assert st.called("dataframe")
    assert st.called("metric")  # dimension cards
    text = st.texts()
    assert "Numeric descriptive statistics" in text
    # Inferential tier now renders below the descriptive tables.
    assert "Inferential Tests" in text


def test_render_does_not_draw_charts() -> None:
    """Statistics Lab is tables-only; charts belong to EDA Explorer."""
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_statistics_lab(st, {})
    assert not st.called("bar_chart")
    assert not st.called("scatter_chart")
    assert not st.called("line_chart")


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
        _render_statistics_lab(st, {DATASET_CONTEXT: context})
    load.assert_not_called()
    assert st.called("warning")
