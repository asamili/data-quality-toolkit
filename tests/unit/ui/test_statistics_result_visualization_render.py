"""Render and ownership contracts for the Statistics Lab result evidence.

Drives the Streamlit-facing renderers through a local recorder double to pin:

* every evidence view is opt-in, renders beside the result that produced it, and
  is owned by the module that already owns that result's rendering;
* enabling an evidence view never triggers a second statistical call, a second
  dataset load, a new download, or a new workspace-save artifact;
* evidence stays privacy-safe — anonymous pair positions, bounded category
  labels, no absolute path, version label or source index;
* charts never carry a verdict in colour alone, and unavailable evidence
  degrades to an explanation instead of a fabricated value;
* existing tables, downloads, saves, typed proportion behaviour, paired
  direction, optional-SciPy degradation and large-file refusal are unchanged.

All fixtures are synthetic; no dataset, screenshot or file fixture is added.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.pages import statistics_lab
from data_quality_toolkit.adapters.ui.pages import statistics_lab_chi_square as chi
from data_quality_toolkit.adapters.ui.pages import statistics_lab_runners as runners
from data_quality_toolkit.adapters.ui.services import statistics as svc
from data_quality_toolkit.adapters.ui.services import statistics_visualization as viz
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT

_PATCH_LOAD = "data_quality_toolkit.adapters.ui.pages.statistics_lab._load_df_and_assess"
_PATCH_STATS_PROFILE = "data_quality_toolkit.adapters.ui.pages.statistics_lab.statistics_profile"


class FakeSt:
    """Streamlit recorder with keyed checkbox/selectbox/number_input control."""

    def __init__(
        self,
        *,
        checkboxes: dict[str, bool] | None = None,
        choices: dict[str, Any] | None = None,
        numbers: dict[str, float] | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> None:
        self.session_state = session_state if session_state is not None else {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.checkboxes = checkboxes or {}
        self.choices = choices or {}
        self.numbers = numbers or {}
        self.text_values: dict[str, str] = {}
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
        return [FakeSt() for _ in range(n)]

    def tabs(self, labels: Sequence[str]) -> list[FakeSt]:
        self._rec("tabs", list(labels))
        return [self for _ in labels]

    def checkbox(self, label: str, **k: Any) -> bool:
        self._rec("checkbox", label, **k)
        key = str(k.get("key") or label)
        return bool(self.checkboxes.get(key, k.get("value", False)))

    def selectbox(self, label: str, options: Any = (), **k: Any) -> Any:
        self._rec("selectbox", label, options, **k)
        opts = list(options)
        key = k.get("key")
        if key in self.choices:
            return self.choices[key]
        return opts[0] if opts else None

    def number_input(self, label: str, value: float = 0.0, **k: Any) -> Any:
        self._rec("number_input", label, value, **k)
        key = k.get("key")
        if key in self.numbers:
            return self.numbers[key]
        return value

    def text_input(self, label: str, **k: Any) -> str:
        self._rec("text_input", label, **k)
        return self.text_values.get(label, str(k.get("value", "")))

    def button(self, label: str, **k: Any) -> bool:
        self._rec("button", label, **k)
        return bool(self.clicks.get(k.get("key", label), False))

    # -- assertion helpers ----------------------------------------------------

    def called(self, name: str) -> bool:
        return any(call == name for call, _a, _k in self.calls)

    def call_count(self, name: str) -> int:
        return sum(1 for call, _a, _k in self.calls if call == name)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))

    def payload(self) -> str:
        chunks: list[str] = []
        for _name, args, kwargs in self.calls:
            for value in (*args, *kwargs.values()):
                if isinstance(value, pd.DataFrame):
                    chunks.append(value.to_csv(index=True))
                elif isinstance(value, str | dict | list):
                    chunks.append(str(value))
        return " ".join(chunks)

    def charts(self) -> list[tuple[Any, dict[str, Any]]]:
        return [
            (args[0], args[1] if len(args) > 1 else {})
            for name, args, _k in self.calls
            if name == "vega_lite_chart" and args
        ]

    def chart_frames(self) -> list[pd.DataFrame]:
        return [data for data, _spec in self.charts() if isinstance(data, pd.DataFrame)]

    def download_names(self) -> list[str]:
        return [
            k["file_name"]
            for name, _a, k in self.calls
            if name == "download_button" and "file_name" in k
        ]

    def button_keys(self) -> list[str]:
        return [k["key"] for name, _a, k in self.calls if name == "button" and "key" in k]

    def checkbox_keys(self) -> list[str]:
        return [k["key"] for name, _a, k in self.calls if name == "checkbox" and "key" in k]


# ── fixtures ─────────────────────────────────────────────────────────────────


def _gof_df() -> pd.DataFrame:
    return pd.DataFrame({"cat": ["a"] * 30 + ["b"] * 30 + ["c"] * 40})


def _contingency_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "left": ["A"] * 40 + ["B"] * 40,
            "right": (["X"] * 30 + ["Y"] * 10) + (["X"] * 10 + ["Y"] * 30),
        }
    )


def _paired_df(rows: int = 30) -> pd.DataFrame:
    # Deterministic, non-constant paired differences: the kernel needs a positive
    # standard deviation of the differences, and each difference stays positive so
    # the contract direction (first minus second) is unambiguous in assertions.
    before = [float(index) for index in range(rows)]
    after = [float(index) - 1.0 - (index % 3) * 0.5 for index in range(rows)]
    return pd.DataFrame({"before": before, "after": after})


def _binary_df() -> pd.DataFrame:
    return pd.DataFrame({"outcome": ["yes"] * 70 + ["no"] * 30})


def _two_group_binary_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "outcome": ["yes"] * 20 + ["no"] * 10 + ["yes"] * 10 + ["no"] * 30,
            "grp": ["A"] * 30 + ["B"] * 40,
        }
    )


def _numeric_group_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "group": ["a", "b"] * 15,
            "value": [float(i % 7) + (0.0 if i % 2 == 0 else 3.0) for i in range(30)],
        }
    )


def _ci_df() -> pd.DataFrame:
    return pd.DataFrame({"value": [float(i % 7) + (i * 0.1) for i in range(40)]})


# ── chi-square goodness of fit ───────────────────────────────────────────────


def test_gof_evidence_is_off_by_default() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()

    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)

    assert chi._GOF_SHOW_EVIDENCE in st.checkbox_keys()
    assert not st.called("vega_lite_chart")


def test_gof_bars_and_contribution_render_through_the_chi_square_module() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={chi._GOF_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)

    charts = st.charts()
    assert charts, "the goodness-of-fit evidence chart must render"
    data, spec = charts[0]
    assert list(data.columns) == ["category", "measure", "count"]
    assert set(data["measure"]) == {"observed", "expected"}
    assert spec["encoding"]["color"]["field"] == "measure"
    text = st.texts()
    assert "Observed against expected counts" in text
    assert "localises where observed and expected counts" in text


def test_gof_evidence_states_its_bound_and_never_reruns_the_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("scipy")
    calls: list[int] = []
    original = chi.run_chi_square_gof_test

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(chi, "run_chi_square_gof_test", counting)
    st = FakeSt(checkboxes={chi._GOF_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)

    assert len(calls) == 1
    assert str(viz.GOF_MAX_CATEGORIES) in st.texts()


def test_gof_evidence_adds_no_download_or_workspace_artifact() -> None:
    pytest.importorskip("scipy")
    off = FakeSt()
    on = FakeSt(checkboxes={chi._GOF_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(off, _gof_df(), 0.05)
    chi.render_chi_square_tests_runner(on, _gof_df(), 0.05)

    assert on.download_names() == off.download_names()
    assert on.button_keys() == off.button_keys()


def test_gof_evidence_unavailable_state_explains_and_still_guides() -> None:
    st = FakeSt(checkboxes={chi._GOF_SHOW_EVIDENCE: True})

    chi._render_gof_evidence(st, {"status": "unavailable", "reason": "scipy is not installed"})

    text = st.texts()
    assert "Evidence view unavailable" in text
    assert "What was compared" in text
    assert not st.called("vega_lite_chart")


# ── chi-square contingency ───────────────────────────────────────────────────


def _independence_st(**checkboxes: bool) -> FakeSt:
    return FakeSt(
        choices={chi._CHI_MODE_KEY: chi._CHI_MODE_IND},
        checkboxes=dict(checkboxes),
    )


def test_contingency_heatmap_and_ranked_cells_render_through_the_chi_square_module() -> None:
    pytest.importorskip("scipy")
    st = _independence_st(**{chi._IND_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _contingency_df(), 0.05)

    charts = st.charts()
    assert charts, "the contingency residual heatmap must render"
    data, spec = charts[0]
    assert spec["mark"]["type"] == "rect"
    assert spec["encoding"]["color"]["field"] == "residual"
    assert {"row_category", "col_category", "observed", "expected", "residual"} <= set(data.columns)
    text = st.texts()
    assert "Signed Pearson residual" in text
    assert "Cells ranked by the size of their departure" in text
    assert "does not establish cause" in text


def test_contingency_heatmap_is_off_by_default() -> None:
    pytest.importorskip("scipy")
    st = _independence_st()

    chi.render_chi_square_tests_runner(st, _contingency_df(), 0.05)

    assert chi._IND_SHOW_EVIDENCE in st.checkbox_keys()
    assert not st.called("vega_lite_chart")


def test_homogeneity_evidence_uses_its_own_toggle_and_framing() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(
        choices={chi._CHI_MODE_KEY: chi._CHI_MODE_HOMOG},
        checkboxes={chi._HOMOG_SHOW_EVIDENCE: True},
    )

    chi.render_chi_square_tests_runner(st, _contingency_df(), 0.05)

    assert chi._HOMOG_SHOW_EVIDENCE in st.checkbox_keys()
    text = st.texts()
    assert "same outcome distribution" in text
    assert st.called("vega_lite_chart")


def test_contingency_evidence_refuses_an_out_of_bounds_table_without_dropping_categories() -> None:
    rows = viz.CONTINGENCY_MAX_ROWS + 5
    result = {
        "status": "ok",
        "row_labels": [f"r{index}" for index in range(rows)],
        "col_labels": ["x", "y"],
        "row_category_count": rows,
        "col_category_count": 2,
        "cells": [
            {"row_category": f"r{row}", "col_category": col, "observed": 1, "expected": 1.0}
            for row in range(rows)
            for col in ("x", "y")
        ],
    }
    st = FakeSt()

    chi._render_contingency_evidence(
        st, result, family="independence", row_header="left", col_header="right"
    )

    assert "Evidence view unavailable" in st.texts()
    assert "bounded at" in st.texts()
    assert not st.called("vega_lite_chart")


# ── paired evidence ──────────────────────────────────────────────────────────


def test_paired_evidence_is_opt_in_and_renders_anonymous_positions() -> None:
    pytest.importorskip("scipy")
    off = FakeSt()
    runners.render_paired_t_runner(off, _paired_df(), 0.05)
    assert runners._PAIRED_T_SHOW_EVIDENCE in off.checkbox_keys()
    assert not off.called("vega_lite_chart")

    st = FakeSt(checkboxes={runners._PAIRED_T_SHOW_EVIDENCE: True})
    runners.render_paired_t_runner(st, _paired_df(), 0.05)

    frames = st.chart_frames()
    assert len(frames) == 2
    assert list(frames[0].columns) == ["pair", "measurement", "value"]
    assert list(frames[1].columns) == ["pair", "before", "after", "difference"]
    assert min(frames[1]["pair"]) == 1
    assert "anonymous positions only" in st.texts()


def test_paired_evidence_preserves_the_contract_difference_direction() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={runners._PAIRED_T_SHOW_EVIDENCE: True})

    runners.render_paired_t_runner(st, _paired_df(), 0.05)

    data = st.chart_frames()[1]
    # before minus after, exactly as the runner handed the pairs to the kernel.
    assert list(data["difference"]) == pytest.approx(list(data["before"] - data["after"]))
    assert bool((data["difference"] > 0).all())
    assert "before minus after" in st.texts()


def test_paired_evidence_reports_excluded_incomplete_pairs() -> None:
    pytest.importorskip("scipy")
    frame = _paired_df()
    frame.loc[0, "after"] = float("nan")
    st = FakeSt(checkboxes={runners._PAIRED_T_SHOW_EVIDENCE: True})

    runners.render_paired_t_runner(st, frame, 0.05)

    assert "1 row(s) were excluded" in st.texts()


def test_paired_evidence_never_triggers_a_second_test_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("scipy")
    calls: list[int] = []
    original = runners.run_paired_t_test

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(runners, "run_paired_t_test", counting)
    st = FakeSt(checkboxes={runners._PAIRED_T_SHOW_EVIDENCE: True})

    runners.render_paired_t_runner(st, _paired_df(), 0.05)

    assert len(calls) == 1


def test_wilcoxon_reuses_the_shared_paired_evidence_view() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={statistics_lab._STATS_WILCOXON_SHOW_EVIDENCE: True})

    statistics_lab._render_wilcoxon(st, _paired_df(), 0.05)

    assert st.called("vega_lite_chart")
    assert "anonymous positions only" in st.texts()


# ── proportions ──────────────────────────────────────────────────────────────


def test_one_proportion_evidence_renders_through_the_runner_module() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={runners._ONE_PROP_SHOW_EVIDENCE: True})

    runners.render_proportion_tests_runner(st, _binary_df(), 0.05)

    charts = st.charts()
    assert charts, "the proportion evidence chart must render"
    data, spec = charts[0]
    # The recorder takes the first typed option, so "no [str]" is the success value.
    assert list(data["label"]) == ["no [str]"]
    assert list(data["successes"]) == [30]
    assert list(data["total"]) == [100]
    assert list(data["proportion"]) == pytest.approx([0.3])
    # The null proportion is drawn as a reference line, not as a verdict colour.
    assert any(layer.get("mark", {}).get("color") == "red" for layer in spec["layer"])
    assert "domain judgement" in st.texts()


def test_two_proportion_evidence_keeps_typed_group_labels_and_the_difference() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(
        choices={runners._PROP_MODE_KEY: runners._PROP_MODE_TWO},
        checkboxes={runners._TWO_PROP_SHOW_EVIDENCE: True},
    )

    runners.render_proportion_tests_runner(st, _two_group_binary_df(), 0.05)

    data = st.chart_frames()[0]
    # Typed, collision-safe group labels survive; the recorder's success value is
    # the first typed outcome option ("no [str]").
    assert list(data["label"]) == ["A [str]", "B [str]"]
    assert list(data["successes"]) == [10, 30]
    assert list(data["total"]) == [30, 40]
    assert "Observed difference (first minus second)" in st.texts()


def test_proportion_evidence_states_that_no_interval_is_invented() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={runners._ONE_PROP_SHOW_EVIDENCE: True})

    runners.render_proportion_tests_runner(st, _binary_df(), 0.05)

    assert "no uncertainty" in st.texts()
    assert "none are invented" in st.texts()


def test_proportion_evidence_is_off_by_default_and_adds_no_artifact() -> None:
    pytest.importorskip("scipy")
    off = FakeSt()
    on = FakeSt(checkboxes={runners._ONE_PROP_SHOW_EVIDENCE: True})

    runners.render_proportion_tests_runner(off, _binary_df(), 0.05)
    runners.render_proportion_tests_runner(on, _binary_df(), 0.05)

    assert not off.called("vega_lite_chart")
    assert on.download_names() == off.download_names()
    assert on.button_keys() == off.button_keys()


# ── estimates, groups and effect sizes ───────────────────────────────────────


def test_confidence_interval_evidence_shows_the_point_and_its_interval() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={statistics_lab._STATS_CI_SHOW_EVIDENCE: True})

    statistics_lab._render_confidence_intervals(st, _ci_df())

    data = st.chart_frames()[0]
    assert {"label", "estimate", "lower", "upper"} <= set(data.columns)
    assert bool(data.iloc[0]["interval_available"]) is True
    assert "Point estimate with its interval" in st.texts()


def test_confidence_interval_evidence_explains_a_missing_interval() -> None:
    st = FakeSt(checkboxes={statistics_lab._STATS_CI_SHOW_EVIDENCE: True})

    statistics_lab._render_confidence_interval_result(
        st,
        {
            "status": "ok",
            "method": "t",
            "confidence": 0.95,
            "point": 10.0,
            "lower": None,
            "upper": None,
            "n": 25,
        },
    )

    assert "never replaced with zero" in st.texts()


def test_effect_size_evidence_marks_a_zero_shift_reference() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={statistics_lab._STATS_EFFECT_SHOW_EVIDENCE: True})

    statistics_lab._render_nonparametric_effect_sizes(
        st, _numeric_group_df(), "value", "group", 0.05
    )

    _data, spec = st.charts()[0]
    assert any(
        layer.get("encoding", {}).get("x", {}).get("datum") == 0.0 for layer in spec["layer"]
    )
    assert "zero-shift reference" in st.texts()


def test_two_group_evidence_plots_group_centres_only() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={statistics_lab._STATS_TWO_GROUP_SHOW_EVIDENCE: True})

    statistics_lab._render_group_comparison(st, _numeric_group_df(), 0.05)

    frames = [frame for frame in st.chart_frames() if "group" in frame.columns]
    assert frames, "the group-centre comparison must render"
    assert list(frames[0].columns) == [
        "group",
        "n",
        "center",
        "lower",
        "upper",
        "interval_available",
    ]
    assert len(frames[0]) == 2
    assert "no individual" in st.texts()


def test_omnibus_evidence_states_it_cannot_identify_which_group_differs() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame(
        {
            "group": ["a", "b", "c"] * 10,
            "value": [float((index * 7) % 11) for index in range(30)],
        }
    )
    st = FakeSt(checkboxes={statistics_lab._STATS_MULTI_GROUP_SHOW_EVIDENCE: True})

    statistics_lab._render_group_comparison(st, df, 0.05)

    text = st.texts()
    assert "does not identify" in text
    assert "post-hoc" in text


# ── distributions and power ──────────────────────────────────────────────────


def test_distribution_curve_is_opt_in_and_shades_the_calculated_region() -> None:
    pytest.importorskip("scipy")
    off = FakeSt()
    statistics_lab._render_distribution_lookup(off)
    assert statistics_lab._STATS_DIST_SHOW_CURVE in off.checkbox_keys()
    assert not off.called("vega_lite_chart")

    st = FakeSt(
        checkboxes={statistics_lab._STATS_DIST_SHOW_CURVE: True},
        choices={statistics_lab._STATS_DIST_CALCULATION: "CDF"},
    )
    statistics_lab._render_distribution_lookup(st)

    data, spec = st.charts()[0]
    assert list(data.columns) == ["x", "value", "shaded"]
    assert len(data) <= viz.DISTRIBUTION_CURVE_MAX_POINTS
    assert bool(data["shaded"].any())
    assert any(layer.get("mark", {}).get("type") == "area" for layer in spec["layer"])
    assert "makes no claim that the active dataset follows" in st.texts()


def test_distribution_curve_is_refused_for_a_critical_value_lookup() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(
        checkboxes={statistics_lab._STATS_DIST_SHOW_CURVE: True},
        choices={statistics_lab._STATS_DIST_CALCULATION: "Critical value (two-tail)"},
    )

    statistics_lab._render_distribution_lookup(st)

    assert "A bounded curve is not available for this calculation" in st.texts()
    assert not st.called("vega_lite_chart")


def test_power_curve_is_opt_in_bounded_and_shows_its_planning_assumptions() -> None:
    pytest.importorskip("scipy")
    off = FakeSt()
    statistics_lab._render_power_analysis(off)
    assert statistics_lab._STATS_POWER_SHOW_CURVE in off.checkbox_keys()
    assert not off.called("vega_lite_chart")

    st = FakeSt(checkboxes={statistics_lab._STATS_POWER_SHOW_CURVE: True})
    statistics_lab._render_power_analysis(st)

    data, _spec = st.charts()[0]
    assert list(data.columns) == ["parameter", "value"]
    assert len(data) <= viz.POWER_CURVE_MAX_POINTS
    text = st.texts()
    assert "two-sided alternative" in text
    assert "no sample size is recommended for you" in text


def test_required_sample_size_curve_varies_the_effect_size() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(
        checkboxes={statistics_lab._STATS_POWER_SHOW_CURVE: True},
        choices={statistics_lab._STATS_POWER_ANALYSIS: "Required n — Cohen's d (two-sample t)"},
    )

    statistics_lab._render_power_analysis(st)

    assert "Required sample size per group against effect size" in st.texts()
    data, _spec = st.charts()[0]
    assert len(data) <= viz.POWER_CURVE_MAX_POINTS


def test_power_curve_is_not_offered_for_an_unsupported_analysis() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(
        checkboxes={statistics_lab._STATS_POWER_SHOW_CURVE: True},
        choices={statistics_lab._STATS_POWER_ANALYSIS: "Required n — variance ratio"},
    )

    statistics_lab._render_power_analysis(st)

    assert "A bounded curve is not offered for this analysis type" in st.texts()
    assert not st.called("vega_lite_chart")


# ── assumption guidance ──────────────────────────────────────────────────────


def test_assumption_guidance_is_opt_in_and_stays_informational() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={statistics_lab._STATS_ASSUMPTION_SHOW_GUIDANCE: True})

    statistics_lab._render_assumption_checks(st, _numeric_group_df(), 0.05)

    text = st.texts()
    assert "never switch the selected test" in text
    assert "compliance score" in text


# ── cross-cutting: no second call, privacy, colour, degradation ──────────────


def test_page_render_with_every_evidence_view_loads_the_dataset_once(tmp_path: Any) -> None:
    pytest.importorskip("scipy")
    frame = pd.DataFrame(
        {
            "group": ["a", "b"] * 15,
            "value": [float(i % 7) + (0.0 if i % 2 else 3.0) for i in range(30)],
            "other": [float(i % 5) for i in range(30)],
        }
    )
    st = FakeSt(
        checkboxes={
            statistics_lab._STATS_CI_SHOW_EVIDENCE: True,
            statistics_lab._STATS_EFFECT_SHOW_EVIDENCE: True,
            statistics_lab._STATS_TWO_GROUP_SHOW_EVIDENCE: True,
            statistics_lab._STATS_WILCOXON_SHOW_EVIDENCE: True,
            statistics_lab._STATS_DIST_SHOW_CURVE: True,
            statistics_lab._STATS_POWER_SHOW_CURVE: True,
            statistics_lab._STATS_ASSUMPTION_SHOW_GUIDANCE: True,
            runners._PAIRED_T_SHOW_EVIDENCE: True,
            runners._ONE_PROP_SHOW_EVIDENCE: True,
            chi._GOF_SHOW_EVIDENCE: True,
        }
    )
    st.text_values["CSV path"] = str(tmp_path / "data.csv")

    with (
        patch(_PATCH_LOAD, return_value=(frame, {}, None)) as load,
        patch(_PATCH_STATS_PROFILE, return_value={"status": "error"}),
    ):
        statistics_lab._render_statistics_lab(st, {})

    assert load.call_count == 1
    text = st.texts()
    assert str(tmp_path) not in text
    assert "0x" not in text
    assert "Traceback" not in text


def test_evidence_views_never_encode_a_verdict_in_colour_alone() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={chi._GOF_SHOW_EVIDENCE: True, runners._ONE_PROP_SHOW_EVIDENCE: True})
    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)
    runners.render_proportion_tests_runner(st, _binary_df(), 0.05)

    verdict_fields = {"reject_null", "decision", "significant", "p_value"}
    for _data, spec in st.charts():
        layers = spec.get("layer", [spec])
        for layer in layers:
            colour = layer.get("encoding", {}).get("color", {})
            assert colour.get("field") not in verdict_fields
    # Every charted number is also present as text in an adjacent table.
    assert st.called("dataframe")


def test_evidence_result_payloads_are_identical_with_and_without_the_chart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("scipy")
    captured: dict[str, list[pd.DataFrame]] = {"off": [], "on": []}

    def capture(bucket: str) -> Any:
        def fake_download(_st: Any, _label: str, df: pd.DataFrame, _file_name: str) -> None:
            captured[bucket].append(df)

        return fake_download

    monkeypatch.setattr(runners, "csv_download_button", capture("off"))
    runners.render_proportion_tests_runner(FakeSt(), _binary_df(), 0.05)
    monkeypatch.setattr(runners, "csv_download_button", capture("on"))
    runners.render_proportion_tests_runner(
        FakeSt(checkboxes={runners._ONE_PROP_SHOW_EVIDENCE: True}), _binary_df(), 0.05
    )

    assert len(captured["off"]) == len(captured["on"]) == 1
    off = captured["off"][0].iloc[0]
    on = captured["on"][0].iloc[0]
    for field in ("statistic", "p_value", "alpha", "alternative", "reject_null", "test"):
        assert off[field] == on[field]


def test_evidence_degrades_safely_when_scipy_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from data_quality_toolkit.domain.statistics import inference

    monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)
    st = FakeSt(checkboxes={chi._GOF_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)  # must not raise

    assert st.called("warning")
    assert not st.called("vega_lite_chart")
    assert "Traceback" not in st.texts()


def test_large_file_mode_still_refuses_before_any_evidence_is_offered() -> None:
    context = DatasetContext(
        source_path="C:/safe/data.csv",
        display_name="data.csv",
        size_bytes=10,
        modified_ns=1,
        large_file_mode=True,
    )
    st = FakeSt(checkboxes={chi._GOF_SHOW_EVIDENCE: True})

    with patch(_PATCH_LOAD) as load:
        statistics_lab._render_statistics_lab(st, {DATASET_CONTEXT: context})

    load.assert_not_called()
    assert st.called("warning")
    assert not st.called("vega_lite_chart")


# ── regression: selection, coverage and typed behaviour are untouched ─────────


def test_testkey_execution_coverage_contract_is_unchanged() -> None:
    assert set(runners.TESTKEY_EXECUTION_COVERAGE) == {
        "ONE_T",
        "ONE_Z",
        "TWO_T_EQ",
        "TWO_T_WELCH",
        "TWO_Z",
        "PAIRED_T",
        "ANOVA",
        "ONE_PROP_Z",
        "TWO_PROP_Z",
        "ONE_VAR_CHI",
        "F_VAR",
        "CHI_GOF",
        "CHI_IND",
        "CHI_HOMOG",
    }


@pytest.mark.parametrize(
    ("variable_type", "group_structure", "expected"),
    [
        ("numeric", "one_sample", "ONE_T"),
        ("numeric", "paired", "PAIRED_T"),
        ("proportion", "two_independent", "TWO_PROP_Z"),
        ("categorical", "goodness_of_fit", "CHI_GOF"),
    ],
)
def test_selection_matrix_is_unchanged(
    variable_type: str, group_structure: str, expected: str
) -> None:
    result = svc.select_hypothesis_test(
        variable_type,
        group_structure,
        paired=group_structure == "paired",
        sigma_known=False,
    )

    assert result["test_key"] == expected


def test_typed_proportion_identity_is_unchanged() -> None:
    frame = pd.DataFrame({"outcome": pd.Series([1, "1", 1, "1"], dtype=object)})

    options, error = svc.outcome_category_options(frame, "outcome")

    assert error is None
    assert [option.label for option in options] == ["1 [int]", "1 [str]"]
