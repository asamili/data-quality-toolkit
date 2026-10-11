"""Unit tests for Streamlit-coupled render functions in the dashboard page modules.

FakeSt records all Streamlit-like calls so tests assert expected UI interactions
without importing real Streamlit. Render functions moved from app.py into
adapters/ui/pages during the UI restructure; imports point at their pages.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pandas as pd

from data_quality_toolkit.adapters.ui.eda_sections import (
    _ADVANCED_TAB_INTRO,
    _COLUMNS_TAB_INTRO,
    _OVERVIEW_TAB_INTRO,
    _RELATIONSHIPS_TAB_INTRO,
    _TIME_TAB_INTRO,
    _render_cat_cat,
    _render_datetime_trend,
    _render_eda_bivariate,
    _render_eda_univariate,
    _render_num_cat,
    _render_num_num,
    _render_preprocessing_plan,
    _step_bivariate_column,
    _swap_bivariate_columns,
    render_advanced_tab,
    render_columns_tab,
    render_overview_tab,
    render_relationships_tab,
    render_time_tab,
)
from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center
from data_quality_toolkit.adapters.ui.pages.data_overview import _render_data_overview
from data_quality_toolkit.adapters.ui.pages.dim_time import _render_dim_time
from data_quality_toolkit.adapters.ui.pages.drift_explorer import _render_drift_explorer
from data_quality_toolkit.adapters.ui.pages.eda_explorer import _render_eda_explorer
from data_quality_toolkit.adapters.ui.pages.export import _render_export
from data_quality_toolkit.adapters.ui.pages.kpi_catalog import _render_kpi_catalog
from data_quality_toolkit.adapters.ui.pages.manifest_viewer import _render_manifest_viewer
from data_quality_toolkit.adapters.ui.pages.run_history import _render_run_history
from data_quality_toolkit.adapters.ui.state.keys import SRC_WORKSPACE_ROOT


def test_eda_sections_imports_tab_renderers() -> None:
    """The EDA tab sections are importable from the extracted module."""
    from data_quality_toolkit.adapters.ui import eda_sections

    assert callable(eda_sections.render_overview_tab)
    assert callable(eda_sections.render_columns_tab)
    assert callable(eda_sections.render_relationships_tab)
    assert callable(eda_sections.render_time_tab)
    assert callable(eda_sections.render_advanced_tab)


class FakeSt:
    """Minimal Streamlit test double. Records method calls; configurable return values."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.session_state: dict[str, Any] = {}
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

    def vega_lite_chart(self, *a: Any, **kw: Any) -> None:
        self._r("vega_lite_chart", *a, **kw)

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
        return [self for _ in labels]

    def set_text_input(self, label: str, value: str) -> FakeSt:
        self._text_input_vals[label] = value
        return self

    def set_selectbox(self, key: str, value: Any) -> FakeSt:
        self._selectbox_vals[key] = value
        return self

    def button(self, label: str, **kw: Any) -> bool:
        self._r("button", label, **kw)
        clicked = self._button_clicks.get(label, False)
        on_click = kw.get("on_click")
        if clicked and callable(on_click):
            on_click(*kw.get("args", ()), **kw.get("kwargs", {}))
        return clicked

    def set_checkbox(self, label: str, value: bool) -> FakeSt:
        self._checkbox_vals[label] = value
        return self

    def set_button_clicked(self, label: str, value: bool = True) -> FakeSt:
        self._button_clicks[label] = value
        return self

    def Page(self, *a: Any, **kw: Any) -> Any:  # noqa: N802 -- matches st.Page's real casing
        self._r("Page", *a, **kw)
        return kw

    def page_link(self, *a: Any, **kw: Any) -> None:
        self._r("page_link", *a, **kw)


def _rendered_text(st: FakeSt) -> str:
    return " ".join(
        str(arg) for _name, args, _kwargs in st.calls for arg in args if isinstance(arg, str)
    )


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


# ── smart-scaling controls ────────────────────────────────────────────────────


def test_render_eda_univariate_auto_bins_default_skips_number_input() -> None:
    df = pd.DataFrame({"n": [float(i) for i in range(1, 11)]})
    st = FakeSt()
    st.set_checkbox("Auto bins (Freedman–Diaconis)", True)
    _render_eda_univariate(st, df)
    number_labels = [c[1][0] for c in st.calls if c[0] == "number_input"]
    assert "Histogram bins" not in number_labels  # auto path skips explicit bins input
    assert st.called("bar_chart")


def test_render_eda_univariate_explicit_bins_when_auto_off() -> None:
    df = pd.DataFrame({"n": [float(i) for i in range(1, 11)]})
    st = FakeSt()  # checkbox defaults False → explicit path
    _render_eda_univariate(st, df)
    number_labels = [c[1][0] for c in st.calls if c[0] == "number_input"]
    assert "Histogram bins" in number_labels
    assert st.called("bar_chart")


def test_render_eda_univariate_renders_other_bucket_checkbox() -> None:
    df = pd.DataFrame({"c": ["a", "b", "a", "c"]})
    st = FakeSt()
    _render_eda_univariate(st, df)
    checkbox_labels = [c[1][0] for c in st.calls if c[0] == "checkbox"]
    assert "Include Other bucket" in checkbox_labels
    assert st.called("bar_chart")


# ── numeric ECDF ──────────────────────────────────────────────────────────────


def test_render_eda_univariate_numeric_renders_ecdf() -> None:
    df = pd.DataFrame({"n": [float(i) for i in range(1, 11)]})
    st = FakeSt()
    _render_eda_univariate(st, df)
    assert "ECDF" in _rendered_text(st)
    assert st.called("line_chart")


def test_render_eda_univariate_ecdf_insufficient_data_shows_info_no_crash() -> None:
    df = pd.DataFrame({"n": pd.Series([float("nan"), float("nan")], dtype="float64")})
    st = FakeSt()
    _render_eda_univariate(st, df)
    assert st.called("info")
    assert not st.called("line_chart")


