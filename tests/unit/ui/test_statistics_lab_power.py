"""Tests for the Statistics Lab Power & Sample size tab render (page tier).

Reuses the lightweight ``FakeSt`` recorder pattern from
``test_statistics_lab_confidence_intervals.py``. The power tab is a planning
tool and takes no dataframe; the closed-form scipy path is guarded with
``importorskip`` so the suite passes with or without the optional ``[stats]``
extra.
"""

from __future__ import annotations

from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.pages import statistics_lab
from data_quality_toolkit.adapters.ui.pages.statistics_lab import (
    _render_power_analysis,
)


class FakeSt:
    """Minimal Streamlit recorder supporting columns/selectbox/context use."""

    def __init__(
        self,
        checkboxes: dict[str, bool] | None = None,
        choices: dict[str, Any] | None = None,
    ) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.checkboxes = checkboxes or {}
        self.choices = choices or {}

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

    def selectbox(self, label: str, options: Any = (), **k: Any) -> Any:
        self._rec("selectbox", label, options, **k)
        opts = list(options)
        key = k.get("key")
        if key in self.choices:
            return self.choices[key]
        return opts[0] if opts else None

    def checkbox(self, label: str, **k: Any) -> bool:
        self._rec("checkbox", label, **k)
        return bool(self.checkboxes.get(str(k.get("key") or label), False))

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))

    def charts(self) -> list[tuple[Any, ...]]:
        return [a for name, a, _k in self.calls if name == "vega_lite_chart"]


def test_section_header_always_renders() -> None:
    st = FakeSt()
    _render_power_analysis(st)
    assert "Power & sample size" in st.texts()


def test_default_path_renders_metric_cards_with_scipy() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()
    _render_power_analysis(st)  # default first option = "Power — one-sample mean"
    assert st.called("metric")  # metric cards rendered for an ok result


def test_unavailable_status_surfaces_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        statistics_lab,
        "power_mean",
        lambda *_a, **_k: {
            "status": "unavailable",
            "reason": "scipy is not installed",
            "method": "normal_power_mean",
        },
    )
    st = FakeSt()
    _render_power_analysis(st)
    assert st.called("warning")
    assert "scipy is not installed" in st.texts()


def test_invalid_status_surfaces_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        statistics_lab,
        "power_mean",
        lambda *_a, **_k: {
            "status": "invalid_input",
            "reason": "sigma must be > 0",
            "method": "normal_power_mean",
        },
    )
    st = FakeSt()
    _render_power_analysis(st)
    assert st.called("info")
    assert "sigma must be > 0" in st.texts()


def test_required_n_prop_path_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the two-proportion required-n analysis and stub an ok result so the
    # per-group sample-size cards render without depending on scipy.
    def _analysis_prop(label: str, options: Any = (), **k: Any) -> Any:
        if k.get("key") == statistics_lab._STATS_POWER_ANALYSIS:
            return "Required n — two proportions"
        opts = list(options)
        return opts[0] if opts else None

    monkeypatch.setattr(
        statistics_lab,
        "required_n_prop",
        lambda *_a, **_k: {
            "status": "ok",
            "reason": None,
            "method": "normal_n_prop",
            "n1": 100,
            "n2": 100,
        },
    )
    st = FakeSt()
    st.selectbox = _analysis_prop  # type: ignore[method-assign]
    _render_power_analysis(st)
    assert st.called("metric")
    assert "per group" in st.texts()


def test_no_crash_without_scipy() -> None:
    # Default render must not raise whether scipy is present (ok path) or absent
    # (unavailable → warning); the header always renders either way.
    st = FakeSt()
    _render_power_analysis(st)
    assert "Power & sample size" in st.texts()


# ── opt-in bounded planning curve ────────────────────────────────────────


def test_power_curve_is_off_by_default() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()

    _render_power_analysis(st)

    assert not st.charts()


def test_power_curve_renders_bounded_points_when_enabled() -> None:
    pytest.importorskip("scipy")
    st = FakeSt({statistics_lab._STATS_POWER_SHOW_CURVE: True})

    _render_power_analysis(st)

    charts = st.charts()
    assert charts
    data = charts[0][0]
    assert list(data.columns) == ["parameter", "value"]
    assert len(data) <= statistics_lab.POWER_CURVE_MAX_POINTS
    assert bool((data["value"] >= 0).all())


def test_power_curve_states_alpha_and_sidedness_and_recommends_nothing() -> None:
    pytest.importorskip("scipy")
    st = FakeSt({statistics_lab._STATS_POWER_SHOW_CURVE: True})

    _render_power_analysis(st)

    text = st.texts()
    assert "alpha=0.05" in text
    assert "two-sided alternative" in text
    assert "no sample size is recommended for you" in text
    assert "assumption you supply" in text


def test_power_curve_marks_the_selected_design_point() -> None:
    pytest.importorskip("scipy")
    st = FakeSt({statistics_lab._STATS_POWER_SHOW_CURVE: True})

    _render_power_analysis(st)

    spec = st.charts()[0][1]
    assert any("datum" in layer.get("encoding", {}).get("x", {}) for layer in spec["layer"])


def test_power_curve_skips_undefined_points_instead_of_plotting_zero() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(
        {statistics_lab._STATS_POWER_SHOW_CURVE: True},
        {statistics_lab._STATS_POWER_ANALYSIS: "Required n — mean"},
    )

    _render_power_analysis(st)

    data = st.charts()[0][0]
    assert bool((data["value"] > 0).all())


def test_power_curve_is_not_offered_for_an_unsupported_analysis() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(
        {statistics_lab._STATS_POWER_SHOW_CURVE: True},
        {statistics_lab._STATS_POWER_ANALYSIS: "Required n — variance ratio"},
    )

    _render_power_analysis(st)

    assert "A bounded curve is not offered for this analysis type" in st.texts()
    assert not st.charts()


def test_power_curve_is_not_offered_without_a_completed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        statistics_lab,
        "power_mean",
        lambda *_a, **_k: {
            "status": "invalid_input",
            "reason": "sigma must be > 0",
            "method": "normal_power_mean",
        },
    )
    st = FakeSt({statistics_lab._STATS_POWER_SHOW_CURVE: True})

    _render_power_analysis(st)

    assert not st.charts()
    assert not any(
        call == "checkbox" and k.get("key") == statistics_lab._STATS_POWER_SHOW_CURVE
        for call, _a, k in st.calls
    )
