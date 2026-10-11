# src/data_quality_toolkit/domain/statistics/assumptions.py
"""Assumption-check kernel: homogeneity of variance (Levene).

A narrow, scipy-guarded companion to ``domain/statistics/inferential.py``. This
module adds only the assumption-check capability the inferential tier does not
already provide — a homogeneity-of-variance (equal-variance) test — so the
Statistics Lab can *display* whether the assumptions behind a group comparison
plausibly hold. It never selects or changes a statistical test.

Normality is already covered by ``inferential.check_normality`` (Shapiro-Wilk)
and is reused as-is rather than duplicated here.

Requires scipy, shipped as the optional ``[stats]`` extra. When scipy is not
installed ``check_equal_variance`` returns ``status="unavailable"`` instead of
raising, mirroring ``inferential`` and ``drift``. It returns a plain dict with
stable keys and a ``status`` field, and never raises except on invalid ``alpha``.

Interpretations are deliberately cautious: "evidence of unequal variance" /
"no strong evidence of unequal variance" — never "proves equal". The Levene test
is median-centered (Brown-Forsythe), which is robust to non-normal data.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from data_quality_toolkit.domain.statistics.core import (
    UNAVAILABLE_REASON,
    import_scipy_stats,
    validate_alpha,
)

__all__ = ["check_equal_variance"]

# Default minimum per-group size for a meaningful variance comparison.
MIN_GROUP_N = 3


def _equal_variance_base(alpha: float) -> dict[str, Any]:
    return {
        "status": "ok",
        "reason": None,
        "alpha": alpha,
        "scipy_available": True,
        "method": "levene",
        "statistic": None,
        "p_value": None,
        "n_groups": 0,
        "interpretation": "",
        "warnings": [],
    }


def _finite_groups(samples: Sequence[Sequence[float]], *, min_group_n: int) -> list[np.ndarray]:
    """Coerce each sample to a finite float array and keep those with >= min_group_n."""
    usable: list[np.ndarray] = []
    for sample in samples:
        arr = np.asarray(list(sample), dtype=float).ravel()
        arr = arr[np.isfinite(arr)]
        if arr.size >= min_group_n:
            usable.append(arr)
    return usable


def check_equal_variance(
    samples: Sequence[Sequence[float]],
    *,
    alpha: float = 0.05,
    min_group_n: int = MIN_GROUP_N,
) -> dict[str, Any]:
    """Levene (median-centered) homogeneity-of-variance check across groups.

    ``samples`` is a sequence of already-split numeric groups; the caller does the
    splitting so this kernel stays pure. Statuses: ``ok`` / ``unavailable`` /
    ``insufficient_data`` / ``not_applicable``. Never raises except on invalid
    ``alpha``.
    """
    validate_alpha(alpha)
    base = _equal_variance_base(alpha)

    stats_mod = import_scipy_stats()
    if stats_mod is None:
        base["status"] = "unavailable"
        base["scipy_available"] = False
        base["reason"] = UNAVAILABLE_REASON
        base["interpretation"] = UNAVAILABLE_REASON
        return base

    usable = _finite_groups(samples, min_group_n=min_group_n)
    base["n_groups"] = len(usable)
    if len(usable) < 2:
        base["status"] = "not_applicable"
        base["reason"] = f"need at least two groups with >= {min_group_n} finite values each"
        base["interpretation"] = base["reason"]
        return base

    if all(np.ptp(arr) == 0.0 for arr in usable):
        base["status"] = "not_applicable"
        base["reason"] = "all groups are constant; the variance test is undefined"
        base["interpretation"] = base["reason"]
        return base

    try:
        result = stats_mod.levene(*usable, center="median")
        statistic = float(result.statistic)
        p_value = float(result.pvalue)
    except (ValueError, ZeroDivisionError, FloatingPointError) as exc:
        base["status"] = "insufficient_data"
        base["reason"] = f"variance test could not be computed: {exc}"
        base["interpretation"] = base["reason"]
        return base

    if not np.isfinite(statistic) or not np.isfinite(p_value):
        base["status"] = "insufficient_data"
        base["reason"] = "variance test produced a non-finite result"
        base["interpretation"] = base["reason"]
        return base

    base["statistic"] = round(statistic, 6)
    base["p_value"] = round(p_value, 6)
    if p_value < alpha:
        base["interpretation"] = (
            f"p={p_value:.4g} < alpha={alpha:g}: evidence of unequal variance across groups "
            "(the equal-variance assumption may not hold)."
        )
    else:
        base["interpretation"] = (
            f"p={p_value:.4g} >= alpha={alpha:g}: no strong evidence of unequal variance."
        )
    return base
