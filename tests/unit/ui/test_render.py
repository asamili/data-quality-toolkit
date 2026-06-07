"""Unit tests for Streamlit-coupled render functions in data_quality_toolkit.ui.app.

FakeSt records all Streamlit-like calls so tests assert expected UI interactions
without importing real Streamlit.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pandas as pd

from data_quality_toolkit.adapters.ui.app import (
    _render_cat_cat,
    _render_data_overview,
    _render_eda_bivariate,
    _render_eda_univariate,
    _render_num_cat,
    _render_num_num,
    _render_preprocessing_plan,
)


class FakeSt:
    """Minimal Streamlit test double. Records method calls; configurable return values."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._text_input_vals: dict[str, str] = {}
        self._selectbox_vals: dict[str, Any] = {}

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def _r(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def subheader(self, *a: Any, **kw: Any) -> None:
        self._r("subheader", *a, **kw)

    def header(self, *a: Any, **kw: Any) -> None:
        self._r("header", *a, **kw)

    def info(self, *a: Any, **kw: Any) -> None:
        self._r("info", *a, **kw)

    def caption(self, *a: Any, **kw: Any) -> None:
        self._r("caption", *a, **kw)

    def error(self, *a: Any, **kw: Any) -> None:
        self._r("error", *a, **kw)

    def warning(self, *a: Any, **kw: Any) -> None:
        self._r("warning", *a, **kw)

    def write(self, *a: Any, **kw: Any) -> None:
        self._r("write", *a, **kw)

    def metric(self, *a: Any, **kw: Any) -> None:
        self._r("metric", *a, **kw)

    def table(self, *a: Any, **kw: Any) -> None:
        self._r("table", *a, **kw)

    def dataframe(self, *a: Any, **kw: Any) -> None:
        self._r("dataframe", *a, **kw)

    def bar_chart(self, *a: Any, **kw: Any) -> None:
        self._r("bar_chart", *a, **kw)

    def scatter_chart(self, *a: Any, **kw: Any) -> None:
        self._r("scatter_chart", *a, **kw)

    def text_input(self, label: str, **kw: Any) -> str:
        self._r("text_input", label, **kw)
        return self._text_input_vals.get(label, "")

    def selectbox(self, label: str, options: list[Any], key: str | None = None, **kw: Any) -> Any:
        self._r("selectbox", label, options, key=key, **kw)
        lookup = key if key is not None else label
        return self._selectbox_vals.get(lookup, options[0] if options else None)

    def columns(self, n: int) -> list[FakeSt]:
        return [FakeSt() for _ in range(n)]

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def call_count(self, name: str) -> int:
        return sum(1 for c in self.calls if c[0] == name)

    def set_text_input(self, label: str, value: str) -> FakeSt:
        self._text_input_vals[label] = value
        return self

    def set_selectbox(self, key: str, value: Any) -> FakeSt:
        self._selectbox_vals[key] = value
        return self


# ── _render_eda_univariate ────────────────────────────────────────────────────


def test_render_eda_univariate_empty_df_shows_info() -> None:
    st = FakeSt()
    _render_eda_univariate(st, pd.DataFrame())
    assert st.called("subheader")
    assert st.called("info")
    assert not st.called("selectbox")


def test_render_eda_univariate_numeric_col_renders_chart() -> None:
    df = pd.DataFrame({"n": [float(i) for i in range(1, 11)]})
    st = FakeSt()
    _render_eda_univariate(st, df)
    assert st.called("selectbox")
    assert st.called("bar_chart")


def test_render_eda_univariate_numeric_col_shows_iqr_caption() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0, 5.0]})
    st = FakeSt()
    _render_eda_univariate(st, df)
    assert st.called("caption")


def test_render_eda_univariate_numeric_all_same_shows_info_not_chart() -> None:
    df = pd.DataFrame({"n": [3.0, 3.0, 3.0, 3.0, 3.0]})
    st = FakeSt()
    _render_eda_univariate(st, df)
    assert st.called("info")
    assert not st.called("bar_chart")


def test_render_eda_univariate_categorical_col_renders_dataframe_and_chart() -> None:
    df = pd.DataFrame({"c": ["a", "b", "a", "c", "a"]})
    st = FakeSt()
    _render_eda_univariate(st, df)
    assert st.called("dataframe")
    assert st.called("bar_chart")


def test_render_eda_univariate_empty_categorical_shows_info() -> None:
    df = pd.DataFrame({"c": pd.Series([], dtype="object")})
    st = FakeSt()
    _render_eda_univariate(st, df)
    assert st.called("info")
    assert not st.called("bar_chart")


# ── _render_num_num ───────────────────────────────────────────────────────────


