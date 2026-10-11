"""Explicit hypothesis-test statistic and p-value engine."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from data_quality_toolkit.domain.statistics.contracts import (
    Alternative,
    PValueResult,
    TestKey,
    coerce_alternative,
    coerce_test_key,
)
from data_quality_toolkit.domain.statistics.core import (
    UNAVAILABLE_REASON,
    clean_numeric,
    import_scipy_stats,
    validate_alpha,
)

__all__ = ["calculate_p_value"]

_TWO_SIDED_ONLY = frozenset(
    {
        TestKey.ANOVA,
        TestKey.CHI_GOF,
        TestKey.CHI_IND,
        TestKey.CHI_HOMOG,
    }
)


def _result(
    *,
    status: str,
    test_key: TestKey,
    alpha: float,
    alternative: Alternative,
    method: str,
    statistic: float | None = None,
    p_value: float | None = None,
    reject_null: bool | None = None,
    reason: str | None = None,
    warnings: tuple[str, ...] = (),
    messages: tuple[str, ...] = (),
    assumptions: dict[str, Any] | None = None,
    scipy_available: bool = True,
) -> dict[str, Any]:
    data = PValueResult(
        status=status,
        test_key=test_key,
        statistic=statistic,
        p_value=p_value,
        alpha=alpha,
        reject_null=reject_null,
        method=method,
        reason=reason,
        alternative=alternative,
        warnings=warnings,
        messages=messages,
        assumptions=assumptions or {},
    ).to_dict()
    data["scipy_available"] = scipy_available
    return data


def _invalid(
    test_key: TestKey,
    alpha: float,
    alternative: Alternative,
    reason: str,
    method: str = "hypothesis_test",
) -> dict[str, Any]:
    return _result(
        status="invalid_input",
        test_key=test_key,
        alpha=alpha,
        alternative=alternative,
        method=method,
        reason=reason,
    )


def _insufficient(
    test_key: TestKey,
    alpha: float,
    alternative: Alternative,
    reason: str,
    method: str,
) -> dict[str, Any]:
    return _result(
        status="insufficient_data",
        test_key=test_key,
        alpha=alpha,
        alternative=alternative,
        method=method,
        reason=reason,
    )


def _finish(
    *,
    test_key: TestKey,
    alpha: float,
    alternative: Alternative,
    method: str,
    statistic: float,
    p_value: float,
    warnings: tuple[str, ...] = (),
    messages: tuple[str, ...] = (),
    assumptions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = float(np.clip(p_value, 0.0, 1.0))
    return _result(
        status="ok",
        test_key=test_key,
        alpha=alpha,
        alternative=alternative,
        method=method,
        statistic=float(statistic),
        p_value=p,
        reject_null=bool(p < alpha),
        warnings=warnings,
        messages=messages,
        assumptions=assumptions,
    )


def _p_from_cdf_sf(cdf: float, sf: float, alternative: Alternative) -> float:
    if alternative == Alternative.GREATER:
        return sf
    if alternative == Alternative.LESS:
        return cdf
    return min(1.0, 2.0 * min(cdf, sf))


def _p_symmetric(stats: Any, statistic: float, df: float | None, alternative: Alternative) -> float:
    if df is None:
        cdf = float(stats.norm.cdf(statistic))
        sf = float(stats.norm.sf(statistic))
    else:
        cdf = float(stats.t.cdf(statistic, df))
        sf = float(stats.t.sf(statistic, df))
    return _p_from_cdf_sf(cdf, sf, alternative)


def _p_upper_tail_only(stats: Any, statistic: float, dist: str, df: Any) -> float:
    if dist == "chi2":
        return float(stats.chi2.sf(statistic, df))
    if dist == "f":
        df1, df2 = df
        return float(stats.f.sf(statistic, df1, df2))
    raise ValueError(f"unsupported upper-tail distribution: {dist}")


def _p_positive_distribution(
    stats: Any,
    statistic: float,
    dist: str,
    df: Any,
    alternative: Alternative,
) -> float:
    if dist == "chi2":
        cdf = float(stats.chi2.cdf(statistic, df))
        sf = float(stats.chi2.sf(statistic, df))
    elif dist == "f":
        df1, df2 = df
        cdf = float(stats.f.cdf(statistic, df1, df2))
        sf = float(stats.f.sf(statistic, df1, df2))
    else:
        raise ValueError(f"unsupported positive distribution: {dist}")
    return _p_from_cdf_sf(cdf, sf, alternative)


def _clean_pair(
    sample_a: Any,
    sample_b: Any,
    *,
    paired: bool = False,
) -> tuple[np.ndarray, np.ndarray, str | None]:
    if paired:
        a = clean_numeric(sample_a, dropna=False)
        b = clean_numeric(sample_b, dropna=False)
        if a.size != b.size:
            return a, b, "paired samples must have equal length"
        keep = np.isfinite(a) & np.isfinite(b)
        return a[keep], b[keep], None
    return clean_numeric(sample_a), clean_numeric(sample_b), None


def _variance(arr: np.ndarray) -> float:
    return float(np.var(arr, ddof=1))


def _one_sample_t(
    stats: Any,
    test_key: TestKey,
    sample: Any,
    null_mean: float,
    alpha: float,
    alternative: Alternative,
    method: str,
) -> dict[str, Any]:
    arr = clean_numeric(sample)
    n = int(arr.size)
    if n < 2:
        return _insufficient(test_key, alpha, alternative, "need at least 2 finite values", method)
    sd = float(np.std(arr, ddof=1))
    if sd <= 0:
        return _invalid(
            test_key, alpha, alternative, "sample standard deviation must be > 0", method
        )
    statistic = (float(np.mean(arr)) - null_mean) / (sd / np.sqrt(n))
    df = n - 1
    p_value = _p_symmetric(stats, statistic, float(df), alternative)
    return _finish(
        test_key=test_key,
        alpha=alpha,
        alternative=alternative,
        method=method,
        statistic=statistic,
        p_value=p_value,
        assumptions={"n": n, "df": df, "null_mean": null_mean},
    )


def _two_sample_t(
    stats: Any,
    test_key: TestKey,
    sample_a: Any,
    sample_b: Any,
    null_difference: float,
    alpha: float,
    alternative: Alternative,
    *,
    equal_var: bool,
) -> dict[str, Any]:
    method = "two_sample_t_equal_var" if equal_var else "two_sample_t_welch"
    a, b, err = _clean_pair(sample_a, sample_b)
    if err is not None:
        return _invalid(test_key, alpha, alternative, err, method)
    n1, n2 = int(a.size), int(b.size)
    if n1 < 2 or n2 < 2:
        return _insufficient(
            test_key,
            alpha,
            alternative,
            "each sample needs at least 2 finite values",
            method,
        )
    var1, var2 = _variance(a), _variance(b)
    mean_diff = float(np.mean(a) - np.mean(b) - null_difference)
    if equal_var:
        df = float(n1 + n2 - 2)
        pooled = ((n1 - 1) * var1 + (n2 - 1) * var2) / df
        se = np.sqrt(pooled * (1.0 / n1 + 1.0 / n2))
    else:
        se = np.sqrt(var1 / n1 + var2 / n2)
        numerator = (var1 / n1 + var2 / n2) ** 2
        denominator = (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
        df = numerator / denominator if denominator > 0 else 0.0
    if se <= 0 or df <= 0:
        return _invalid(test_key, alpha, alternative, "standard error must be > 0", method)
    statistic = mean_diff / se
    p_value = _p_symmetric(stats, statistic, float(df), alternative)
    return _finish(
        test_key=test_key,
        alpha=alpha,
        alternative=alternative,
        method=method,
        statistic=statistic,
        p_value=p_value,
        assumptions={"n_a": n1, "n_b": n2, "df": float(df), "null_difference": null_difference},
    )


def _one_sample_z(
    stats: Any,
    sample: Any,
    null_mean: float,
    sigma: float | None,
    alpha: float,
    alternative: Alternative,
) -> dict[str, Any]:
    method = "one_sample_z"
    arr = clean_numeric(sample)
    n = int(arr.size)
    if n < 1:
        return _insufficient(
            TestKey.ONE_Z, alpha, alternative, "need at least 1 finite value", method
        )
    if sigma is None or sigma <= 0:
        return _invalid(TestKey.ONE_Z, alpha, alternative, "sigma must be > 0", method)
    statistic = (float(np.mean(arr)) - null_mean) / (sigma / np.sqrt(n))
    p_value = _p_symmetric(stats, statistic, None, alternative)
    return _finish(
        test_key=TestKey.ONE_Z,
        alpha=alpha,
        alternative=alternative,
        method=method,
        statistic=statistic,
        p_value=p_value,
        assumptions={"n": n, "sigma": sigma, "null_mean": null_mean},
    )


def _two_sample_z(
    stats: Any,
    sample_a: Any,
    sample_b: Any,
    null_difference: float,
    sigma_a: float | None,
    sigma_b: float | None,
    alpha: float,
    alternative: Alternative,
) -> dict[str, Any]:
    method = "two_sample_z"
    a, b, err = _clean_pair(sample_a, sample_b)
    if err is not None:
        return _invalid(TestKey.TWO_Z, alpha, alternative, err, method)
    n1, n2 = int(a.size), int(b.size)
    if n1 < 1 or n2 < 1:
        return _insufficient(
            TestKey.TWO_Z,
            alpha,
            alternative,
            "each sample needs at least 1 finite value",
            method,
        )
    if sigma_a is None or sigma_b is None or sigma_a <= 0 or sigma_b <= 0:
        return _invalid(
            TestKey.TWO_Z, alpha, alternative, "sigma_a and sigma_b must be > 0", method
        )
    se = np.sqrt(sigma_a**2 / n1 + sigma_b**2 / n2)
    statistic = (float(np.mean(a) - np.mean(b) - null_difference)) / se
    p_value = _p_symmetric(stats, statistic, None, alternative)
    return _finish(
        test_key=TestKey.TWO_Z,
        alpha=alpha,
        alternative=alternative,
        method=method,
        statistic=statistic,
        p_value=p_value,
        assumptions={
            "n_a": n1,
            "n_b": n2,
            "sigma_a": sigma_a,
            "sigma_b": sigma_b,
            "null_difference": null_difference,
        },
    )


def _paired_t(
    stats: Any,
    sample_a: Any,
    sample_b: Any,
    null_difference: float,
    alpha: float,
    alternative: Alternative,
) -> dict[str, Any]:
    method = "paired_t"
    a, b, err = _clean_pair(sample_a, sample_b, paired=True)
    if err is not None:
        return _invalid(TestKey.PAIRED_T, alpha, alternative, err, method)
    return _one_sample_t(
        stats,
        TestKey.PAIRED_T,
        a - b,
        null_difference,
        alpha,
        alternative,
        method,
    )


def _anova(
    stats: Any,
    groups: Sequence[Any] | None,
    alpha: float,
    alternative: Alternative,
    warnings: tuple[str, ...],
) -> dict[str, Any]:
    method = "one_way_anova"
    if groups is None:
        return _invalid(TestKey.ANOVA, alpha, alternative, "groups are required", method)
    arrays = [clean_numeric(group) for group in groups]
    if len(arrays) < 2:
        return _insufficient(TestKey.ANOVA, alpha, alternative, "need at least 2 groups", method)
    if any(arr.size < 2 for arr in arrays):
        return _insufficient(
            TestKey.ANOVA,
            alpha,
            alternative,
            "each group needs at least 2 finite values",
            method,
        )
    result = stats.f_oneway(*arrays)
    return _finish(
        test_key=TestKey.ANOVA,
        alpha=alpha,
        alternative=alternative,
        method=method,
        statistic=float(result.statistic),
        p_value=float(result.pvalue),
        warnings=warnings,
        assumptions={"group_count": len(arrays), "n_total": int(sum(arr.size for arr in arrays))},
    )


def _one_prop_z(
    stats: Any,
    successes: int | None,
    n: int | None,
    null_proportion: float | None,
    alpha: float,
    alternative: Alternative,
) -> dict[str, Any]:
    method = "one_proportion_z"
    if successes is None or n is None or null_proportion is None:
        return _invalid(
            TestKey.ONE_PROP_Z,
            alpha,
            alternative,
            "successes, n, and null_proportion are required",
            method,
        )
    if n <= 0:
        return _invalid(TestKey.ONE_PROP_Z, alpha, alternative, "n must be > 0", method)
    if not 0 <= successes <= n:
        return _invalid(
            TestKey.ONE_PROP_Z,
            alpha,
            alternative,
            "require 0 <= successes <= n",
            method,
        )
    if not 0.0 < null_proportion < 1.0:
        return _invalid(
            TestKey.ONE_PROP_Z,
            alpha,
            alternative,
            "null_proportion must be in (0, 1)",
            method,
        )
    phat = successes / n
    se = np.sqrt(null_proportion * (1.0 - null_proportion) / n)
    statistic = (phat - null_proportion) / se
    p_value = _p_symmetric(stats, statistic, None, alternative)
    return _finish(
        test_key=TestKey.ONE_PROP_Z,
        alpha=alpha,
        alternative=alternative,
        method=method,
        statistic=statistic,
        p_value=p_value,
        assumptions={"successes": successes, "n": n, "null_proportion": null_proportion},
    )


def _two_prop_z(
    stats: Any,
    successes_a: int | None,
    n_a: int | None,
    successes_b: int | None,
    n_b: int | None,
    alpha: float,
    alternative: Alternative,
) -> dict[str, Any]:
    method = "two_proportion_z"
    missing = any(value is None for value in (successes_a, n_a, successes_b, n_b))
    if missing:
        return _invalid(
            TestKey.TWO_PROP_Z,
            alpha,
            alternative,
            "successes_a, n_a, successes_b, and n_b are required",
            method,
        )
    assert successes_a is not None
    assert successes_b is not None
    assert n_a is not None
    assert n_b is not None
    if n_a <= 0 or n_b <= 0:
        return _invalid(TestKey.TWO_PROP_Z, alpha, alternative, "n_a and n_b must be > 0", method)
    if not (0 <= successes_a <= n_a and 0 <= successes_b <= n_b):
        return _invalid(
            TestKey.TWO_PROP_Z,
            alpha,
            alternative,
            "require 0 <= successes <= n for both groups",
            method,
        )
    pooled = (successes_a + successes_b) / (n_a + n_b)
    se = np.sqrt(pooled * (1.0 - pooled) * (1.0 / n_a + 1.0 / n_b))
    if se <= 0:
        return _invalid(
            TestKey.TWO_PROP_Z, alpha, alternative, "standard error must be > 0", method
        )
    p_a = successes_a / n_a
    p_b = successes_b / n_b
    statistic = (p_a - p_b) / se
    p_value = _p_symmetric(stats, statistic, None, alternative)
    return _finish(
        test_key=TestKey.TWO_PROP_Z,
        alpha=alpha,
        alternative=alternative,
        method=method,
        statistic=statistic,
        p_value=p_value,
        assumptions={
            "successes_a": successes_a,
            "n_a": n_a,
            "successes_b": successes_b,
            "n_b": n_b,
        },
    )


def _one_var_chi(
    stats: Any,
    sample: Any,
    null_variance: float | None,
    alpha: float,
    alternative: Alternative,
) -> dict[str, Any]:
    method = "one_variance_chi_square"
    arr = clean_numeric(sample)
    n = int(arr.size)
    if n < 2:
        return _insufficient(
            TestKey.ONE_VAR_CHI, alpha, alternative, "need at least 2 values", method
        )
    if null_variance is None or null_variance <= 0:
        return _invalid(
            TestKey.ONE_VAR_CHI,
            alpha,
            alternative,
            "null_variance must be > 0",
            method,
        )
    df = n - 1
    statistic = df * _variance(arr) / null_variance
    p_value = _p_positive_distribution(stats, statistic, "chi2", df, alternative)
    return _finish(
        test_key=TestKey.ONE_VAR_CHI,
        alpha=alpha,
        alternative=alternative,
        method=method,
        statistic=statistic,
        p_value=p_value,
        assumptions={"n": n, "df": df, "null_variance": null_variance},
    )


def _f_var(
    stats: Any,
    sample_a: Any,
    sample_b: Any,
    alpha: float,
    alternative: Alternative,
) -> dict[str, Any]:
    method = "f_variance_ratio"
    a, b, err = _clean_pair(sample_a, sample_b)
    if err is not None:
        return _invalid(TestKey.F_VAR, alpha, alternative, err, method)
    n1, n2 = int(a.size), int(b.size)
    if n1 < 2 or n2 < 2:
        return _insufficient(TestKey.F_VAR, alpha, alternative, "each sample needs n >= 2", method)
    var1, var2 = _variance(a), _variance(b)
    if var2 <= 0:
        return _invalid(TestKey.F_VAR, alpha, alternative, "sample_b variance must be > 0", method)
    statistic = var1 / var2
    df = (n1 - 1, n2 - 1)
    p_value = _p_positive_distribution(stats, statistic, "f", df, alternative)
    return _finish(
        test_key=TestKey.F_VAR,
        alpha=alpha,
        alternative=alternative,
        method=method,
        statistic=statistic,
        p_value=p_value,
        assumptions={"n_a": n1, "n_b": n2, "df_a": df[0], "df_b": df[1]},
    )


def _observed_expected(
    observed: Any,
    expected: Any | None,
) -> tuple[np.ndarray, np.ndarray | None, str | None]:
    obs = np.asarray(observed, dtype=float).ravel()
    exp = None if expected is None else np.asarray(expected, dtype=float).ravel()
    if obs.size < 2:
        return obs, exp, "observed must contain at least 2 categories"
    if np.any(obs < 0):
        return obs, exp, "observed counts must be non-negative"
    if float(np.sum(obs)) <= 0:
        return obs, exp, "observed counts must sum to > 0"
    if exp is not None:
        if exp.size != obs.size:
            return obs, exp, "expected must have the same length as observed"
        if np.any(exp <= 0):
            return obs, exp, "expected counts must be > 0"
        exp = exp * (float(np.sum(obs)) / float(np.sum(exp)))
    return obs, exp, None


# Expected-count reliability diagnostics for the chi-square family (informational).
# Conventional guidance: the chi-square approximation becomes unreliable when any
# expected cell count is below 1, or when more than 20% of the expected cell counts
# are below 5. These are interpretation diagnostics owned by the domain, not validity
# gates: they never change the statistic, the p-value, or which test is run.
_EXPECTED_MIN_FLOOR = 1.0
_EXPECTED_SMALL_CELL = 5.0
_EXPECTED_SMALL_CELL_FRACTION = 0.2

_EXPECTED_BELOW_ONE_WARNING = (
    "Some expected cell counts are below 1; the chi-square approximation may be "
    "unreliable (informational; the test is unchanged)."
)


def _expected_count_diagnostics(
    expected: Any,
) -> tuple[tuple[str, ...], dict[str, Any]]:
    """Classify the expected counts a chi-square test actually used.

    Returns ``(warnings, diagnostics)``. ``warnings`` carries the operator-facing
    reliability messages; ``diagnostics`` carries the structured counterpart every
    surface can consume without re-deriving the thresholds. Deterministic and purely
    informational — the caller never alters the test because of it.
    """
    flat = np.asarray(expected, dtype=float).ravel()
    finite = flat[np.isfinite(flat)]
    if finite.size == 0:
        return (), {
            "cells": int(flat.size),
            "min_expected": None,
            "cells_below_1": 0,
            "cells_below_5": 0,
            "fraction_below_5": None,
            "any_below_1": False,
            "over_20pct_below_5": False,
            "sparse": False,
        }
    min_expected = float(finite.min())
    below_one = int(np.count_nonzero(finite < _EXPECTED_MIN_FLOOR))
    below_five = int(np.count_nonzero(finite < _EXPECTED_SMALL_CELL))
    fraction_small = float(below_five) / float(finite.size)
    any_below_one = min_expected < _EXPECTED_MIN_FLOOR
    over_fraction = fraction_small > _EXPECTED_SMALL_CELL_FRACTION

    warnings: list[str] = []
    if any_below_one:
        warnings.append(_EXPECTED_BELOW_ONE_WARNING)
    if over_fraction:
        warnings.append(
            f"{fraction_small * 100:.0f}% of expected cell counts are below 5 (>20%); the "
            "chi-square approximation may be unreliable (informational; the test is unchanged)."
        )
    diagnostics = {
        "cells": int(finite.size),
        "min_expected": min_expected,
        "cells_below_1": below_one,
        "cells_below_5": below_five,
        "fraction_below_5": fraction_small,
        "any_below_1": any_below_one,
        "over_20pct_below_5": over_fraction,
        "sparse": bool(warnings),
    }
    return tuple(warnings), diagnostics


def _chi_gof(
    stats: Any,
    observed: Any,
    expected: Any | None,
    alpha: float,
    alternative: Alternative,
    warnings: tuple[str, ...],
) -> dict[str, Any]:
    method = "chi_square_goodness_of_fit"
    obs, exp, err = _observed_expected(observed, expected)
    if err is not None:
        return _invalid(TestKey.CHI_GOF, alpha, alternative, err, method)
    result = stats.chisquare(f_obs=obs, f_exp=exp)
    # scipy assigns an equal expected count to every category when f_exp is omitted;
    # diagnose the expected counts the test actually used, never a re-derived table.
    expected_used = exp if exp is not None else np.full(obs.size, float(np.sum(obs)) / obs.size)
    expected_warnings, expected_diagnostics = _expected_count_diagnostics(expected_used)
    return _finish(
        test_key=TestKey.CHI_GOF,
        alpha=alpha,
        alternative=alternative,
        method=method,
        statistic=float(result.statistic),
        p_value=float(result.pvalue),
        warnings=warnings + expected_warnings,
        assumptions={
            "categories": int(obs.size),
            "df": int(obs.size - 1),
            "expected_counts": expected_diagnostics,
            "continuity_correction": False,
        },
    )


def _chi_table(
    stats: Any,
    test_key: TestKey,
    table: Any,
    alpha: float,
    alternative: Alternative,
    warnings: tuple[str, ...],
) -> dict[str, Any]:
    method = "chi_square_independence" if test_key == TestKey.CHI_IND else "chi_square_homogeneity"
    arr = np.asarray(table, dtype=float)
    if arr.ndim != 2 or min(arr.shape) < 2:
        return _invalid(test_key, alpha, alternative, "table must be a 2-D matrix", method)
    if np.any(arr < 0):
        return _invalid(test_key, alpha, alternative, "table counts must be non-negative", method)
    if float(np.sum(arr)) <= 0:
        return _invalid(test_key, alpha, alternative, "table counts must sum to > 0", method)
    result = stats.chi2_contingency(arr)
    statistic = float(result.statistic)
    p_value = float(result.pvalue)
    dof = int(result.dof)
    expected_warnings, expected_diagnostics = _expected_count_diagnostics(result.expected_freq)
    # scipy's chi2_contingency defaults to correction=True and applies Yates' continuity
    # correction only when dof == 1 — which, given the 2-D minimum-2 shape guard above,
    # means exactly a 2x2 table. The behaviour is preserved and disclosed, not changed.
    correction_applied = dof == 1
    messages: tuple[str, ...] = ()
    if correction_applied:
        messages = (
            "Yates' continuity correction was applied because the table has 1 degree of "
            "freedom (2x2); the reported statistic and p-value are the corrected values.",
        )
    return _finish(
        test_key=test_key,
        alpha=alpha,
        alternative=alternative,
        method=method,
        statistic=statistic,
        p_value=p_value,
        warnings=warnings + expected_warnings,
        messages=messages,
        assumptions={
            "rows": int(arr.shape[0]),
            "columns": int(arr.shape[1]),
            "dof": dof,
            "expected_counts": expected_diagnostics,
            "continuity_correction": correction_applied,
        },
    )


def _coerce_alpha_alt(
    test_key: TestKey,
    alpha: float,
    alternative: Alternative | str,
) -> tuple[Alternative, dict[str, Any] | None]:
    try:
        validate_alpha(alpha)
    except ValueError as exc:
        return Alternative.TWO_SIDED, _invalid(test_key, alpha, Alternative.TWO_SIDED, str(exc))
    try:
        alt = coerce_alternative(alternative)
    except ValueError as exc:
        return Alternative.TWO_SIDED, _invalid(test_key, alpha, Alternative.TWO_SIDED, str(exc))
    return alt, None


def calculate_p_value(  # noqa: C901
    test_key: TestKey | str,
    *,
    sample: Any = None,
    sample_a: Any = None,
    sample_b: Any = None,
    groups: Sequence[Any] | None = None,
    successes: int | None = None,
    n: int | None = None,
    successes_a: int | None = None,
    n_a: int | None = None,
    successes_b: int | None = None,
    n_b: int | None = None,
    observed: Any = None,
    expected: Any = None,
    table: Any = None,
    null_mean: float = 0.0,
    null_difference: float = 0.0,
    null_proportion: float | None = None,
    null_variance: float | None = None,
    sigma: float | None = None,
    sigma_a: float | None = None,
    sigma_b: float | None = None,
    alternative: Alternative | str = Alternative.TWO_SIDED,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Run an explicit first-wave hypothesis-test branch and return a status dict."""
    try:
        key = coerce_test_key(test_key)
    except ValueError:
        key = TestKey.UNKNOWN
    alt, invalid = _coerce_alpha_alt(key, alpha, alternative)
    if invalid is not None:
        return invalid

    if key == TestKey.UNKNOWN:
        return _result(
            status="unsupported",
            test_key=key,
            alpha=alpha,
            alternative=alt,
            method="hypothesis_test",
            reason="unsupported or unknown test key",
        )

    warnings: list[str] = []
    if key in _TWO_SIDED_ONLY and alt != Alternative.TWO_SIDED:
        warnings.append(f"{key.value} is handled as two-sided in the first-wave engine.")
        alt = Alternative.TWO_SIDED

    stats = import_scipy_stats()
    if stats is None:
        return _result(
            status="unavailable",
            test_key=key,
            alpha=alpha,
            alternative=alt,
            method="hypothesis_test",
            reason=UNAVAILABLE_REASON,
            scipy_available=False,
        )

    if key == TestKey.ONE_Z:
        return _one_sample_z(stats, sample, null_mean, sigma, alpha, alt)
    if key == TestKey.ONE_T:
        return _one_sample_t(stats, key, sample, null_mean, alpha, alt, "one_sample_t")
    if key == TestKey.TWO_Z:
        sig_a = sigma if sigma_a is None else sigma_a
        sig_b = sigma if sigma_b is None else sigma_b
        return _two_sample_z(
            stats,
            sample_a,
            sample_b,
            null_difference,
            sig_a,
            sig_b,
            alpha,
            alt,
        )
    if key == TestKey.TWO_T_EQ:
        return _two_sample_t(
            stats,
            key,
            sample_a,
            sample_b,
            null_difference,
            alpha,
            alt,
            equal_var=True,
        )
    if key == TestKey.TWO_T_WELCH:
        return _two_sample_t(
            stats,
            key,
            sample_a,
            sample_b,
            null_difference,
            alpha,
            alt,
            equal_var=False,
        )
    if key == TestKey.PAIRED_T:
        return _paired_t(stats, sample_a, sample_b, null_difference, alpha, alt)
    if key == TestKey.ANOVA:
        return _anova(stats, groups, alpha, alt, tuple(warnings))
    if key == TestKey.ONE_PROP_Z:
        return _one_prop_z(stats, successes, n, null_proportion, alpha, alt)
    if key == TestKey.TWO_PROP_Z:
        return _two_prop_z(stats, successes_a, n_a, successes_b, n_b, alpha, alt)
    if key == TestKey.ONE_VAR_CHI:
        return _one_var_chi(stats, sample, null_variance, alpha, alt)
    if key == TestKey.F_VAR:
        return _f_var(stats, sample_a, sample_b, alpha, alt)
    if key == TestKey.CHI_GOF:
        return _chi_gof(stats, observed, expected, alpha, alt, tuple(warnings))
    if key in {TestKey.CHI_IND, TestKey.CHI_HOMOG}:
        return _chi_table(stats, key, table, alpha, alt, tuple(warnings))

    return _result(
        status="unsupported",
        test_key=key,
        alpha=alpha,
        alternative=alt,
        method="hypothesis_test",
        reason=f"{key.value} is not implemented in the first-wave engine",
    )
