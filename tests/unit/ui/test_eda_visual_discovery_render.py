"""Render contracts for the P2 EDA visual-discovery expansion.

Exercises the Streamlit-facing section renderers through a local recorder
double: the new visuals draw, disclose sampling/truncation, carry their
exploratory caveats, degrade to an explanation instead of crashing, and never
trigger a second dataset load, a second assessment, or a raw path/version-label
leak. Existing EDA sections must still render alongside them.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui import eda_sections
from data_quality_toolkit.adapters.ui.eda import (
    CATEGORICAL_ASSOC_MAX_ROWS,
    PARETO_MIN_CATEGORY_COUNT,
    QQ_MAX_POINTS,
)
from data_quality_toolkit.adapters.ui.eda_sections import (
    _BIV_CROSSTAB_STACKED,
    _EDA_CORR_COLUMNS,
    _EDA_HIST_LOG_SCALE,
    _EDA_SHOW_CAT_ASSOC,
    _EDA_SHOW_CORR_PAIRS,
    _EDA_SHOW_MISSING_STRUCTURE,
    _EDA_SHOW_PARETO,
    _EDA_SHOW_QQ,
    _SAVE_CATEGORICAL_ASSOC_BTN,
    _SAVE_CORRELATION_PAIRS_BTN,
    _SAVE_MISSING_ASSOC_BTN,
    _SAVE_PARETO_BTN,
    _render_cat_cat,
    _render_categorical_association,
    _render_correlation_matrix,
    _render_correlation_pairs,
    _render_eda_univariate,
    _render_structural_missingness,
    _render_visual_guide,
    render_advanced_tab,
    render_columns_tab,
    render_overview_tab,
    render_relationships_tab,
    render_time_tab,
)

_EDA_MODULE = "data_quality_toolkit.adapters.ui.eda"
_LOADER_MODULE = "data_quality_toolkit.adapters.ui.services.managed_frame_loader"


class FakeSt:
    """Streamlit recorder with keyed widgets, sufficient for the EDA renderers."""

    def __init__(self) -> None:
        self.session_state: dict[str, Any] = {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.checkbox_values: dict[str, bool] = {}
        self.selectbox_values: dict[str, Any] = {}
        self.multiselect_values: dict[str, list[Any]] = {}
        self.clicks: dict[str, bool] = {}

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
        return [self for _ in range(n)]

    def expander(self, label: str, **k: Any) -> FakeSt:
        self._rec("expander", label, **k)
        return self

    def checkbox(self, label: str, **k: Any) -> bool:
        self._rec("checkbox", label, **k)
        key = str(k.get("key") or label)
        return self.checkbox_values.get(key, bool(k.get("value", False)))

    def selectbox(self, label: str, options: Sequence[Any] = (), **k: Any) -> Any:
        values = list(options)
        self._rec("selectbox", label, values, **k)
        key = str(k.get("key") or label)
        return self.selectbox_values.get(key, values[0] if values else None)

    def multiselect(self, label: str, options: Sequence[Any] = (), **k: Any) -> list[Any]:
        values = list(options)
        self._rec("multiselect", label, values, **k)
        key = str(k.get("key") or label)
        return self.multiselect_values.get(key, list(k.get("default") or []))

    def number_input(self, label: str, **k: Any) -> Any:
        self._rec("number_input", label, **k)
        return k.get("value", k.get("min_value", 1))

    def button(self, label: str, **k: Any) -> bool:
        self._rec("button", label, **k)
        clicked = self.clicks.get(str(k.get("key")), False)
        on_click = k.get("on_click")
        if clicked and callable(on_click):
            on_click(*k.get("args", ()), **k.get("kwargs", {}))
        return clicked

    def download_button(self, *a: Any, **k: Any) -> None:
        self._rec("download_button", *a, **k)

    # -- assertions helpers ---------------------------------------------------

    def named(self, name: str) -> list[tuple[Any, ...]]:
        return [args for call, args, _ in self.calls if call == name]

    def called(self, name: str) -> bool:
        return bool(self.named(name))

    def text(self) -> str:
        return " ".join(
            str(arg)
            for _name, args, kwargs in self.calls
            for arg in (*args, *kwargs.values())
            if isinstance(arg, str)
        )

    def payload(self) -> str:
        """Every string that reached a chart/table call, including frame contents."""
        chunks: list[str] = []
        for _name, args, kwargs in self.calls:
            for value in (*args, *kwargs.values()):
                if isinstance(value, pd.DataFrame):
                    chunks.append(value.to_csv(index=True))
                elif isinstance(value, str | dict | list):
                    chunks.append(str(value))
        return " ".join(chunks)

    def button_keys(self) -> list[str]:
        return [k["key"] for name, _a, k in self.calls if name == "button" and "key" in k]

    def download_names(self) -> list[str]:
        return [
            k["file_name"]
            for name, _a, k in self.calls
            if name == "download_button" and "file_name" in k
        ]

    def subheaders(self) -> list[str]:
        return [str(args[0]) for args in self.named("subheader") if args]


def _discovery_df(rows: int = 60) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "amount": [float(i) for i in range(1, rows + 1)],
            "score": [float((i * 7) % 23) + 1.0 for i in range(rows)],
            "partial": [None if i % 3 == 0 else float(i) for i in range(rows)],
            "also_partial": [None if i % 3 == 0 else float(i * 2) for i in range(rows)],
            "segment": ["retail" if i % 2 else "wholesale" for i in range(rows)],
            "region": ["north" if i % 3 else "south" for i in range(rows)],
            "ts": pd.date_range("2025-01-01", periods=rows, freq="D").astype(str),
        }
    )


# ── Q-Q visual diagnostic ────────────────────────────────────────────────────


def test_qq_diagnostic_is_off_by_default_and_renders_when_enabled() -> None:
    off = FakeSt()
    _render_eda_univariate(off, _discovery_df())
    assert "not a normality test" not in off.text()

    on = FakeSt()
    on.checkbox_values[_EDA_SHOW_QQ] = True
    _render_eda_univariate(on, _discovery_df())

    assert "Q-Q plot: amount" in on.text()
    assert len(on.named("vega_lite_chart")) > len(off.named("vega_lite_chart"))


def test_qq_diagnostic_renders_its_visual_only_caveat() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_QQ] = True

    _render_eda_univariate(st, _discovery_df())

    text = st.text()
    assert "visual diagnostic" in text
    assert "not a normality test" in text
    assert "Statistics Lab" in text


def test_qq_diagnostic_discloses_rank_sampling_on_large_columns() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_QQ] = True
    df = pd.DataFrame({"amount": [float(i) for i in range(QQ_MAX_POINTS * 3)]})

    _render_eda_univariate(st, df)

    assert "evenly spaced by rank" in st.text()


def test_qq_diagnostic_unavailable_state_explains_and_does_not_crash() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_QQ] = True
    df = pd.DataFrame({"amount": [5.0] * 12})

    _render_eda_univariate(st, df)

    text = st.text()
    assert "Q-Q needs at least" in text
    assert "Statistics Lab" in text


def test_histogram_log_scale_option_renders_and_guards_non_positive_values() -> None:
    positive = FakeSt()
    positive.checkbox_values[_EDA_HIST_LOG_SCALE] = True
    _render_eda_univariate(positive, _discovery_df())
    assert "Log-scaled value axis" in positive.text()

    with_zero = FakeSt()
    with_zero.checkbox_values[_EDA_HIST_LOG_SCALE] = True
    _render_eda_univariate(with_zero, pd.DataFrame({"amount": [0.0, 1.0, 2.0, 3.0, 4.0]}))
    assert "Log scale needs strictly positive values" in with_zero.text()


# ── Pareto ───────────────────────────────────────────────────────────────────


def _pareto_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"segment": ["a"] * 20 + ["b"] * 12 + ["c"] * 7 + ["rare"] * 2 + ["rarer"] * 1}
    )


def test_pareto_is_off_by_default_and_renders_bars_with_cumulative_line() -> None:
    off = FakeSt()
    _render_eda_univariate(off, _pareto_df())
    assert "eda_pareto.csv" not in off.download_names()

    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_PARETO] = True
    _render_eda_univariate(st, _pareto_df())

    assert "Pareto details" in st.text()
    specs = [args[1] for args in st.named("vega_lite_chart") if len(args) > 1]
    layered = [spec for spec in specs if isinstance(spec, dict) and "layer" in spec]
    marks = [layer["mark"] for spec in layered for layer in spec["layer"]]
    assert "bar" in marks
    assert any(isinstance(mark, dict) and mark.get("type") == "line" for mark in marks)


def test_pareto_reports_rare_category_suppression() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_PARETO] = True

    _render_eda_univariate(st, _pareto_df())

    text = st.text()
    assert f"fewer than {PARETO_MIN_CATEGORY_COUNT} rows" in text
    assert "(other) bucket" in text
    assert "does not mean the leading" in text


def test_pareto_download_and_workspace_save_are_wired_without_writing(tmp_path: Path) -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_PARETO] = True

    _render_eda_univariate(st, _pareto_df())

    assert "eda_pareto.csv" in st.download_names()
    assert _SAVE_PARETO_BTN in st.button_keys()
    assert not (tmp_path / "analysis").exists()


def test_pareto_refuses_identifier_like_columns_with_an_explanation() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_PARETO] = True

    _render_eda_univariate(st, pd.DataFrame({"row_key": [f"k-{i}" for i in range(80)]}))

    assert "close to unique per row" in st.text()


# ── structural missingness ───────────────────────────────────────────────────


def test_structural_missingness_is_opt_in() -> None:
    st = FakeSt()

    _render_structural_missingness(st, _discovery_df())

    assert "Missingness structure" in st.subheaders()
    assert not st.called("vega_lite_chart")


def test_missingness_pattern_renders_anonymously() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_MISSING_STRUCTURE] = True
    df = _discovery_df()
    df.index = [f"source-row-{i}" for i in range(len(df))]

    _render_structural_missingness(st, df)

    text = st.text()
    assert "Missingness pattern" in text
    assert "sequential display positions only" in text
    assert "source-row-" not in st.payload()


def test_missingness_association_renders_heatmap_pairs_and_mechanism_caveat() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_MISSING_STRUCTURE] = True

    _render_structural_missingness(st, _discovery_df())

    text = st.text()
    assert "Missingness association" in text
    assert "MCAR, MAR or MNAR" in text
    assert "eda_missingness_association.csv" in st.download_names()
    assert _SAVE_MISSING_ASSOC_BTN in st.button_keys()


def test_missingness_structure_empty_state_does_not_crash() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_MISSING_STRUCTURE] = True

    _render_structural_missingness(st, pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}))

    assert "every column in this dataset is complete" in st.text()
    assert not st.called("vega_lite_chart")


def test_missingness_structure_discloses_row_and_column_truncation() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_MISSING_STRUCTURE] = True
    df = pd.DataFrame(
        {f"c{i}": [None if row % (i + 2) else 1.0 for row in range(4_000)] for i in range(50)}
    )

    _render_structural_missingness(st, df)

    text = st.text()
    assert "Bounded view" in text
    assert "evenly spaced, deterministic" in text


def test_missingness_association_single_varying_column_is_explained() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_MISSING_STRUCTURE] = True
    df = pd.DataFrame({"only": [None if i % 2 else 1.0 for i in range(20)], "full": range(20)})

    _render_structural_missingness(st, df)

    assert "at least two columns whose missingness varies" in st.text()


# ── numeric correlation: selection and ranked pairs ──────────────────────────


def test_correlation_column_selection_widget_is_offered_and_bounded() -> None:
    st = FakeSt()

    _render_correlation_matrix(st, _discovery_df())

    selections = [args for args in st.named("multiselect")]
    assert selections, "correlation section must offer an explicit column selection"
    keys = [k.get("key") for name, _a, k in st.calls if name == "multiselect"]
    assert _EDA_CORR_COLUMNS in keys


def test_correlation_honors_an_explicit_column_selection() -> None:
    st = FakeSt()
    st.multiselect_values[_EDA_CORR_COLUMNS] = ["amount", "score"]

    heatmap = _render_correlation_matrix(st, _discovery_df())

    assert heatmap is not None
    assert list(heatmap["matrix"].columns) == ["amount", "score"]


def test_ranked_correlation_pairs_render_without_diagonal_or_mirrors() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_CORR_PAIRS] = True

    heatmap = _render_correlation_matrix(st, _discovery_df())
    _render_correlation_pairs(st, heatmap)

    frames = [args[0] for args in st.named("dataframe") if args]
    ranked = [f for f in frames if isinstance(f, pd.DataFrame) and "abs_correlation" in f.columns]
    assert ranked, "ranked pairs table must render"
    pairs = ranked[0]
    assert all(pairs["column_x"] != pairs["column_y"])
    seen = {frozenset((row.column_x, row.column_y)) for row in pairs.itertuples()}
    assert len(seen) == len(pairs)
    assert "does not establish causation" in st.text()


def test_ranked_correlation_pairs_are_off_by_default_and_wire_downloads() -> None:
    off = FakeSt()
    _render_correlation_pairs(off, _render_correlation_matrix(FakeSt(), _discovery_df()))
    assert "eda_correlation_pairs.csv" not in off.download_names()

    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_CORR_PAIRS] = True
    _render_correlation_pairs(st, _render_correlation_matrix(FakeSt(), _discovery_df()))

    assert "eda_correlation_pairs.csv" in st.download_names()
    assert _SAVE_CORRELATION_PAIRS_BTN in st.button_keys()


def test_ranked_correlation_pairs_ignore_an_unavailable_matrix() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_CORR_PAIRS] = True

    _render_correlation_pairs(st, None)

    assert not st.called("dataframe")


# ── categorical association ──────────────────────────────────────────────────


def test_categorical_association_is_opt_in_and_renders_bounded_matrix() -> None:
    off = FakeSt()
    _render_categorical_association(off, _discovery_df())
    assert "Categorical association" in off.subheaders()
    assert not off.called("vega_lite_chart")

    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_CAT_ASSOC] = True
    _render_categorical_association(st, _discovery_df())

    assert st.called("vega_lite_chart")
    assert "Association strength (0-1)" in st.text()
    assert "does not prove causation or statistical significance" in st.text()


def test_categorical_association_wires_pair_download_and_save() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_CAT_ASSOC] = True

    _render_categorical_association(st, _discovery_df())

    assert "eda_categorical_association.csv" in st.download_names()
    assert _SAVE_CATEGORICAL_ASSOC_BTN in st.button_keys()


def test_categorical_association_explains_excluded_columns() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_CAT_ASSOC] = True
    df = pd.DataFrame(
        {
            "constant": ["same"] * 40,
            "identifier": [f"id-{i}" for i in range(40)],
            "segment": ["a" if i % 2 else "b" for i in range(40)],
            "region": ["p" if i % 3 else "q" for i in range(40)],
        }
    )

    _render_categorical_association(st, df)

    text = st.text()
    assert "Excluded columns" in text
    assert "only one level" in text
    assert "identifier-like" in text


def test_categorical_association_discloses_row_sampling() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_CAT_ASSOC] = True
    rows = CATEGORICAL_ASSOC_MAX_ROWS + 250
    df = pd.DataFrame(
        {
            "segment": ["a" if i % 2 else "b" for i in range(rows)],
            "region": ["p" if i % 3 else "q" for i in range(rows)],
        }
    )

    _render_categorical_association(st, df)

    assert "Sample-derived" in st.text()


def test_categorical_association_unavailable_state_does_not_crash() -> None:
    st = FakeSt()
    st.checkbox_values[_EDA_SHOW_CAT_ASSOC] = True

    _render_categorical_association(st, pd.DataFrame({"n": [1.0, 2.0, 3.0]}))

    assert "at least two usable categorical columns" in st.text()
    assert not st.called("vega_lite_chart")


# ── categorical pair: normalized stacked comparison ──────────────────────────


def test_cat_cat_stacked_view_is_optional_and_keeps_group_counts_in_tooltip() -> None:
    df = _discovery_df()
    off = FakeSt()
    _render_cat_cat(off, df, "segment", "region")
    assert not off.called("vega_lite_chart")

    st = FakeSt()
    st.checkbox_values[_BIV_CROSSTAB_STACKED] = True
    _render_cat_cat(st, df, "segment", "region")

    specs = [args[1] for args in st.named("vega_lite_chart") if len(args) > 1]
    stacked = [s for s in specs if isinstance(s, dict) and s.get("mark") == "bar"]
    assert stacked, "100% stacked comparison must render"
    tooltip_fields = [t["field"] for t in stacked[0]["encoding"]["tooltip"]]
    assert "count" in tooltip_fields
    assert stacked[0]["encoding"]["x"]["stack"] == "normalize"
    assert "Shares hide group size" in st.text()


# ── type-aware visual guide ──────────────────────────────────────────────────


def test_visual_guide_renders_questions_targets_and_caveats() -> None:
    st = FakeSt()

    _render_visual_guide(st, _discovery_df())

    text = st.text()
    assert "Suggested visuals" in text
    assert "Try:" in text
    assert "Where:" in text
    assert "Why:" in text
    assert "no statistical test is selected or run" in text


def test_visual_guide_stays_silent_on_an_empty_frame() -> None:
    st = FakeSt()

    _render_visual_guide(st, pd.DataFrame())

    assert not st.calls


# ── tab-level integration: existing sections survive, nothing reloads ────────

_ALL_TAB_SUBHEADINGS = (
    "Smart Guide",
    "Dataset profile",
    "Missingness",
    "Missingness structure",
    "Duplicate rows",
    "Data types",
    "Preprocessing Recommendations",
    "Numeric distributions",
    "Categorical top values",
    "EDA — Bivariate Explorer",
    "Datetime trends",
    "Distribution shape (skewness & kurtosis)",
    "Correlation matrix",
    "Categorical association",
    "Outlier summary",
)


def _render_all_tabs(st: FakeSt, df: pd.DataFrame) -> None:
    render_overview_tab(st, df, None, None)
    render_columns_tab(st, df)
    render_relationships_tab(st, df)
    render_time_tab(st, df)
    render_advanced_tab(st, df)


def test_all_existing_and_new_eda_sections_render_together() -> None:
    st = FakeSt()

    _render_all_tabs(st, _discovery_df())

    rendered = st.subheaders()
    for heading in _ALL_TAB_SUBHEADINGS:
        assert heading in rendered, f"missing EDA section: {heading}"


def test_existing_download_wiring_is_preserved_across_tabs() -> None:
    st = FakeSt()

    _render_all_tabs(st, _discovery_df())

    names = st.download_names()
    for expected in (
        "eda_missingness.csv",
        "eda_distribution.csv",
        "eda_categories.csv",
        "eda_skew_kurtosis.csv",
        "eda_correlation.csv",
        "eda_outliers.csv",
    ):
        assert expected in names


def test_rendering_tabs_never_loads_or_assesses_the_dataset_again() -> None:
    st = FakeSt()
    st.checkbox_values.update(
        {
            _EDA_SHOW_QQ: True,
            _EDA_SHOW_PARETO: True,
            _EDA_SHOW_MISSING_STRUCTURE: True,
            _EDA_SHOW_CORR_PAIRS: True,
            _EDA_SHOW_CAT_ASSOC: True,
        }
    )

    with (
        patch(f"{_EDA_MODULE}._load_df_and_assess") as mock_load,
        patch(f"{_EDA_MODULE}._compute_load_and_assess") as mock_compute,
        patch(f"{_LOADER_MODULE}.get_managed_frame") as mock_frame,
        patch(f"{_LOADER_MODULE}.get_managed_assessment") as mock_assess,
    ):
        _render_all_tabs(st, _discovery_df())

    mock_load.assert_not_called()
    mock_compute.assert_not_called()
    mock_frame.assert_not_called()
    mock_assess.assert_not_called()


def test_every_new_visual_renders_without_crashing_on_a_degenerate_frame() -> None:
    st = FakeSt()
    st.checkbox_values.update(
        {
            _EDA_SHOW_QQ: True,
            _EDA_SHOW_PARETO: True,
            _EDA_SHOW_MISSING_STRUCTURE: True,
            _EDA_SHOW_CORR_PAIRS: True,
            _EDA_SHOW_CAT_ASSOC: True,
            _EDA_HIST_LOG_SCALE: True,
            _BIV_CROSSTAB_STACKED: True,
        }
    )
    degenerate = pd.DataFrame({"constant": [1.0, 1.0], "blank": pd.Series([None, None])})

    _render_all_tabs(st, degenerate)

    assert st.called("info")


def test_empty_dataframe_renders_all_tabs_without_crashing() -> None:
    st = FakeSt()

    _render_all_tabs(st, pd.DataFrame())

    assert st.called("info")


# ── privacy: no raw paths, no version labels ─────────────────────────────────


@pytest.mark.parametrize("token", ("C:\\", "C:/", "/home/", "/tmp/", "asamili", "version_label"))
def test_rendered_eda_output_carries_no_path_or_version_label(token: str) -> None:
    st = FakeSt()
    st.checkbox_values.update(
        {
            _EDA_SHOW_QQ: True,
            _EDA_SHOW_PARETO: True,
            _EDA_SHOW_MISSING_STRUCTURE: True,
            _EDA_SHOW_CORR_PAIRS: True,
            _EDA_SHOW_CAT_ASSOC: True,
        }
    )

    _render_all_tabs(st, _discovery_df())

    assert token not in st.payload()


def test_eda_section_source_never_reads_the_context_version_label() -> None:
    source = inspect.getsource(eda_sections)

    assert "version_label" not in source
    assert "source_path" not in source
    assert "absolute_path" not in source
