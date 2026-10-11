# src/data_quality_toolkit/domain/statistics/core.py
"""Shared kernel helpers for the statistics domain.

Optional-dependency guard, input validation, and critical-value conversions used
by the other statistics kernel modules (distributions, intervals, effect_size,
bootstrap, power). Pure and dependency-light: only numpy at import time.

scipy is the optional ``[stats]`` extra and is reached through
``import_scipy_stats`` so a missing scipy never crashes import. Critical-value
conversions return ``None`` when scipy is unavailable, mirroring the graceful
degradation in ``inferential`` and ``drift``.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from typing import Any

import numpy as np

__all__ = [
    "UNAVAILABLE_REASON",
    "import_scipy_stats",
    "scipy_available",
    "validate_alpha",
    "validate_confidence",
    "clean_numeric",
    "has_enough_observations",
    "confidence_level_to_z",
    "confidence_level_to_t",
    "z_to_confidence_level",
]

UNAVAILABLE_REASON = (
    "scipy is not installed; install the stats extra: pip install data-quality-toolkit[stats]"
)

# Normal-approximation threshold: at/above this df the t critical value is
# indistinguishable from the z value, so we fall back to the normal quantile.
_T_NORMAL_FALLBACK_DF = 1000


def import_scipy_stats() -> Any | None:
    """Return ``scipy.stats``, or ``None`` when scipy is not installed."""
    try:
        from scipy import stats
    except ImportError:
        return None
    return stats


def scipy_available() -> bool:
    """Return True when scipy is importable, without importing it."""
    try:
        return importlib.util.find_spec("scipy") is not None
    except (ImportError, ValueError):
        return False


def validate_alpha(alpha: float) -> None:
    """Raise ``ValueError`` unless ``alpha`` is a probability in the open (0, 1)."""
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")


def validate_confidence(confidence: float) -> None:
    """Raise ``ValueError`` unless ``confidence`` is in the open (0, 1)."""
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")


def clean_numeric(
    values: Sequence[float] | np.ndarray | Any,
    *,
    dropna: bool = True,
    max_rows: int | None = None,
    seed: int = 0,
) -> np.ndarray:
    """Coerce ``values`` to a 1-D float array, optionally dropping non-finite values.

    When ``max_rows`` is set and the cleaned array is larger, a deterministic
    sub-sample (seeded, order-preserving) of ``max_rows`` values is returned so
    downstream compute stays bounded.
    """
    arr = np.asarray(values, dtype=float).ravel()
    if dropna:
        arr = arr[np.isfinite(arr)]
    if max_rows is not None and arr.size > max_rows:
        rng = np.random.default_rng(seed)
        idx = np.sort(rng.choice(arr.size, size=max_rows, replace=False))
        arr = arr[idx]
    return arr


def has_enough_observations(values: np.ndarray | Sequence[float], min_n: int = 2) -> bool:
    """Return True when ``values`` holds at least ``min_n`` entries."""
    return int(np.asarray(values).size) >= min_n


def confidence_level_to_z(confidence_level: float) -> float | None:
    """Two-sided z critical value for a confidence level: ``Phi^-1((1+c)/2)``.

    Returns ``None`` when scipy is unavailable.
    """
    validate_confidence(confidence_level)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.norm.ppf((1.0 + confidence_level) / 2.0))


def confidence_level_to_t(confidence_level: float, df: float) -> float | None:
    """Two-sided t critical value for a confidence level and degrees of freedom.

    Falls back to the normal quantile when ``df >= 1000``. Returns ``None`` when
    scipy is unavailable.
    """
    validate_confidence(confidence_level)
    if df <= 0:
        raise ValueError(f"df must be > 0, got {df}")
    stats = import_scipy_stats()
    if stats is None:
        return None
    quantile = (1.0 + confidence_level) / 2.0
    if df >= _T_NORMAL_FALLBACK_DF:
        return float(stats.norm.ppf(quantile))
    return float(stats.t.ppf(quantile, df))


def z_to_confidence_level(z: float) -> float | None:
    """Confidence level implied by a two-sided z value: ``2*Phi(|z|) - 1``.

    Returns ``None`` when scipy is unavailable.
    """
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(2.0 * stats.norm.cdf(abs(z)) - 1.0)
