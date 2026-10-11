"""Tests for the Statistics Lab confidence-interval section render (page tier).

Reuses the lightweight ``FakeSt`` recorder pattern from
``test_statistics_lab_inferential.py``. The bootstrap-percentile path renders
without scipy; the closed-form mean path is guarded with ``importorskip`` so the
suite passes with or without the optional ``[stats]`` extra.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.pages import statistics_lab
from data_quality_toolkit.adapters.ui.pages.statistics_lab import (
    _render_confidence_intervals,
)


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


_DF = pd.DataFrame({"value": [float(i % 7) + (i * 0.1) for i in range(40)]})


def test_section_header_always_renders() -> None:
    st = FakeSt()
    _render_confidence_intervals(st, _DF)
    assert "Confidence interval" in st.texts()


def test_no_numeric_columns_shows_info() -> None:
    st = FakeSt()
    _render_confidence_intervals(st, pd.DataFrame({"c": ["a", "b", "c"]}))
    assert st.called("info")
    assert "numeric column" in st.texts()


def test_bootstrap_path_renders_without_scipy() -> None:
    # FakeSt.selectbox returns the first option; force the bootstrap method so the
    # rendered path is the pure-numpy percentile bootstrap (no scipy required).
    st = FakeSt()

    def _method_first(*_args: Any, **kwargs: Any) -> Any:
        if kwargs.get("key") == statistics_lab._STATS_CI_METHOD:
            return "Bootstrap mean (percentile)"
        options = list(_args[1]) if len(_args) > 1 else []
        return options[0] if options else None

    st.selectbox = _method_first  # type: ignore[method-assign]
    _render_confidence_intervals(st, _DF)
    assert st.called("metric")  # metric cards rendered for an ok result


def test_mean_path_renders_metric_cards_with_scipy() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()
    _render_confidence_intervals(st, _DF)  # default first option = "Mean (t-interval)"
    assert st.called("metric")
    assert "confidence interval" in st.texts().lower()


def test_unavailable_status_surfaces_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        statistics_lab,
        "mean_confidence_interval",
        lambda *_a, **_k: {
            "status": "unavailable",
            "reason": "scipy is not installed",
            "method": "t",
            "confidence": 0.95,
            "point": None,
            "lower": None,
            "upper": None,
            "n": None,
        },
    )
    st = FakeSt()
    _render_confidence_intervals(st, _DF)
    assert st.called("warning")
    assert "scipy is not installed" in st.texts()


def test_invalid_status_surfaces_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        statistics_lab,
        "mean_confidence_interval",
        lambda *_a, **_k: {
            "status": "insufficient_data",
            "reason": "need at least 2 finite values",
            "method": "t",
            "confidence": 0.95,
            "point": None,
            "lower": None,
            "upper": None,
            "n": 1,
        },
    )
    st = FakeSt()
    _render_confidence_intervals(st, _DF)
    assert st.called("info")
    assert "at least 2" in st.texts()


def test_no_crash_on_tiny_frame() -> None:
    tiny = pd.DataFrame({"value": [1.0]})
    st = FakeSt()
    _render_confidence_intervals(st, tiny)  # must not raise on degenerate input
    assert "Confidence interval" in st.texts()


# ── opt-in estimate / interval evidence ──────────────────────────────────


def test_interval_evidence_is_off_by_default() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()

    _render_confidence_intervals(st, _DF)

    assert not st.charts()
    assert "Point estimate with its interval" not in st.texts()


def test_interval_evidence_renders_point_and_bounds_when_enabled() -> None:
    pytest.importorskip("scipy")
    st = FakeSt({statistics_lab._STATS_CI_SHOW_EVIDENCE: True})

    _render_confidence_intervals(st, _DF)

    charts = st.charts()
    assert charts
    data = charts[0][0]
    assert {"label", "estimate", "lower", "upper"} <= set(data.columns)
    assert bool(data.iloc[0]["interval_available"]) is True
    # Numbers stay readable as text, never conveyed by geometry alone.
    assert st.called("dataframe")


def test_interval_evidence_carries_its_uncertainty_caveats() -> None:
    pytest.importorskip("scipy")
    st = FakeSt({statistics_lab._STATS_CI_SHOW_EVIDENCE: True})

    _render_confidence_intervals(st, _DF)

    text = st.texts()
    assert "not that the reference is the true value" in text
    assert "Uncertainty" in text
    assert "What this does not show" in text


def test_interval_evidence_adds_no_second_service_call(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    calls: list[int] = []
    original = statistics_lab.mean_confidence_interval

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(statistics_lab, "mean_confidence_interval", counting)

    _render_confidence_intervals(FakeSt({statistics_lab._STATS_CI_SHOW_EVIDENCE: True}), _DF)

    assert len(calls) == 1


def test_interval_evidence_is_not_offered_for_an_unavailable_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        statistics_lab,
        "mean_confidence_interval",
        lambda *_a, **_k: {
            "status": "unavailable",
            "reason": "scipy is not installed",
            "method": "t",
            "confidence": 0.95,
            "point": None,
            "lower": None,
            "upper": None,
            "n": None,
        },
    )
    st = FakeSt({statistics_lab._STATS_CI_SHOW_EVIDENCE: True})

    _render_confidence_intervals(st, _DF)

    assert st.called("warning")
    assert not st.charts()