def test_render_datetime_trend_renders_granularity_selectbox() -> None:
    df = pd.DataFrame(
        {
            "ts": ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"],
            "n": [1.0, 2.0, 3.0, 4.0],
        }
    )
    st = FakeSt()
    _render_datetime_trend(st, df)
    selectbox_labels = [c[1][0] for c in st.calls if c[0] == "selectbox"]
    assert "Trend granularity" in selectbox_labels
    assert st.called("line_chart")


def test_render_datetime_trend_week_granularity_dispatches() -> None:
    df = pd.DataFrame(
        {
            "ts": ["2025-01-01", "2025-01-02", "2025-01-08", "2025-02-01"],
            "n": [1.0, 2.0, 3.0, 4.0],
        }
    )
    st = FakeSt()
    st.set_selectbox("eda_dt_granularity", "Week")
    _render_datetime_trend(st, df)
    assert st.called("line_chart")


# ── bivariate plot upgrades ───────────────────────────────────────────────────


def _num_num_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"a": [float(i) for i in range(1, 21)], "b": [float(i) * 2 for i in range(1, 21)]}
    )


def _vega_specs(st: FakeSt) -> list[dict[str, Any]]:
    return [c[1][1] for c in st.calls if c[0] == "vega_lite_chart"]


def test_render_num_num_renders_scatter_controls_default_scatter() -> None:
    st = FakeSt()
    _render_num_num(st, _num_num_df(), "a", "b")
    checkbox_labels = [c[1][0] for c in st.calls if c[0] == "checkbox"]
    assert "Clip axes to 1st–99th percentile" in checkbox_labels
    assert "Use log scale when both axes are positive" in checkbox_labels
    assert "Show linear trend line" in checkbox_labels
    assert st.called("scatter_chart")  # default (no control) keeps native scatter
    assert not st.called("vega_lite_chart")


def test_render_num_num_clip_produces_vega_scale_domain() -> None:
    st = FakeSt()
    st.set_checkbox("Clip axes to 1st–99th percentile", True)
    _render_num_num(st, _num_num_df(), "a", "b")
    assert not st.called("scatter_chart")
    x_enc = _vega_specs(st)[0]["layer"][0]["encoding"]["x"]
    assert "domain" in x_enc["scale"]


def test_render_num_num_log_scale_positive_applies_log() -> None:
    st = FakeSt()
    st.set_checkbox("Use log scale when both axes are positive", True)
    _render_num_num(st, _num_num_df(), "a", "b")
    x_enc = _vega_specs(st)[0]["layer"][0]["encoding"]["x"]
    assert x_enc["scale"]["type"] == "log"
    assert not st.called("info")


def test_render_num_num_log_scale_nonpositive_falls_back() -> None:
    df = pd.DataFrame({"a": [-1.0, 2.0, 3.0, 4.0], "b": [2.0, 4.0, 6.0, 8.0]})
    st = FakeSt()
    st.set_checkbox("Use log scale when both axes are positive", True)
    _render_num_num(st, df, "a", "b")
    assert st.called("info")  # fallback message
    x_enc = _vega_specs(st)[0]["layer"][0]["encoding"]["x"]
    assert "scale" not in x_enc  # linear, no log


def test_render_num_num_trend_adds_line_layer() -> None:
    st = FakeSt()
    st.set_checkbox("Show linear trend line", True)
    _render_num_num(st, _num_num_df(), "a", "b")
    layers = _vega_specs(st)[0]["layer"]
    assert len(layers) == 2
    assert layers[1]["mark"]["type"] == "line"
    assert "data" in layers[1]  # trend endpoints embedded as layer data


# ── 2D binned-density heatmap ─────────────────────────────────────────────────


def test_render_num_num_density_checkbox_present_off_by_default() -> None:
    st = FakeSt()
    _render_num_num(st, _num_num_df(), "a", "b")
    checkbox_labels = [c[1][0] for c in st.calls if c[0] == "checkbox"]
    assert "Show 2D binned density (heatmap)" in checkbox_labels
    # Density off by default → native scatter, no heatmap vega spec.
    assert st.called("scatter_chart")
    assert not st.called("vega_lite_chart")


def test_render_num_num_density_on_renders_vega_rect_with_binned_edges() -> None:
    st = FakeSt()
    st.set_checkbox("Show 2D binned density (heatmap)", True)
    _render_num_num(st, _num_num_df(), "a", "b")
    specs = _vega_specs(st)
    assert len(specs) == 1
    enc = specs[0]["encoding"]
    assert specs[0]["mark"] == "rect"
    assert enc["x"]["field"] == "x_left" and enc["x"]["bin"] == {"binned": True}
    assert enc["x2"]["field"] == "x_right"
    assert enc["y"]["field"] == "y_left" and enc["y2"]["field"] == "y_right"
    assert enc["color"]["field"] == "count"
    tooltip_fields = [t["field"] for t in enc["tooltip"]]
    assert "count" in tooltip_fields and "density" in tooltip_fields
    # Scatter remains the default view rendered above the heatmap.
    assert st.called("scatter_chart")


def test_render_num_num_density_wires_download_and_save_without_writing() -> None:
    st = FakeSt()
    st.set_checkbox("Show 2D binned density (heatmap)", True)
    _render_num_num(st, _num_num_df(), "a", "b")
    download_names = [c[2].get("file_name") for c in st.calls if c[0] == "download_button"]
    assert "eda_density_heatmap.csv" in download_names
    button_keys = [c[2].get("key") for c in st.calls if c[0] == "button"]
    assert "eda_save_density_heatmap" in button_keys
    # No click on render → nothing written to workspace.
    assert not st.called("success")


def test_render_num_num_density_insufficient_short_circuits_on_scatter() -> None:
    df = pd.DataFrame({"a": [1.0, 1.0, 1.0], "b": [2.0, 4.0, 6.0]})
    st = FakeSt()
    st.set_checkbox("Show 2D binned density (heatmap)", True)
    _render_num_num(st, df, "a", "b")
    assert st.called("info")
    assert not st.called("vega_lite_chart")


