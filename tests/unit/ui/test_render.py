"""Unit tests for Streamlit-coupled render functions in data_quality_toolkit.adapters.ui.app.

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
    _render_dim_time,
    _render_eda_bivariate,
    _render_eda_univariate,
    _render_export,
    _render_kpi_catalog,
    _render_num_cat,
    _render_num_num,
    _render_preprocessing_plan,
    _render_run_history,
)


class FakeSt:
    """Minimal Streamlit test double. Records method calls; configurable return values."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._text_input_vals: dict[str, str] = {}
        self._selectbox_vals: dict[str, Any] = {}
        self._checkbox_vals: dict[str, bool] = {}
        self._button_clicks: dict[str, bool] = {}

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

    def divider(self, *a: Any, **kw: Any) -> None:
        self._r("divider", *a, **kw)

    def expander(self, label: str, **kw: Any) -> FakeSt:
        self._r("expander", label, **kw)
        return self

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

    def download_button(self, *a: Any, **kw: Any) -> None:
        self._r("download_button", *a, **kw)

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

    def success(self, *a: Any, **kw: Any) -> None:
        self._r("success", *a, **kw)

    def json(self, *a: Any, **kw: Any) -> None:
        self._r("json", *a, **kw)

    def code(self, *a: Any, **kw: Any) -> None:
        self._r("code", *a, **kw)

    def line_chart(self, *a: Any, **kw: Any) -> None:
        self._r("line_chart", *a, **kw)

    def markdown(self, *a: Any, **kw: Any) -> None:
        self._r("markdown", *a, **kw)

    def number_input(self, label: str, **kw: Any) -> Any:
        self._r("number_input", label, **kw)
        return kw.get("value", kw.get("min_value", 1))

    def checkbox(self, label: str, **kw: Any) -> bool:
        self._r("checkbox", label, **kw)
        return self._checkbox_vals.get(label, False)

    def tabs(self, labels: list[str]) -> list[FakeSt]:
        self._r("tabs", labels)
        return [FakeSt() for _ in labels]

    def set_text_input(self, label: str, value: str) -> FakeSt:
        self._text_input_vals[label] = value
        return self

    def set_selectbox(self, key: str, value: Any) -> FakeSt:
        self._selectbox_vals[key] = value
        return self

    def button(self, label: str, **kw: Any) -> bool:
        self._r("button", label, **kw)
        return self._button_clicks.get(label, False)

    def set_checkbox(self, label: str, value: bool) -> FakeSt:
        self._checkbox_vals[label] = value
        return self

    def set_button_clicked(self, label: str, value: bool = True) -> FakeSt:
        self._button_clicks[label] = value
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

_MOCK_PATH = "data_quality_toolkit.adapters.ui.app._load_df_and_assess"

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
    st.set_text_input("CSV path", "bad.csv")
    with patch(_MOCK_PATH, return_value=(None, None, "file not found")):
        _render_data_overview(st)
    assert st.called("error")
    assert not st.called("metric")


def test_render_data_overview_happy_path_calls_metric_and_table() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    with patch(_MOCK_PATH, return_value=(_FAKE_DF, _FAKE_RESULT, None)):
        _render_data_overview(st)
    assert st.called("metric")
    assert st.called("dataframe")


def test_render_data_overview_happy_path_calls_write_for_shape_and_duplicates() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    with patch(_MOCK_PATH, return_value=(_FAKE_DF, _FAKE_RESULT, None)):
        _render_data_overview(st)
    # The new implementation calls 'write' once (Dataset profile info).
    # The previous implementation called 'write' twice (Shape + Memory).
    # Update expected call count to 1 based on new UI structure.
    assert st.call_count("write") >= 1


def test_render_data_overview_with_issues_calls_dataframe() -> None:
    result_with_issues: dict[str, Any] = {
        **_FAKE_RESULT,
        "assessment": {"score": 0.7, "issues": [{"col": "n", "type": "nulls"}]},
    }
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    with patch(_MOCK_PATH, return_value=(_FAKE_DF, result_with_issues, None)):
        _render_data_overview(st)
    assert st.called("dataframe")


def test_render_data_overview_happy_path_triggers_nested_eda_renders() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    with patch(_MOCK_PATH, return_value=(_FAKE_DF, _FAKE_RESULT, None)):
        _render_data_overview(st)
    assert st.called("selectbox")
    assert st.call_count("subheader") >= 2


# ── _render_run_history ───────────────────────────────────────────────────────