def test_render_num_num_valid_pair_calls_scatter_chart() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [2.0, 4.0, 6.0, 8.0]})
    st = FakeSt()
    _render_num_num(st, df, "a", "b")
    assert st.called("scatter_chart")
    assert st.called("caption")


def test_render_num_num_non_numeric_col_shows_info() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "s": ["x", "y", "z"]})
    st = FakeSt()
    _render_num_num(st, df, "a", "s")
    assert st.called("info")
    assert not st.called("scatter_chart")


def test_render_num_num_single_row_shows_info() -> None:
    df = pd.DataFrame({"a": [1.0], "b": [2.0]})
    st = FakeSt()
    _render_num_num(st, df, "a", "b")
    assert st.called("info")
    assert not st.called("scatter_chart")


def test_render_num_num_constant_column_shows_info() -> None:
    df = pd.DataFrame({"a": [1.0, 1.0, 1.0], "b": [2.0, 3.0, 4.0]})
    st = FakeSt()
    _render_num_num(st, df, "a", "b")
    assert st.called("info")
    assert not st.called("scatter_chart")


# ── _render_num_cat ───────────────────────────────────────────────────────────


def test_render_num_cat_valid_pair_calls_bar_chart_and_dataframe() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0], "c": ["a", "a", "b", "b"]})
    st = FakeSt()
    _render_num_cat(st, df, "n", "c")
    assert st.called("bar_chart")
    assert st.called("dataframe")
    assert st.called("caption")


def test_render_num_cat_string_numeric_col_shows_info() -> None:
    df = pd.DataFrame({"s": ["x", "y", "z"], "c": ["a", "b", "c"]})
    st = FakeSt()
    _render_num_cat(st, df, "s", "c")
    assert st.called("info")
    assert not st.called("bar_chart")


def test_render_num_cat_both_numeric_shows_info() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0], "m": [3.0, 4.0]})
    st = FakeSt()
    _render_num_cat(st, df, "n", "m")
    assert st.called("info")
    assert not st.called("bar_chart")


def test_render_num_cat_empty_df_shows_info() -> None:
    df = pd.DataFrame({"n": pd.Series([], dtype="float64"), "c": pd.Series([], dtype="object")})
    st = FakeSt()
    _render_num_cat(st, df, "n", "c")
    assert st.called("info")


# ── _render_cat_cat ───────────────────────────────────────────────────────────


def test_render_cat_cat_valid_pair_calls_dataframe() -> None:
    df = pd.DataFrame({"a": ["x", "x", "y"], "b": ["p", "q", "p"]})
    st = FakeSt()
    _render_cat_cat(st, df, "a", "b")
    assert st.called("dataframe")
    assert st.called("caption")


def test_render_cat_cat_numeric_col_shows_info() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0], "c": ["a", "b", "c"]})
    st = FakeSt()
    _render_cat_cat(st, df, "n", "c")
    assert st.called("info")
    assert not st.called("dataframe")


def test_render_cat_cat_empty_df_shows_info() -> None:
    df = pd.DataFrame({"a": pd.Series([], dtype="object"), "b": pd.Series([], dtype="object")})
    st = FakeSt()
    _render_cat_cat(st, df, "a", "b")
    assert st.called("info")
    assert not st.called("dataframe")


# ── _render_eda_bivariate ─────────────────────────────────────────────────────


def test_render_eda_bivariate_empty_df_shows_info_no_selectbox() -> None:
    st = FakeSt()
    _render_eda_bivariate(st, pd.DataFrame())
    assert st.called("subheader")
    assert st.called("info")
    assert not st.called("selectbox")


def test_render_eda_bivariate_single_col_shows_info() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    st = FakeSt()
    _render_eda_bivariate(st, df)
    assert st.called("info")
    assert not st.called("selectbox")


def test_render_eda_bivariate_same_col_selected_shows_info() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
    st = FakeSt()
    st.set_selectbox("biv_col1", "a")
    st.set_selectbox("biv_col2", "a")
    _render_eda_bivariate(st, df)
    assert st.called("info")
    assert not st.called("scatter_chart")


def test_render_eda_bivariate_num_num_dispatches_scatter() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [2.0, 4.0, 6.0, 8.0]})
    st = FakeSt()
    st.set_selectbox("biv_col1", "a")
    st.set_selectbox("biv_col2", "b")
    _render_eda_bivariate(st, df)
    assert st.called("scatter_chart")


def test_render_eda_bivariate_cat_cat_dispatches_dataframe() -> None:
    df = pd.DataFrame({"a": ["x", "y", "x"], "b": ["p", "q", "p"]})
    st = FakeSt()
    st.set_selectbox("biv_col1", "a")
    st.set_selectbox("biv_col2", "b")
    _render_eda_bivariate(st, df)
    assert st.called("dataframe")