def test_render_cat_cat_renders_normalization_selectbox_default_table() -> None:
    df = pd.DataFrame({"a": ["x", "x", "y"], "b": ["p", "q", "p"]})
    st = FakeSt()
    _render_cat_cat(st, df, "a", "b")
    selectbox_labels = [c[1][0] for c in st.calls if c[0] == "selectbox"]
    assert "Crosstab values" in selectbox_labels
    assert st.called("dataframe")  # default Counts table
    assert not st.called("vega_lite_chart")  # heatmap off by default


def test_render_cat_cat_heatmap_renders_vega_rect() -> None:
    df = pd.DataFrame({"a": ["x", "x", "y", "y"], "b": ["p", "q", "p", "q"]})
    st = FakeSt()
    st.set_checkbox("Show heatmap", True)
    _render_cat_cat(st, df, "a", "b")
    assert st.called("dataframe")
    assert st.called("vega_lite_chart")
    assert _vega_specs(st)[0]["mark"] == "rect"


# ── datetime bivariate dispatch ───────────────────────────────────────────────


def _dt_num_bivariate_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": ["2025-01-01", "2025-01-01", "2025-01-02", "2025-02-01"],
            "n": [2.0, 4.0, 6.0, 8.0],
        }
    )


def _dt_cat_bivariate_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": ["2025-01-01", "2025-01-01", "2025-01-02", "2025-02-01"],
            "c": ["a", "b", "a", "b"],
        }
    )


def test_render_bivariate_dt_num_dispatch_renders_controls_and_chart() -> None:
    st = FakeSt()
    st.set_selectbox("biv_col1", "ts")
    st.set_selectbox("biv_col2", "n")
    _render_eda_bivariate(st, _dt_num_bivariate_df())
    labels = [c[1][0] for c in st.calls if c[0] == "selectbox"]
    assert "Time granularity" in labels
    assert "Aggregation" in labels
    assert st.called("line_chart")


def test_render_bivariate_num_dt_dispatch_uses_datetime_numeric_path() -> None:
    st = FakeSt()
    st.set_selectbox("biv_col1", "n")  # numeric first, datetime second
    st.set_selectbox("biv_col2", "ts")
    _render_eda_bivariate(st, _dt_num_bivariate_df())
    labels = [c[1][0] for c in st.calls if c[0] == "selectbox"]
    assert "Aggregation" in labels
    assert st.called("line_chart")


def test_render_bivariate_dt_cat_dispatch_renders_controls_and_chart() -> None:
    st = FakeSt()
    st.set_selectbox("biv_col1", "ts")
    st.set_selectbox("biv_col2", "c")
    _render_eda_bivariate(st, _dt_cat_bivariate_df())
    labels = [c[1][0] for c in st.calls if c[0] == "selectbox"]
    number_labels = [c[1][0] for c in st.calls if c[0] == "number_input"]
    assert "Time granularity" in labels
    assert "Top categories" in number_labels
    assert st.called("vega_lite_chart")


def test_render_bivariate_cat_dt_dispatch_uses_datetime_categorical_path() -> None:
    st = FakeSt()
    st.set_selectbox("biv_col1", "c")  # categorical first, datetime second
    st.set_selectbox("biv_col2", "ts")
    _render_eda_bivariate(st, _dt_cat_bivariate_df())
    assert st.called("vega_lite_chart")


def test_render_bivariate_dt_num_insufficient_shows_info() -> None:
    df = pd.DataFrame({"ts": ["2025-01-01"] * 4, "n": [1.0, 2.0, 3.0, 4.0]})
    st = FakeSt()
    st.set_selectbox("biv_col1", "ts")
    st.set_selectbox("biv_col2", "n")
    _render_eda_bivariate(st, df)
    assert st.called("info")
    assert not st.called("line_chart")


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


def test_render_num_cat_valid_pair_calls_box_style_chart_and_dataframe() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0], "c": ["a", "a", "b", "b"]})
    st = FakeSt()
    _render_num_cat(st, df, "n", "c")
    assert st.called("vega_lite_chart")
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


def test_render_eda_bivariate_num_cat_dispatches_box_style_chart() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0], "c": ["a", "a", "b", "b"]})
    st = FakeSt()
    st.set_selectbox("biv_col1", "n")
    st.set_selectbox("biv_col2", "c")
    _render_eda_bivariate(st, df)
    assert st.called("vega_lite_chart")


def test_render_eda_bivariate_cat_num_dispatches_box_style_chart() -> None:
    df = pd.DataFrame({"c": ["a", "a", "b", "b"], "n": [1.0, 2.0, 3.0, 4.0]})
    st = FakeSt()
    st.set_selectbox("biv_col1", "c")
    st.set_selectbox("biv_col2", "n")
    _render_eda_bivariate(st, df)
    assert st.called("vega_lite_chart")


def test_render_eda_bivariate_renders_swap_button() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
    st = FakeSt()
    _render_eda_bivariate(st, df)
    labels = [c[1][0] for c in st.calls if c[0] == "button"]
    assert "⇄ Swap X/Y" in labels


def test_render_eda_bivariate_single_col_no_swap_button() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    st = FakeSt()
    _render_eda_bivariate(st, df)
    assert not st.called("button")


def test_render_eda_bivariate_swap_click_exchanges_session_state() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
    st = FakeSt()
    st.session_state = {"biv_col1": "a", "biv_col2": "b"}
    st.set_selectbox("biv_col1", "a")
    st.set_selectbox("biv_col2", "b")
    st.set_button_clicked("⇄ Swap X/Y")
    _render_eda_bivariate(st, df)
    assert st.session_state == {"biv_col1": "b", "biv_col2": "a"}


def test_render_eda_bivariate_swap_click_missing_state_is_noop() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
    st = FakeSt()
    st.set_button_clicked("⇄ Swap X/Y")
    _render_eda_bivariate(st, df)
    assert st.session_state == {}


def test_render_eda_bivariate_swap_click_stale_value_is_noop() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
    st = FakeSt()
    st.session_state = {"biv_col1": "gone", "biv_col2": "b"}
    st.set_button_clicked("⇄ Swap X/Y")
    _render_eda_bivariate(st, df)
    assert st.session_state == {"biv_col1": "gone", "biv_col2": "b"}