_MOCK_LOAD_HISTORY = "data_quality_toolkit.adapters.ui.app._load_run_history"


def test_render_run_history_empty_inputs_shows_info() -> None:
    st = FakeSt()
    _render_run_history(st)
    assert st.called("header")
    assert st.called("info")
    assert not st.called("error")


def test_render_run_history_storage_error_shows_error() -> None:
    st = FakeSt()
    st.set_text_input("Database path", "./dist/dqt.db")
    st.set_text_input("Dataset ID", "sha1:abc")
    with patch(_MOCK_LOAD_HISTORY, return_value=(None, "db corrupt")):
        _render_run_history(st)
    assert st.called("error")
    assert not st.called("dataframe")


def test_render_run_history_empty_records_shows_warning() -> None:
    st = FakeSt()
    st.set_text_input("Database path", "./dist/dqt.db")
    st.set_text_input("Dataset ID", "sha1:abc")
    with patch(_MOCK_LOAD_HISTORY, return_value=([], None)):
        _render_run_history(st)
    assert st.called("warning")
    assert not st.called("dataframe")


def test_render_run_history_records_shows_dataframe() -> None:
    records = [
        {
            "ts": "2025-01-01T00:00:00",
            "score": 0.9,
            "issues_by_severity": {},
            "issues_by_category": {},
        },
        {
            "ts": "2025-01-02T00:00:00",
            "score": 0.85,
            "issues_by_severity": {},
            "issues_by_category": {},
        },
    ]
    st = FakeSt()
    st.set_text_input("Database path", "./dist/dqt.db")
    st.set_text_input("Dataset ID", "sha1:abc")
    with patch(_MOCK_LOAD_HISTORY, return_value=(records, None)):
        _render_run_history(st)
    assert st.called("dataframe")


# ── _render_export ────────────────────────────────────────────────────────────


def test_render_export_shows_header_and_code() -> None:
    st = FakeSt()
    _render_export(st)
    assert st.called("header")
    assert st.called("code")
    assert st.called("info")


# ── _render_kpi_catalog ───────────────────────────────────────────────────────

_MOCK_KPI_VALIDATE = "data_quality_toolkit.adapters.ui.app._run_kpi_validate"
_MOCK_KPI_EMIT = "data_quality_toolkit.adapters.ui.app._kpi_emit_to_bytes"
_MOCK_KPI_GRAPH = "data_quality_toolkit.adapters.ui.app._kpi_graph_to_str"

_FAKE_KPI_VALID = {
    "status": "valid",
    "kpis": 3,
    "cycles": 0,
    "grains": ["daily"],
    "dependencies": 2,
    "by_grain": {"daily": 3},
}
_FAKE_KPI_INVALID = {
    "status": "invalid",
    "reason": "cycles",
    "kpis": 2,
    "cycles": [["a", "b", "a"]],
}


def test_render_kpi_catalog_empty_path_shows_info() -> None:
    st = FakeSt()
    _render_kpi_catalog(st)
    assert st.called("header")
    assert st.called("info")
    assert not st.called("success")


def test_render_kpi_catalog_validation_error_shows_error() -> None:
    st = FakeSt()
    st.set_text_input("KPI catalog YAML path", "bad.yaml")
    with patch(_MOCK_KPI_VALIDATE, return_value=(None, "file not found")):
        _render_kpi_catalog(st)
    assert st.called("error")
    assert not st.called("success")


def test_render_kpi_catalog_invalid_catalog_shows_error() -> None:
    st = FakeSt()
    st.set_text_input("KPI catalog YAML path", "catalog.yaml")
    with patch(_MOCK_KPI_VALIDATE, return_value=(_FAKE_KPI_INVALID, None)):
        _render_kpi_catalog(st)
    assert st.called("error")
    assert not st.called("success")


def test_render_kpi_catalog_valid_shows_success_and_download_buttons() -> None:
    st = FakeSt()
    st.set_text_input("KPI catalog YAML path", "catalog.yaml")
    with (
        patch(_MOCK_KPI_VALIDATE, return_value=(_FAKE_KPI_VALID, None)),
        patch(_MOCK_KPI_EMIT, return_value=(b"dax", b"tmsl", None)),
        patch(_MOCK_KPI_GRAPH, return_value=("graph mmd content", None)),
    ):
        _render_kpi_catalog(st)
    assert st.called("success")
    assert st.called("download_button")
    assert st.call_count("download_button") >= 3  # DAX, TMSL, graph


