"""Tests for the inferential-statistics domain helpers.

Covers the scipy-unavailable path (monkeypatched), deterministic orchestration
via a FakeStats stand-in, real-scipy correctness behind importorskip, and the
bounded/invalid/insufficient edge cases. Mirrors the guarding style of
``tests/unit/statistics/test_drift.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.domain.statistics import inferential


class FakeStats:
    """Deterministic stand-in for scipy.stats."""

    def __init__(self, p: float = 0.5) -> None:
        self.p = p

    def shapiro(self, a: Any) -> SimpleNamespace:
        return SimpleNamespace(statistic=0.95, pvalue=self.p)

    def ttest_ind(self, a: Any, b: Any, equal_var: bool = True) -> SimpleNamespace:
        return SimpleNamespace(statistic=2.0, pvalue=self.p)

    def mannwhitneyu(self, a: Any, b: Any, alternative: str = "two-sided") -> SimpleNamespace:
        return SimpleNamespace(statistic=10.0, pvalue=self.p)

    def f_oneway(self, *arrays: Any) -> SimpleNamespace:
        return SimpleNamespace(statistic=3.0, pvalue=self.p)

    def kruskal(self, *arrays: Any) -> SimpleNamespace:
        return SimpleNamespace(statistic=4.0, pvalue=self.p)


def _patch(monkeypatch: pytest.MonkeyPatch, fake: FakeStats | None) -> None:
    monkeypatch.setattr(inferential, "_import_scipy_stats", lambda: fake)


def _two_group_df(n: int = 20) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "metric": np.concatenate([rng.normal(0, 1, n), rng.normal(1, 1, n)]),
            "group": ["a"] * n + ["b"] * n,
        }
    )


# ── unavailable path ─────────────────────────────────────────────────────────


class TestUnavailable:
    def test_normality_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, None)
        result = inferential.check_normality(pd.Series([1.0, 2.0, 3.0, 4.0]))
        assert result["status"] == "unavailable"
        assert result["scipy_available"] is False
        assert "data-quality-toolkit[stats]" in result["reason"]

    def test_two_group_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, None)
        result = inferential.compare_two_groups(_two_group_df(), "metric", "group")
        assert result["status"] == "unavailable"
        assert result["scipy_available"] is False

    def test_multi_group_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, None)
        result = inferential.compare_multi_group(_two_group_df(), "metric", "group")
        assert result["status"] == "unavailable"

    def test_ab_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, None)
        result = inferential.ab_compare(_two_group_df(), "group", "a", "b", "metric")
        assert result["status"] == "unavailable"


# ── orchestration via FakeStats (no scipy required) ──────────────────────────


class TestOrchestration:
    def test_normality_ok_significant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(p=0.001))
        result = inferential.check_normality(pd.Series(range(10)), alpha=0.05)
        assert result["status"] == "ok"
        assert result["method"] == "shapiro_wilk"
        assert "evidence against normality" in result["interpretation"]

    def test_normality_ok_not_significant_wording(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(p=0.9))
        result = inferential.check_normality(pd.Series(range(10)), alpha=0.05)
        assert "no strong evidence against normality" in result["interpretation"]
        # Never overclaims.
        assert "proves normal" not in result["interpretation"].lower()

    def test_normality_down_samples_above_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(p=0.2))
        result = inferential.check_normality(pd.Series(range(100)), max_sample=10)
        assert result["status"] == "ok"
        assert result["sample_size"] == 10
        assert any("down-sampled" in w for w in result["warnings"])

    def test_normality_skipped_large_sample(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(p=0.2))
        result = inferential.check_normality(pd.Series(range(100)), hard_cap=10)
        assert result["status"] == "skipped_large_sample"

    def test_two_group_ok_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(p=0.01))
        result = inferential.compare_two_groups(_two_group_df(), "metric", "group", alpha=0.05)
        assert result["status"] == "ok"
        assert result["group_a"] == "a"
        assert result["group_b"] == "b"
        assert result["n_a"] == 20 and result["n_b"] == 20
        assert result["welch"]["significant"] is True
        assert result["mann_whitney"]["significant"] is True
        assert result["cohens_d"] is not None
        assert result["effect_size_label"].startswith("Cohen's d")

    def test_two_group_too_many_groups(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats())
        df = pd.DataFrame({"metric": range(9), "group": ["a", "b", "c"] * 3})
        result = inferential.compare_two_groups(df, "metric", "group")
        assert result["status"] == "too_many_groups"

    def test_two_group_too_few_groups(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats())
        df = pd.DataFrame({"metric": [1.0, 2.0, 3.0], "group": ["a", "a", "a"]})
        result = inferential.compare_two_groups(df, "metric", "group")
        assert result["status"] == "too_few_groups"

    def test_invalid_type_non_numeric_metric(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats())
        df = pd.DataFrame({"metric": ["x", "y", "z", "w"], "group": ["a", "a", "b", "b"]})
        result = inferential.compare_two_groups(df, "metric", "group")
        assert result["status"] == "invalid_type"

    def test_insufficient_data_small_groups(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats())
        df = pd.DataFrame({"metric": [1.0, 2.0], "group": ["a", "b"]})
        result = inferential.compare_two_groups(df, "metric", "group", min_group_n=3)
        assert result["status"] == "insufficient_data"

    def test_nan_dropped_before_compute(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(p=0.2))
        df = pd.DataFrame(
            {
                "metric": [1.0, 2.0, 3.0, np.nan, 5.0, 6.0, 7.0, 8.0],
                "group": ["a", "a", "a", "a", "b", "b", "b", "b"],
            }
        )
        result = inferential.compare_two_groups(df, "metric", "group")
        assert result["status"] == "ok"
        assert result["n_a"] == 3  # NaN row removed

    def test_multi_group_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(p=0.2))
        df = pd.DataFrame({"metric": list(range(12)), "group": (["a", "b", "c", "d"] * 3)})
        result = inferential.compare_multi_group(df, "metric", "group")
        assert result["status"] == "ok"
        assert result["n_groups"] == 4
        assert {g["group"] for g in result["groups"]} == {"a", "b", "c", "d"}

    def test_multi_group_truncates_above_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(p=0.2))
        rng = np.random.default_rng(1)
        groups = [f"g{i}" for i in range(6) for _ in range(4)]
        df = pd.DataFrame({"metric": rng.normal(size=len(groups)), "group": groups})
        result = inferential.compare_multi_group(df, "metric", "group", max_groups=3)
        assert result["truncated"] is True
        assert result["n_groups"] == 3
        assert any("truncated" in w for w in result["warnings"])

    def test_ab_invalid_when_values_equal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats())
        result = inferential.ab_compare(_two_group_df(), "group", "a", "a", "metric")
        assert result["status"] == "invalid_type"

    def test_ab_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(p=0.01))
        result = inferential.ab_compare(_two_group_df(), "group", "a", "b", "metric")
        assert result["status"] == "ok"
        assert result["group_a"] == "a"
        assert result["group_b"] == "b"


# ── alpha validation ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1, 1.5])
def test_invalid_alpha_raises(alpha: float) -> None:
    with pytest.raises(ValueError, match="alpha"):
        inferential.check_normality(pd.Series([1.0, 2.0, 3.0]), alpha=alpha)


# ── Cohen's d math ───────────────────────────────────────────────────────────


class TestCohensD:
    def test_zero_when_identical(self) -> None:
        a = np.array([1.0, 2.0, 3.0, 4.0])
        assert inferential._cohens_d(a, a.copy()) == 0.0

    def test_zero_pooled_sd_returns_zero(self) -> None:
        a = np.array([5.0, 5.0, 5.0])
        b = np.array([5.0, 5.0, 5.0])
        assert inferential._cohens_d(a, b) == 0.0

    def test_sign_matches_mean_difference(self) -> None:
        a = np.array([10.0, 11.0, 12.0, 13.0])
        b = np.array([1.0, 2.0, 3.0, 4.0])
        assert inferential._cohens_d(a, b) > 0


# ── real scipy correctness ───────────────────────────────────────────────────


class TestRealScipy:
    def test_normality_rejects_clearly_nonnormal(self) -> None:
        pytest.importorskip("scipy")
        # Heavily skewed exponential-like data should give evidence against normality.
        rng = np.random.default_rng(7)
        series = pd.Series(rng.exponential(1.0, 400))
        result = inferential.check_normality(series, alpha=0.05)
        assert result["status"] == "ok"
        assert result["p_value"] < 0.05

    def test_two_group_detects_shift(self) -> None:
        pytest.importorskip("scipy")
        rng = np.random.default_rng(7)
        df = pd.DataFrame(
            {
                "metric": np.concatenate([rng.normal(0, 1, 200), rng.normal(3, 1, 200)]),
                "group": ["a"] * 200 + ["b"] * 200,
            }
        )
        result = inferential.compare_two_groups(df, "metric", "group")
        assert result["status"] == "ok"
        assert result["welch"]["significant"] is True
        assert result["mann_whitney"]["significant"] is True

    def test_two_group_no_difference(self) -> None:
        pytest.importorskip("scipy")
        rng = np.random.default_rng(7)
        values = rng.normal(0, 1, 400)
        df = pd.DataFrame({"metric": values, "group": ["a"] * 200 + ["b"] * 200})
        result = inferential.compare_two_groups(df, "metric", "group")
        assert result["status"] == "ok"
        assert result["welch"]["significant"] is False

    def test_multi_group_detects_difference(self) -> None:
        pytest.importorskip("scipy")
        rng = np.random.default_rng(7)
        df = pd.DataFrame(
            {
                "metric": np.concatenate(
                    [rng.normal(0, 1, 100), rng.normal(2, 1, 100), rng.normal(4, 1, 100)]
                ),
                "group": ["a"] * 100 + ["b"] * 100 + ["c"] * 100,
            }
        )
        result = inferential.compare_multi_group(df, "metric", "group")
        assert result["status"] == "ok"
        assert result["anova"]["significant"] is True
        assert result["kruskal"]["significant"] is True