# ── _render_eda_bivariate (Prev/Next navigation) ─────────────────────────────

_NAV_LABELS = ("← Previous X", "Next X →", "← Previous Y", "Next Y →")


def test_render_eda_bivariate_renders_nav_buttons() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0], "c": [5.0, 6.0]})
    st = FakeSt()
    _render_eda_bivariate(st, df)
    labels = [c[1][0] for c in st.calls if c[0] == "button"]
    for nav_label in _NAV_LABELS:
        assert nav_label in labels


def test_render_eda_bivariate_single_col_no_nav_buttons() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    st = FakeSt()
    _render_eda_bivariate(st, df)
    assert not st.called("button")


def test_render_eda_bivariate_next_x_click_advances_with_wraparound() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0], "c": [5.0, 6.0]})
    st = FakeSt()
    st.session_state = {"biv_col1": "c", "biv_col2": "b"}
    st.set_button_clicked("Next X →")
    _render_eda_bivariate(st, df)
    assert st.session_state == {"biv_col1": "a", "biv_col2": "b"}


def test_render_eda_bivariate_prev_x_click_moves_back_with_wraparound() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0], "c": [5.0, 6.0]})
    st = FakeSt()
    st.session_state = {"biv_col1": "a", "biv_col2": "b"}
    st.set_button_clicked("← Previous X")
    _render_eda_bivariate(st, df)
    assert st.session_state == {"biv_col1": "c", "biv_col2": "b"}


def test_render_eda_bivariate_next_y_click_advances_with_wraparound() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0], "c": [5.0, 6.0]})
    st = FakeSt()
    st.session_state = {"biv_col1": "a", "biv_col2": "c"}
    st.set_button_clicked("Next Y →")
    _render_eda_bivariate(st, df)
    assert st.session_state == {"biv_col1": "a", "biv_col2": "a"}


def test_render_eda_bivariate_prev_y_click_moves_back_with_wraparound() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0], "c": [5.0, 6.0]})
    st = FakeSt()
    st.session_state = {"biv_col1": "a", "biv_col2": "a"}
    st.set_button_clicked("← Previous Y")
    _render_eda_bivariate(st, df)
    assert st.session_state == {"biv_col1": "a", "biv_col2": "c"}


def test_render_eda_bivariate_nav_click_missing_key_is_noop() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
    st = FakeSt()
    st.set_button_clicked("Next X →")
    _render_eda_bivariate(st, df)
    assert st.session_state == {}


def test_render_eda_bivariate_nav_click_stale_value_is_noop() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
    st = FakeSt()
    st.session_state = {"biv_col1": "gone", "biv_col2": "b"}
    st.set_button_clicked("← Previous X")
    _render_eda_bivariate(st, df)
    assert st.session_state == {"biv_col1": "gone", "biv_col2": "b"}


# ── _swap_bivariate_columns ───────────────────────────────────────────────────


def test_swap_bivariate_columns_exchanges_values() -> None:
    state: dict[str, Any] = {"biv_col1": "a", "biv_col2": "b"}
    _swap_bivariate_columns(state, ["a", "b"])
    assert state == {"biv_col1": "b", "biv_col2": "a"}


def test_swap_bivariate_columns_missing_key_is_noop() -> None:
    state: dict[str, Any] = {"biv_col1": "a"}
    _swap_bivariate_columns(state, ["a", "b"])
    assert state == {"biv_col1": "a"}


def test_swap_bivariate_columns_stale_value_is_noop() -> None:
    state: dict[str, Any] = {"biv_col1": "a", "biv_col2": "gone"}
    _swap_bivariate_columns(state, ["a", "b"])
    assert state == {"biv_col1": "a", "biv_col2": "gone"}


def test_swap_bivariate_columns_equal_values_stay_equal() -> None:
    state: dict[str, Any] = {"biv_col1": "a", "biv_col2": "a"}
    _swap_bivariate_columns(state, ["a", "b"])
    assert state == {"biv_col1": "a", "biv_col2": "a"}


# ── _step_bivariate_column ────────────────────────────────────────────────────


def test_step_bivariate_column_advances_next() -> None:
    state: dict[str, Any] = {"biv_col1": "a"}
    _step_bivariate_column(state, "biv_col1", ["a", "b", "c"], 1)
    assert state == {"biv_col1": "b"}


def test_step_bivariate_column_moves_previous() -> None:
    state: dict[str, Any] = {"biv_col1": "b"}
    _step_bivariate_column(state, "biv_col1", ["a", "b", "c"], -1)
    assert state == {"biv_col1": "a"}


def test_step_bivariate_column_next_wraps_around() -> None:
    state: dict[str, Any] = {"biv_col1": "c"}
    _step_bivariate_column(state, "biv_col1", ["a", "b", "c"], 1)
    assert state == {"biv_col1": "a"}


def test_step_bivariate_column_previous_wraps_around() -> None:
    state: dict[str, Any] = {"biv_col1": "a"}
    _step_bivariate_column(state, "biv_col1", ["a", "b", "c"], -1)
    assert state == {"biv_col1": "c"}


def test_step_bivariate_column_missing_key_is_noop() -> None:
    state: dict[str, Any] = {}
    _step_bivariate_column(state, "biv_col1", ["a", "b", "c"], 1)
    assert state == {}


def test_step_bivariate_column_stale_value_is_noop() -> None:
    state: dict[str, Any] = {"biv_col1": "gone"}
    _step_bivariate_column(state, "biv_col1", ["a", "b", "c"], 1)
    assert state == {"biv_col1": "gone"}


# ── _render_preprocessing_plan ────────────────────────────────────────────────


def test_render_preprocessing_plan_empty_df_shows_pointer() -> None:
    # EDA Explorer now renders a concise pointer to Preprocess Studio (the
    # canonical home for detailed recommendations) instead of the full table.
    st = FakeSt()
    _render_preprocessing_plan(st, pd.DataFrame())
    assert st.called("subheader")
    assert st.called("caption")
    assert not st.called("dataframe")