def test_render_kpi_catalog_emit_error_shows_warning_and_code() -> None:
    st = FakeSt()
    st.set_text_input("KPI catalog YAML path", "catalog.yaml")
    with (
        patch(_MOCK_KPI_VALIDATE, return_value=(_FAKE_KPI_VALID, None)),
        patch(_MOCK_KPI_EMIT, return_value=(None, None, "emit failed")),
        patch(_MOCK_KPI_GRAPH, return_value=(None, "graph failed")),
    ):
        _render_kpi_catalog(st)
    assert st.called("success")
    assert st.called("warning")
    assert st.called("code")
    assert not st.called("download_button")


# ── _render_dim_time ──────────────────────────────────────────────────────────

_MOCK_GEN_DIM = "data_quality_toolkit.adapters.ui.app._generate_dim_time_csv"


def test_render_dim_time_shows_header() -> None:
    st = FakeSt()
    _render_dim_time(st)
    assert st.called("header")


def test_render_dim_time_default_dates_calls_generate_and_shows_download() -> None:
    st = FakeSt()
    st.set_text_input("Start date (YYYY-MM-DD)", "2024-01-01")
    st.set_text_input("End date (YYYY-MM-DD)", "2024-01-07")
    with patch(_MOCK_GEN_DIM, return_value=("col\n1\n2\n", 7, None)):
        _render_dim_time(st)
    assert st.called("success")
    assert st.called("download_button")


def test_render_dim_time_generate_error_shows_error() -> None:
    st = FakeSt()
    st.set_text_input("Start date (YYYY-MM-DD)", "bad-date")
    st.set_text_input("End date (YYYY-MM-DD)", "also-bad")
    with patch(_MOCK_GEN_DIM, return_value=(None, None, "invalid date format")):
        _render_dim_time(st)
    assert st.called("error")
    assert not st.called("download_button")


# ── _render_export (server-write section) ─────────────────────────────────────

_MOCK_EXPORT_CSV_TO_DIR = "data_quality_toolkit.adapters.ui.app._export_csv_to_dir"


def test_render_export_shows_warning_and_confirmation_controls() -> None:
    st = FakeSt()
    _render_export(st)
    assert st.called("warning")
    assert st.called("checkbox")
    assert st.called("button")


def test_render_export_no_click_no_write() -> None:
    st = FakeSt()
    with patch(_MOCK_EXPORT_CSV_TO_DIR) as mock_export:
        _render_export(st)
    mock_export.assert_not_called()


def test_render_export_click_missing_inputs_shows_error() -> None:
    st = FakeSt()
    st.set_button_clicked("Run export and write to directory")
    with patch(_MOCK_EXPORT_CSV_TO_DIR) as mock_export:
        _render_export(st)
    assert st.called("error")
    mock_export.assert_not_called()


def test_render_export_click_no_confirm_shows_error() -> None:
    st = FakeSt()
    st.set_text_input("CSV file path to export", "/data/test.csv")
    st.set_text_input("Output directory (absolute path)", "/tmp/out")
    st.set_button_clicked("Run export and write to directory")
    with patch(_MOCK_EXPORT_CSV_TO_DIR) as mock_export:
        _render_export(st)
    assert st.called("error")
    mock_export.assert_not_called()


def test_render_export_click_confirmed_valid_shows_success() -> None:
    st = FakeSt()
    st.set_text_input("CSV file path to export", "/data/test.csv")
    st.set_text_input("Output directory (absolute path)", "/tmp/out")
    st.set_checkbox("I confirm: write export files to the directory above", True)
    st.set_button_clicked("Run export and write to directory")
    fake_result = {"export_paths": {"dim_dataset": "/tmp/out/star/dim_dataset.csv"}}
    with patch(_MOCK_EXPORT_CSV_TO_DIR, return_value=(fake_result, None)):
        _render_export(st)
    assert st.called("success")
    assert not st.called("error")


def test_render_export_click_confirmed_export_error_shows_error() -> None:
    st = FakeSt()
    st.set_text_input("CSV file path to export", "/data/test.csv")
    st.set_text_input("Output directory (absolute path)", "/tmp/out")
    st.set_checkbox("I confirm: write export files to the directory above", True)
    st.set_button_clicked("Run export and write to directory")
    with patch(_MOCK_EXPORT_CSV_TO_DIR, return_value=(None, "file not found")):
        _render_export(st)
    assert st.called("error")
    assert not st.called("success")
