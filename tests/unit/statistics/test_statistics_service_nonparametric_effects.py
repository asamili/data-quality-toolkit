"""Tests for the nonparametric effect-size wrapper in the Statistics Lab service.

The service stays streamlit-free and wires the existing effect-size kernel
(``cliffs_delta``, ``hodges_lehmann_estimate``, ``hodges_lehmann_ci``). These
tests pin the ok-path shape, the group-count / insufficient / invalid statuses,
the sign orientation (matching the domain two-group ordering), the graceful
scipy-absent degrade for the Hodges-Lehmann confidence band, and the exact pairwise
ceiling: above it Hodges-Lehmann is reported as not computed while Cliff's delta stays.
"""

from __future__ import annotations

import inspect
import tracemalloc
from typing import Any

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.services import statistics as svc
from data_quality_toolkit.domain.statistics import effect_size


def _df(n: int = 30) -> pd.DataFrame:
    """Two well-separated groups (b clearly above a) for a stable effect size."""
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "metric": np.concatenate([rng.normal(0.0, 1.0, n), rng.normal(4.0, 1.0, n)]),
            "group": ["a"] * n + ["b"] * n,
        }
    )


def test_service_stays_streamlit_free() -> None:
    src = inspect.getsource(svc)
    assert "import streamlit" not in src


def test_ok_shape_and_keys() -> None:
    result = svc.nonparametric_effect_sizes(_df(), "metric", "group")
    assert result["status"] == "ok"
    assert result["group_a"] == "a"
    assert result["group_b"] == "b"
    assert result["n_a"] == 30
    assert result["n_b"] == 30
    assert -1.0 <= result["cliffs_delta"] <= 1.0
    assert result["cliffs_interpretation"] in {"negligible", "small", "medium", "large"}
    assert set(result["hodges_lehmann"]) >= {"status", "estimate", "method"}


def test_sign_orientation_matches_group_ordering() -> None:
    # b is centered above a; ordering is sorted(str) → group_a='a'. Since a < b,
    # Cliff's delta (a vs b) and the HL shift (a - b) are negative.
    result = svc.nonparametric_effect_sizes(_df(), "metric", "group")
    assert result["cliffs_delta"] < 0
    assert result["cliffs_interpretation"] == "large"
    assert float(result["hodges_lehmann"]["estimate"]) < 0


def test_cliffs_interpretation_bands() -> None:
    assert svc._cliffs_delta_interpretation(0.0) == "negligible"
    assert svc._cliffs_delta_interpretation(0.2) == "small"
    assert svc._cliffs_delta_interpretation(-0.4) == "medium"
    assert svc._cliffs_delta_interpretation(0.9) == "large"


def test_hodges_lehmann_ci_contains_estimate_with_scipy() -> None:
    pytest.importorskip("scipy")
    result = svc.nonparametric_effect_sizes(_df(), "metric", "group", confidence=0.95)
    hl = result["hodges_lehmann"]
    assert hl["status"] == "ok"
    assert hl["lower"] <= hl["estimate"] <= hl["upper"]
    assert hl["confidence"] == pytest.approx(0.95)


def test_too_many_groups_status() -> None:
    df = pd.DataFrame({"metric": [1.0, 2.0, 3.0], "group": ["a", "b", "c"]})
    result = svc.nonparametric_effect_sizes(df, "metric", "group")
    assert result["status"] == "too_many_groups"
    assert result["cliffs_delta"] is None


def test_too_few_groups_status() -> None:
    df = pd.DataFrame({"metric": [1.0, 2.0, 3.0], "group": ["a", "a", "a"]})
    result = svc.nonparametric_effect_sizes(df, "metric", "group")
    assert result["status"] == "too_few_groups"


def test_insufficient_data_status() -> None:
    df = pd.DataFrame({"metric": [1.0, 2.0], "group": ["a", "b"]})
    result = svc.nonparametric_effect_sizes(df, "metric", "group")
    assert result["status"] == "insufficient_data"


