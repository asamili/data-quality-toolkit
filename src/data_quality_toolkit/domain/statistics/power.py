# src/data_quality_toolkit/domain/statistics/power.py
"""Closed-form power and sample-size helpers for the statistics domain.

Normal-approximation engine using only scipy's normal quantile/cdf — no
statsmodels. Every function is scipy-guarded and returns a status dict; it
degrades to ``status="unavailable"`` when scipy (the optional ``[stats]`` extra)
is absent and never raises ImportError. Invalid alpha/parameters raise
``ValueError`` (alpha) or return ``status="invalid_input"`` (numeric domain
errors such as zero effect size).

``required_n_cohend`` returns an explicit scalar ``n_per_group`` — the extracted
notebook's tuple-return bug is intentionally fixed here.

Out of scope this wave (need statsmodels): power_anova, sequential_boundaries,
regression power.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from data_quality_toolkit.domain.statistics.core import (
    UNAVAILABLE_REASON,
    import_scipy_stats,
    validate_alpha,
)

__all__ = [
    "power_mean",
    "power_prop",
    "required_n_mean",
    "required_n_prop",
    "required_n_variance",
    "required_n_cohend",
]

_ALTERNATIVES = frozenset({"two-sided", "greater", "less"})


def _base(method: str) -> dict[str, Any]:
    return {"status": "ok", "reason": None, "method": method}


def _unavailable(base: dict[str, Any]) -> dict[str, Any]:
    base["status"] = "unavailable"
    base["reason"] = UNAVAILABLE_REASON
    return base


def _invalid(base: dict[str, Any], reason: str) -> dict[str, Any]:
    base["status"] = "invalid_input"
    base["reason"] = reason
    return base


def _validate_alternative(alternative: str) -> None:
    if alternative not in _ALTERNATIVES:
        raise ValueError(f"alternative must be one of {sorted(_ALTERNATIVES)}, got {alternative!r}")


def _z_alpha(stats: Any, alpha: float, alternative: str) -> float:
    tail = alpha / 2.0 if alternative == "two-sided" else alpha
    return float(stats.norm.ppf(1.0 - tail))


def power_mean(
    n: int,
    delta: float,
    sigma: float,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> dict[str, Any]:
    """Statistical power for a one-sample mean test (normal approximation)."""
    validate_alpha(alpha)
    _validate_alternative(alternative)
    base = _base("normal_power_mean")
    if sigma <= 0:
        return _invalid(base, "sigma must be > 0")
    if n <= 0:
        return _invalid(base, "n must be > 0")
    stats = import_scipy_stats()
    if stats is None:
        return _unavailable(base)

    effect = delta / (sigma / np.sqrt(n))
    c = _z_alpha(stats, alpha, alternative)
    if alternative == "two-sided":
        power = float(stats.norm.cdf(-c + effect) + stats.norm.cdf(-c - effect))
    elif alternative == "greater":
        power = float(stats.norm.cdf(effect - c))
    else:
        power = float(stats.norm.cdf(-c - effect))
    base["power"] = float(np.clip(power, 0.0, 1.0))
    return base


def power_prop(
    n: int,
    p1: float,
    p2: float,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> dict[str, Any]:
    """Statistical power for a two-proportion test (normal approximation)."""
    validate_alpha(alpha)
    _validate_alternative(alternative)
    base = _base("normal_power_prop")
    if n <= 0:
        return _invalid(base, "n must be > 0")
    if not (0.0 <= p1 <= 1.0 and 0.0 <= p2 <= 1.0):
        return _invalid(base, "p1 and p2 must be in [0, 1]")
    pbar = (p1 + p2) / 2.0
    se_null = np.sqrt(2.0 * pbar * (1.0 - pbar) / n)
    se_alt = np.sqrt(p1 * (1.0 - p1) / n + p2 * (1.0 - p2) / n)
    if se_alt == 0:
        return _invalid(base, "alternative standard error is zero (degenerate p1/p2)")
    stats = import_scipy_stats()
    if stats is None:
        return _unavailable(base)
    c = _z_alpha(stats, alpha, alternative)
    diff = p1 - p2
    if alternative == "two-sided":
        upper_tail = float(stats.norm.cdf((diff - c * se_null) / se_alt))
        lower_tail = float(stats.norm.cdf((-c * se_null - diff) / se_alt))
        power = upper_tail + lower_tail
    elif alternative == "greater":
        power = float(stats.norm.cdf((diff - c * se_null) / se_alt))
    else:
        power = float(stats.norm.cdf((-c * se_null - diff) / se_alt))
    base["power"] = float(np.clip(power, 0.0, 1.0))
    return base


def required_n_mean(
    delta: float,
    sigma: float,
    alpha: float = 0.05,
    power: float = 0.8,
    alternative: str = "two-sided",
) -> dict[str, Any]:
    """Required sample size for a mean test (normal approximation)."""
    validate_alpha(alpha)
    _validate_alternative(alternative)
    base = _base("normal_n_mean")
    if sigma <= 0:
        return _invalid(base, "sigma must be > 0")
    if delta == 0:
        return _invalid(base, "delta must be non-zero")
    if not 0.0 < power < 1.0:
        return _invalid(base, "power must be in (0, 1)")
    stats = import_scipy_stats()
    if stats is None:
        return _unavailable(base)

    z_a = _z_alpha(stats, alpha, alternative)
    z_b = float(stats.norm.ppf(power))
    n = ((z_a + z_b) * sigma / abs(delta)) ** 2
    base["n"] = int(np.ceil(n))
    return base


def required_n_prop(
    p1: float,
    p2: float,
    alpha: float = 0.05,
    power: float = 0.8,
    alternative: str = "two-sided",
    ratio: float = 1.0,
) -> dict[str, Any]:
    """Required per-group sample sizes for a two-proportion test."""
    validate_alpha(alpha)
    _validate_alternative(alternative)
    base = _base("normal_n_prop")
    if not (0.0 <= p1 <= 1.0 and 0.0 <= p2 <= 1.0):
        return _invalid(base, "p1 and p2 must be in [0, 1]")
    if p1 == p2:
        return _invalid(base, "p1 and p2 must differ")
    if ratio <= 0:
        return _invalid(base, "ratio must be > 0")
    if not 0.0 < power < 1.0:
        return _invalid(base, "power must be in (0, 1)")
    stats = import_scipy_stats()
    if stats is None:
        return _unavailable(base)

    z_a = _z_alpha(stats, alpha, alternative)
    z_b = float(stats.norm.ppf(power))
    pbar = (p1 + ratio * p2) / (1.0 + ratio)
    qbar = 1.0 - pbar
    pooled = z_a * np.sqrt((1.0 + 1.0 / ratio) * pbar * qbar)
    unpooled = z_b * np.sqrt(p1 * (1.0 - p1) + p2 * (1.0 - p2) / ratio)
    n1 = (pooled + unpooled) ** 2 / (p1 - p2) ** 2
    n1_ceil = int(np.ceil(n1))
    base["n1"] = n1_ceil
    base["n2"] = int(np.ceil(n1_ceil * ratio))
    return base


def required_n_variance(ratio: float, alpha: float = 0.05, power: float = 0.8) -> dict[str, Any]:
    """Required sample size for a variance-ratio test (normal approximation)."""
    validate_alpha(alpha)
    base = _base("normal_n_variance")
    if ratio <= 0:
        return _invalid(base, "ratio must be > 0")
    if ratio == 1.0:
        return _invalid(base, "ratio must differ from 1 (no detectable effect at ratio=1)")
    if not 0.0 < power < 1.0:
        return _invalid(base, "power must be in (0, 1)")
    stats = import_scipy_stats()
    if stats is None:
        return _unavailable(base)

    z_a = float(stats.norm.ppf(1.0 - alpha / 2.0))
    z_b = float(stats.norm.ppf(power))
    n = 2.0 * ((z_a + z_b) / np.log(ratio)) ** 2 + 2.0
    base["n"] = int(np.ceil(n))
    return base


def required_n_cohend(
    delta: float, alpha: float = 0.05, power: float = 0.8, ratio: float = 1.0
) -> dict[str, Any]:
    """Required per-group sample size for a two-sample t-test from Cohen's d.

    Returns an explicit scalar ``n_per_group`` (fixes the extracted tuple bug).
    """
    validate_alpha(alpha)
    base = _base("normal_n_cohend")
    if delta == 0:
        return _invalid(base, "delta (Cohen's d) must be non-zero")
    if ratio <= 0:
        return _invalid(base, "ratio must be > 0")
    if not 0.0 < power < 1.0:
        return _invalid(base, "power must be in (0, 1)")
    stats = import_scipy_stats()
    if stats is None:
        return _unavailable(base)

    z_a = float(stats.norm.ppf(1.0 - alpha / 2.0))
    z_b = float(stats.norm.ppf(power))
    n_per_group = ((z_a + z_b) ** 2) * (1.0 / ratio + 1.0) / (delta**2)
    base["n_per_group"] = int(np.ceil(n_per_group))
    return base
