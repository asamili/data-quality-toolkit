# src/data_quality_toolkit/domain/statistics/intervals.py
"""Confidence-interval bank for the statistics domain.

Formulas follow the extracted FEATURE_LOGIC_CATALOG. Every function is
scipy-guarded (critical values come from scipy) and returns a status dict with a
stable contract; it degrades to ``status="unavailable"`` when scipy (the
optional ``[stats]`` extra) is absent and never raises ImportError. Invalid
confidence raises ``ValueError``.

Result contract (keys always present): status, reason, method, confidence,
point, lower, upper, n, se. ``status`` is one of ok / unavailable /
insufficient_data / invalid_input.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from data_quality_toolkit.domain.statistics.core import (
    UNAVAILABLE_REASON,
    clean_numeric,
    import_scipy_stats,
    validate_confidence,
)

__all__ = [
    "ci_mean",
    "ci_mean_diff",
    "ci_prop",
    "ci_prop_diff",
    "ci_var",
    "ci_var_ratio",
]

_PROP_METHODS = frozenset({"wald", "wilson", "jeffreys"})


def _base(confidence: float, method: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "reason": None,
        "method": method,
        "confidence": confidence,
        "point": None,
        "lower": None,
        "upper": None,
        "n": None,
        "se": None,
    }


def _unavailable(base: dict[str, Any]) -> dict[str, Any]:
    base["status"] = "unavailable"
    base["reason"] = UNAVAILABLE_REASON
    return base


def _mark(base: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    base["status"] = status
    base["reason"] = reason
    return base


def _fill(base: dict[str, Any], point: float, lower: float, upper: float) -> dict[str, Any]:
    base["point"] = round(float(point), 6)
    base["lower"] = round(float(lower), 6)
    base["upper"] = round(float(upper), 6)
    return base


def ci_mean(
    data: Any, confidence: float = 0.95, known_sigma: float | None = None
) -> dict[str, Any]:
    """CI for a population mean. z-interval when ``known_sigma`` is given, else t-interval."""
    validate_confidence(confidence)
    base = _base(confidence, "z" if known_sigma is not None else "t")
    stats = import_scipy_stats()
    if stats is None:
        return _unavailable(base)

    arr = clean_numeric(data)
    n = int(arr.size)
    base["n"] = n
    if n < 2:
        return _mark(base, "insufficient_data", "need at least 2 finite values")

    mean = float(np.mean(arr))
    quantile = (1.0 + confidence) / 2.0
    if known_sigma is not None:
        if known_sigma <= 0:
            return _mark(base, "invalid_input", "known_sigma must be > 0")
        se = known_sigma / np.sqrt(n)
        crit = float(stats.norm.ppf(quantile))
    else:
        se = float(np.std(arr, ddof=1)) / np.sqrt(n)
        crit = float(stats.t.ppf(quantile, n - 1))
    margin = crit * se
    base["se"] = round(float(se), 6)
    return _fill(base, mean, mean - margin, mean + margin)


def ci_mean_diff(
    data1: Any,
    data2: Any,
    confidence: float = 0.95,
    paired: bool = False,
    equal_var: bool = True,
) -> dict[str, Any]:
    """CI for a difference in means: paired, pooled (equal var), or Welch (unequal)."""
    validate_confidence(confidence)
    if paired:
        method = "paired"
    elif equal_var:
        method = "pooled"
    else:
        method = "welch"
    base = _base(confidence, method)
    stats = import_scipy_stats()
    if stats is None:
        return _unavailable(base)

    if paired:
        a = clean_numeric(data1, dropna=False)
        b = clean_numeric(data2, dropna=False)
        if a.size != b.size:
            return _mark(base, "invalid_input", "paired data must have equal length")
        diff = a - b
        diff = diff[np.isfinite(diff)]
        return ci_mean(diff, confidence)

    a = clean_numeric(data1)
    b = clean_numeric(data2)
    n1, n2 = int(a.size), int(b.size)
    if n1 < 2 or n2 < 2:
        return _mark(base, "insufficient_data", "each group needs at least 2 finite values")

    mean_diff = float(np.mean(a) - np.mean(b))
    var1 = float(np.var(a, ddof=1))
    var2 = float(np.var(b, ddof=1))
    quantile = (1.0 + confidence) / 2.0
    if equal_var:
        pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
        se = np.sqrt(pooled_var * (1.0 / n1 + 1.0 / n2))
        df = float(n1 + n2 - 2)
    else:
        se = np.sqrt(var1 / n1 + var2 / n2)
        df = (var1 / n1 + var2 / n2) ** 2 / (
            (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
        )
    crit = float(stats.t.ppf(quantile, df))
    margin = crit * se
    base["n"] = n1 + n2
    base["se"] = round(float(se), 6)
    return _fill(base, mean_diff, mean_diff - margin, mean_diff + margin)


def _wilson(phat: float, n: int, z: float) -> tuple[float, float]:
    denom = 1.0 + z**2 / n
    center = (phat + z**2 / (2.0 * n)) / denom
    half = (z * np.sqrt(phat * (1.0 - phat) / n + z**2 / (4.0 * n**2))) / denom
    return center - half, center + half


def ci_prop(
    successes: int, n: int, confidence: float = 0.95, method: str = "wilson"
) -> dict[str, Any]:
    """CI for a population proportion: wald, wilson (default), or jeffreys."""
    validate_confidence(confidence)
    if method not in _PROP_METHODS:
        raise ValueError(f"method must be one of {sorted(_PROP_METHODS)}, got {method!r}")
    base = _base(confidence, method)
    stats = import_scipy_stats()
    if stats is None:
        return _unavailable(base)
    if n <= 0:
        return _mark(base, "invalid_input", "n must be > 0")
    if not 0 <= successes <= n:
        return _mark(base, "invalid_input", "require 0 <= successes <= n")

    base["n"] = int(n)
    phat = successes / n
    alpha = 1.0 - confidence
    z = float(stats.norm.ppf(1.0 - alpha / 2.0))
    if method == "wald":
        se = np.sqrt(phat * (1.0 - phat) / n)
        base["se"] = round(float(se), 6)
        lower, upper = phat - z * se, phat + z * se
    elif method == "wilson":
        lower, upper = _wilson(phat, n, z)
    else:  # jeffreys
        a_post = successes + 0.5
        b_post = n - successes + 0.5
        lower = 0.0 if successes == 0 else float(stats.beta.ppf(alpha / 2.0, a_post, b_post))
        upper = 1.0 if successes == n else float(stats.beta.ppf(1.0 - alpha / 2.0, a_post, b_post))
    return _fill(base, phat, max(0.0, lower), min(1.0, upper))


def ci_prop_diff(
    successes1: int, n1: int, successes2: int, n2: int, confidence: float = 0.95
) -> dict[str, Any]:
    """CI for a difference in proportions via the normal approximation."""
    validate_confidence(confidence)
    base = _base(confidence, "normal")
    stats = import_scipy_stats()
    if stats is None:
        return _unavailable(base)
    if n1 <= 0 or n2 <= 0:
        return _mark(base, "invalid_input", "n1 and n2 must be > 0")
    if not (0 <= successes1 <= n1 and 0 <= successes2 <= n2):
        return _mark(base, "invalid_input", "require 0 <= successes <= n for each group")

    p1 = successes1 / n1
    p2 = successes2 / n2
    diff = p1 - p2
    se = np.sqrt(p1 * (1.0 - p1) / n1 + p2 * (1.0 - p2) / n2)
    z = float(stats.norm.ppf((1.0 + confidence) / 2.0))
    margin = z * se
    base["n"] = int(n1 + n2)
    base["se"] = round(float(se), 6)
    return _fill(base, diff, diff - margin, diff + margin)


def ci_var(s2: float, n: int, confidence: float = 0.95) -> dict[str, Any]:
    """CI for a variance via the chi-square distribution. Requires ``n >= 3``."""
    validate_confidence(confidence)
    base = _base(confidence, "chi2")
    stats = import_scipy_stats()
    if stats is None:
        return _unavailable(base)
    if n < 3:
        return _mark(base, "insufficient_data", "need n >= 3 for a variance interval")
    if s2 < 0:
        return _mark(base, "invalid_input", "s2 (sample variance) must be >= 0")

    base["n"] = int(n)
    alpha = 1.0 - confidence
    df = n - 1
    chi_hi = float(stats.chi2.ppf(1.0 - alpha / 2.0, df))
    chi_lo = float(stats.chi2.ppf(alpha / 2.0, df))
    lower = df * s2 / chi_hi
    upper = df * s2 / chi_lo
    return _fill(base, s2, lower, upper)


def ci_var_ratio(
    s1_2: float, n1: int, s2_2: float, n2: int, confidence: float = 0.95
) -> dict[str, Any]:
    """CI for a ratio of variances (s1^2 / s2^2) via the F distribution."""
    validate_confidence(confidence)
    base = _base(confidence, "f")
    stats = import_scipy_stats()
    if stats is None:
        return _unavailable(base)
    if n1 < 2 or n2 < 2:
        return _mark(base, "insufficient_data", "each sample needs n >= 2")
    if s1_2 < 0 or s2_2 <= 0:
        return _mark(base, "invalid_input", "require s1_2 >= 0 and s2_2 > 0")

    base["n"] = int(n1 + n2)
    alpha = 1.0 - confidence
    df1, df2 = n1 - 1, n2 - 1
    ratio = s1_2 / s2_2
    f_hi = float(stats.f.ppf(1.0 - alpha / 2.0, df1, df2))
    f_lo = float(stats.f.ppf(alpha / 2.0, df1, df2))
    lower = ratio / f_hi
    upper = ratio / f_lo
    return _fill(base, ratio, lower, upper)