def test_non_numeric_metric_is_structured() -> None:
    df = pd.DataFrame({"metric": ["x", "y"], "group": ["a", "b"]})
    result = svc.nonparametric_effect_sizes(df, "metric", "group")
    assert result["status"] == "invalid_input"
    assert "not numeric" in str(result["reason"])


def test_missing_group_column_is_structured() -> None:
    result = svc.nonparametric_effect_sizes(_df(), "metric", "absent")
    assert result["status"] == "invalid_input"
    assert "group column not found" in str(result["reason"])


def test_scipy_absent_degrades_ci_but_keeps_cliffs_and_estimate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from data_quality_toolkit.domain.statistics import effect_size

    monkeypatch.setattr(effect_size, "import_scipy_stats", lambda: None)

    result = svc.nonparametric_effect_sizes(_df(), "metric", "group")
    assert result["status"] == "ok"
    assert result["cliffs_delta"] is not None
    hl = result["hodges_lehmann"]
    assert hl["status"] == "unavailable"
    # Point estimate still surfaced from the pure-numpy fallback.
    assert hl["estimate"] is not None


# ── exact pairwise ceiling ───────────────────────────────────────────────────


class _PairwiseTripwire:
    """Stands in for ``numpy`` inside ``effect_size`` only; forbids ``np.subtract``."""

    def __init__(self) -> None:
        self.pairwise_calls = 0

    def __getattr__(self, name: str) -> Any:
        if name == "subtract":
            self.pairwise_calls += 1
            raise AssertionError("a full pairwise difference array was requested")
        return getattr(np, name)


def _split_df(n_a: int, n_b: int) -> pd.DataFrame:
    """Deterministic tied integer metric split into groups 'a' (n_a) and 'b' (n_b)."""
    return pd.DataFrame(
        {
            "metric": np.concatenate(
                [np.arange(n_a) % 23 + 1.0, np.arange(n_b) % 19 + 3.0],
            ),
            "group": ["a"] * n_a + ["b"] * n_b,
        }
    )


def _arm_service_guard(monkeypatch: pytest.MonkeyPatch) -> _PairwiseTripwire:
    """Forbid every pairwise HL entry point the service could reach."""

    def forbidden(*_a: object, **_k: object) -> object:
        raise AssertionError("an exact Hodges-Lehmann computation was requested")

    tripwire = _PairwiseTripwire()
    monkeypatch.setattr(effect_size, "np", tripwire)
    monkeypatch.setattr(svc, "_hodges_lehmann_ci", forbidden)
    monkeypatch.setattr(svc, "_hodges_lehmann_estimate", forbidden)
    return tripwire


def _without_scipy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a missing scipy for the kernel and for the service's own ceiling branch."""
    monkeypatch.setattr(effect_size, "import_scipy_stats", lambda: None)
    monkeypatch.setattr(svc, "_import_scipy_stats", lambda: None)


def _assert_bounded_limit_state(result: dict[str, Any], confidence: float = 0.95) -> None:
    assert result["status"] == "ok"
    assert result["hodges_lehmann"] == {
        "status": "pairwise_limit_exceeded",
        "reason": effect_size.PAIRWISE_LIMIT_REASON,
        "confidence": confidence,
        "estimate": None,
        "lower": None,
        "upper": None,
        "method": "hodges_lehmann_normal_approx",
    }
    reason = str(result["hodges_lehmann"]["reason"])
    assert "1,000,000 pairwise differences" in reason
    assert len(reason) < 300


def test_normal_split_keeps_exact_kernel_semantics() -> None:
    pytest.importorskip("scipy")
    df = _split_df(40, 55)
    a = df.loc[df["group"] == "a", "metric"].tolist()
    b = df.loc[df["group"] == "b", "metric"].tolist()
    result = svc.nonparametric_effect_sizes(df, "metric", "group", confidence=0.9)
    assert result["cliffs_delta"] == round(effect_size.cliffs_delta(a, b), 6)
    assert result["hodges_lehmann"] == effect_size.hodges_lehmann_ci(a, b, confidence=0.9)
    assert result["hodges_lehmann"]["status"] == "ok"