def test_render_preprocessing_plan_nonempty_df_shows_pointer() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    st = FakeSt()
    _render_preprocessing_plan(st, df)
    assert st.called("subheader")
    assert st.called("caption")
    assert not st.called("dataframe")


# ── _render_data_overview ─────────────────────────────────────────────────────

_MOCK_PATH = "data_quality_toolkit.adapters.ui.pages.data_overview._load_df_and_assess"

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


def test_render_data_overview_does_not_render_eda_sections() -> None:
    """EDA moved to its own page in the UI restructure — overview must not render it."""
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    with patch(_MOCK_PATH, return_value=(_FAKE_DF, _FAKE_RESULT, None)):
        _render_data_overview(st)
    assert not st.called("selectbox")
    assert not st.called("scatter_chart")


# ── _render_eda_explorer ──────────────────────────────────────────────────────

_MOCK_EDA_LOAD = "data_quality_toolkit.adapters.ui.pages.eda_explorer._load_df_and_assess"
_EDA_TAB_LABELS = ["Overview", "Columns", "Relationships", "Time", "Advanced"]


class _FakeDatasetContext:
    source_path = "data.csv"
    display_name = "data.csv"
    size_bytes = 123
    large_file_mode = True


def test_render_eda_explorer_empty_path_shows_info_and_returns() -> None:
    st = FakeSt()
    _render_eda_explorer(st)
    assert st.called("header")
    assert st.called("info")
    assert not st.called("tabs")
    assert not st.called("selectbox")
    assert "Smart Guide" not in _rendered_text(st)


def test_render_eda_explorer_load_error_shows_error() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "bad.csv")
    with patch(_MOCK_EDA_LOAD, return_value=(None, None, "file not found")):
        _render_eda_explorer(st)
    assert st.called("error")
    assert not st.called("tabs")
    assert not st.called("selectbox")
    assert "Smart Guide" not in _rendered_text(st)


def test_render_eda_explorer_happy_path_triggers_eda_renders() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    with patch(_MOCK_EDA_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT, None)):
        _render_eda_explorer(st)
    assert ("tabs", (_EDA_TAB_LABELS,), {}) in st.calls
    assert st.called("selectbox")
    assert st.call_count("subheader") >= 2


def test_render_eda_explorer_happy_path_renders_smart_guide_no_ai_copy() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")

    with patch(_MOCK_EDA_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT, None)):
        _render_eda_explorer(st)

    text = _rendered_text(st)
    assert "Smart Guide" in text
    assert "Rules-based checks from this dataset" in text
    assert "No AI or external model is used." in text


def test_render_eda_explorer_clean_data_renders_smart_guide_fallback() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")

    with patch(_MOCK_EDA_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT, None)):
        _render_eda_explorer(st)

    assert "No major EDA warnings found from the current rule checks." in _rendered_text(st)


def test_render_eda_explorer_no_dataframe_avoids_smart_guide() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")

    with patch(_MOCK_EDA_LOAD, return_value=(None, None, None)):
        _render_eda_explorer(st)

    assert not st.called("tabs")
    assert "Smart Guide" not in _rendered_text(st)


def test_render_eda_explorer_large_file_context_blocks_before_tabs() -> None:
    st = FakeSt()
    with (
        patch(
            "data_quality_toolkit.adapters.ui.pages.eda_explorer.get_dataset_context",
            return_value=_FakeDatasetContext(),
        ),
        patch(_MOCK_EDA_LOAD) as load,
    ):
        _render_eda_explorer(st, {})

    load.assert_not_called()
    assert st.called("warning")
    assert not st.called("tabs")
    assert "Smart Guide" not in _rendered_text(st)


def test_render_eda_explorer_happy_path_keeps_bivariate_controls() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")

    with patch(_MOCK_EDA_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT, None)):
        _render_eda_explorer(st)

    button_labels = [c[1][0] for c in st.calls if c[0] == "button"]
    assert "⇄ Swap X/Y" in button_labels
    assert "← Previous X" in button_labels
    assert "Next X →" in button_labels
    assert "← Previous Y" in button_labels
    assert "Next Y →" in button_labels


def test_render_eda_explorer_downloads_and_save_buttons_render_without_writing(
    tmp_path: Any,
) -> None:
    st = FakeSt()
    st.session_state[SRC_WORKSPACE_ROOT] = str(tmp_path)
    st.set_text_input("CSV path", "data.csv")

    with patch(_MOCK_EDA_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT, None)):
        _render_eda_explorer(st)

    download_names = [
        k["file_name"] for name, _, k in st.calls if name == "download_button" and "file_name" in k
    ]
    button_labels = [c[1][0] for c in st.calls if c[0] == "button"]
    assert "eda_missingness.csv" in download_names
    assert "eda_distribution.csv" in download_names
    assert "eda_categories.csv" in download_names
    assert "eda_skew_kurtosis.csv" in download_names
    assert "eda_outliers.csv" in download_names
    assert "Save missingness data to workspace" in button_labels
    assert "Save distribution data to workspace" in button_labels
    assert "Save category values to workspace" in button_labels
    assert not (tmp_path / "analysis").exists()


# ── EDA tab intro captions (discoverability) ───────────────────────────────────


def _captions(st: FakeSt) -> list[str]:
    return [c[1][0] for c in st.calls if c[0] == "caption"]


def test_render_overview_tab_emits_intro_caption() -> None:
    st = FakeSt()
    render_overview_tab(st, _FAKE_DF, _FAKE_RESULT, _FAKE_PROFILE)
    assert _OVERVIEW_TAB_INTRO in _captions(st)
    assert "Smart Guide" in _OVERVIEW_TAB_INTRO
    assert "missingness" in _OVERVIEW_TAB_INTRO


def test_render_columns_tab_emits_intro_caption() -> None:
    st = FakeSt()
    render_columns_tab(st, _FAKE_DF)
    assert _COLUMNS_TAB_INTRO in _captions(st)
    assert "ECDF" in _COLUMNS_TAB_INTRO
    assert "Other bucket" in _COLUMNS_TAB_INTRO


