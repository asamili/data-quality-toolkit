"""Tests for effect-size estimators (Cohen's d, Cliff's delta, Hodges-Lehmann)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from data_quality_toolkit.domain.statistics import effect_size

_LIMIT = effect_size.MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS


class _PairwiseTripwire:
    """Stands in for ``numpy`` inside ``effect_size`` only; forbids the pairwise builder.

    Every attribute is delegated to numpy except ``subtract`` (the
    ``np.subtract.outer`` pair materializer), which raises instead.
    """

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


def _reference_cliffs_delta(a: list[float], b: list[float]) -> float:
    """Definition-level Cliff's delta over every pair (tiny test vectors only)."""
    total = sum((x > y) - (x < y) for x in a for y in b)
    return total / (len(a) * len(b))


def _reference_hodges_lehmann(a: np.ndarray, b: np.ndarray, confidence: float) -> dict[str, Any]:
    """The exact pre-bound HL formula, recomputed independently (<= the ceiling)."""
    stats = pytest.importorskip("scipy.stats")
    diffs = np.subtract.outer(a, b).ravel()
    estimate = float(np.median(diffs))
    margin = float(stats.norm.ppf((1.0 + confidence) / 2.0)) * (
        float(np.std(diffs, ddof=1)) / np.sqrt(diffs.size)
    )
    return {
        "estimate": round(estimate, 6),
        "lower": round(estimate - margin, 6),
        "upper": round(estimate + margin, 6),
    }


