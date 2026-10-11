"""Statistics Lab helpers: dependency-free descriptive stats plus scipy-guarded
inferential wrappers.

Pure, deterministic, streamlit-free. Descriptive helpers use only pandas/numpy
(core dependencies). Inferential helpers delegate to
``domain.statistics.inferential`` and are guarded on the optional ``[stats]``
extra (scipy); ``inferential_available`` probes scipy without importing it so the
page can degrade gracefully when scipy is absent.
"""

from __future__ import annotations

import importlib.util
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data_quality_toolkit.adapters.ui.services.statistics_eligibility import (
    IDENTIFIER_LIKE,
    STATS_CATEGORICAL_MAX_LEVELS,
    TOO_MANY_LEVELS,
    classify_categorical_column,
    exceeds_level_ceiling,
    summarize_labels,
)
from data_quality_toolkit.api import compare_ab as _api_compare_ab
from data_quality_toolkit.api import run_statistical_test as _api_run_statistical_test
from data_quality_toolkit.api import select_statistical_test as _api_select_statistical_test
from data_quality_toolkit.api import stats_profile_csv as _api_stats_profile_csv
from data_quality_toolkit.domain.statistics import assumptions as _assumptions
from data_quality_toolkit.domain.statistics import distributions as _distributions
from data_quality_toolkit.domain.statistics import inferential as _inferential
from data_quality_toolkit.domain.statistics.bootstrap import (
    DEFAULT_N_BOOTSTRAP as _DEFAULT_N_BOOTSTRAP,
)
from data_quality_toolkit.domain.statistics.bootstrap import bootstrap_ci as _bootstrap_ci
from data_quality_toolkit.domain.statistics.core import (
    UNAVAILABLE_REASON as _STATS_UNAVAILABLE_REASON,
)
from data_quality_toolkit.domain.statistics.core import clean_numeric as _clean_numeric
from data_quality_toolkit.domain.statistics.core import (
    confidence_level_to_t as _confidence_level_to_t,
)
from data_quality_toolkit.domain.statistics.core import (
    confidence_level_to_z as _confidence_level_to_z,
)
from data_quality_toolkit.domain.statistics.core import (
    has_enough_observations as _has_enough_observations,
)
from data_quality_toolkit.domain.statistics.core import import_scipy_stats as _import_scipy_stats
from data_quality_toolkit.domain.statistics.core import validate_alpha as _validate_alpha
from data_quality_toolkit.domain.statistics.core import validate_confidence as _validate_confidence
from data_quality_toolkit.domain.statistics.descriptive import numeric_summary as _numeric_summary
from data_quality_toolkit.domain.statistics.effect_size import (
    MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS as _MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS,
)
from data_quality_toolkit.domain.statistics.effect_size import (
    PAIRWISE_LIMIT_REASON as _PAIRWISE_LIMIT_REASON,
)
from data_quality_toolkit.domain.statistics.effect_size import (
    PAIRWISE_LIMIT_STATUS as _PAIRWISE_LIMIT_STATUS,
)
from data_quality_toolkit.domain.statistics.effect_size import cliffs_delta as _cliffs_delta
from data_quality_toolkit.domain.statistics.effect_size import (
    hodges_lehmann_ci as _hodges_lehmann_ci,
)
from data_quality_toolkit.domain.statistics.effect_size import (
    hodges_lehmann_estimate as _hodges_lehmann_estimate,
)
from data_quality_toolkit.domain.statistics.effect_size import (
    pairwise_comparison_count as _pairwise_comparison_count,
)
from data_quality_toolkit.domain.statistics.intervals import ci_mean as _ci_mean
from data_quality_toolkit.domain.statistics.multivariate import (
    categorical_associations as _categorical_associations,
)
from data_quality_toolkit.domain.statistics.multivariate import (
    covariance_matrix as _covariance_matrix,
)
from data_quality_toolkit.domain.statistics.multivariate import (
    grouped_numeric_by_category_summary as _grouped_numeric_by_category_summary,
)
from data_quality_toolkit.domain.statistics.multivariate import (
    top_correlations as _top_correlations,
)
from data_quality_toolkit.domain.statistics.multivariate import (
    variance_inflation_factors as _variance_inflation_factors,
)
from data_quality_toolkit.domain.statistics.power import power_mean as _power_mean
from data_quality_toolkit.domain.statistics.power import power_prop as _power_prop
from data_quality_toolkit.domain.statistics.power import required_n_cohend as _required_n_cohend
from data_quality_toolkit.domain.statistics.power import required_n_mean as _required_n_mean
from data_quality_toolkit.domain.statistics.power import required_n_prop as _required_n_prop
from data_quality_toolkit.domain.statistics.power import required_n_variance as _required_n_variance

# Bound the number of numeric columns summarized so wide frames stay responsive.
MAX_DESCRIBE_COLUMNS = 100

# Theoretical distributions surfaced by the Statistics Lab Distributions tab.
_DISTRIBUTION_CHOICES: tuple[str, ...] = (
    "Normal",
    "Student t",
    "Chi-square",
    "F",
    "Binomial",
    "Poisson",
)
_DISTRIBUTION_CALCULATIONS: dict[str, tuple[str, ...]] = {
    "Normal": ("PDF", "CDF", "Critical value (two-tail)"),
    "Student t": ("PDF", "CDF", "Critical value (two-tail)"),
    "Chi-square": ("PDF", "CDF"),
    "F": ("PDF", "CDF"),
    "Binomial": ("PMF", "CDF"),
    "Poisson": ("PMF", "CDF"),
}
_DistributionEval = tuple[float | None, dict[str, Any], str, str | None]
_DistributionEvaluator = Callable[[str, dict[str, Any]], _DistributionEval]


def distribution_choices() -> tuple[str, ...]:
    """Return the bounded theoretical distributions exposed in Statistics Lab."""
    return _DISTRIBUTION_CHOICES


def distribution_calculation_choices(distribution: str) -> tuple[str, ...]:
    """Return the bounded calculation choices for a supported distribution."""
    return _DISTRIBUTION_CALCULATIONS.get(str(distribution), ())


def _distribution_status(
    status: str,
    reason: str | None,
    *,
    distribution: str,
    calculation: str,
    parameters: dict[str, Any] | None = None,
    value: float | None = None,
    method: str = "ui_distribution_lookup",
    tail: str | None = None,
    explanation: str | None = None,
) -> dict[str, Any]:
    """Return a stable status dict for theoretical distribution lookups."""
    return {
        "status": status,
        "reason": reason,
        "distribution": distribution,
        "calculation": calculation,
        "parameters": parameters or {},
        "value": value,
        "method": method,
        "tail": tail,
        "explanation": explanation,
    }


