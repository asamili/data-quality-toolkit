"""Tests for the Statistics Lab nonparametric effect-size render (page tier).

Reuses the lightweight ``FakeSt`` recorder pattern from
``test_statistics_lab_inferential.py``. Cliff's delta and the Hodges-Lehmann
point estimate render without scipy; the confidence bounds render only when
scipy is present (guarded with ``importorskip``). Insufficient / degenerate input
surfaces an info callout rather than crashing, and a split above the exact
Hodges-Lehmann pairwise ceiling keeps Cliff's delta while showing no HL number.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.pages import statistics_lab
from data_quality_toolkit.adapters.ui.pages.statistics_lab import (
    _render_group_comparison,
    _render_nonparametric_effect_sizes,
)
from data_quality_toolkit.domain.statistics import effect_size


class FakeSt:
    """Minimal Streamlit recorder supporting columns/selectbox/context use."""

    def __init__(self, checkboxes: dict[str, bool] | None = None) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.checkboxes = checkboxes or {}

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


# group column first so the group selectbox picks a non-metric column.
_DF = pd.DataFrame(
    {
        "group": ["a", "b"] * 15,
        "value": [float(i % 7) + (0.0 if i % 2 == 0 else 3.0) for i in range(30)],
    }
)


def test_section_and_cliffs_render_without_scipy() -> None:
    st = FakeSt()
    _render_nonparametric_effect_sizes(st, _DF, "value", "group", 0.05)
    text = st.texts()
    assert "Nonparametric effect sizes" in text
    assert "Cliff's delta" in text
    assert "Effect size interpretation" in text
    assert "Sample sizes" in text
    assert "Hodges-Lehmann estimate" in text
    assert st.called("metric")


def test_confidence_bounds_render_with_scipy() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()
    _render_nonparametric_effect_sizes(st, _DF, "value", "group", 0.05)
    text = st.texts()
    assert "Lower bound" in text
    assert "Upper bound" in text
    assert "Method" in text
    # No unavailable info callout when the band is computed.
    assert "unavailable" not in text


def test_insufficient_data_renders_info_state() -> None:
    tiny = pd.DataFrame({"group": ["a", "b"], "value": [1.0, 2.0]})
    st = FakeSt()
    _render_nonparametric_effect_sizes(st, tiny, "value", "group", 0.05)
    assert st.called("info")
    assert "at least 2 finite values" in st.texts()


def test_no_crash_on_single_group() -> None:
    one = pd.DataFrame({"group": ["a"] * 6, "value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]})
    st = FakeSt()
    _render_nonparametric_effect_sizes(st, one, "value", "group", 0.05)  # must not raise
    assert st.called("info")


def test_group_comparison_two_group_includes_effect_sizes() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()
    _render_group_comparison(st, _DF, 0.05)
    text = st.texts()
    # Existing two-group display is preserved alongside the new effect sizes.
    assert "Group comparison" in text
    assert "Nonparametric effect sizes" in text
    assert "Cliff's delta" in text


# ── opt-in effect / group evidence ───────────────────────────────────────


def test_effect_evidence_is_off_by_default() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()

    _render_nonparametric_effect_sizes(st, _DF, "value", "group", 0.05)

    assert not st.charts()


def test_effect_evidence_shows_the_shift_against_a_zero_reference() -> None:
    pytest.importorskip("scipy")
    st = FakeSt({statistics_lab._STATS_EFFECT_SHOW_EVIDENCE: True})

    _render_nonparametric_effect_sizes(st, _DF, "value", "group", 0.05)

    data, spec = st.charts()[0]
    assert list(data["label"]) == ["Hodges-Lehmann shift"]
    assert any(
        layer.get("encoding", {}).get("x", {}).get("datum") == 0.0 for layer in spec["layer"]
    )
    assert "zero-shift reference" in st.texts()


def test_effect_evidence_keeps_magnitude_bands_out_of_a_verdict() -> None:
    pytest.importorskip("scipy")
    st = FakeSt({statistics_lab._STATS_EFFECT_SHOW_EVIDENCE: True})

    _render_nonparametric_effect_sizes(st, _DF, "value", "group", 0.05)

    text = st.texts()
    assert "conventional labels, not thresholds of importance" in text
    assert "carries no p-value" in text


def test_effect_evidence_marks_an_unavailable_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        statistics_lab,
        "nonparametric_effect_sizes",
        lambda *_a, **_k: {
            "status": "ok",
            "reason": None,
            "confidence": 0.95,
            "group_a": "a",
            "group_b": "b",
            "n_a": 15,
            "n_b": 15,
            "cliffs_delta": 0.4,
            "cliffs_interpretation": "medium",
            "hodges_lehmann": {
                "status": "unavailable",
                "reason": "scipy is not installed",
                "estimate": 1.5,
                "lower": None,
                "upper": None,
            },
        },
    )
    st = FakeSt({statistics_lab._STATS_EFFECT_SHOW_EVIDENCE: True})

    _render_nonparametric_effect_sizes(st, _DF, "value", "group", 0.05)

    text = st.texts()
    assert "Not available from this result" in text
    assert "never replaced with zero" in text
    data = st.charts()[0][0]
    assert data.iloc[0]["lower"] is None
    assert data.iloc[0]["upper"] is None


def test_two_group_comparison_evidence_plots_group_centres_only() -> None:
    pytest.importorskip("scipy")
    st = FakeSt({statistics_lab._STATS_TWO_GROUP_SHOW_EVIDENCE: True})

    _render_group_comparison(st, _DF, 0.05)

    frames = [args[0] for args in st.charts() if "group" in getattr(args[0], "columns", [])]
    assert frames
    assert list(frames[0]["group"]) == ["a", "b"]
    assert "no individual" in st.texts()


def test_effect_evidence_never_recomputes_the_effect_sizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("scipy")
    calls: list[int] = []
    original = statistics_lab.nonparametric_effect_sizes

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(statistics_lab, "nonparametric_effect_sizes", counting)

    _render_nonparametric_effect_sizes(
        FakeSt({statistics_lab._STATS_EFFECT_SHOW_EVIDENCE: True}), _DF, "value", "group", 0.05
    )

    assert len(calls) == 1


# ── R4: exact Hodges-Lehmann pairwise ceiling ───────────────────────────────

# 1,000 x 1,001 = 1,001,000 pairs: one step past the exact Hodges-Lehmann ceiling.
_OVER_CEILING_DF = pd.DataFrame(
    {
        "group": ["a"] * 1000 + ["b"] * 1001,
        "value": [float(i % 17) for i in range(1000)] + [float(i % 13 + 2) for i in range(1001)],
    }
)


class _PairwiseTripwire:
    """Stands in for ``numpy`` inside ``effect_size`` only; forbids ``np.subtract``."""

    def __init__(self) -> None:
        self.pairwise_calls = 0

    def __getattr__(self, name: str) -> Any:
        if name == "subtract":
            self.pairwise_calls += 1
            raise AssertionError("a full pairwise difference array was requested")
        return getattr(np, name)


@pytest.fixture
def tripwire(monkeypatch: pytest.MonkeyPatch) -> _PairwiseTripwire:
    armed = _PairwiseTripwire()
    monkeypatch.setattr(effect_size, "np", armed)
    return armed


def _metrics(st: FakeSt) -> dict[str, Any]:
    return {a[0]: a[1] for name, a, _k in st.calls if name == "metric"}


def test_over_ceiling_split_renders_cliffs_and_a_bounded_limit_message(
    tripwire: _PairwiseTripwire,
) -> None:
    pytest.importorskip("scipy")
    st = FakeSt()

    _render_nonparametric_effect_sizes(st, _OVER_CEILING_DF, "value", "group", 0.05)

    assert tripwire.pairwise_calls == 0
    metrics = _metrics(st)
    assert metrics["Cliff's delta"] != "n/a"
    float(metrics["Cliff's delta"])
    assert metrics["Sample sizes"] == "1,000 · 1,001"
    # The exact estimate was not computed, so nothing numeric stands in for it.
    assert metrics["Hodges-Lehmann estimate"] == "n/a"
    assert "Lower bound" not in metrics
    assert "Upper bound" not in metrics
    infos = [str(a[0]) for name, a, _k in st.calls if name == "info"]
    assert len(infos) == 1
    assert "not computed" in infos[0]
    assert "1,000,000 pairwise differences" in infos[0]
    assert len(infos[0]) < 300


def test_over_ceiling_evidence_view_draws_no_estimate(tripwire: _PairwiseTripwire) -> None:
    st = FakeSt({statistics_lab._STATS_EFFECT_SHOW_EVIDENCE: True})

    _render_nonparametric_effect_sizes(st, _OVER_CEILING_DF, "value", "group", 0.05)

    assert tripwire.pairwise_calls == 0
    assert not st.charts()
    assert "Evidence view unavailable" in st.texts()
