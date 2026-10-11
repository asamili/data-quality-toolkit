"""Tests for the assumption-check domain kernel (Levene equal-variance).

Covers the scipy-unavailable path (monkeypatched), deterministic orchestration
via a FakeStats stand-in, real-scipy correctness behind importorskip, and the
not-applicable / insufficient edge cases. Mirrors the guarding style of
``tests/unit/statistics/test_inferential.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from data_quality_toolkit.domain.statistics import assumptions


class FakeStats:
    """Deterministic stand-in for scipy.stats."""

    def __init__(self, p: float = 0.5) -> None:
        self.p = p

    def levene(self, *arrays: Any, center: str = "median") -> SimpleNamespace:
        return SimpleNamespace(statistic=1.5, pvalue=self.p)


def _patch(monkeypatch: pytest.MonkeyPatch, fake: FakeStats | None) -> None:
    monkeypatch.setattr(assumptions, "import_scipy_stats", lambda: fake)


def _two_groups() -> list[list[float]]:
    return [[1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 4.0, 6.0, 8.0, 10.0]]


# ── unavailable path ─────────────────────────────────────────────────────────


def test_equal_variance_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, None)
    result = assumptions.check_equal_variance(_two_groups())
    assert result["status"] == "unavailable"
    assert result["scipy_available"] is False
    assert "data-quality-toolkit[stats]" in result["reason"]


# ── orchestration via FakeStats (no scipy required) ──────────────────────────


def test_equal_variance_ok_no_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, FakeStats(p=0.9))
    result = assumptions.check_equal_variance(_two_groups(), alpha=0.05)
    assert result["status"] == "ok"
    assert result["method"] == "levene"
    assert result["n_groups"] == 2
    assert "no strong evidence of unequal variance" in result["interpretation"]
    assert "proves equal" not in result["interpretation"].lower()


def test_equal_variance_ok_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, FakeStats(p=0.001))
    result = assumptions.check_equal_variance(_two_groups(), alpha=0.05)
    assert result["status"] == "ok"
    assert "evidence of unequal variance" in result["interpretation"]


def test_equal_variance_too_few_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, FakeStats())
    result = assumptions.check_equal_variance([[1.0, 2.0, 3.0]])
    assert result["status"] == "not_applicable"
    assert result["n_groups"] == 1


def test_equal_variance_small_groups_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, FakeStats())
    # Second group has only 2 values (< min_group_n=3) so it is dropped, leaving one group.
    result = assumptions.check_equal_variance([[1.0, 2.0, 3.0, 4.0], [5.0, 6.0]])
    assert result["status"] == "not_applicable"
    assert result["n_groups"] == 1


def test_equal_variance_all_constant_not_applicable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, FakeStats())
    result = assumptions.check_equal_variance([[5.0, 5.0, 5.0], [5.0, 5.0, 5.0]])
    assert result["status"] == "not_applicable"
    assert "constant" in result["reason"]


def test_equal_variance_nan_result_insufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, FakeStats(p=float("nan")))
    result = assumptions.check_equal_variance(_two_groups())
    assert result["status"] == "insufficient_data"


def test_equal_variance_drops_non_finite(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, FakeStats(p=0.5))
    groups = [[1.0, 2.0, 3.0, np.nan], [4.0, 5.0, 6.0, np.inf]]
    result = assumptions.check_equal_variance(groups)
    assert result["status"] == "ok"
    assert result["n_groups"] == 2


# ── alpha validation ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1, 1.5])
def test_invalid_alpha_raises(alpha: float) -> None:
    with pytest.raises(ValueError, match="alpha"):
        assumptions.check_equal_variance(_two_groups(), alpha=alpha)


# ── real scipy correctness ───────────────────────────────────────────────────


class TestRealScipy:
    def test_equal_variance_no_evidence_when_equal(self) -> None:
        pytest.importorskip("scipy")
        rng = np.random.default_rng(7)
        groups = [list(rng.normal(0, 1, 200)), list(rng.normal(3, 1, 200))]
        result = assumptions.check_equal_variance(groups, alpha=0.05)
        assert result["status"] == "ok"
        assert result["p_value"] >= 0.05

    def test_equal_variance_detects_unequal(self) -> None:
        pytest.importorskip("scipy")
        rng = np.random.default_rng(7)
        groups = [list(rng.normal(0, 1, 200)), list(rng.normal(0, 5, 200))]
        result = assumptions.check_equal_variance(groups, alpha=0.05)
        assert result["status"] == "ok"
        assert result["p_value"] < 0.05
        assert "evidence of unequal variance" in result["interpretation"]