def test_split_exactly_at_the_ceiling_is_computed_exactly() -> None:
    pytest.importorskip("scipy")
    df = _split_df(1000, 1000)
    a = df.loc[df["group"] == "a", "metric"].tolist()
    b = df.loc[df["group"] == "b", "metric"].tolist()
    result = svc.nonparametric_effect_sizes(df, "metric", "group")
    assert result["n_a"] * result["n_b"] == effect_size.MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS
    assert result["hodges_lehmann"] == effect_size.hodges_lehmann_ci(a, b)
    assert result["hodges_lehmann"]["status"] == "ok"
    assert result["hodges_lehmann"]["estimate"] is not None


def test_split_above_the_ceiling_skips_hodges_lehmann_but_keeps_cliffs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("scipy")
    df = _split_df(1000, 1001)
    a = df.loc[df["group"] == "a", "metric"].tolist()
    b = df.loc[df["group"] == "b", "metric"].tolist()
    expected_delta = round(effect_size.cliffs_delta(a, b), 6)

    tripwire = _arm_service_guard(monkeypatch)
    result = svc.nonparametric_effect_sizes(df, "metric", "group")

    assert tripwire.pairwise_calls == 0
    assert result["n_a"] == 1000
    assert result["n_b"] == 1001
    assert result["cliffs_delta"] == expected_delta
    assert result["cliffs_interpretation"] in {"negligible", "small", "medium", "large"}
    _assert_bounded_limit_state(result)