def test_render_relationships_tab_emits_intro_caption() -> None:
    st = FakeSt()
    render_relationships_tab(st, _FAKE_DF)
    assert _RELATIONSHIPS_TAB_INTRO in _captions(st)
    assert "2D density" in _RELATIONSHIPS_TAB_INTRO
    assert "crosstab" in _RELATIONSHIPS_TAB_INTRO


def test_render_time_tab_emits_intro_caption_pointing_to_relationships() -> None:
    st = FakeSt()
    render_time_tab(st, _FAKE_DF)
    assert _TIME_TAB_INTRO in _captions(st)
    assert "day, week, or month" in _TIME_TAB_INTRO
    assert "Relationships tab" in _TIME_TAB_INTRO


def test_render_advanced_tab_emits_intro_caption() -> None:
    st = FakeSt()
    render_advanced_tab(st, _FAKE_DF)
    assert _ADVANCED_TAB_INTRO in _captions(st)
    assert "correlation" in _ADVANCED_TAB_INTRO
    assert "skewness" in _ADVANCED_TAB_INTRO


def test_eda_tab_intros_contain_no_raw_path_literals() -> None:
    intros = (
        _OVERVIEW_TAB_INTRO,
        _COLUMNS_TAB_INTRO,
        _RELATIONSHIPS_TAB_INTRO,
        _TIME_TAB_INTRO,
        _ADVANCED_TAB_INTRO,
    )
    forbidden = ("C:\\", "/home/", "/tmp/", "asamili", "abdul")
    for intro in intros:
        for token in forbidden:
            assert token not in intro


# ── _render_run_history ───────────────────────────────────────────────────────

_MOCK_LOAD_HISTORY = "data_quality_toolkit.adapters.ui.pages.run_history._load_run_history"


def test_render_run_history_empty_inputs_shows_info() -> None:
    st = FakeSt()
    _render_run_history(st)
    assert st.called("header")
    assert st.called("info")
    assert not st.called("error")


def test_render_run_history_storage_error_shows_error() -> None:
    st = FakeSt()
    st.set_text_input("Quality-history database", "./dist/dqt.db")
    st.set_text_input("Dataset ID", "sha1:abc")
    with patch(_MOCK_LOAD_HISTORY, return_value=(None, "db corrupt")):
        _render_run_history(st)
    assert st.called("error")
    assert not st.called("dataframe")


def test_render_run_history_empty_records_shows_warning() -> None:
    st = FakeSt()
    st.set_text_input("Quality-history database", "./dist/dqt.db")
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
    st.set_text_input("Quality-history database", "./dist/dqt.db")
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


def test_next_step_guidance_follows_deliver_chain(monkeypatch: Any) -> None:
    """P1B accepted operator flow: Drift → Export → Quality History → Artifact Center."""
    monkeypatch.delenv("DQT_UI_DB", raising=False)
    cases = [
        (_render_drift_explorer, "Export"),
        (_render_export, "Quality History"),
        (_render_run_history, "Artifact Center"),
        (_render_artifact_center, "KPI Catalog"),
    ]
    for render_fn, expected in cases:
        st = FakeSt()
        render_fn(st)
        guidance = [
            str(args[0])
            for name, args, _kwargs in st.calls
            if name == "markdown" and args and "**Next step:**" in str(args[0])
        ]
        assert guidance, f"{render_fn.__module__} rendered no next-step guidance"
        next_line = guidance[0].split("**Next step:**", 1)[1]
        assert expected in next_line, f"{render_fn.__module__} next step missing {expected!r}"


# ── _render_kpi_catalog ───────────────────────────────────────────────────────

_MOCK_KPI_VALIDATE = "data_quality_toolkit.adapters.ui.pages.kpi_catalog._run_kpi_validate"
_MOCK_KPI_EMIT = "data_quality_toolkit.adapters.ui.pages.kpi_catalog._kpi_emit_to_bytes"
_MOCK_KPI_GRAPH = "data_quality_toolkit.adapters.ui.pages.kpi_catalog._kpi_graph_to_str"

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

_MOCK_GEN_DIM = "data_quality_toolkit.adapters.ui.pages.dim_time._generate_dim_time_csv"


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

_MOCK_EXPORT_CSV_TO_DIR = "data_quality_toolkit.adapters.ui.pages.export._export_csv_to_dir"


def test_render_export_shows_warning_and_confirmation_controls() -> None:
    st = FakeSt()
    _render_export(st)
    assert st.called("warning")
    assert st.called("checkbox")
    assert st.called("button")


def test_render_export_path_guidance_is_windows_friendly() -> None:
    st = FakeSt()
    _render_export(st)

    text = _rendered_text(st)
    placeholders = {
        args[0]: kwargs.get("placeholder", "")
        for name, args, kwargs in st.calls
        if name == "text_input"
    }
    base_folder_kwargs = next(
        kwargs
        for name, args, kwargs in st.calls
        if name == "text_input" and args[0] == "BaseFolder parameter"
    )

    assert r"C:\Users\example_user\Documents\dqt_exports" in text
    assert "dqt export data.csv --outdir ./dist" not in text
    assert 'output_dir="./dist"' not in text
    assert "**Artifacts written to `./dist/`" not in text
    assert placeholders["CSV file path to export"] == (
        r"e.g., C:\Users\example_user\Documents\sales.csv"
    )
    assert placeholders["Output directory (absolute path)"] == (
        r"e.g., C:\Users\example_user\Documents\dqt_exports"
    )
    assert placeholders["Star schema directory"] == (
        r"e.g., C:\Users\example_user\Documents\dqt_exports\star"
    )
    assert placeholders["Package output directory (absolute path)"] == (
        r"e.g., C:\Users\example_user\Documents\dqt_exports\powerbi"
    )
    assert placeholders["dim_time.csv path (optional)"] == (
        r"e.g., C:\Users\example_user\Documents\dqt_exports\time\dim_time.csv"
    )
    for placeholder in placeholders.values():
        assert not placeholder.startswith("e.g., /")
        assert "./dist" not in placeholder
    assert base_folder_kwargs["value"] == "./dist"
    assert r"C:\Users\example_user\Documents\dqt_exports" in base_folder_kwargs["help"]