def test_render_eda_bivariate_num_cat_dispatches_bar_chart() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0], "c": ["a", "a", "b", "b"]})
    st = FakeSt()
    st.set_selectbox("biv_col1", "n")
    st.set_selectbox("biv_col2", "c")
    _render_eda_bivariate(st, df)
    assert st.called("bar_chart")


def test_render_eda_bivariate_cat_num_dispatches_bar_chart() -> None:
    df = pd.DataFrame({"c": ["a", "a", "b", "b"], "n": [1.0, 2.0, 3.0, 4.0]})
    st = FakeSt()
    st.set_selectbox("biv_col1", "c")
    st.set_selectbox("biv_col2", "n")
    _render_eda_bivariate(st, df)
    assert st.called("bar_chart")


# ── _render_preprocessing_plan ────────────────────────────────────────────────


def test_render_preprocessing_plan_empty_df_shows_info() -> None:
    st = FakeSt()
    _render_preprocessing_plan(st, pd.DataFrame())
    assert st.called("subheader")
    assert st.called("info")
    assert not st.called("dataframe")


def test_render_preprocessing_plan_nonempty_df_calls_dataframe() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    st = FakeSt()
    _render_preprocessing_plan(st, df)
    assert st.called("dataframe")
    assert not st.called("info")


def test_render_preprocessing_plan_numeric_with_nulls_included() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, None, 5.0]})
    st = FakeSt()
    _render_preprocessing_plan(st, df)
    assert st.called("dataframe")


# ── _render_data_overview ─────────────────────────────────────────────────────

_MOCK_PATH = "data_quality_toolkit.ui.app._load_df_and_assess"

_FAKE_DF = pd.DataFrame({"n": [1.0, 2.0, 3.0], "c": ["a", "b", "a"]})
_FAKE_PROFILE: dict[str, Any] = {
    "rows": 3,
    "cols": 2,
    "memory_mb": 0.01,
    "columns": [
        {"name": "n", "dtype": "float64", "nulls": 0, "unique": 3, "min": 1.0, "max": 3.0},
        {"name": "c", "dtype": "object", "nulls": 0, "unique": 2},
    ],
}
_FAKE_ASSESSMENT: dict[str, Any] = {"score": 0.95, "issues": []}
_FAKE_RESULT: dict[str, Any] = {
    "run_id": "r1",
    "dataset_id": "sha1:abc",
    "ts": "2025-01-01T00:00:00Z",
    "meta": {},
    "profile": _FAKE_PROFILE,
    "assessment": _FAKE_ASSESSMENT,
}


def test_render_data_overview_empty_path_shows_info_and_returns() -> None:
    st = FakeSt()
    _render_data_overview(st)
    assert st.called("header")
    assert st.called("info")
    assert not st.called("metric")


def test_render_data_overview_load_error_shows_error() -> None:
    st = FakeSt()
    st.set_text_input("CSV path for data overview", "bad.csv")
    with patch(_MOCK_PATH, return_value=(None, None, "file not found")):
        _render_data_overview(st)
    assert st.called("error")
    assert not st.called("metric")


def test_render_data_overview_happy_path_calls_metric_and_table() -> None:
    st = FakeSt()
    st.set_text_input("CSV path for data overview", "data.csv")
    with patch(_MOCK_PATH, return_value=(_FAKE_DF, _FAKE_RESULT, None)):
        _render_data_overview(st)
    assert st.called("metric")
    assert st.called("table")


def test_render_data_overview_happy_path_calls_write_for_shape_and_duplicates() -> None:
    st = FakeSt()
    st.set_text_input("CSV path for data overview", "data.csv")
    with patch(_MOCK_PATH, return_value=(_FAKE_DF, _FAKE_RESULT, None)):
        _render_data_overview(st)
    assert st.call_count("write") >= 2


def test_render_data_overview_with_issues_calls_dataframe() -> None:
    result_with_issues: dict[str, Any] = {
        **_FAKE_RESULT,
        "assessment": {"score": 0.7, "issues": [{"col": "n", "type": "nulls"}]},
    }
    st = FakeSt()
    st.set_text_input("CSV path for data overview", "data.csv")
    with patch(_MOCK_PATH, return_value=(_FAKE_DF, result_with_issues, None)):
        _render_data_overview(st)
    assert st.called("dataframe")


def test_render_data_overview_happy_path_triggers_nested_eda_renders() -> None:
    st = FakeSt()
    st.set_text_input("CSV path for data overview", "data.csv")
    with patch(_MOCK_PATH, return_value=(_FAKE_DF, _FAKE_RESULT, None)):
        _render_data_overview(st)
    assert st.called("selectbox")
    assert st.call_count("subheader") >= 2