def _float_param(params: dict[str, Any], name: str, default: float) -> float:
    value = params.get(name, default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _int_param(params: dict[str, Any], name: str, default: int) -> int:
    value = params.get(name, default)
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not numeric.is_integer():
        raise ValueError(f"{name} must be an integer")
    return int(numeric)


def _distribution_explanation(
    distribution: str,
    calculation: str,
    parameters: dict[str, Any],
    *,
    tail: str | None = None,
) -> str:
    if tail == "two-tail":
        alpha = float(parameters.get("alpha", 0.05))
        return (
            f"{distribution} two-tail critical value for alpha={alpha:.4g}; "
            "alpha is split equally across both tails."
        )
    if calculation == "CDF":
        point = parameters.get("x", parameters.get("k"))
        return f"{distribution} CDF evaluated at {point}."
    point = parameters.get("x", parameters.get("k"))
    return f"{distribution} {calculation} evaluated at {point}."


def _normal_distribution_value(calculation: str, params: dict[str, Any]) -> _DistributionEval:
    if calculation == "Critical value (two-tail)":
        alpha = _float_param(params, "alpha", 0.05)
        _validate_alpha(alpha)
        used = {"alpha": alpha, "confidence_level": 1.0 - alpha}
        return _confidence_level_to_z(1.0 - alpha), used, "confidence_level_to_z", "two-tail"
    x = _float_param(params, "x", 0.0)
    mu = _float_param(params, "mu", 0.0)
    sigma = _float_param(params, "sigma", 1.0)
    used = {"x": x, "mu": mu, "sigma": sigma}
    if calculation == "PDF":
        return _distributions.normal_pdf(x, mu=mu, sigma=sigma), used, "normal_pdf", None
    return _distributions.normal_cdf(x, mu=mu, sigma=sigma), used, "normal_cdf", None


def _student_t_distribution_value(calculation: str, params: dict[str, Any]) -> _DistributionEval:
    df = _float_param(params, "df", 10.0)
    if calculation == "Critical value (two-tail)":
        alpha = _float_param(params, "alpha", 0.05)
        _validate_alpha(alpha)
        used = {"df": df, "alpha": alpha, "confidence_level": 1.0 - alpha}
        return _confidence_level_to_t(1.0 - alpha, df=df), used, "confidence_level_to_t", "two-tail"
    x = _float_param(params, "x", 0.0)
    used = {"x": x, "df": df}
    if calculation == "PDF":
        return _distributions.t_pdf(x, df=df), used, "t_pdf", None
    return _distributions.t_cdf(x, df=df), used, "t_cdf", None


def _chi_square_distribution_value(calculation: str, params: dict[str, Any]) -> _DistributionEval:
    x = _float_param(params, "x", 1.0)
    df = _float_param(params, "df", 5.0)
    used = {"x": x, "df": df}
    if calculation == "PDF":
        return _distributions.chi2_pdf(x, df=df), used, "chi2_pdf", None
    return _distributions.chi2_cdf(x, df=df), used, "chi2_cdf", None


def _f_distribution_value(calculation: str, params: dict[str, Any]) -> _DistributionEval:
    x = _float_param(params, "x", 1.0)
    df1 = _float_param(params, "df1", 5.0)
    df2 = _float_param(params, "df2", 20.0)
    used = {"x": x, "df1": df1, "df2": df2}
    if calculation == "PDF":
        return _distributions.f_pdf(x, df1=df1, df2=df2), used, "f_pdf", None
    return _distributions.f_cdf(x, df1=df1, df2=df2), used, "f_cdf", None


def _binomial_distribution_value(calculation: str, params: dict[str, Any]) -> _DistributionEval:
    k = _int_param(params, "k", 3)
    n = _int_param(params, "n", 10)
    p = _float_param(params, "p", 0.5)
    if k < 0:
        raise ValueError(f"k must be >= 0, got {k}")
    used = {"k": k, "n": n, "p": p}
    if calculation == "PMF":
        return _distributions.binom_pmf(k, n=n, p=p), used, "binom_pmf", None
    return _distributions.binom_cdf(k, n=n, p=p), used, "binom_cdf", None


def _poisson_distribution_value(calculation: str, params: dict[str, Any]) -> _DistributionEval:
    k = _int_param(params, "k", 3)
    lam = _float_param(params, "lam", 3.0)
    if k < 0:
        raise ValueError(f"k must be >= 0, got {k}")
    used = {"k": k, "lam": lam}
    if calculation == "PMF":
        return _distributions.poisson_pmf(k, lam=lam), used, "poisson_pmf", None
    return _distributions.poisson_cdf(k, lam=lam), used, "poisson_cdf", None


_DISTRIBUTION_EVALUATORS: dict[str, _DistributionEvaluator] = {
    "Normal": _normal_distribution_value,
    "Student t": _student_t_distribution_value,
    "Chi-square": _chi_square_distribution_value,
    "F": _f_distribution_value,
    "Binomial": _binomial_distribution_value,
    "Poisson": _poisson_distribution_value,
}


def _complete_distribution_result(
    *,
    distribution: str,
    calculation: str,
    value: float | None,
    used: dict[str, Any],
    method: str,
    tail: str | None,
) -> dict[str, Any]:
    if value is None:
        return _distribution_status(
            "unavailable",
            _STATS_UNAVAILABLE_REASON,
            distribution=distribution,
            calculation=calculation,
            parameters=used,
            method=method,
            tail=tail,
        )

    return _distribution_status(
        "ok",
        None,
        distribution=distribution,
        calculation=calculation,
        parameters=used,
        value=round(float(value), 10),
        method=method,
        tail=tail,
        explanation=_distribution_explanation(distribution, calculation, used, tail=tail),
    )


def theoretical_distribution_result(
    distribution: str,
    calculation: str,
    **params: Any,
) -> dict[str, Any]:
    """Evaluate a bounded theoretical distribution lookup.

    Delegates to the existing scipy-guarded distribution wrappers and the
    existing two-sided z/t critical-value helpers. The wrapper never raises for
    invalid operator input; it returns a status dict suitable for UI display.
    """
    distribution = str(distribution)
    calculation = str(calculation)
    if distribution not in _DISTRIBUTION_CALCULATIONS:
        return _distribution_status(
            "invalid_input",
            f"unsupported distribution: {distribution}",
            distribution=distribution,
            calculation=calculation,
        )
    if calculation not in _DISTRIBUTION_CALCULATIONS[distribution]:
        return _distribution_status(
            "invalid_input",
            f"unsupported calculation for {distribution}: {calculation}",
            distribution=distribution,
            calculation=calculation,
        )

    try:
        evaluator = _DISTRIBUTION_EVALUATORS[distribution]
        value, used, method, tail = evaluator(calculation, params)
    except ValueError as exc:
        return _distribution_status(
            "invalid_input",
            str(exc),
            distribution=distribution,
            calculation=calculation,
        )
    return _complete_distribution_result(
        distribution=distribution,
        calculation=calculation,
        value=value,
        used=used,
        method=method,
        tail=tail,
    )


def numeric_descriptive_stats(
    df: pd.DataFrame, max_columns: int = MAX_DESCRIBE_COLUMNS
) -> pd.DataFrame | None:
    """Return per-column descriptive statistics for numeric columns.

    Columns: count, mean, median, std, min, max, skew, kurtosis. Returns None
    when the frame has no numeric columns. Skew/kurtosis are NaN when pandas
    cannot compute them (too few values); this is surfaced, not hidden.
    """
    numeric = df.select_dtypes(include="number").iloc[:, : max(0, max_columns)]
    summary = _numeric_summary(numeric)
    if summary.empty:
        return None
    columns = ["count", "mean", "median", "std", "min", "max", "skew", "kurtosis"]
    return summary.loc[:, columns].round(4)


def column_type_overview(df: pd.DataFrame) -> dict[str, int]:
    """Return a compact count of numeric vs categorical/other columns."""
    numeric = df.select_dtypes(include="number").shape[1]
    total = df.shape[1]
    return {
        "total_columns": int(total),
        "numeric_columns": int(numeric),
        "categorical_or_other_columns": int(total - numeric),
    }


def multivariate_covariance_matrix(df: pd.DataFrame) -> pd.DataFrame | None:
    """Covariance matrix across numeric columns; None when fewer than two exist."""
    result = _covariance_matrix(df)
    return None if result.empty else result


def multivariate_vif_table(df: pd.DataFrame) -> pd.DataFrame | None:
    """VIF/multicollinearity table; None when fewer than two usable numeric columns."""
    result = _variance_inflation_factors(df)
    return None if result.empty else result


def multivariate_top_correlations(
    df: pd.DataFrame, *, method: str = "pearson", top_k: int | None = None
) -> pd.DataFrame | None:
    """Ranked strongest pairwise correlations; None when fewer than two numeric columns."""
    result = _top_correlations(df, method=method, top_k=top_k)
    return None if result.empty else result


def multivariate_categorical_associations(df: pd.DataFrame) -> pd.DataFrame | None:
    """Cramér's V categorical association table; None when fewer than two categoricals."""
    result = _categorical_associations(df)
    return None if result.empty else result


def multivariate_grouped_summary(
    df: pd.DataFrame, *, category: str | None = None
) -> pd.DataFrame | None:
    """Grouped numeric-by-categorical summary; None when no usable columns exist."""
    result = _grouped_numeric_by_category_summary(df, category=category)
    return None if result.empty else result


def statistics_profile(
    csv_path: str | Path,
    *,
    columns: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return a DQT public-API statistics profile for a local CSV path."""
    return dict(_api_stats_profile_csv(csv_path, columns=columns))


def profile_numeric_summary_dataframe(result: dict[str, Any]) -> pd.DataFrame | None:
    """Build a display table from ``stats_profile_csv`` numeric summary rows."""
    if result.get("status") != "ok":
        return None
    rows = result.get("numeric_summary") or []
    if not rows:
        return None
    return pd.DataFrame(rows)


def select_hypothesis_test(
    variable_type: str,
    group_structure: str,
    *,
    sigma_known: bool | None = None,
    equal_variance_assumed: bool | None = None,
    paired: bool | None = None,
    alternative: str = "two-sided",
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Select a representative statistical test through the public API."""
    return dict(
        _api_select_statistical_test(
            variable_type,
            group_structure,
            sigma_known=sigma_known,
            equal_variance_assumed=equal_variance_assumed,
            paired=paired,
            alternative=alternative,
            alpha=alpha,
        )
    )


def _public_test_status(
    *,
    status: str,
    reason: str,
    test_key: str = "UNKNOWN",
    alpha: float = 0.05,
    alternative: str = "two-sided",
    method: str = "ui_statistics_service",
) -> dict[str, Any]:
    """Return the same status-dict vocabulary as the public test API."""
    return {
        "status": status,
        "test_key": test_key,
        "statistic": None,
        "p_value": None,
        "alpha": alpha,
        "reject_null": None,
        "method": method,
        "reason": reason,
        "alternative": alternative,
        "warnings": [],
        "messages": [],
        "assumptions": {},
        "scipy_available": inferential_available(),
    }


def _is_numeric_metric(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)


def _numeric_sample_from_column(df: pd.DataFrame, metric: str) -> list[float] | dict[str, Any]:
    if metric not in df.columns:
        return _public_test_status(
            status="invalid_input",
            reason=f"metric column not found: {metric!r}",
        )
    if not _is_numeric_metric(df[metric]):
        return _public_test_status(
            status="invalid_input",
            reason=f"metric column {metric!r} is not numeric",
        )
    return [float(value) for value in df[metric].dropna().astype(float).tolist()]


def _numeric_samples_by_group(
    df: pd.DataFrame,
    metric: str,
    group_col: str,
    a_value: Any,
    b_value: Any,
) -> tuple[list[float], list[float]] | dict[str, Any]:
    sample = _numeric_sample_from_column(df, metric)
    if isinstance(sample, dict):
        return sample
    if group_col not in df.columns:
        return _public_test_status(
            status="invalid_input",
            reason=f"group column not found: {group_col!r}",
        )
    if metric == group_col:
        return _public_test_status(
            status="invalid_input",
            reason="metric and group column must be different",
        )
    if str(a_value) == str(b_value):
        return _public_test_status(
            status="invalid_input",
            reason="A and B values must be different",
        )

    clean = df[[metric, group_col]].dropna()
    group_values = clean[group_col].astype(str)
    sample_a = [
        float(value) for value in clean.loc[group_values == str(a_value), metric].astype(float)
    ]
    sample_b = [
        float(value) for value in clean.loc[group_values == str(b_value), metric].astype(float)
    ]
    return sample_a, sample_b


def run_one_sample_numeric_test(
    df: pd.DataFrame,
    metric: str,
    *,
    null_mean: float = 0.0,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> dict[str, Any]:
    """Run a one-sample numeric t-test through the public API."""
    sample = _numeric_sample_from_column(df, metric)
    if isinstance(sample, dict):
        sample["test_key"] = "ONE_T"
        sample["alpha"] = alpha
        sample["alternative"] = alternative
        return sample
    return dict(
        _api_run_statistical_test(
            "ONE_T",
            sample=sample,
            null_mean=null_mean,
            alpha=alpha,
            alternative=alternative,
        )
    )


def run_two_sample_numeric_test(
    df: pd.DataFrame,
    metric: str,
    group_col: str,
    a_value: Any,
    b_value: Any,
    *,
    equal_variance_assumed: bool = False,
    null_difference: float = 0.0,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> dict[str, Any]:
    """Run a two-sample numeric t-test through the public API."""
    samples = _numeric_samples_by_group(df, metric, group_col, a_value, b_value)
    test_key = "TWO_T_EQ" if equal_variance_assumed else "TWO_T_WELCH"
    if isinstance(samples, dict):
        samples["test_key"] = test_key
        samples["alpha"] = alpha
        samples["alternative"] = alternative
        return samples
    sample_a, sample_b = samples
    result = dict(
        _api_run_statistical_test(
            test_key,
            sample_a=sample_a,
            sample_b=sample_b,
            null_difference=null_difference,
            alpha=alpha,
            alternative=alternative,
        )
    )
    result.update(
        {
            "group_a": str(a_value),
            "group_b": str(b_value),
            "metric": metric,
            "group_col": group_col,
        }
    )
    return result


def compare_numeric_ab(
    df: pd.DataFrame,
    group_col: str,
    a_value: Any,
    b_value: Any,
    metric: str,
    *,
    equal_variance_assumed: bool = False,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> dict[str, Any]:
    """Run a numeric A/B comparison through the public API."""
    samples = _numeric_samples_by_group(df, metric, group_col, a_value, b_value)
    if isinstance(samples, dict):
        samples["test_key"] = "TWO_T_EQ" if equal_variance_assumed else "TWO_T_WELCH"
        samples["alpha"] = alpha
        samples["alternative"] = alternative
        return samples
    sample_a, sample_b = samples
    result = dict(
        _api_compare_ab(
            sample_a,
            sample_b,
            variable_type="numeric",
            group_structure="two_independent",
            alpha=alpha,
            alternative=alternative,
            equal_variance_assumed=equal_variance_assumed,
        )
    )
    result.update(
        {
            "group_a": str(a_value),
            "group_b": str(b_value),
            "metric": metric,
            "group_col": group_col,
            "n_a": len(sample_a),
            "n_b": len(sample_b),
        }
    )
    return result


# ── inferential tier (scipy-guarded; optional [stats] extra) ──────────────────


def inferential_available() -> bool:
    """Return True when scipy is importable, without importing it."""
    try:
        return importlib.util.find_spec("scipy") is not None
    except (ImportError, ValueError):
        return False


def normality_check(series: pd.Series, *, alpha: float = 0.05) -> dict[str, Any]:
    """Shapiro-Wilk normality status dict (see domain.statistics.inferential)."""
    return _inferential.check_normality(series, alpha=alpha)


def two_group_comparison(
    df: pd.DataFrame, metric: str, group_col: str, *, alpha: float = 0.05
) -> dict[str, Any]:
    """Welch t-test + Mann-Whitney U for a 2-level group (status dict)."""
    return _inferential.compare_two_groups(df, metric, group_col, alpha=alpha)


def multi_group_comparison(
    df: pd.DataFrame, metric: str, group_col: str, *, alpha: float = 0.05
) -> dict[str, Any]:
    """ANOVA + Kruskal-Wallis across bounded groups (status dict)."""
    return _inferential.compare_multi_group(df, metric, group_col, alpha=alpha)


def ab_comparison(
    df: pd.DataFrame,
    group_col: str,
    a_value: Any,
    b_value: Any,
    metric: str,
    *,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """A vs B comparison on a numeric metric (status dict)."""
    return _inferential.ab_compare(df, group_col, a_value, b_value, metric, alpha=alpha)


def group_summary_dataframe(result: dict[str, Any]) -> pd.DataFrame | None:
    """Build a display/CSV table from a multi-group result's ``groups`` list.

    Returns None when the result carries no per-group summary.
    """
    groups = result.get("groups")
    if not groups:
        return None
    return pd.DataFrame(groups, columns=["group", "n", "mean", "median", "std"])


# Bounded alternatives accepted by the paired Wilcoxon service wrapper.
WILCOXON_ALTERNATIVES: tuple[str, ...] = ("two-sided", "greater", "less")


def _wilcoxon_status(status: str, reason: str, *, alpha: float, alternative: str) -> dict[str, Any]:
    """Return a Wilcoxon-shaped status dict for service-level validation failures."""
    return {
        "status": status,
        "reason": reason,
        "alpha": alpha,
        "scipy_available": inferential_available(),
        "test_name": "Wilcoxon signed-rank",
        "method": "wilcoxon_signed_rank",
        "alternative": alternative,
        "statistic": None,
        "p_value": None,
        "n_pairs": 0,
        "n_nonzero_differences": 0,
        "significant": None,
        "interpretation": reason,
        "caveat": None,
    }


def paired_wilcoxon_test(
    df: pd.DataFrame,
    column_a: str,
    column_b: str,
    *,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> dict[str, Any]:
    """Wilcoxon signed-rank test for two paired numeric columns (status dict).

    Validates that both columns exist, are numeric, and are distinct, then delegates
    to ``domain.statistics.inferential.wilcoxon_signed_rank`` which drops incomplete
    pairs and guards scipy. Never raises except on invalid ``alpha``.
    """
    _validate_alpha(alpha)
    if alternative not in WILCOXON_ALTERNATIVES:
        return _wilcoxon_status(
            "invalid_input",
            f"alternative must be one of {WILCOXON_ALTERNATIVES}",
            alpha=alpha,
            alternative=alternative,
        )
    for column in (column_a, column_b):
        if column not in df.columns:
            return _wilcoxon_status(
                "invalid_input",
                f"column not found: {column!r}",
                alpha=alpha,
                alternative=alternative,
            )
    if column_a == column_b:
        return _wilcoxon_status(
            "invalid_input",
            "select two different numeric columns for a paired test",
            alpha=alpha,
            alternative=alternative,
        )
    if not _is_numeric_metric(df[column_a]) or not _is_numeric_metric(df[column_b]):
        return _wilcoxon_status(
            "invalid_input",
            "both columns must be numeric for a paired test",
            alpha=alpha,
            alternative=alternative,
        )
    result = dict(
        _inferential.wilcoxon_signed_rank(
            df[column_a], df[column_b], alpha=alpha, alternative=alternative
        )
    )
    result.update({"column_a": str(column_a), "column_b": str(column_b)})
    return result


def run_paired_t_test(
    df: pd.DataFrame,
    column_a: str,
    column_b: str,
    *,
    null_difference: float = 0.0,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> dict[str, Any]:
    """Parametric paired t-test for two paired numeric columns (status dict).

    Validates that both columns exist, are numeric, and are distinct, applies
    pairwise exclusion (a row is dropped only when either member of the pair is
    missing or non-finite, matching the kernel's paired cleaning so reported
    counts agree with the computation), and delegates to the public
    ``run_statistical_test`` seam with ``PAIRED_T``. Never raises for invalid
    operator input; returns a status dict suitable for UI display.
    """

    def _status(status: str, reason: str) -> dict[str, Any]:
        shaped = _public_test_status(
            status=status,
            reason=reason,
            test_key="PAIRED_T",
            alpha=alpha,
            alternative=alternative,
        )
        shaped.update({"column_a": str(column_a), "column_b": str(column_b)})
        return shaped

    for column in (column_a, column_b):
        if column not in df.columns:
            return _status("invalid_input", f"column not found: {column!r}")
    if column_a == column_b:
        return _status("invalid_input", "select two different numeric columns for a paired t-test")
    if not _is_numeric_metric(df[column_a]) or not _is_numeric_metric(df[column_b]):
        return _status("invalid_input", "both columns must be numeric for a paired t-test")

    values_a = df[column_a].astype(float).to_numpy()
    values_b = df[column_b].astype(float).to_numpy()
    keep = np.isfinite(values_a) & np.isfinite(values_b)
    n_pairs = int(keep.sum())
    n_excluded_rows = int(len(df) - n_pairs)
    if n_pairs < 2:
        insufficient = _status(
            "insufficient_data",
            "need at least 2 complete pairs (rows where both selected columns are "
            f"present and finite); found {n_pairs}",
        )
        insufficient.update({"n_pairs": n_pairs, "n_excluded_rows": n_excluded_rows})
        return insufficient

    result = dict(
        _api_run_statistical_test(
            "PAIRED_T",
            sample_a=values_a[keep].tolist(),
            sample_b=values_b[keep].tolist(),
            null_difference=null_difference,
            alpha=alpha,
            alternative=alternative,
        )
    )
    result.update(
        {
            "column_a": str(column_a),
            "column_b": str(column_b),
            "n_pairs": n_pairs,
            "n_excluded_rows": n_excluded_rows,
        }
    )
    return result


# ── proportion z-tests (loaded-dataset binary outcomes; via the public seam) ──
#
# Both runners route through the existing run_statistical_test public seam
# (ONE_PROP_Z / TWO_PROP_Z) with no signature or formula change. Binary-outcome and
# group preparation compares values by type-aware identity (runtime type plus native
# value), never by text: int 1 and str "1", bool True and str "True", bool True and
# int 1, and float 1.0 and int 1 stay distinct categories. Display labels carry a
# type suffix for the operator but never drive computation. A column with anything
# other than exactly two distinct typed categories is rejected, never silently
# collapsed. Missing and non-finite (±inf) values are excluded before category
# determination. Reported counts match the successes/n handed to the kernel.

_PROPORTION_ALTERNATIVES: tuple[str, ...] = ("two-sided", "greater", "less")

# A type-aware category identity: (type module, type qualname, native value). Using
# the runtime type keeps distinct native values apart even when text conversion or
# Python ``==`` would merge them (``1``/``"1"``, ``True``/``"True"``, ``True``/``1``,
# ``1.0``/``1``). Identity, never the display label, drives all computation.
_CategoryIdentity = tuple[str, str, Any]


@dataclass(frozen=True)
class CategoryOption:
    """A type-safe category selection token for the proportion runners.

    ``identity`` is a stable, type-aware key that distinguishes native scalars which
    render with the same text. ``value`` is the original native scalar used for all
    computation. ``label`` is operator-facing display text only and never controls
    computation.
    """

    identity: _CategoryIdentity
    value: Any
    label: str


def _category_identity(value: Any) -> _CategoryIdentity:
    """Type-aware identity distinguishing values that share text or compare equal."""
    value_type = type(value)
    return (value_type.__module__, value_type.__qualname__, value)


# Bounded safe display for category values: reject opaque object representations
# (memory addresses), control characters, and excessively long text so nothing
# unsafe reaches selectbox labels, error messages, or result tables.
_MAX_CATEGORY_TEXT = 100
_OBJECT_ADDRESS_RE = re.compile(r"object at 0x[0-9a-f]+", re.IGNORECASE)


def _safe_scalar_text(value: Any) -> tuple[str | None, str | None]:
    """Return (safe display text, None) or (None, reason) for a scalar category value.

    Produces bounded, deterministic operator-facing text. Rejects — never leaks —
    opaque default object representations (memory addresses), control characters, and
    excessively long text; never uses an unrestricted repr fallback.
    """
    try:
        text = value if isinstance(value, str) else str(value)
    except Exception:  # noqa: BLE001 - a hostile __str__ must not crash selection
        return None, "value could not be converted to display text"
    if _OBJECT_ADDRESS_RE.search(text):
        return None, "value has an opaque default representation (memory address)"
    if any(ord(character) < 32 for character in text):
        return None, "value contains control characters"
    if len(text) > _MAX_CATEGORY_TEXT:
        return None, f"value text exceeds {_MAX_CATEGORY_TEXT} characters"
    return text, None


def _safe_display_label(value: Any) -> str:
    """Best-effort concise, safe label for a single value (type-suffixed form).

    Used for status/provenance fields on error paths where the complete option set is
    unavailable. Never leaks unsafe text: an unsafe value yields a bounded placeholder
    rather than an opaque representation.
    """
    text, error = _safe_scalar_text(value)
    if error is not None:
        return f"<unsafe {type(value).__name__} value>"
    return f"{text} [{type(value).__name__}]"


def _is_invalid_category(value: Any) -> bool:
    """True when a scalar is missing (None/NaN/pd.NA) or a non-finite float (±inf)."""
    if value is None:
        return True
    if isinstance(value, float) and not math.isfinite(value):
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _valid_category_scalars(series: pd.Series) -> list[Any]:
    """Native scalars with missing and non-finite values removed (order preserved)."""
    return [value for value in series.tolist() if not _is_invalid_category(value)]


def _typed_categories(values: list[Any], column: str) -> tuple[list[CategoryOption], str | None]:
    """Distinct, collision-safe categories from valid scalars.

    Groups by type-aware identity so distinct native types are never merged. Labels are
    generated across the whole option set in two stages: a concise ``<text> [<type
    name>]`` form, upgraded to the full ``<text> [<module>.<qualname>]`` form for any
    identities whose concise label would collide. Returns a structured error (never a
    repr/address/hash/ordinal fallback, never a crash) when a value cannot be displayed
    safely or when distinct identities cannot be labelled unambiguously. Ordering is by
    the final label (a string), never by comparing mixed native types.
    """
    entries: dict[_CategoryIdentity, tuple[Any, str]] = {}
    for value in values:
        identity = _category_identity(value)
        try:
            hash(identity)
        except TypeError:
            return [], (
                f"column {column!r} contains a value that cannot be used as a category "
                f"(unhashable {type(value).__name__}); select a scalar column"
            )
        if identity in entries:
            continue
        text, text_error = _safe_scalar_text(value)
        if text_error is not None or text is None:
            return [], (
                f"column {column!r} contains a value that cannot be displayed safely: "
                f"{text_error}"
            )
        entries[identity] = (value, text)

    concise = {
        identity: f"{text} [{type(value).__name__}]" for identity, (value, text) in entries.items()
    }
    concise_counts: dict[str, int] = {}
    for label in concise.values():
        concise_counts[label] = concise_counts.get(label, 0) + 1

    final: dict[_CategoryIdentity, str] = {}
    for identity, (_value, text) in entries.items():
        if concise_counts[concise[identity]] == 1:
            final[identity] = concise[identity]
        else:
            final[identity] = f"{text} [{identity[0]}.{identity[1]}]"

    final_counts: dict[str, int] = {}
    for label in final.values():
        final_counts[label] = final_counts.get(label, 0) + 1
    if any(count > 1 for count in final_counts.values()):
        return [], (
            f"column {column!r} has distinct values that cannot be displayed unambiguously; "
            "convert or rename the column so each category has a distinct label"
        )

    options = [
        CategoryOption(identity, entries[identity][0], final[identity]) for identity in entries
    ]
    options.sort(key=lambda option: option.label)
    return options, None


def outcome_category_options(
    df: pd.DataFrame, column: str
) -> tuple[list[CategoryOption], str | None]:
    """Collision-safe distinct outcome categories (missing and non-finite excluded).

    Returns (options, None) on success or ([], reason) when the category set cannot be
    displayed safely/unambiguously; ([], None) when the column is absent. Reused by the
    proportion service functions so label generation is defined once.
    """
    if column not in df.columns:
        return [], None
    return _typed_categories(_valid_category_scalars(df[column]), column)


def group_category_options(
    df: pd.DataFrame, column: str
) -> tuple[list[CategoryOption], str | None]:
    """Collision-safe distinct group categories (missing and non-finite excluded).

    Non-finite numeric group values (±inf) are excluded here and classified as invalid
    rows during counting; they never appear as selectable groups.

    A grouping column above the accepted level ceiling, or one whose values are
    effectively identifier-like, is refused from its level count alone before any
    category is materialized: a stale or session-injected pathological selection
    therefore builds no typed category, no option object, and no label, and its reason
    stays a bounded count. The verdict comes from the shared eligibility classifier, so
    the 2..STATS_CATEGORICAL_MAX_LEVELS grouping policy is defined in exactly one place.
    Empty, constant, and undisplayable columns are not this guard's business and keep
    their existing handling.
    """
    if column not in df.columns:
        return [], None
    eligibility = classify_categorical_column(df, column)
    if eligibility.status == IDENTIFIER_LIKE:
        return [], _identifier_like_reason(f"grouping column {column!r}", eligibility.level_count)
    if eligibility.status == TOO_MANY_LEVELS:
        return [], _too_many_levels_reason(f"grouping column {column!r}", eligibility.level_count)
    return _typed_categories(_valid_category_scalars(df[column]), column)


def _too_many_levels_reason(noun: str, levels: int) -> str:
    """Bounded count-only rejection for a column above the categorical ceiling.

    Never enumerates category labels: at this cardinality the label set is exactly
    the payload the ceiling exists to prevent from being built at all.
    """
    return (
        f"{noun} contains {levels:,} distinct non-missing values; this categorical "
        f"analysis is limited to {STATS_CATEGORICAL_MAX_LEVELS} distinct categories"
    )


def _identifier_like_reason(noun: str, levels: int) -> str:
    """Bounded count-only rejection for a near-unique, identifier-like column.

    Like the ceiling reason it never enumerates category labels: an identifier-like
    column's label set is exactly the payload this refusal exists to avoid building.
    """
    return (
        f"{noun} contains {levels:,} distinct non-missing values and is effectively "
        "identifier-like; select a column with repeated levels"
    )


def _binary_outcome_error(
    categories: list[CategoryOption], success_identity: _CategoryIdentity
) -> str | None:
    """Return an actionable reason when the outcome is not a valid binary column.

    The exact binary rule (exactly two distinct typed categories, with an explicitly
    selected success category) is defined once; a multi-category column is never
    silently collapsed. Membership is by type-aware identity, not display text. The
    observed-value text is bounded by the shared label-summary policy so a wide
    column cannot produce an oversized reason string.
    """
    if len(categories) != 2:
        labels = [option.label for option in categories]
        return (
            "outcome column must have exactly two distinct non-missing values; found "
            f"{len(categories)}: {summarize_labels(labels)}"
        )
    if success_identity not in {option.identity for option in categories}:
        labels = [option.label for option in categories]
        return f"success value must be one of the observed values {summarize_labels(labels)}"
    return None


def _validate_binary_outcome(
    df: pd.DataFrame, outcome_column: str, success_identity: _CategoryIdentity
) -> tuple[list[CategoryOption], str | None]:
    """Return (collision-safe typed categories, error) for a binary outcome column."""
    excessive = exceeds_level_ceiling(df[outcome_column])
    if excessive is not None:
        return [], _too_many_levels_reason(f"outcome column {outcome_column!r}", excessive)
    categories, error = _typed_categories(
        _valid_category_scalars(df[outcome_column]), outcome_column
    )
    if error is not None:
        return [], error
    return categories, _binary_outcome_error(categories, success_identity)


def _validate_group_selection(
    df: pd.DataFrame,
    group_column: str,
    selections: list[tuple[str, _CategoryIdentity]],
) -> tuple[str | None, dict[_CategoryIdentity, str]]:
    """Return (error, final label by identity) for the grouping column and selections.

    Groups are identified by type-aware identity (never by text), non-finite numeric
    group values are excluded as invalid, and labels are collision-safe. Error is None
    with a populated label map when the column has at least two distinct typed groups
    and every selected group is present.
    """
    excessive = exceeds_level_ceiling(df[group_column])
    if excessive is not None:
        return _too_many_levels_reason(f"grouping column {group_column!r}", excessive), {}
    group_categories, error = _typed_categories(
        _valid_category_scalars(df[group_column]), group_column
    )
    if error is not None:
        return error, {}
    if len(group_categories) < 2:
        return "grouping column must have at least two distinct non-missing values", {}
    group_identities = {option.identity for option in group_categories}
    unknown = [label for label, identity in selections if identity not in group_identities]
    if unknown:
        return f"unknown selected group: {unknown[0]}", {}
    return None, {option.identity: option.label for option in group_categories}


def _two_proportion_group_counts(
    df: pd.DataFrame,
    outcome_column: str,
    group_column: str,
    success_identity: _CategoryIdentity,
    group_a_identity: _CategoryIdentity,
    group_b_identity: _CategoryIdentity,
) -> dict[str, int]:
    """Partition rows into the two selected groups and count eligible successes.

    Single pass over native scalars using type-aware identity. A row is eligible only
    when its outcome is valid (non-missing/finite) and its group is valid and matches
    one of the two selected typed groups. Rows with an invalid outcome or an invalid
    group (including ±inf group values) count only in ``invalid_or_missing_rows``;
    valid rows whose group is neither selected group count only in
    ``rows_outside_groups``. The four buckets partition ``total_rows`` exactly.
    """
    total_rows = int(len(df))
    invalid_or_missing_rows = 0
    rows_outside_groups = 0
    n_a = n_b = successes_a = successes_b = 0
    for outcome_value, group_value in zip(df[outcome_column].tolist(), df[group_column].tolist()):
        if _is_invalid_category(outcome_value) or _is_invalid_category(group_value):
            invalid_or_missing_rows += 1
            continue
        group_identity = _category_identity(group_value)
        is_success = _category_identity(outcome_value) == success_identity
        if group_identity == group_a_identity:
            n_a += 1
            successes_a += int(is_success)
        elif group_identity == group_b_identity:
            n_b += 1
            successes_b += int(is_success)
        else:
            rows_outside_groups += 1
    return {
        "total_rows": total_rows,
        "invalid_or_missing_rows": invalid_or_missing_rows,
        "rows_outside_groups": rows_outside_groups,
        "n_a": n_a,
        "n_b": n_b,
        "successes_a": successes_a,
        "successes_b": successes_b,
    }


def run_one_proportion_z_test(
    df: pd.DataFrame,
    outcome_column: str,
    success_value: Any,
    *,
    null_proportion: float,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> dict[str, Any]:
    """One-proportion z-test on a binary outcome column (status dict).

    Streamlit-free. Uses type-aware category identity so distinct native values that
    share a text form (int ``1`` vs str ``"1"``, bool ``True`` vs str ``"True"``) are
    never merged. Keeps only non-missing/finite values, requires exactly two distinct
    typed categories, counts successes for the explicitly selected typed category, and
    routes through the public ``run_statistical_test`` seam with ``ONE_PROP_Z``. Never
    raises for invalid operator input; returns a status dict suitable for UI display.
    """
    success_identity = _category_identity(success_value)
    success_label = _safe_display_label(success_value)

    def _status(status: str, reason: str, **extra: Any) -> dict[str, Any]:
        shaped = _public_test_status(
            status=status,
            reason=reason,
            test_key="ONE_PROP_Z",
            alpha=alpha,
            alternative=alternative,
        )
        shaped.update(
            {
                "outcome_column": str(outcome_column),
                "success_value": success_value,
                "success_label": success_label,
                "null_proportion": null_proportion,
            }
        )
        shaped.update(extra)
        return shaped

    if outcome_column not in df.columns:
        return _status("invalid_input", f"outcome column not found: {outcome_column!r}")
    if not isinstance(null_proportion, int | float) or not math.isfinite(float(null_proportion)):
        return _status("invalid_input", "null proportion must be a finite number in (0, 1)")
    if not 0.0 < float(null_proportion) < 1.0:
        return _status("invalid_input", "null proportion must be strictly between 0 and 1")

    valid_values = _valid_category_scalars(df[outcome_column])
    total_rows = int(len(df))
    valid_rows = len(valid_values)
    excluded_rows = total_rows - valid_rows
    counts = {
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "excluded_rows": excluded_rows,
    }
    if valid_rows < 1:
        return _status("insufficient_data", "need at least one non-missing outcome value", **counts)
    excessive = exceeds_level_ceiling(valid_values)
    if excessive is not None:
        return _status(
            "invalid_input",
            _too_many_levels_reason(f"outcome column {outcome_column!r}", excessive),
            category_count=excessive,
            **counts,
        )
    categories, category_error = _typed_categories(valid_values, str(outcome_column))
    if category_error is not None:
        return _status("invalid_input", category_error, **counts)
    binary_error = _binary_outcome_error(categories, success_identity)
    observed_labels = [option.label for option in categories]
    if binary_error is not None:
        return _status("invalid_input", binary_error, observed_values=observed_labels, **counts)

    # Use the collision-safe label from the full option set for provenance.
    success_label = {option.identity: option.label for option in categories}.get(
        success_identity, success_label
    )
    success_count = sum(
        1 for value in valid_values if _category_identity(value) == success_identity
    )
    failure_count = valid_rows - success_count
    result = dict(
        _api_run_statistical_test(
            "ONE_PROP_Z",
            successes=success_count,
            n=valid_rows,
            null_proportion=float(null_proportion),
            alpha=alpha,
            alternative=alternative,
        )
    )
    result.update(
        {
            "outcome_column": str(outcome_column),
            "success_value": success_value,
            "success_label": success_label,
            "observed_values": observed_labels,
            "null_proportion": float(null_proportion),
            "success_count": success_count,
            "failure_count": failure_count,
            "observed_proportion": success_count / valid_rows,
            **counts,
        }
    )
    return result


def run_two_proportion_z_test(
    df: pd.DataFrame,
    outcome_column: str,
    success_value: Any,
    group_column: str,
    group_a: Any,
    group_b: Any,
    *,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> dict[str, Any]:
    """Two-proportion z-test comparing a binary success proportion between two groups.

    Streamlit-free. Applies the same type-aware binary rule to the outcome column,
    identifies groups by type-aware identity (so int ``1`` and str ``"1"`` are
    distinct groups), classifies missing and non-finite (±inf) group rows as invalid,
    filters to the two explicitly selected typed groups, and routes through the public
    ``run_statistical_test`` seam with ``TWO_PROP_Z``. The comparison direction is the
    first selected group minus the second. Never raises for invalid operator input.
    """
    success_identity = _category_identity(success_value)
    success_label = _safe_display_label(success_value)
    group_a_identity = _category_identity(group_a)
    group_b_identity = _category_identity(group_b)
    group_a_label = _safe_display_label(group_a)
    group_b_label = _safe_display_label(group_b)

    def _status(status: str, reason: str, **extra: Any) -> dict[str, Any]:
        shaped = _public_test_status(
            status=status,
            reason=reason,
            test_key="TWO_PROP_Z",
            alpha=alpha,
            alternative=alternative,
        )
        shaped.update(
            {
                "outcome_column": str(outcome_column),
                "success_value": success_value,
                "success_label": success_label,
                "group_column": str(group_column),
                "group_a": group_a,
                "group_b": group_b,
                "group_a_label": group_a_label,
                "group_b_label": group_b_label,
            }
        )
        shaped.update(extra)
        return shaped

    for column in (outcome_column, group_column):
        if column not in df.columns:
            return _status("invalid_input", f"column not found: {column!r}")
    if outcome_column == group_column:
        return _status("invalid_input", "outcome and grouping columns must be different")
    if group_a_identity == group_b_identity:
        return _status("invalid_input", "the two comparison groups must be different")

    outcome_categories, binary_error = _validate_binary_outcome(
        df, str(outcome_column), success_identity
    )
    observed_labels = [option.label for option in outcome_categories]
    if binary_error is not None:
        return _status("invalid_input", binary_error, observed_values=observed_labels)
    success_label = {option.identity: option.label for option in outcome_categories}.get(
        success_identity, success_label
    )

    group_error, group_labels = _validate_group_selection(
        df,
        str(group_column),
        [(group_a_label, group_a_identity), (group_b_label, group_b_identity)],
    )
    if group_error is not None:
        return _status("invalid_input", group_error)
    group_a_label = group_labels[group_a_identity]
    group_b_label = group_labels[group_b_identity]

    counts: dict[str, Any] = {
        **_two_proportion_group_counts(
            df,
            str(outcome_column),
            str(group_column),
            success_identity,
            group_a_identity,
            group_b_identity,
        ),
        "observed_values": observed_labels,
    }
    n_a = int(counts["n_a"])
    n_b = int(counts["n_b"])
    successes_a = int(counts["successes_a"])
    successes_b = int(counts["successes_b"])
    if n_a < 1 or n_b < 1:
        empty = group_a_label if n_a < 1 else group_b_label
        return _status(
            "insufficient_data",
            f"selected group {empty} has no valid observations",
            **counts,
        )

    result = dict(
        _api_run_statistical_test(
            "TWO_PROP_Z",
            successes_a=successes_a,
            n_a=n_a,
            successes_b=successes_b,
            n_b=n_b,
            alpha=alpha,
            alternative=alternative,
        )
    )
    proportion_a = successes_a / n_a
    proportion_b = successes_b / n_b
    result.update(
        {
            "outcome_column": str(outcome_column),
            "success_value": success_value,
            "success_label": success_label,
            "group_column": str(group_column),
            "group_a": group_a,
            "group_b": group_b,
            "group_a_label": group_a_label,
            "group_b_label": group_b_label,
            "proportion_a": proportion_a,
            "proportion_b": proportion_b,
            "proportion_difference": proportion_a - proportion_b,
            **counts,
        }
    )
    return result


# ── chi-square tests (loaded-dataset categorical tests; via the public seam) ──
#
# All three chi-square runners reuse the accepted type-aware, collision-safe
# category identity system (``_typed_categories`` / ``_category_identity`` /
# ``_valid_category_scalars`` / ``_is_invalid_category``): native typed values remain
# authoritative for grouping, counting, and table placement while collision-safe
# labels are the only text shown. Missing and non-finite (±inf) values are excluded
# per row; opaque / control-character / overlong / unresolved-collision categories are
# rejected before execution. Computation routes only through the public
# ``run_statistical_test`` seam (``CHI_GOF`` / ``CHI_IND`` / ``CHI_HOMOG``) with no
# signature or formula change. Chi-square tests are right-tail (the kernel handles all
# three as two-sided/right-tail); no one-sided control is exposed. Expected-frequency
# diagnostics are informational and never switch the test or block execution.

# Custom goodness-of-fit proportions must sum to 1 within this documented tolerance;
# invalid inputs are rejected with a structured message, never silently normalized.
_CHI_GOF_PROPORTION_TOLERANCE = 1e-6


def chi_square_gof_options(
    df: pd.DataFrame, column: str
) -> tuple[list[CategoryOption], str | None]:
    """Collision-safe distinct categories for a goodness-of-fit column.

    Reuses the accepted typed-category system: missing and non-finite values are
    excluded, native typed values stay distinct even when their text collides, and an
    unsafe/ambiguous category set yields ``([], reason)``. ``([], None)`` when the
    column is absent. The runner renders one expected-proportion input per returned
    option and maps proportions back by ``option.identity`` (never by text).
    """
    if column not in df.columns:
        return [], None
    return _typed_categories(_valid_category_scalars(df[column]), column)


def _gof_expected_proportions(
    options: list[CategoryOption],
    expected_proportions: Mapping[_CategoryIdentity, float],
) -> tuple[list[float], str | None]:
    """Validate an identity-keyed custom expected-proportion mapping.

    Returns ``(proportions, None)`` in option order, or ``([], reason)`` when a category
    is unmapped, a value is non-finite or not strictly positive, or the total does not
    equal 1 within ``_CHI_GOF_PROPORTION_TOLERANCE``. Inputs are never normalized.
    """
    proportions: list[float] = []
    for option in options:
        if option.identity not in expected_proportions:
            return [], f"missing expected proportion for category {option.label}"
        raw = expected_proportions[option.identity]
        if not isinstance(raw, int | float) or not math.isfinite(float(raw)):
            return [], f"expected proportion for {option.label} must be a finite number"
        if float(raw) <= 0.0:
            return (
                [],
                f"expected proportion for {option.label} must be strictly greater than zero",
            )
        proportions.append(float(raw))
    proportion_total = sum(proportions)
    if abs(proportion_total - 1.0) > _CHI_GOF_PROPORTION_TOLERANCE:
        return [], (
            "expected proportions must sum to 1 within "
            f"{_CHI_GOF_PROPORTION_TOLERANCE:g}; got {proportion_total:.6g}"
        )
    return proportions, None


def _gof_category_options(
    valid_values: list[Any], column: str
) -> tuple[list[CategoryOption], str | None, int]:
    """Ceiling-guarded, collision-safe categories for a goodness-of-fit column.

    The cheap ceiling runs first, so a pathological column is refused before any
    category option, label, observed vector or category payload exists. The exact
    typed count is re-checked afterwards because type-aware identity can keep apart
    values the cheap count merged. Returns ``(options, reason, category_count)``.
    """
    excessive = exceeds_level_ceiling(valid_values)
    if excessive is not None:
        return [], _too_many_levels_reason(f"column {column!r}", excessive), excessive
    options, error = _typed_categories(valid_values, column)
    if error is not None:
        return [], error, len(options)
    if len(options) < 2:
        return (
            [],
            "goodness-of-fit needs at least two distinct non-missing categories; "
            f"found {len(options)}",
            len(options),
        )
    if len(options) > STATS_CATEGORICAL_MAX_LEVELS:
        return [], _too_many_levels_reason(f"column {column!r}", len(options)), len(options)
    return options, None, len(options)


def run_chi_square_gof_test(
    df: pd.DataFrame,
    column: str,
    *,
    expected_proportions: Mapping[_CategoryIdentity, float] | None = None,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Chi-square goodness-of-fit test for one categorical column (status dict).

    Streamlit-free. Answers "does the observed categorical distribution match the
    expected distribution?" using all valid retained typed categories (at least two
    required) in deterministic label order. ``expected_proportions=None`` assigns equal
    expected probability to every category; a mapping keyed by ``option.identity``
    supplies explicit custom proportions. Custom proportions must each be finite and
    strictly greater than zero, must cover every retained category exactly, and must
    sum to 1 within ``_CHI_GOF_PROPORTION_TOLERANCE`` — invalid inputs are rejected with
    a structured message, never silently normalized. Routes through the public
    ``run_statistical_test`` seam with ``CHI_GOF`` (right-tail). Never raises for invalid
    operator input.
    """

    def _status(status: str, reason: str, **extra: Any) -> dict[str, Any]:
        shaped = _public_test_status(
            status=status,
            reason=reason,
            test_key="CHI_GOF",
            alpha=alpha,
            alternative="two-sided",
        )
        shaped.update({"column": str(column)})
        shaped.update(extra)
        return shaped

    if column not in df.columns:
        return _status("invalid_input", f"column not found: {column!r}")

    valid_values = _valid_category_scalars(df[column])
    total_rows = int(len(df))
    valid_rows = len(valid_values)
    counts: dict[str, Any] = {
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "excluded_rows": total_rows - valid_rows,
    }
    if valid_rows < 1:
        return _status(
            "insufficient_data", "need at least one non-missing category value", **counts
        )

    # L2 computation safety: eligibility is resolved before the observed vector and
    # the category payload are built, never after.
    options, category_error, category_count = _gof_category_options(valid_values, str(column))
    if category_error is not None:
        return _status("invalid_input", category_error, category_count=category_count, **counts)

    identity_index = {option.identity: index for index, option in enumerate(options)}
    observed = [0] * len(options)
    for value in valid_values:
        observed[identity_index[_category_identity(value)]] += 1

    observed_labels = [option.label for option in options]
    if expected_proportions is None:
        expected_mode = "equal"
        expected_props = [1.0 / category_count] * category_count
    else:
        expected_mode = "custom"
        expected_props, proportion_error = _gof_expected_proportions(options, expected_proportions)
        if proportion_error is not None:
            return _status(
                "invalid_input",
                proportion_error,
                category_count=category_count,
                observed_values=observed_labels,
                **counts,
            )

    expected_counts = [proportion * valid_rows for proportion in expected_props]
    categories = [
        {
            "category": options[index].label,
            "observed": observed[index],
            "expected_proportion": expected_props[index],
            "expected_count": expected_counts[index],
        }
        for index in range(category_count)
    ]

    result: dict[str, Any] = dict(
        _api_run_statistical_test(
            "CHI_GOF",
            observed=observed,
            expected=expected_counts,
            alpha=alpha,
        )
    )
    assumptions = result.get("assumptions") or {}
    result.update(
        {
            "column": str(column),
            "expected_mode": expected_mode,
            "category_count": category_count,
            "observed_values": observed_labels,
            "observed_counts": list(observed),
            "categories": categories,
            "degrees_of_freedom": assumptions.get("df"),
            **counts,
        }
    )
    return result


def _contingency_axis(
    values: list[Any], column: str, noun: str
) -> tuple[list[CategoryOption], tuple[str, str] | None]:
    """Ceiling-guarded, collision-safe categories for one contingency axis.

    The cheap ceiling runs before ``_typed_categories`` and the exact typed count is
    re-checked after it, so both axes are resolved before the observed matrix or the
    expected ``np.outer`` matrix is allocated. Returns ``(options, error)`` where
    ``error`` is a ``(status, reason)`` pair.
    """
    excessive = exceeds_level_ceiling(values)
    if excessive is not None:
        return [], ("invalid_input", _too_many_levels_reason(noun, excessive))
    options, error = _typed_categories(values, column)
    if error is not None:
        return [], ("invalid_input", error)
    if len(options) < 2:
        return [], ("invalid_input", f"{noun} must have at least two distinct non-missing values")
    if len(options) > STATS_CATEGORICAL_MAX_LEVELS:
        return [], ("invalid_input", _too_many_levels_reason(noun, len(options)))
    return options, None


def _build_contingency(
    df: pd.DataFrame,
    row_column: str,
    col_column: str,
    *,
    row_noun: str,
    col_noun: str,
) -> tuple[dict[str, Any] | None, tuple[str, str] | None, dict[str, int]]:
    """Build a deterministic observed contingency table with typed, collision-safe axes.

    Shared by the independence and homogeneity runners. A row is excluded when either
    selected value is missing or non-finite; the two axes are labelled independently
    with the accepted collision-safe typed-category system (an unsafe/ambiguous category
    set rejects the whole selection). Expected counts are derived deterministically from
    the observed margins for the operator-facing evidence table only — the test statistic
    and the authoritative expected-count reliability diagnostics both come from the public
    kernel, never from this layer. Returns ``(prepared, error, counts)`` where
    ``error`` is ``(status, reason)`` or ``None`` and ``counts`` is always populated.
    """
    total_rows = int(len(df))
    pairs: list[tuple[Any, Any]] = []
    for row_value, col_value in zip(df[row_column].tolist(), df[col_column].tolist()):
        if _is_invalid_category(row_value) or _is_invalid_category(col_value):
            continue
        pairs.append((row_value, col_value))
    valid_rows = len(pairs)
    counts = {
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "excluded_rows": total_rows - valid_rows,
    }
    if valid_rows < 1:
        reason = "no rows where both selected columns are present and finite"
        return None, ("insufficient_data", reason), counts
    # L2 computation safety, per axis: both axes are fully resolved before the
    # observed matrix and the expected np.outer matrix below are allocated.
    row_options, row_error = _contingency_axis([row for row, _ in pairs], str(row_column), row_noun)
    if row_error is not None:
        return None, row_error, counts
    col_options, col_error = _contingency_axis([col for _, col in pairs], str(col_column), col_noun)
    if col_error is not None:
        return None, col_error, counts

    row_index = {option.identity: index for index, option in enumerate(row_options)}
    col_index = {option.identity: index for index, option in enumerate(col_options)}
    n_rows, n_cols = len(row_options), len(col_options)
    observed = [[0] * n_cols for _ in range(n_rows)]
    for row_value, col_value in pairs:
        observed[row_index[_category_identity(row_value)]][
            col_index[_category_identity(col_value)]
        ] += 1
    observed_array = np.asarray(observed, dtype=float)
    expected = (
        np.outer(observed_array.sum(axis=1), observed_array.sum(axis=0)) / observed_array.sum()
    )
    prepared: dict[str, Any] = {
        "row_options": row_options,
        "col_options": col_options,
        "observed": observed,
        "expected": expected.tolist(),
        "row_category_count": n_rows,
        "col_category_count": n_cols,
        **counts,
    }
    return prepared, None, counts


def _run_contingency_test(
    df: pd.DataFrame,
    test_key: str,
    row_column: str,
    col_column: str,
    *,
    alpha: float,
    row_noun: str,
    col_noun: str,
    labels: dict[str, Any],
) -> dict[str, Any]:
    """Prepare a contingency table and route it through the public seam for *test_key*.

    Shared orchestration for ``CHI_IND`` and ``CHI_HOMOG``: the two tests differ only in
    the axis nouns, the operator-facing label keys, and the ``test_key`` passed to the
    public ``run_statistical_test`` seam — never in the table-preparation primitive or the
    formula. Right-tail chi-square; never raises for invalid operator input.
    """

    def _status(status: str, reason: str, **extra: Any) -> dict[str, Any]:
        shaped = _public_test_status(
            status=status,
            reason=reason,
            test_key=test_key,
            alpha=alpha,
            alternative="two-sided",
        )
        shaped.update(labels)
        shaped.update(extra)
        return shaped

    if row_column not in df.columns:
        return _status("invalid_input", f"column not found: {row_column!r}")
    if col_column not in df.columns:
        return _status("invalid_input", f"column not found: {col_column!r}")
    if row_column == col_column:
        return _status("invalid_input", "the two selected columns must be different")

    prepared, error, counts = _build_contingency(
        df, row_column, col_column, row_noun=row_noun, col_noun=col_noun
    )
    if error is not None or prepared is None:
        status, reason = error if error is not None else ("invalid_input", "invalid table")
        return _status(status, reason, **counts)

    row_options = prepared["row_options"]
    col_options = prepared["col_options"]
    cells = [
        {
            "row_category": row_options[i].label,
            "col_category": col_options[j].label,
            "observed": prepared["observed"][i][j],
            "expected": prepared["expected"][i][j],
        }
        for i in range(prepared["row_category_count"])
        for j in range(prepared["col_category_count"])
    ]

    # The kernel result already carries the authoritative expected-count diagnostics
    # (and any continuity-correction disclosure); this layer presents them unchanged.
    result: dict[str, Any] = dict(
        _api_run_statistical_test(test_key, table=prepared["observed"], alpha=alpha)
    )
    assumptions = result.get("assumptions") or {}
    result.update(
        {
            **labels,
            "row_labels": [option.label for option in row_options],
            "col_labels": [option.label for option in col_options],
            "row_category_count": prepared["row_category_count"],
            "col_category_count": prepared["col_category_count"],
            "observed_rows": prepared["row_category_count"],
            "observed_cols": prepared["col_category_count"],
            "cells": cells,
            "degrees_of_freedom": assumptions.get("dof"),
            **counts,
        }
    )
    return result


def run_chi_square_independence_test(
    df: pd.DataFrame,
    first_column: str,
    second_column: str,
    *,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Chi-square test of independence between two categorical columns (status dict).

    Streamlit-free. Answers "are two categorical variables statistically associated?"
    (null: independent; alternative: associated). Builds one deterministic observed
    contingency table via the shared typed, collision-safe primitive (rows = first
    column, columns = second column), derives expected counts from the observed margins
    for the evidence table, and routes through the public ``run_statistical_test`` seam
    with ``CHI_IND`` (right-tail). Expected-frequency diagnostics are owned by the domain
    kernel and surfaced here unchanged: they are informational and never switch the test.
    """
    return _run_contingency_test(
        df,
        "CHI_IND",
        str(first_column),
        str(second_column),
        alpha=alpha,
        row_noun=f"first column {first_column!r}",
        col_noun=f"second column {second_column!r}",
        labels={"first_column": str(first_column), "second_column": str(second_column)},
    )


def run_chi_square_homogeneity_test(
    df: pd.DataFrame,
    group_column: str,
    outcome_column: str,
    *,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Chi-square test of homogeneity across populations/groups (status dict).

    Streamlit-free. Answers "is the distribution of a categorical outcome the same across
    the selected populations/groups?" (null: every group has the same outcome
    distribution; alternative: at least one group differs). Reuses the same shared typed,
    collision-safe contingency primitive as the independence test — the evidence table is
    oriented with groups on the row axis and outcome categories on the column axis — and
    routes through the public ``run_statistical_test`` seam with the distinct ``CHI_HOMOG``
    key (never ``CHI_IND``), so the domain formula is neither duplicated nor modified.
    Right-tail chi-square; the kernel's expected-frequency diagnostics are surfaced
    unchanged and are informational; no causal or post-hoc claim is made.
    """
    return _run_contingency_test(
        df,
        "CHI_HOMOG",
        str(group_column),
        str(outcome_column),
        alpha=alpha,
        row_noun=f"group column {group_column!r}",
        col_noun=f"outcome column {outcome_column!r}",
        labels={"group_column": str(group_column), "outcome_column": str(outcome_column)},
    )


# ── nonparametric effect sizes (wires the existing effect_size kernel) ────────

# Cliff's delta magnitude bands (display-only labels; Romano et al. 2006). These
# categorize the kernel estimate for operators — they are not new estimators.
_CLIFFS_DELTA_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (0.147, "negligible"),
    (0.33, "small"),
    (0.474, "medium"),
)


def _cliffs_delta_interpretation(delta: float) -> str:
    """Map a Cliff's delta value to a plain-language magnitude band."""
    magnitude = abs(delta)
    for threshold, label in _CLIFFS_DELTA_THRESHOLDS:
        if magnitude < threshold:
            return label
    return "large"


def _effect_size_status(status: str, reason: str) -> dict[str, Any]:
    """Return a nonparametric effect-size status dict with a stable shape."""
    return {
        "status": status,
        "reason": reason,
        "group_a": None,
        "group_b": None,
        "n_a": None,
        "n_b": None,
        "cliffs_delta": None,
        "cliffs_interpretation": None,
        "hodges_lehmann": None,
    }


def _two_level_samples(
    df: pd.DataFrame, metric: str, group_col: str
) -> tuple[str, str, list[float], list[float]] | dict[str, Any]:
    """Split a numeric metric into exactly two group samples, or a status dict.

    Groups are ordered by ``sorted(str(level))`` — matching
    ``domain.statistics.inferential.compare_two_groups`` — so effect-size signs
    align with the panel's existing Δ mean (A−B) and Cohen's d orientation.
    """
    sample = _numeric_sample_from_column(df, metric)
    if isinstance(sample, dict):
        return _effect_size_status(
            str(sample.get("status") or "invalid_input"),
            str(sample.get("reason") or "unusable metric column"),
        )
    if group_col not in df.columns:
        return _effect_size_status("invalid_input", f"group column not found: {group_col!r}")
    if metric == group_col:
        return _effect_size_status("invalid_input", "metric and group column must be different")

    clean = df[[metric, group_col]].dropna()
    levels = sorted(clean[group_col].astype(str).unique())
    if len(levels) < 2:
        return _effect_size_status(
            "too_few_groups", "need exactly two groups; found fewer than two"
        )
    if len(levels) > 2:
        return _effect_size_status(
            "too_many_groups",
            f"found {len(levels)} groups; effect sizes need exactly two (use A/B to pick two)",
        )

    group_a, group_b = levels[0], levels[1]
    samples = _numeric_samples_by_group(df, metric, group_col, group_a, group_b)
    if isinstance(samples, dict):
        return _effect_size_status(
            str(samples.get("status") or "invalid_input"),
            str(samples.get("reason") or "unusable group split"),
        )
    sample_a, sample_b = samples
    if len(sample_a) < 2 or len(sample_b) < 2:
        return _effect_size_status("insufficient_data", "each group needs at least 2 finite values")
    return group_a, group_b, sample_a, sample_b


def _hodges_lehmann_pairwise_limit(confidence: float) -> dict[str, Any]:
    """The ``hodges_lehmann`` sub-dict for a split too large for the exact computation.

    Same keys and status order as the kernel's status dict: a missing scipy still
    reads ``unavailable`` ahead of ``pairwise_limit_exceeded``. Nothing is estimated
    either way, so estimate and bounds stay ``None`` rather than being approximated.
    """
    _validate_confidence(confidence)
    unavailable = _import_scipy_stats() is None
    return {
        "status": "unavailable" if unavailable else _PAIRWISE_LIMIT_STATUS,
        "reason": _STATS_UNAVAILABLE_REASON if unavailable else _PAIRWISE_LIMIT_REASON,
        "confidence": confidence,
        "estimate": None,
        "lower": None,
        "upper": None,
        "method": "hodges_lehmann_normal_approx",
    }


def nonparametric_effect_sizes(
    df: pd.DataFrame, metric: str, group_col: str, *, confidence: float = 0.95
) -> dict[str, Any]:
    """Cliff's delta + Hodges-Lehmann shift for an independent two-group split.

    Wires the existing effect-size kernel (``cliffs_delta``,
    ``hodges_lehmann_estimate``, ``hodges_lehmann_ci``). Cliff's delta and the HL
    point estimate are pure numpy (always available); the HL confidence band needs
    scipy and degrades to a structured ``unavailable`` status inside the
    ``hodges_lehmann`` sub-dict without failing the whole result.

    The exact HL computation materializes every pairwise difference, so a split
    forming more than ``MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS`` pairs is never sent
    to it: the ``hodges_lehmann`` sub-dict carries a ``pairwise_limit_exceeded``
    status with no estimate, while Cliff's delta (exact without pairs) is still
    reported. As in the kernel, a missing scipy (``unavailable``) and then a group
    with fewer than two finite values (``insufficient_data``) take precedence over
    the pairwise limit.
    """
    resolved = _two_level_samples(df, metric, group_col)
    if isinstance(resolved, dict):
        return resolved
    group_a, group_b, sample_a, sample_b = resolved

    delta = _cliffs_delta(sample_a, sample_b)
    within_limit = (
        _pairwise_comparison_count(sample_a, sample_b) <= _MAX_EXACT_PAIRWISE_EFFECT_SIZE_PAIRS
    )
    finite_enough = all(
        _has_enough_observations(_clean_numeric(sample)) for sample in (sample_a, sample_b)
    )
    if finite_enough and not within_limit:
        hodges_lehmann = _hodges_lehmann_pairwise_limit(confidence)
    else:
        # The kernel reports unavailable / insufficient_data before its own pairwise
        # limit, without forming any pairs.
        hodges_lehmann = dict(_hodges_lehmann_ci(sample_a, sample_b, confidence=confidence))
        # Surface a point estimate even when the scipy band is unavailable/insufficient,
        # unless it would need more pairs than the exact ceiling allows.
        if hodges_lehmann.get("estimate") is None and within_limit:
            hodges_lehmann["estimate"] = round(_hodges_lehmann_estimate(sample_a, sample_b), 6)
    return {
        "status": "ok",
        "reason": None,
        "confidence": confidence,
        "group_a": group_a,
        "group_b": group_b,
        "n_a": len(sample_a),
        "n_b": len(sample_b),
        "cliffs_delta": round(float(delta), 6),
        "cliffs_interpretation": _cliffs_delta_interpretation(delta),
        "hodges_lehmann": hodges_lehmann,
    }


# ── confidence intervals (wires the existing statistics interval/bootstrap kernel) ──

# Operator-clear, bounded confidence levels surfaced by Statistics Lab.
_CI_CONFIDENCE_CHOICES: tuple[float, ...] = (0.95, 0.90, 0.99)


def confidence_interval_choices() -> tuple[float, ...]:
    """Return the bounded confidence levels the CI controls offer."""
    return _CI_CONFIDENCE_CHOICES


def _ci_status(
    status: str,
    reason: str,
    *,
    method: str = "ui_statistics_service",
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Return a CI-shaped status dict mirroring the domain interval contract."""
    return {
        "status": status,
        "reason": reason,
        "method": method,
        "confidence": confidence,
        "point": None,
        "lower": None,
        "upper": None,
        "n": None,
    }


def _with_interpretation(result: dict[str, Any]) -> dict[str, Any]:
    """Attach a plain-language interpretation to an ``ok`` confidence interval."""
    if result.get("status") == "ok":
        confidence = float(result.get("confidence") or 0.0) * 100.0
        result["interpretation"] = (
            f"{confidence:.0f}% confident the true mean is between "
            f"{result.get('lower')} and {result.get('upper')}."
        )
    return result


def mean_confidence_interval(
    df: pd.DataFrame, metric: str, *, confidence: float = 0.95
) -> dict[str, Any]:
    """Closed-form t-interval for a numeric column's mean (domain ``ci_mean``)."""
    sample = _numeric_sample_from_column(df, metric)
    if isinstance(sample, dict):
        return _ci_status(
            str(sample.get("status") or "invalid_input"),
            str(sample.get("reason") or "unusable metric column"),
            confidence=confidence,
        )
    return _with_interpretation(dict(_ci_mean(sample, confidence=confidence)))


def bootstrap_mean_confidence_interval(
    df: pd.DataFrame,
    metric: str,
    *,
    confidence: float = 0.95,
    n_bootstrap: int = _DEFAULT_N_BOOTSTRAP,
    method: str = "percentile",
) -> dict[str, Any]:
    """Bootstrap CI for a numeric column's mean (domain ``bootstrap_ci``).

    ``percentile`` is pure numpy (always available); ``bca`` needs scipy and
    degrades to a structured ``unavailable`` status when it is absent.
    ``n_bootstrap`` is clamped to ``MAX_N_BOOTSTRAP`` by the domain kernel.
    """
    sample = _numeric_sample_from_column(df, metric)
    if isinstance(sample, dict):
        return _ci_status(
            str(sample.get("status") or "invalid_input"),
            str(sample.get("reason") or "unusable metric column"),
            method=method,
            confidence=confidence,
        )
    return _with_interpretation(
        dict(
            _bootstrap_ci(
                sample,
                confidence=confidence,
                n_bootstrap=n_bootstrap,
                method=method,
            )
        )
    )


# ── power & sample size (wires the existing closed-form power/sample-size kernel) ──

# Operator-clear, bounded power targets surfaced by the Power & Sample size tab.
_POWER_TARGET_CHOICES: tuple[float, ...] = (0.80, 0.90, 0.95)


def power_target_choices() -> tuple[float, ...]:
    """Return the bounded target-power levels the power controls offer."""
    return _POWER_TARGET_CHOICES


def _power_invalid(method: str, reason: str) -> dict[str, Any]:
    """Return a power-shaped ``invalid_input`` status dict (never raises upward)."""
    return {"status": "invalid_input", "reason": reason, "method": method}


def power_mean(
    n: int,
    delta: float,
    sigma: float,
    *,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> dict[str, Any]:
    """Power for a one-sample mean test (domain ``power_mean``)."""
    try:
        return dict(_power_mean(n, delta, sigma, alpha=alpha, alternative=alternative))
    except ValueError as exc:
        return _power_invalid("normal_power_mean", str(exc))


def power_prop(
    n: int,
    p1: float,
    p2: float,
    *,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> dict[str, Any]:
    """Power for a two-proportion test (domain ``power_prop``)."""
    try:
        return dict(_power_prop(n, p1, p2, alpha=alpha, alternative=alternative))
    except ValueError as exc:
        return _power_invalid("normal_power_prop", str(exc))


def required_n_mean(
    delta: float,
    sigma: float,
    *,
    alpha: float = 0.05,
    power: float = 0.8,
    alternative: str = "two-sided",
) -> dict[str, Any]:
    """Required sample size for a mean test (domain ``required_n_mean``)."""
    try:
        return dict(
            _required_n_mean(delta, sigma, alpha=alpha, power=power, alternative=alternative)
        )
    except ValueError as exc:
        return _power_invalid("normal_n_mean", str(exc))


def required_n_prop(
    p1: float,
    p2: float,
    *,
    alpha: float = 0.05,
    power: float = 0.8,
    alternative: str = "two-sided",
) -> dict[str, Any]:
    """Required per-group sample sizes for a two-proportion test (domain ``required_n_prop``)."""
    try:
        return dict(_required_n_prop(p1, p2, alpha=alpha, power=power, alternative=alternative))
    except ValueError as exc:
        return _power_invalid("normal_n_prop", str(exc))


def required_n_variance(
    ratio: float,
    *,
    alpha: float = 0.05,
    power: float = 0.8,
) -> dict[str, Any]:
    """Required sample size for a variance-ratio test (domain ``required_n_variance``)."""
    try:
        return dict(_required_n_variance(ratio, alpha=alpha, power=power))
    except ValueError as exc:
        return _power_invalid("normal_n_variance", str(exc))


def required_n_cohend(
    delta: float,
    *,
    alpha: float = 0.05,
    power: float = 0.8,
) -> dict[str, Any]:
    """Required per-group sample size for a two-sample t-test from Cohen's d.

    Delegates to domain ``required_n_cohend`` (returns scalar ``n_per_group``).
    """
    try:
        return dict(_required_n_cohend(delta, alpha=alpha, power=power))
    except ValueError as exc:
        return _power_invalid("normal_n_cohend", str(exc))


# ── assumption checks (informational display; never selects or changes a test) ──
#
# These wrappers *display* whether the assumptions behind a statistical test
# plausibly hold. They are purely informational: they do not choose Welch vs
# t-test, Mann-Whitney vs t-test, or Kruskal vs ANOVA, and they never change a
# p-value verdict. Normality reuses ``inferential.check_normality`` (Shapiro-Wilk);
# equal variance uses the new ``assumptions.check_equal_variance`` (Levene);
# sample-size and missing-value summaries are pure pandas.

# Bound how many groups are checked so wide group columns stay responsive.
ASSUMPTION_MAX_GROUPS = 20
# Minimum per-group / per-column size for a meaningful check.
ASSUMPTION_MIN_N = 3
# Rule-of-thumb caution thresholds (clearly labeled guidance, not hard rules).
_ASSUMPTION_SMALL_SAMPLE = 30
_ASSUMPTION_SMALL_GROUP = 15
# Assumption status vocabulary surfaced to operators.
_ASSUMPTION_STATUSES = ("pass", "caution", "fail", "unavailable", "not_applicable")


def _assumption_check(
    name: str,
    status: str,
    *,
    alpha: float,
    statistic: float | None = None,
    p_value: float | None = None,
    interpretation: str = "",
    caveat: str | None = None,
) -> dict[str, Any]:
    """Return a single, stable assumption-check result dict."""
    return {
        "name": name,
        "status": status,
        "statistic": statistic,
        "p_value": p_value,
        "alpha": alpha,
        "interpretation": interpretation,
        "caveat": caveat,
    }


# Normality result status → assumption status (with an optional caveat).
_NORMALITY_NOT_APPLICABLE = {"insufficient_data", "invalid_type", "skipped_large_sample"}


def _normality_assumption(series: pd.Series, name: str, *, alpha: float) -> dict[str, Any]:
    """Map an ``inferential.check_normality`` result into an assumption check.

    Guards constant columns *before* calling Shapiro-Wilk (a constant column has
    no testable distribution) so the domain helper is reused unchanged and scipy
    is never handed degenerate input.
    """
    clean = series.dropna()
    if int(clean.nunique()) <= 1:
        return _assumption_check(
            name,
            "not_applicable",
            alpha=alpha,
            interpretation="constant column; normality is not testable.",
            caveat="all non-null values are identical",
        )
    result = _inferential.check_normality(series, alpha=alpha)
    status = str(result.get("status"))
    interpretation = str(result.get("interpretation") or "")
    if status == "ok":
        p_value = result.get("p_value")
        mapped = "pass" if (p_value is not None and p_value >= alpha) else "caution"
        return _assumption_check(
            name,
            mapped,
            alpha=alpha,
            statistic=result.get("statistic"),
            p_value=p_value,
            interpretation=interpretation,
        )
    if status == "unavailable":
        return _assumption_check(
            name,
            "unavailable",
            alpha=alpha,
            interpretation=interpretation,
            caveat=str(result.get("reason") or ""),
        )
    if status in _NORMALITY_NOT_APPLICABLE:
        return _assumption_check(
            name,
            "not_applicable",
            alpha=alpha,
            interpretation=interpretation,
            caveat=str(result.get("reason") or ""),
        )
    return _assumption_check(
        name,
        "not_applicable",
        alpha=alpha,
        interpretation=interpretation,
        caveat=str(result.get("reason") or status),
    )


def _equal_variance_assumption(samples: list[list[float]], *, alpha: float) -> dict[str, Any]:
    """Map a Levene ``check_equal_variance`` result into an assumption check."""
    result = _assumptions.check_equal_variance(samples, alpha=alpha, min_group_n=ASSUMPTION_MIN_N)
    status = str(result.get("status"))
    interpretation = str(result.get("interpretation") or "")
    name = "Equal variance (Levene)"
    if status == "ok":
        p_value = result.get("p_value")
        mapped = "pass" if (p_value is not None and p_value >= alpha) else "caution"
        return _assumption_check(
            name,
            mapped,
            alpha=alpha,
            statistic=result.get("statistic"),
            p_value=p_value,
            interpretation=interpretation,
        )
    if status == "unavailable":
        return _assumption_check(
            name,
            "unavailable",
            alpha=alpha,
            interpretation=interpretation,
            caveat=str(result.get("reason") or ""),
        )
    return _assumption_check(
        name,
        "not_applicable",
        alpha=alpha,
        interpretation=interpretation,
        caveat=str(result.get("reason") or ""),
    )


def _sample_size_assumption(
    n: int, name: str, *, alpha: float, min_n: int, caution_n: int, unit: str
) -> dict[str, Any]:
    """Rule-of-thumb sample-size guidance (clearly informational, not a hard gate)."""
    if n < min_n:
        return _assumption_check(
            name,
            "fail",
            alpha=alpha,
            interpretation=(f"{unit} n={n:,} is below the {min_n} needed to compute a check."),
            caveat="too few values to assess assumptions",
        )
    if n < caution_n:
        return _assumption_check(
            name,
            "caution",
            alpha=alpha,
            interpretation=(
                f"small {unit} (n={n:,} < {caution_n}); assumption tests and results "
                "are less reliable. Rule-of-thumb guidance only."
            ),
        )
    return _assumption_check(
        name,
        "pass",
        alpha=alpha,
        interpretation=f"{unit} n={n:,} is adequate for these checks.",
    )


def _missing_value_assumption(
    df: pd.DataFrame, columns: list[str], *, alpha: float
) -> dict[str, Any]:
    """Summarize rows dropped for missing values across the relevant columns."""
    name = "Missing values"
    total = int(len(df))
    if total == 0:
        return _assumption_check(
            name,
            "not_applicable",
            alpha=alpha,
            interpretation="no rows to assess.",
        )
    dropped = int(df[columns].isna().any(axis=1).sum())
    pct = round(dropped / total * 100.0, 2)
    if dropped == 0:
        return _assumption_check(
            name,
            "pass",
            alpha=alpha,
            interpretation="no missing values in the selected columns.",
        )
    return _assumption_check(
        name,
        "caution",
        alpha=alpha,
        interpretation=(
            f"{dropped:,} of {total:,} rows ({pct:g}%) have missing values and are "
            "dropped before the checks."
        ),
    )


def _assumption_result(
    *,
    status: str,
    metric: str,
    alpha: float,
    group_col: str | None = None,
    reason: str | None = None,
    checks: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Return a stable assumption-checks result envelope."""
    result: dict[str, Any] = {
        "status": status,
        "reason": reason,
        "metric": metric,
        "alpha": alpha,
        "scipy_available": inferential_available(),
        "checks": checks or [],
        "warnings": warnings or [],
    }
    if group_col is not None:
        result["group_col"] = group_col
    return result


def assumption_checks_one_sample(
    df: pd.DataFrame, metric: str, *, alpha: float = 0.05
) -> dict[str, Any]:
    """Informational assumption checks for a single numeric column.

    Returns normality (Shapiro-Wilk), a sample-size caution, and a missing-value
    summary. Never selects or changes a statistical test.
    """
    _validate_alpha(alpha)
    if metric not in df.columns:
        return _assumption_result(
            status="invalid_input",
            metric=metric,
            alpha=alpha,
            reason=f"metric column not found: {metric!r}",
        )
    if not _is_numeric_metric(df[metric]):
        return _assumption_result(
            status="invalid_input",
            metric=metric,
            alpha=alpha,
            reason=f"metric column {metric!r} is not numeric",
        )
    series = df[metric]
    n = int(series.dropna().size)
    checks = [
        _normality_assumption(series, "Normality (Shapiro-Wilk)", alpha=alpha),
        _sample_size_assumption(
            n,
            "Sample size",
            alpha=alpha,
            min_n=ASSUMPTION_MIN_N,
            caution_n=_ASSUMPTION_SMALL_SAMPLE,
            unit="sample",
        ),
        _missing_value_assumption(df, [metric], alpha=alpha),
    ]
    return _assumption_result(status="ok", metric=metric, alpha=alpha, checks=checks)


def assumption_checks_grouped(
    df: pd.DataFrame, metric: str, group_col: str, *, alpha: float = 0.05
) -> dict[str, Any]:
    """Informational assumption checks for a numeric metric split by a group column.

    Returns per-group normality, an equal-variance (Levene) check, a minimum
    group-size caution, and a missing-value summary. Never selects or changes a
    statistical test.
    """
    _validate_alpha(alpha)
    if metric not in df.columns:
        return _assumption_result(
            status="invalid_input",
            metric=metric,
            alpha=alpha,
            group_col=group_col,
            reason=f"metric column not found: {metric!r}",
        )
    if group_col not in df.columns:
        return _assumption_result(
            status="invalid_input",
            metric=metric,
            alpha=alpha,
            group_col=group_col,
            reason=f"group column not found: {group_col!r}",
        )
    if metric == group_col:
        return _assumption_result(
            status="invalid_input",
            metric=metric,
            alpha=alpha,
            group_col=group_col,
            reason="metric and group column must be different",
        )
    if not _is_numeric_metric(df[metric]):
        return _assumption_result(
            status="invalid_input",
            metric=metric,
            alpha=alpha,
            group_col=group_col,
            reason=f"metric column {metric!r} is not numeric",
        )

    clean = df[[metric, group_col]].dropna()
    as_str = clean[group_col].astype(str)
    counts = as_str.value_counts()
    warnings: list[str] = []
    kept = list(counts.index)
    if len(kept) > ASSUMPTION_MAX_GROUPS:
        kept = list(counts.index[:ASSUMPTION_MAX_GROUPS])
        warnings.append(
            f"found {len(counts)} groups; checks shown for the "
            f"{ASSUMPTION_MAX_GROUPS} most frequent"
        )

    checks: list[dict[str, Any]] = []
    samples: list[list[float]] = []
    smallest = int(counts.min()) if not counts.empty else 0
    for name in kept:
        values = clean.loc[as_str == name, metric]
        samples.append([float(v) for v in values.astype(float)])
        checks.append(_normality_assumption(values, f"Normality — {name}", alpha=alpha))
    checks.append(_equal_variance_assumption(samples, alpha=alpha))
    checks.append(
        _sample_size_assumption(
            smallest,
            "Minimum group size",
            alpha=alpha,
            min_n=ASSUMPTION_MIN_N,
            caution_n=_ASSUMPTION_SMALL_GROUP,
            unit="smallest group",
        )
    )
    checks.append(_missing_value_assumption(df, [metric, group_col], alpha=alpha))
    return _assumption_result(
        status="ok",
        metric=metric,
        alpha=alpha,
        group_col=group_col,
        checks=checks,
        warnings=warnings,
    )


def assumption_checks_dataframe(result: dict[str, Any]) -> pd.DataFrame | None:
    """Build a display/CSV table from an assumption-checks result's ``checks`` list.

    Returns None when the result carries no checks.
    """
    checks = result.get("checks")
    if not checks:
        return None
    rows = [
        {
            "check": check.get("name"),
            "status": check.get("status"),
            "statistic": check.get("statistic"),
            "p_value": check.get("p_value"),
            "alpha": check.get("alpha"),
            "interpretation": check.get("interpretation"),
            "caveat": check.get("caveat"),
        }
        for check in checks
    ]
    return pd.DataFrame(
        rows,
        columns=["check", "status", "statistic", "p_value", "alpha", "interpretation", "caveat"],
    )