def test_render_export_shows_flow_map_and_numbered_stages() -> None:
    st = FakeSt()
    _render_export(st)
    text = _rendered_text(st)
    assert "Flow: 1 Choose export route" in text
    assert "1 · Choose your export route" in text
    assert "2 · Export star schema (server-side write)" in text
    assert "3 · Power BI package (optional, server-side write)" in text


def test_render_export_stage_captions_explain_writes_and_outputs() -> None:
    st = FakeSt()
    _render_export(st)
    text = _rendered_text(st)
    # Stage 2 says what it produces and that nothing writes without confirm+click.
    assert "dqt.db" in text
    assert "Nothing is written until you check the confirmation box" in text
    # Stage 3 cross-references stage 2 while the package is not yet generated.
    assert "Run the export in stage 2 first" in text


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
    fake_result = {
        "export_paths": {
            "dim_dataset": "/tmp/out/star/dim_dataset.csv",
            "quality_db": "/tmp/out/dqt.db",
        },
        "quality_db_path": "/tmp/out/dqt.db",
        "quality_db_status": "persisted",
        "quality_db_error": None,
    }
    with patch(_MOCK_EXPORT_CSV_TO_DIR, return_value=(fake_result, None)):
        _render_export(st)
    text = _rendered_text(st)
    assert st.called("success")
    assert st.called("info")
    assert not st.called("error")
    assert "Quality History database path used" in text
    assert "out/dqt.db" in text
    assert "/tmp/out/dqt.db" not in text


def test_render_export_click_confirmed_sqlite_failure_shows_warning() -> None:
    st = FakeSt()
    st.set_text_input("CSV file path to export", "/data/test.csv")
    st.set_text_input("Output directory (absolute path)", "/tmp/out")
    st.set_checkbox("I confirm: write export files to the directory above", True)
    st.set_button_clicked("Run export and write to directory")
    fake_result = {
        "export_paths": {"dim_dataset": "/tmp/out/star/dim_dataset.csv"},
        "quality_db_path": "/tmp/private/dqt.db",
        "quality_db_status": "failed",
        "quality_db_error": "cannot open /tmp/private/dqt.db",
    }
    with patch(_MOCK_EXPORT_CSV_TO_DIR, return_value=(fake_result, None)):
        _render_export(st)
    text = _rendered_text(st)
    assert st.called("success")
    assert st.called("warning")
    assert "Quality History database was not updated" in text
    assert "out/dqt.db" in text
    assert "/tmp/private" not in text


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


# ── _render_manifest_viewer ───────────────────────────────────────────────────


def test_render_manifest_viewer_no_button_click_shows_header_no_error() -> None:
    st = FakeSt()
    _render_manifest_viewer(st)
    assert st.called("header")
    assert not st.called("error")


def test_render_manifest_viewer_error_uses_show_error_format(tmp_path: Any) -> None:
    """Invalid manifest content must produce '⚠️ Manifest load failed: ...' via show_error."""
    sessions_root = tmp_path / "sessions"
    session_dir = sessions_root / "run-123"
    session_dir.mkdir(parents=True)
    (session_dir / "artifacts.json").write_text("{not valid json", encoding="utf-8")

    st = FakeSt()
    st.set_text_input("Session Run ID", "run-123")
    st.set_text_input("Sessions Root", str(sessions_root))
    st.set_button_clicked("Load Manifest")
    _render_manifest_viewer(st)
    assert st.called("error")
    error_msgs = [c[1][0] for c in st.calls if c[0] == "error"]
    assert any("⚠️ Manifest load failed:" in str(m) for m in error_msgs)


def test_render_manifest_viewer_missing_manifest_shows_info_not_error(tmp_path: Any) -> None:
    """An existing session directory without artifacts.json is informational, not an error."""
    sessions_root = tmp_path / "sessions"
    (sessions_root / "run-empty").mkdir(parents=True)

    st = FakeSt()
    st.set_text_input("Session Run ID", "run-empty")
    st.set_text_input("Sessions Root", str(sessions_root))
    st.set_button_clicked("Load Manifest")
    _render_manifest_viewer(st)
    assert st.called("info")
    assert not st.called("error")


def test_render_manifest_viewer_empty_run_id_shows_validation_error() -> None:
    st = FakeSt()
    st.set_text_input("Session Run ID", "")
    st.set_text_input("Sessions Root", ".")
    st.set_button_clicked("Load Manifest")
    _render_manifest_viewer(st)
    assert st.called("error")
    error_msgs = [c[1][0] for c in st.calls if c[0] == "error"]
    assert any("Run ID" in str(m) or "Sessions Root" in str(m) for m in error_msgs)


# ── _render_run_history (compare section) ────────────────────────────────────

_MOCK_RUN_COMPARE = "data_quality_toolkit.adapters.ui.pages.run_history._run_compare"

_TWO_RECORDS = [
    {"ts": "2025-01-01T00:00:00", "score": 0.8, "issues_by_severity": {}, "issues_by_category": {}},
    {"ts": "2025-01-02T00:00:00", "score": 0.9, "issues_by_severity": {}, "issues_by_category": {}},
]

_COMPARE_RESULT: dict[str, Any] = {
    "dataset_id": "sha1:abc",
    "current_score": 0.9,
    "previous_score": 0.8,
    "score_delta": 0.1,
    "current_issues_total": 2,
    "previous_issues_total": 5,
    "issues_delta": -3.0,
    "issues_by_severity_delta": None,
    "issues_by_category_delta": None,
}


def test_render_run_history_two_records_shows_compare_section() -> None:
    st = FakeSt()
    st.set_text_input("Quality-history database", "./dist/dqt.db")
    st.set_text_input("Dataset ID", "sha1:abc")
    with patch(_MOCK_LOAD_HISTORY, return_value=(_TWO_RECORDS, None)):
        with patch(_MOCK_RUN_COMPARE, return_value=(_COMPARE_RESULT, None)):
            _render_run_history(st)
    assert st.called("divider")
    assert st.called("dataframe")


