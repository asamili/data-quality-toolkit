# src/data_quality_toolkit/domain/statistics/bootstrap.py
"""Bootstrap confidence intervals for the statistics domain.

``bootstrap_ci`` resamples with replacement using a seeded, local
``numpy.random.Generator`` (no global random-state pollution) and supports two
interval methods:

- ``percentile`` (default): pure numpy, always available.
- ``bca`` (bias-corrected & accelerated): needs scipy for the normal quantile;
  returns ``status="unavailable"`` when scipy (the optional ``[stats]`` extra)
  is absent.

Resampling is bounded by ``MAX_N_BOOTSTRAP`` to keep compute predictable.
Returns a status dict (keys: status, reason, method, confidence, point, lower,
upper, n, n_bootstrap).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from data_quality_toolkit.domain.statistics.core import (
    UNAVAILABLE_REASON,
    clean_numeric,
    import_scipy_stats,
    validate_confidence,
)

__all__ = ["bootstrap_ci", "DEFAULT_N_BOOTSTRAP", "MAX_N_BOOTSTRAP"]

DEFAULT_N_BOOTSTRAP = 10_000
MAX_N_BOOTSTRAP = 100_000
_METHODS = frozenset({"percentile", "bca"})


def _base(confidence: float, method: str, n_bootstrap: int) -> dict[str, Any]:
    return {
        "status": "ok",
        "reason": None,
        "method": method,
        "confidence": confidence,
        "point": None,
        "lower": None,
        "upper": None,
        "n": None,
        "n_bootstrap": n_bootstrap,
    }


def _bootstrap_replicates(
    arr: np.ndarray, statistic: Callable[[np.ndarray], float], n_bootstrap: int, rng: Any
) -> np.ndarray:
    n = arr.size
    reps = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        reps[i] = float(statistic(arr[rng.integers(0, n, size=n)]))
    return reps


def _bca_endpoints(
    arr: np.ndarray,
    reps: np.ndarray,
    orig: float,
    statistic: Callable[[np.ndarray], float],
    confidence: float,
    stats: Any,
) -> tuple[float, float]:
    """Bias-corrected & accelerated percentile endpoints (fractions in [0, 1])."""
    prop_less = float(np.mean(reps < orig))
    z0 = float(stats.norm.ppf(np.clip(prop_less, 1e-6, 1.0 - 1e-6)))

    n = arr.size
    jack = np.empty(n, dtype=float)
    for i in range(n):
        jack[i] = float(statistic(np.delete(arr, i)))
    jbar = float(np.mean(jack))
    num = float(np.sum((jbar - jack) ** 3))
    den = 6.0 * float(np.sum((jbar - jack) ** 2)) ** 1.5
    accel = num / den if den != 0 else 0.0

    alpha = 1.0 - confidence
    z_lo = float(stats.norm.ppf(alpha / 2.0))
    z_hi = float(stats.norm.ppf(1.0 - alpha / 2.0))

    def adjust(z: float) -> float:
        return float(stats.norm.cdf(z0 + (z0 + z) / (1.0 - accel * (z0 + z))))

    return adjust(z_lo), adjust(z_hi)


def bootstrap_ci(
    data: Any,
    statistic: Callable[[np.ndarray], float] = np.mean,
    confidence: float = 0.95,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
    method: str = "percentile",
    seed: int = 0,
) -> dict[str, Any]:
    """Bootstrap CI for ``statistic`` of ``data``.

    ``method`` is ``percentile`` (default, pure numpy) or ``bca`` (needs scipy).
    Deterministic for a fixed ``seed``. Statuses: ok / unavailable /
    insufficient_data.
    """
    validate_confidence(confidence)
    if method not in _METHODS:
        raise ValueError(f"method must be one of {sorted(_METHODS)}, got {method!r}")
    n_boot = min(int(n_bootstrap), MAX_N_BOOTSTRAP)
    if n_boot < 1:
        raise ValueError("n_bootstrap must be >= 1")
    base = _base(confidence, method, n_boot)

    stats = import_scipy_stats()
    if method == "bca" and stats is None:
        base["status"] = "unavailable"
        base["reason"] = UNAVAILABLE_REASON
        return base

    arr = clean_numeric(data)
    n = int(arr.size)
    base["n"] = n
    if n < 2:
        base["status"] = "insufficient_data"
        base["reason"] = "need at least 2 finite values"
        return base

    rng = np.random.default_rng(seed)
    reps = _bootstrap_replicates(arr, statistic, n_boot, rng)
    orig = float(statistic(arr))
    base["point"] = round(orig, 6)
    alpha = 1.0 - confidence

    if method == "percentile":
        lo_frac, hi_frac = alpha / 2.0, 1.0 - alpha / 2.0
    else:  # bca
        lo_frac, hi_frac = _bca_endpoints(arr, reps, orig, statistic, confidence, stats)

    base["lower"] = round(float(np.quantile(reps, lo_frac)), 6)
    base["upper"] = round(float(np.quantile(reps, hi_frac)), 6)
    return base
