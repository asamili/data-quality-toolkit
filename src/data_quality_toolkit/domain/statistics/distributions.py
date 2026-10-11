# src/data_quality_toolkit/domain/statistics/distributions.py
"""Thin scipy-guarded distribution wrappers (pdf / cdf / pmf).

Internal kernel layer with consistent input validation. Each function returns a
``float`` when scipy is available, or ``None`` when scipy (the optional
``[stats]`` extra) is not installed — never raising ImportError. Invalid
parameters raise ``ValueError`` regardless of scipy availability.

Covered families (first wave): normal, Student-t, chi-square, F, binomial,
Poisson, uniform, exponential.
"""

from __future__ import annotations

from data_quality_toolkit.domain.statistics.core import import_scipy_stats

__all__ = [
    "normal_pdf",
    "normal_cdf",
    "t_pdf",
    "t_cdf",
    "chi2_pdf",
    "chi2_cdf",
    "f_pdf",
    "f_cdf",
    "binom_pmf",
    "binom_cdf",
    "poisson_pmf",
    "poisson_cdf",
    "uniform_pdf",
    "uniform_cdf",
    "exponential_pdf",
    "exponential_cdf",
]


def _require_positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")


# ── Normal ────────────────────────────────────────────────────────────────────


def normal_pdf(x: float, mu: float = 0.0, sigma: float = 1.0) -> float | None:
    """Normal pdf at ``x``. Requires ``sigma > 0``."""
    _require_positive("sigma", sigma)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.norm.pdf(x, loc=mu, scale=sigma))


def normal_cdf(x: float, mu: float = 0.0, sigma: float = 1.0) -> float | None:
    """Normal cdf at ``x``. Requires ``sigma > 0``."""
    _require_positive("sigma", sigma)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.norm.cdf(x, loc=mu, scale=sigma))


# ── Student-t ─────────────────────────────────────────────────────────────────


def t_pdf(x: float, df: float) -> float | None:
    """Student-t pdf at ``x``. Requires ``df > 0``."""
    _require_positive("df", df)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.t.pdf(x, df))


def t_cdf(x: float, df: float) -> float | None:
    """Student-t cdf at ``x``. Requires ``df > 0``."""
    _require_positive("df", df)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.t.cdf(x, df))


# ── Chi-square ────────────────────────────────────────────────────────────────


def chi2_pdf(x: float, df: float) -> float | None:
    """Chi-square pdf at ``x``. Requires ``df > 0``."""
    _require_positive("df", df)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.chi2.pdf(x, df))


def chi2_cdf(x: float, df: float) -> float | None:
    """Chi-square cdf at ``x``. Requires ``df > 0``."""
    _require_positive("df", df)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.chi2.cdf(x, df))


# ── F ─────────────────────────────────────────────────────────────────────────


def f_pdf(x: float, df1: float, df2: float) -> float | None:
    """F pdf at ``x``. Requires ``df1 > 0`` and ``df2 > 0``."""
    _require_positive("df1", df1)
    _require_positive("df2", df2)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.f.pdf(x, df1, df2))


def f_cdf(x: float, df1: float, df2: float) -> float | None:
    """F cdf at ``x``. Requires ``df1 > 0`` and ``df2 > 0``."""
    _require_positive("df1", df1)
    _require_positive("df2", df2)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.f.cdf(x, df1, df2))


# ── Binomial ──────────────────────────────────────────────────────────────────


def _validate_binom(n: int, p: float) -> None:
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"p must be in [0, 1], got {p}")


def binom_pmf(k: int, n: int, p: float) -> float | None:
    """Binomial pmf at ``k``. Requires ``n >= 0`` and ``0 <= p <= 1``."""
    _validate_binom(n, p)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.binom.pmf(k, n, p))


def binom_cdf(k: int, n: int, p: float) -> float | None:
    """Binomial cdf at ``k``. Requires ``n >= 0`` and ``0 <= p <= 1``."""
    _validate_binom(n, p)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.binom.cdf(k, n, p))


# ── Poisson ───────────────────────────────────────────────────────────────────


def poisson_pmf(k: int, lam: float) -> float | None:
    """Poisson pmf at ``k``. Requires ``lam > 0``."""
    _require_positive("lam", lam)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.poisson.pmf(k, lam))


def poisson_cdf(k: int, lam: float) -> float | None:
    """Poisson cdf at ``k``. Requires ``lam > 0``."""
    _require_positive("lam", lam)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.poisson.cdf(k, lam))


# ── Uniform ───────────────────────────────────────────────────────────────────


def _validate_uniform(a: float, b: float) -> None:
    if not a < b:
        raise ValueError(f"require a < b, got a={a}, b={b}")


def uniform_pdf(x: float, a: float = 0.0, b: float = 1.0) -> float | None:
    """Uniform pdf at ``x`` over [a, b]. Requires ``a < b``."""
    _validate_uniform(a, b)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.uniform.pdf(x, loc=a, scale=b - a))


def uniform_cdf(x: float, a: float = 0.0, b: float = 1.0) -> float | None:
    """Uniform cdf at ``x`` over [a, b]. Requires ``a < b``."""
    _validate_uniform(a, b)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.uniform.cdf(x, loc=a, scale=b - a))


# ── Exponential ───────────────────────────────────────────────────────────────


def exponential_pdf(x: float, lam: float = 1.0) -> float | None:
    """Exponential pdf at ``x`` with rate ``lam`` (scipy scale = 1/lam). ``lam > 0``."""
    _require_positive("lam", lam)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.expon.pdf(x, scale=1.0 / lam))


def exponential_cdf(x: float, lam: float = 1.0) -> float | None:
    """Exponential cdf at ``x`` with rate ``lam`` (scipy scale = 1/lam). ``lam > 0``."""
    _require_positive("lam", lam)
    stats = import_scipy_stats()
    if stats is None:
        return None
    return float(stats.expon.cdf(x, scale=1.0 / lam))