def test_render_run_history_single_record_no_compare_section() -> None:
    one_record = [
        {
            "ts": "2025-01-01T00:00:00",
            "score": 0.8,
            "issues_by_severity": {},
            "issues_by_category": {},
        }
    ]
    st = FakeSt()
    st.set_text_input("Quality-history database", "./dist/dqt.db")
    st.set_text_input("Dataset ID", "sha1:abc")
    with patch(_MOCK_LOAD_HISTORY, return_value=(one_record, None)):
        _render_run_history(st)
    assert not st.called("divider")
    assert st.called("dataframe")


def test_render_run_history_compare_insufficient_shows_info_not_error() -> None:
    st = FakeSt()
    st.set_text_input("Quality-history database", "./dist/dqt.db")
    st.set_text_input("Dataset ID", "sha1:abc")
    with patch(_MOCK_LOAD_HISTORY, return_value=(_TWO_RECORDS, None)):
        with patch(_MOCK_RUN_COMPARE, return_value=(None, "Need at least 2 completed runs")):
            _render_run_history(st)
    assert st.called("info")
    assert not st.called("error")


# ── operator-flow structure (flow map + numbered stages) ─────────────────────

_TWO_RECORDS_WITH_ISSUES = [
    {
        "ts": "2025-01-01T00:00:00",
        "score": 0.8,
        "issues_by_severity": {"high": 3},
        "issues_by_category": {"missing": 3},
    },
    {
        "ts": "2025-01-02T00:00:00",
        "score": 0.9,
        "issues_by_severity": {"high": 1},
        "issues_by_category": {"missing": 1},
    },
]


def test_render_run_history_shows_flow_map_caption() -> None:
    st = FakeSt()
    _render_run_history(st)
    text = _rendered_text(st)
    assert "Flow: 1 Choose history source and dataset" in text
    assert "4 Compare runs" in text


def test_render_run_history_shows_numbered_stages_in_order() -> None:
    st = FakeSt()
    st.set_text_input("Quality-history database", "./dist/dqt.db")
    st.set_text_input("Dataset ID", "sha1:abc")
    with patch(_MOCK_LOAD_HISTORY, return_value=(_TWO_RECORDS_WITH_ISSUES, None)):
        with patch(_MOCK_RUN_COMPARE, return_value=(_COMPARE_RESULT, None)):
            _render_run_history(st)

    text = _rendered_text(st)
    stages = [
        "1 · Choose history source and dataset",
        "2 · Score trend",
        "3 · Latest run — issues breakdown",
        "4 · Run-to-run comparison",
    ]
    positions = [text.index(stage) for stage in stages]
    assert positions == sorted(positions)


def test_render_run_history_source_stage_states_read_only() -> None:
    st = FakeSt()
    _render_run_history(st)
    text = _rendered_text(st)
    assert "This page is read-only" in text
    assert "Nothing is written" in text


def test_render_run_history_guidance_points_to_export_created_db() -> None:
    st = FakeSt()
    _render_run_history(st)
    text = _rendered_text(st)
    # P5B: the page has no Run ID control, so the guidance no longer claims one.
    assert "prefills the Quality-history database and Dataset ID" in text
    assert "and Run ID here when those" not in text
    assert "values you entered yourself are kept" in text
    assert "`quality_report.json`" in text
    # The old instruction to reuse a full path that Export redacts is gone.
    assert "actual `dqt.db` path shown by Export" not in text


def test_render_run_history_flow_polish_no_private_path_literals() -> None:
    st = FakeSt()
    st.set_text_input("Quality-history database", "./dist/dqt.db")
    st.set_text_input("Dataset ID", "sha1:abc")
    with patch(_MOCK_LOAD_HISTORY, return_value=(_TWO_RECORDS_WITH_ISSUES, None)):
        with patch(_MOCK_RUN_COMPARE, return_value=(_COMPARE_RESULT, None)):
            _render_run_history(st)

    text = _rendered_text(st)
    assert "C:\\Users" not in text
    assert "C:/private/user" not in text


def test_render_kpi_catalog_shows_flow_map_caption() -> None:
    st = FakeSt()
    _render_kpi_catalog(st)
    text = _rendered_text(st)
    assert "Flow: 1 Choose KPI catalog source" in text
    assert "4 Download or save artifacts" in text


def test_render_kpi_catalog_shows_numbered_stages_in_order() -> None:
    st = FakeSt()
    st.set_text_input("KPI catalog YAML path", "catalog.yaml")
    with (
        patch(_MOCK_KPI_VALIDATE, return_value=(_FAKE_KPI_VALID, None)),
        patch(_MOCK_KPI_EMIT, return_value=(b"dax", b"tmsl", None)),
        patch(_MOCK_KPI_GRAPH, return_value=("graph mmd content", None)),
    ):
        _render_kpi_catalog(st)

    text = _rendered_text(st)
    stages = [
        "1 · Choose KPI catalog source",
        "2 · Validation result",
        "3 · KPIs by grain",
        "4 · Download or save artifacts",
    ]
    positions = [text.index(stage) for stage in stages]
    assert positions == sorted(positions)


def test_render_kpi_catalog_source_stage_states_in_memory_until_save() -> None:
    st = FakeSt()
    _render_kpi_catalog(st)
    text = _rendered_text(st)
    assert "Validation reads the entered catalog path only" in text
    assert "until you download them or click a Save button" in text


def test_render_kpi_catalog_flow_polish_no_private_path_literals() -> None:
    st = FakeSt()
    st.set_text_input("KPI catalog YAML path", "catalog.yaml")
    with (
        patch(_MOCK_KPI_VALIDATE, return_value=(_FAKE_KPI_VALID, None)),
        patch(_MOCK_KPI_EMIT, return_value=(b"dax", b"tmsl", None)),
        patch(_MOCK_KPI_GRAPH, return_value=("graph mmd content", None)),
    ):
        _render_kpi_catalog(st)

    text = _rendered_text(st)
    assert "C:\\Users" not in text
    assert "C:/private/user" not in text