class TestCohenD:
    def test_zero_when_identical(self) -> None:
        a = np.array([1.0, 2.0, 3.0, 4.0])
        assert effect_size.cohen_d(a, a.copy()) == 0.0

    def test_zero_pooled_sd(self) -> None:
        assert effect_size.cohen_d([5.0, 5.0, 5.0], [5.0, 5.0, 5.0]) == 0.0

    def test_sign_follows_mean_difference(self) -> None:
        assert effect_size.cohen_d([10.0, 11.0, 12.0, 13.0], [1.0, 2.0, 3.0, 4.0]) > 0
        assert effect_size.cohen_d([1.0, 2.0, 3.0, 4.0], [10.0, 11.0, 12.0, 13.0]) < 0

    def test_insufficient_data_returns_zero(self) -> None:
        assert effect_size.cohen_d([1.0], [2.0, 3.0]) == 0.0

    def test_drops_non_finite(self) -> None:
        a = [1.0, 2.0, 3.0, np.nan]
        b = [4.0, 5.0, 6.0, np.inf]
        assert effect_size.cohen_d(a, b) == pytest.approx(
            effect_size.cohen_d([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
        )


class TestCliffsDelta:
    def test_perfect_separation_positive(self) -> None:
        assert effect_size.cliffs_delta([10, 11, 12], [1, 2, 3]) == pytest.approx(1.0)

    def test_perfect_separation_negative(self) -> None:
        assert effect_size.cliffs_delta([1, 2, 3], [10, 11, 12]) == pytest.approx(-1.0)

    def test_identical_is_zero(self) -> None:
        assert effect_size.cliffs_delta([1, 2, 3], [1, 2, 3]) == pytest.approx(0.0)

    def test_bounded(self) -> None:
        rng = np.random.default_rng(0)
        d = effect_size.cliffs_delta(rng.normal(size=50), rng.normal(size=50))
        assert -1.0 <= d <= 1.0


_CLIFFS_CASES = {
    "single_greater": ([2.0], [1.0]),
    "single_less": ([1.0], [2.0]),
    "single_tie": ([3.0], [3.0]),
    "all_a_greater": ([10.0, 11.0, 12.0], [1.0, 2.0, 3.0]),
    "all_a_less": ([1.0, 2.0, 3.0], [10.0, 11.0, 12.0]),
    "identical": ([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]),
    "ties": ([1.0, 2.0, 2.0, 3.0], [2.0, 2.0, 4.0]),
    "repeated_values": ([5.0] * 6 + [1.0], [5.0] * 3 + [9.0, 9.0]),
    "negatives": ([-3.0, -1.0, -7.5], [-2.0, -1.0, 0.0, -9.0]),
    "floats": ([0.1, 0.2, 0.30000000000000004], [0.3, 0.2, 0.1 + 0.2]),
    "signed_zero": ([0.0, -0.0, 1.0], [-0.0, 0.0]),
    "unequal_sizes": ([1.0, 4.0], [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
    "extreme_magnitudes": ([1e308, -1e308, 5e-324], [-1e308, 0.0, 1e308]),
}


class TestCliffsDeltaExactness:
    """The sorted-count Cliff's delta reproduces the pairwise definition exactly."""

    @pytest.mark.parametrize("case", sorted(_CLIFFS_CASES))
    def test_matches_the_pairwise_definition(self, case: str) -> None:
        a, b = _CLIFFS_CASES[case]
        assert effect_size.cliffs_delta(a, b) == _reference_cliffs_delta(a, b)

    def test_single_values_hit_every_sign(self) -> None:
        assert effect_size.cliffs_delta([2.0], [1.0]) == 1.0
        assert effect_size.cliffs_delta([1.0], [2.0]) == -1.0
        assert effect_size.cliffs_delta([1.0], [1.0]) == 0.0

    def test_tied_counts_are_exact_fractions(self) -> None:
        a = [1.0, 2.0, 2.0, 3.0]
        b = [1.0, 2.0, 3.0]
        # greater pairs: (2,1)x2, (3,1), (3,2) = 4 ; lesser pairs: (1,2), (1,3), (2,3)x2 = 4
        assert effect_size.cliffs_delta(a, b) == 0.0
        assert effect_size.cliffs_delta(a, [1.0]) == 3 / 4

    def test_empty_either_group_returns_zero(self) -> None:
        assert effect_size.cliffs_delta([], [1.0, 2.0]) == 0.0
        assert effect_size.cliffs_delta([1.0, 2.0], []) == 0.0
        assert effect_size.cliffs_delta([], []) == 0.0
        assert effect_size.cliffs_delta([np.nan, np.inf], [1.0]) == 0.0

    def test_non_finite_values_are_dropped_before_counting(self) -> None:
        a = [1.0, np.nan, 3.0, -np.inf]
        b = [2.0, np.inf, 2.0]
        assert effect_size.cliffs_delta(a, b) == _reference_cliffs_delta([1.0, 3.0], [2.0, 2.0])

    def test_returns_a_python_float(self) -> None:
        assert type(effect_size.cliffs_delta([1, 2, 3], [2, 3])) is float

    def test_deterministic_random_vectors_match_the_definition(self) -> None:
        rng = np.random.default_rng(20260922)
        for trial in range(300):
            na, nb = (int(n) for n in rng.integers(1, 25, size=2))
            if trial % 3 == 0:
                a = rng.integers(-4, 5, size=na).astype(float).tolist()
                b = rng.integers(-4, 5, size=nb).astype(float).tolist()
            elif trial % 3 == 1:
                a = rng.normal(size=na).round(1).tolist()
                b = rng.normal(0.25, size=nb).round(1).tolist()
            else:
                a = rng.normal(size=na).tolist()
                b = rng.normal(size=nb).tolist()
            assert effect_size.cliffs_delta(a, b) == _reference_cliffs_delta(a, b)

    def test_never_materializes_pairwise_differences(self, tripwire: _PairwiseTripwire) -> None:
        a = np.arange(30_000, dtype=float) % 97
        b = np.arange(45_000, dtype=float) % 89
        # 1.35 billion pairs: only reachable with a bounded-memory exact algorithm.
        delta = effect_size.cliffs_delta(a, b)
        assert -1.0 <= delta <= 1.0
        assert tripwire.pairwise_calls == 0


class TestHodgesLehmann:
    def test_estimate_is_median_pairwise_diff(self) -> None:
        # a shifted +5 from b -> HL estimate ~ 5
        est = effect_size.hodges_lehmann_estimate([6, 7, 8], [1, 2, 3])
        assert est == pytest.approx(5.0)

    def test_estimate_empty_returns_zero(self) -> None:
        assert effect_size.hodges_lehmann_estimate([], [1, 2]) == 0.0

    def test_ci_ok_contains_estimate(self) -> None:
        pytest.importorskip("scipy")
        rng = np.random.default_rng(1)
        result = effect_size.hodges_lehmann_ci(rng.normal(5, 1, 40), rng.normal(0, 1, 40))
        assert result["status"] == "ok"
        assert result["lower"] <= result["estimate"] <= result["upper"]

    def test_ci_insufficient(self) -> None:
        pytest.importorskip("scipy")
        result = effect_size.hodges_lehmann_ci([1.0], [2.0])
        assert result["status"] == "insufficient_data"

    def test_ci_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(effect_size, "import_scipy_stats", lambda: None)
        result = effect_size.hodges_lehmann_ci([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
        assert result["status"] == "unavailable"


def _ties_sample(size: int, offset: int) -> np.ndarray:
    """Deterministic integer-valued sample with heavy ties."""
    return ((np.arange(size) * 7 + offset) % 31).astype(float)


class TestHodgesLehmannPairwiseCeiling:
    """Exact HL below/at the ceiling is unchanged; above it nothing is materialized."""

    def test_ceiling_is_the_admitted_value(self) -> None:
        assert _LIMIT == 1_000_000
        assert "1,000,000 pairwise differences" in effect_size.PAIRWISE_LIMIT_REASON
        assert len(effect_size.PAIRWISE_LIMIT_REASON) < 300

    def test_pairwise_comparison_count_uses_finite_values_only(self) -> None:
        assert effect_size.pairwise_comparison_count([1.0, np.nan, 2.0], [np.inf, 3.0]) == 2
        assert effect_size.pairwise_comparison_count([], [1.0]) == 0
        assert effect_size.pairwise_comparison_count(np.zeros(29_706), np.zeros(44_405)) == (
            1_319_094_930
        )

    @pytest.mark.parametrize(("na", "nb"), [(999, 1000), (1000, 1000)])
    def test_ci_at_or_below_the_ceiling_is_the_exact_formula(self, na: int, nb: int) -> None:
        pytest.importorskip("scipy")
        a, b = _ties_sample(na, 3), _ties_sample(nb, 0)
        for confidence in (0.90, 0.95, 0.99):
            result = effect_size.hodges_lehmann_ci(a, b, confidence=confidence)
            assert result["status"] == "ok"
            assert result["method"] == "hodges_lehmann_normal_approx"
            expected = _reference_hodges_lehmann(a, b, confidence)
            assert {key: result[key] for key in expected} == expected

    @pytest.mark.parametrize(("na", "nb"), [(999, 1000), (1000, 1000)])
    def test_estimate_at_or_below_the_ceiling_is_the_exact_median(self, na: int, nb: int) -> None:
        a, b = _ties_sample(na, 3), _ties_sample(nb, 0)
        expected = float(np.median(np.subtract.outer(a, b).ravel()))
        assert effect_size.hodges_lehmann_estimate(a, b) == expected

    @pytest.mark.parametrize(
        ("na", "nb", "materialized"),
        [(999, 1000, 999_000), (1000, 1000, 1_000_000), (1000, 1001, None), (1001, 1000, None)],
    )
    def test_pairwise_builder_is_reached_only_within_the_ceiling(
        self, monkeypatch: pytest.MonkeyPatch, na: int, nb: int, materialized: int | None
    ) -> None:
        pytest.importorskip("scipy")
        sizes: list[int] = []
        original = effect_size._pairwise_differences

        def spy(arr_a: np.ndarray, arr_b: np.ndarray) -> np.ndarray:
            sizes.append(int(arr_a.size) * int(arr_b.size))
            return original(arr_a, arr_b)

        monkeypatch.setattr(effect_size, "_pairwise_differences", spy)
        result = effect_size.hodges_lehmann_ci(np.zeros(na), np.ones(nb))
        if materialized is None:
            assert sizes == []
            assert result["status"] == effect_size.PAIRWISE_LIMIT_STATUS
        else:
            assert sizes == [materialized]
            assert result["status"] == "ok"
            assert result["estimate"] == -1.0

    def test_ci_above_the_ceiling_is_refused_before_materialization(
        self, tripwire: _PairwiseTripwire
    ) -> None:
        pytest.importorskip("scipy")
        result = effect_size.hodges_lehmann_ci(np.zeros(1000), np.ones(1001), confidence=0.9)
        assert tripwire.pairwise_calls == 0
        assert result == {
            "status": "pairwise_limit_exceeded",
            "reason": effect_size.PAIRWISE_LIMIT_REASON,
            "confidence": 0.9,
            "estimate": None,
            "lower": None,
            "upper": None,
            "method": "hodges_lehmann_normal_approx",
        }

    def test_ci_at_pathological_scale_is_refused_before_materialization(
        self, tripwire: _PairwiseTripwire
    ) -> None:
        pytest.importorskip("scipy")
        result = effect_size.hodges_lehmann_ci(np.zeros(29_706), np.ones(44_405))
        assert tripwire.pairwise_calls == 0
        assert result["status"] == effect_size.PAIRWISE_LIMIT_STATUS
        assert result["estimate"] is None

    def test_ci_without_scipy_above_the_ceiling_never_materializes(
        self, monkeypatch: pytest.MonkeyPatch, tripwire: _PairwiseTripwire
    ) -> None:
        monkeypatch.setattr(effect_size, "import_scipy_stats", lambda: None)
        result = effect_size.hodges_lehmann_ci(np.zeros(29_706), np.ones(44_405))
        assert result["status"] == "unavailable"
        assert tripwire.pairwise_calls == 0

    @pytest.mark.parametrize(("na", "nb"), [(1000, 1001), (29_706, 44_405)])
    def test_estimate_above_the_ceiling_raises_before_materialization(
        self, tripwire: _PairwiseTripwire, na: int, nb: int
    ) -> None:
        with pytest.raises(effect_size.PairwiseLimitExceededError) as caught:
            effect_size.hodges_lehmann_estimate(np.full(na, 7.25), np.full(nb, 3.5))
        assert tripwire.pairwise_calls == 0
        message = str(caught.value)
        assert message == effect_size.PAIRWISE_LIMIT_REASON
        assert "7.25" not in message
        assert "3.5" not in message

    def test_limit_error_is_a_value_error(self) -> None:
        assert issubclass(effect_size.PairwiseLimitExceededError, ValueError)

    def test_non_finite_values_do_not_count_toward_the_ceiling(self) -> None:
        pytest.importorskip("scipy")
        padded = np.concatenate([_ties_sample(1000, 3), np.full(5, np.nan)])
        result = effect_size.hodges_lehmann_ci(padded, _ties_sample(1000, 0))
        assert result["status"] == "ok"