def test_missing_scipy_reads_unavailable_above_the_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enough finite values on both sides and above the ceiling, but the kernel reports
    unavailable first; the service guard still forms no pairs and runs no fallback."""
    df = _split_df(1001, 1000)
    a = df.loc[df["group"] == "a", "metric"].tolist()
    b = df.loc[df["group"] == "b", "metric"].tolist()
    _without_scipy(monkeypatch)
    tripwire = _arm_service_guard(monkeypatch)

    result = svc.nonparametric_effect_sizes(df, "metric", "group")
    kernel = effect_size.hodges_lehmann_ci(a, b)

    assert tripwire.pairwise_calls == 0
    assert result["status"] == "ok"
    assert -1.0 <= result["cliffs_delta"] <= 1.0
    assert kernel["status"] == "unavailable"
    # Same status, reason and (absent) numbers as the kernel; nothing is estimated.
    assert result["hodges_lehmann"] == kernel
    assert kernel["estimate"] is None


def test_ceiling_guard_keeps_the_confidence_contract() -> None:
    with pytest.raises(ValueError, match="confidence"):
        svc.nonparametric_effect_sizes(_split_df(1000, 1001), "metric", "group", confidence=1.5)


def test_ceiling_counts_finite_values_like_the_kernel() -> None:
    pytest.importorskip("scipy")
    df = _split_df(1000, 1000)
    padded = pd.concat(
        [df, pd.DataFrame({"metric": [np.inf, -np.inf], "group": ["a", "b"]})],
        ignore_index=True,
    )
    result = svc.nonparametric_effect_sizes(padded, "metric", "group")
    assert result["hodges_lehmann"]["status"] == "ok"


def test_pathological_split_returns_bounded_state_without_pairwise_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("scipy")
    n_a, n_b = 29_706, 44_405
    df = _split_df(n_a, n_b)
    assert len(df) == 74_111
    tripwire = _arm_service_guard(monkeypatch)

    tracemalloc.start()
    try:
        result = svc.nonparametric_effect_sizes(df, "metric", "group")
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert result["n_a"] * result["n_b"] == 1_319_094_930
    assert tripwire.pairwise_calls == 0
    # One float64 pair array alone would be ~9.8 GiB; the bounded path stays tiny.
    assert peak < 64 * 1024 * 1024
    assert -1.0 <= result["cliffs_delta"] <= 1.0
    _assert_bounded_limit_state(result)


# ── HL status precedence after finite-value filtering ────────────────────────
#
# The kernel reports unavailable, then insufficient_data (a group with fewer than two
# finite values), and only then pairwise_limit_exceeded. The service must agree even
# when raw rows pass its own size check but non-finite values leave one group short.


def _finite_values(n: int, offset: float = 0.0) -> list[float]:
    """Deterministic, heavily tied finite values."""
    return [float(i % 29) + offset for i in range(n)]


def _frame(a_values: list[float], b_values: list[float]) -> pd.DataFrame:
    """Groups 'a' and 'b' carrying the given raw metric values (NaN / inf kept)."""
    return pd.DataFrame(
        {
            "metric": [*a_values, *b_values],
            "group": ["a"] * len(a_values) + ["b"] * len(b_values),
        }
    )


def _service_hl_status(result: dict[str, Any]) -> str:
    """The HL status a caller sees; a split rejected before any estimator runs reports
    its status on the whole result instead of the ``hodges_lehmann`` sub-dict."""
    if result["status"] != "ok":
        return str(result["status"])
    return str(result["hodges_lehmann"]["status"])


@pytest.fixture(scope="module")
def over_ceiling_values() -> list[float]:
    """One more finite value than the ceiling: 1 x this is just above it."""
    return _finite_values(effect_size.MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS + 1, 2.0)


def _forbid_point_estimate(monkeypatch: pytest.MonkeyPatch) -> _PairwiseTripwire:
    def forbidden(*_a: object, **_k: object) -> object:
        raise AssertionError("an exact Hodges-Lehmann point estimate was requested")

    tripwire = _PairwiseTripwire()
    monkeypatch.setattr(effect_size, "np", tripwire)
    monkeypatch.setattr(svc, "_hodges_lehmann_estimate", forbidden)
    return tripwire


@pytest.mark.parametrize("deficient", ["a", "b"])
def test_one_finite_value_beside_a_huge_group_is_insufficient_like_the_kernel(
    monkeypatch: pytest.MonkeyPatch, over_ceiling_values: list[float], deficient: str
) -> None:
    pytest.importorskip("scipy")
    short = [5.0, np.inf] if deficient == "a" else [-np.inf, 5.0]
    raw_a, raw_b = (
        (short, over_ceiling_values) if deficient == "a" else (over_ceiling_values, short)
    )
    assert (
        effect_size.pairwise_comparison_count(raw_a, raw_b)
        > effect_size.MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS
    )
    df = _frame(raw_a, raw_b)
    tripwire = _forbid_point_estimate(monkeypatch)

    result = svc.nonparametric_effect_sizes(df, "metric", "group")
    kernel = effect_size.hodges_lehmann_ci(raw_a, raw_b)

    assert tripwire.pairwise_calls == 0
    assert result["status"] == "ok"
    assert (result["n_a"], result["n_b"]) == (len(raw_a), len(raw_b))
    assert -1.0 <= result["cliffs_delta"] <= 1.0
    assert kernel["status"] == "insufficient_data"
    # Same status, reason and (absent) numbers as the kernel; nothing is estimated.
    assert result["hodges_lehmann"] == kernel
    assert kernel["estimate"] is None
    assert kernel["lower"] is None
    assert kernel["upper"] is None


def test_unavailable_still_precedes_insufficient_data_above_the_ceiling(
    monkeypatch: pytest.MonkeyPatch, over_ceiling_values: list[float]
) -> None:
    _without_scipy(monkeypatch)
    raw_a = [5.0, np.inf]
    tripwire = _forbid_point_estimate(monkeypatch)

    result = svc.nonparametric_effect_sizes(_frame(raw_a, over_ceiling_values), "metric", "group")
    kernel = effect_size.hodges_lehmann_ci(raw_a, over_ceiling_values)

    assert tripwire.pairwise_calls == 0
    assert kernel["status"] == "unavailable"
    assert result["hodges_lehmann"] == kernel


_OK, _SHORT, _LIMITED = "ok", "insufficient_data", "pairwise_limit_exceeded"

# case -> (raw group a, raw group b, status both layers must report)
_AGREEMENT_CASES: dict[str, tuple[list[float], list[float], str]] = {
    "nan_in_a": ([1.0, np.nan, 2.0, 3.0], [4.0, 5.0, 6.0], _OK),
    "pos_inf_in_b": ([1.0, 2.0, 3.0], [np.inf, 4.0, 5.0], _OK),
    "neg_inf_in_a": ([-np.inf, 1.0, 2.0], [3.0, 4.0], _OK),
    "several_non_finite": (
        [np.nan, np.inf, -np.inf, 1.0, 2.0],
        [np.inf, np.nan, 3.0, -np.inf, 4.0],
        _OK,
    ),
    "one_finite_in_a": ([5.0, np.inf], [1.0, 2.0, 3.0], _SHORT),
    "one_finite_in_b": ([1.0, 2.0, 3.0], [-np.inf, 7.0], _SHORT),
    "one_finite_in_a_after_nan_rows": ([np.nan, 5.0, np.nan], [1.0, 2.0], _SHORT),
    "exactly_two_finite_each": ([np.inf, 1.0, np.nan, 2.0], [3.0, -np.inf, 4.0], _OK),
    "large_raw_one_finite": ([np.inf] * 5_000 + [1.0], _finite_values(3_000), _SHORT),
    "finite_at_ceiling_large_raw": (
        _finite_values(1_000) + [np.inf] * 400,
        _finite_values(1_000, 2.0) + [-np.inf] * 400,
        _OK,
    ),
    "finite_over_ceiling_asymmetric": (
        _finite_values(1_001) + [np.nan] * 500,
        _finite_values(1_000, 2.0) + [np.inf] * 300,
        _LIMITED,
    ),
    # 101 x 9,901 = 1,000,001 finite pairs: one pair past the ceiling.
    "finite_one_pair_over_ceiling": (_finite_values(101), _finite_values(9_901, 2.0), _LIMITED),
}


@pytest.mark.parametrize("case", sorted(_AGREEMENT_CASES))
def test_hl_status_agrees_with_the_kernel_after_finite_filtering(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    pytest.importorskip("scipy")
    raw_a, raw_b, expected = _AGREEMENT_CASES[case]
    over_ceiling = (
        effect_size.pairwise_comparison_count(raw_a, raw_b)
        > effect_size.MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS
    )
    tripwire = _PairwiseTripwire()
    if over_ceiling:
        monkeypatch.setattr(effect_size, "np", tripwire)

    kernel = effect_size.hodges_lehmann_ci(raw_a, raw_b)["status"]
    service = _service_hl_status(
        svc.nonparametric_effect_sizes(_frame(raw_a, raw_b), "metric", "group")
    )

    assert service == kernel == expected
    assert tripwire.pairwise_calls == 0


@pytest.mark.parametrize("case", sorted(_AGREEMENT_CASES))
def test_missing_scipy_reads_unavailable_like_the_kernel_after_finite_filtering(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    raw_a, raw_b, _with_scipy = _AGREEMENT_CASES[case]
    over_ceiling = (
        effect_size.pairwise_comparison_count(raw_a, raw_b)
        > effect_size.MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS
    )
    _without_scipy(monkeypatch)
    tripwire = _PairwiseTripwire()
    if over_ceiling:
        monkeypatch.setattr(effect_size, "np", tripwire)

    kernel = effect_size.hodges_lehmann_ci(raw_a, raw_b)["status"]
    result = svc.nonparametric_effect_sizes(_frame(raw_a, raw_b), "metric", "group")

    assert kernel == "unavailable"
    if result["status"] == "ok":
        assert result["hodges_lehmann"]["status"] == kernel
    else:
        # Rejected on raw group size before any estimator runs: no HL status exists.
        assert result["status"] == _SHORT
        assert result["hodges_lehmann"] is None
    assert tripwire.pairwise_calls == 0
