# src/data_quality_toolkit/domain/statistics/effect_size.py
"""Effect-size estimators for the statistics domain.

``cohen_d``, ``cliffs_delta``, and ``hodges_lehmann_estimate`` are pure
numpy (no scipy) and always available. ``hodges_lehmann_ci`` needs scipy for its
normal critical value and returns a status dict (``unavailable`` when scipy is
absent), consistent with the rest of the kernel.

All functions drop non-finite values defensively and return a clearly-defined
value (0.0 effect) when there is too little data to estimate one.

The exact Hodges-Lehmann estimators materialize every pairwise difference, so they
refuse inputs above ``MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS`` pairs rather than
approximate: ``hodges_lehmann_ci`` returns a ``pairwise_limit_exceeded`` status and
``hodges_lehmann_estimate`` raises ``PairwiseLimitExceededError``. Cliff's delta is
counted exactly from sorted ranks and never forms the pairs.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from data_quality_toolkit.domain.statistics.core import (
    UNAVAILABLE_REASON,
    import_scipy_stats,
    validate_confidence,
)

__all__ = [
    "MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS",
    "PAIRWISE_LIMIT_REASON",
    "PAIRWISE_LIMIT_STATUS",
    "PairwiseLimitExceededError",
    "cohen_d",
    "cliffs_delta",
    "hodges_lehmann_estimate",
    "hodges_lehmann_ci",
    "pairwise_comparison_count",
]

# Safety ceiling on the pairwise differences an exact estimator may materialize
# (1,000,000 float64 values ~ 7.6 MiB per array). Above it the exact result is not
# computed at all: it is never replaced by a sampled or approximate one.
MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS = 1_000_000

PAIRWISE_LIMIT_STATUS = "pairwise_limit_exceeded"
PAIRWISE_LIMIT_REASON = (
    "exact Hodges-Lehmann effect size was not computed because this comparison requires "
    f"more than {MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS:,} pairwise differences"
)


class PairwiseLimitExceededError(ValueError):
    """An exact pairwise estimator was asked for more pairs than the safety ceiling."""


def _clean_pair(a: Any, b: Any) -> tuple[np.ndarray, np.ndarray]:
    arr_a = np.asarray(a, dtype=float).ravel()
    arr_b = np.asarray(b, dtype=float).ravel()
    return arr_a[np.isfinite(arr_a)], arr_b[np.isfinite(arr_b)]


def pairwise_comparison_count(a: Any, b: Any) -> int:
    """Number of finite ``(a_i, b_j)`` pairs an exact pairwise estimator would form."""
    arr_a, arr_b = _clean_pair(a, b)
    return int(arr_a.size) * int(arr_b.size)


def _exceeds_pairwise_limit(arr_a: np.ndarray, arr_b: np.ndarray) -> bool:
    return int(arr_a.size) * int(arr_b.size) > MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS


def _pairwise_differences(arr_a: np.ndarray, arr_b: np.ndarray) -> np.ndarray:
    """Every pairwise difference ``a_i - b_j``; refused above the pairwise ceiling."""
    if _exceeds_pairwise_limit(arr_a, arr_b):
        raise PairwiseLimitExceededError(PAIRWISE_LIMIT_REASON)
    return np.subtract.outer(arr_a, arr_b).ravel()


def cohen_d(a: Any, b: Any) -> float:
    """Pooled-SD Cohen's d effect size (``mean(a) - mean(b)`` over pooled SD).

    Returns 0.0 when either group has fewer than 2 finite values or the pooled
    SD is zero. Sign follows ``mean(a) - mean(b)``.
    """
    arr_a, arr_b = _clean_pair(a, b)
    na, nb = arr_a.size, arr_b.size
    if na < 2 or nb < 2:
        return 0.0
    var_a = float(np.var(arr_a, ddof=1))
    var_b = float(np.var(arr_b, ddof=1))
    pooled = np.sqrt(((na - 1) * var_a + (nb - 1) * var_b) / (na + nb - 2))
    if pooled == 0:
        return 0.0
    return float((np.mean(arr_a) - np.mean(arr_b)) / pooled)


def cliffs_delta(a: Any, b: Any) -> float:
    """Cliff's delta ordinal effect size in [-1, 1].

    ``delta = (#(a > b) - #(a < b)) / (na * nb)``. Returns 0.0 when either group
    is empty.

    The two counts are exact: each ``a_i`` is located in the sorted ``b`` sample,
    so ties contribute zero and no ``na x nb`` pair array is built
    (O((na + nb) log nb) time, O(na + nb) memory).
    """
    arr_a, arr_b = _clean_pair(a, b)
    if arr_a.size == 0 or arr_b.size == 0:
        return 0.0
    sorted_b = np.sort(arr_b)
    below = np.searchsorted(sorted_b, arr_a, side="left")
    at_or_below = np.searchsorted(sorted_b, arr_a, side="right")
    greater = int(below.sum())
    lesser = int(arr_b.size) * int(arr_a.size) - int(at_or_below.sum())
    return float(np.float64(greater - lesser) / (arr_a.size * arr_b.size))


def hodges_lehmann_estimate(a: Any, b: Any) -> float:
    """Hodges-Lehmann location shift: the median of all pairwise differences a-b.

    Returns 0.0 when either group is empty. Raises ``PairwiseLimitExceededError``
    before any pairwise work when the groups would form more than
    ``MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS`` pairs.
    """
    arr_a, arr_b = _clean_pair(a, b)
    if arr_a.size == 0 or arr_b.size == 0:
        return 0.0
    diffs = _pairwise_differences(arr_a, arr_b)
    return float(np.median(diffs))


def hodges_lehmann_ci(a: Any, b: Any, confidence: float = 0.95) -> dict[str, Any]:
    """Hodges-Lehmann shift estimate with a large-sample normal band.

    Returns a status dict with keys: status, reason, confidence, estimate,
    lower, upper, method. Statuses: ``ok`` / ``unavailable`` / ``insufficient_data``
    / ``pairwise_limit_exceeded`` (more than ``MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS``
    pairs; nothing is estimated). The band uses the SE of the pairwise-difference
    vector and a normal z — a large-sample approximation
    (method=``hodges_lehmann_normal_approx``).
    """
    validate_confidence(confidence)
    base: dict[str, Any] = {
        "status": "ok",
        "reason": None,
        "confidence": confidence,
        "estimate": None,
        "lower": None,
        "upper": None,
        "method": "hodges_lehmann_normal_approx",
    }
    stats = import_scipy_stats()
    if stats is None:
        base["status"] = "unavailable"
        base["reason"] = UNAVAILABLE_REASON
        return base

    arr_a, arr_b = _clean_pair(a, b)
    if arr_a.size < 2 or arr_b.size < 2:
        base["status"] = "insufficient_data"
        base["reason"] = "each group needs at least 2 finite values"
        return base
    if _exceeds_pairwise_limit(arr_a, arr_b):
        base["status"] = PAIRWISE_LIMIT_STATUS
        base["reason"] = PAIRWISE_LIMIT_REASON
        return base

    diffs = _pairwise_differences(arr_a, arr_b)
    estimate = float(np.median(diffs))
    se = float(np.std(diffs, ddof=1)) / np.sqrt(diffs.size)
    z = float(stats.norm.ppf((1.0 + confidence) / 2.0))
    margin = z * se
    base["estimate"] = round(estimate, 6)
    base["lower"] = round(estimate - margin, 6)
    base["upper"] = round(estimate + margin, 6)
    return base
