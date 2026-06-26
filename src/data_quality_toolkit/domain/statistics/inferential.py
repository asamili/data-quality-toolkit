# src/data_quality_toolkit/domain/statistics/inferential.py
"""Inferential statistics: normality, group comparison, and A/B testing.

A small, bounded inferential tier for the Statistics Lab page:
- Normality: Shapiro-Wilk on a single numeric column.
- Two-group: Welch t-test + Mann-Whitney U for a numeric metric split by a
  two-level group column (with a simple, clearly-labeled Cohen's d effect size).
- Multi-group: one-way ANOVA + Kruskal-Wallis across bounded groups.
- A/B: pick two group values and compare a numeric metric.

Requires scipy, shipped as the optional ``[stats]`` extra. When scipy is not
installed every entry point returns ``status="unavailable"`` instead of raising,
mirroring ``domain/statistics/drift.py``. All functions return plain dicts with
stable keys and a ``status`` field; they never raise except on invalid ``alpha``.

Interpretations are deliberately cautious: we report "evidence against
normality" / "no strong evidence against normality" and "no strong evidence of a
difference" — never "proves normal" or "proves different". p-values are reported
uncorrected for multiple testing.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "check_normality",
    "compare_two_groups",
    "compare_multi_group",
    "ab_compare",
]

_UNAVAILABLE_REASON = (
    "scipy is not installed; install the stats extra: pip install data-quality-toolkit[stats]"
)
_EFFECT_SIZE_LABEL = "Cohen's d (pooled SD; simple effect size)"

# Bounds keep the page responsive and the compute predictable.
MAX_GROUPS = 20
MAX_ROWS = 200_000
MIN_GROUP_N = 3
NORMALITY_SAMPLE_N = 5000
NORMALITY_HARD_CAP = 5_000_000


def _import_scipy_stats() -> Any | None:
    """Return scipy.stats, or None when scipy is not installed."""
    try:
        from scipy import stats
    except ImportError:
        return None
    return stats


def _validate_alpha(alpha: float) -> None:
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")


def _is_numeric(series: pd.Series) -> bool:
    """True for real numeric columns; bool columns are not treated as metrics."""
    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)


def _cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    """Pooled-SD Cohen's d (simple effect size). Returns 0.0 when SD is zero."""
    na, nb = a.size, b.size
    if na < 2 or nb < 2:
        return 0.0
    var_a = float(np.var(a, ddof=1))
    var_b = float(np.var(b, ddof=1))
    pooled = np.sqrt(((na - 1) * var_a + (nb - 1) * var_b) / (na + nb - 2))
    if pooled == 0:
        return 0.0
    return float((np.mean(a) - np.mean(b)) / pooled)


# ---------------------------------------------------------------------------
# Normality
# ---------------------------------------------------------------------------


def _normality_base(alpha: float) -> dict[str, Any]:
    return {
        "status": "ok",
        "reason": None,
        "alpha": alpha,
        "scipy_available": True,
        "method": None,
        "statistic": None,
        "p_value": None,
        "sample_size": 0,
        "interpretation": "",
        "warnings": [],
    }


def check_normality(
    series: pd.Series,
    *,
    alpha: float = 0.05,
    max_sample: int = NORMALITY_SAMPLE_N,
    hard_cap: int = NORMALITY_HARD_CAP,
    seed: int = 0,
) -> dict[str, Any]:
    """Shapiro-Wilk normality check for a single numeric column.

    Down-samples deterministically above ``max_sample`` and reports
    ``skipped_large_sample`` above ``hard_cap`` to keep compute bounded. Returns
    a status dict (statuses: ``ok`` / ``unavailable`` / ``insufficient_data`` /
    ``invalid_type`` / ``skipped_large_sample``).
    """
    _validate_alpha(alpha)
    base = _normality_base(alpha)

    stats_mod = _import_scipy_stats()
    if stats_mod is None:
        base["status"] = "unavailable"
        base["scipy_available"] = False
        base["reason"] = _UNAVAILABLE_REASON
        base["interpretation"] = _UNAVAILABLE_REASON
        return base

    if not _is_numeric(series):
        base["status"] = "invalid_type"
        base["reason"] = "column is not numeric; normality check needs a numeric column"
        base["interpretation"] = base["reason"]
        return base

    clean = series.dropna()
    n = int(clean.size)
    if n < 3:
        base["status"] = "insufficient_data"
        base["sample_size"] = n
        base["reason"] = "need at least 3 non-null values for a normality check"
        base["interpretation"] = base["reason"]
        return base
    if n > hard_cap:
        base["status"] = "skipped_large_sample"
        base["sample_size"] = n
        base["reason"] = f"sample of {n:,} exceeds the {hard_cap:,} cap; normality check skipped"
        base["interpretation"] = base["reason"]
        return base

    sample = clean
    if n > max_sample:
        sample = clean.sample(n=max_sample, random_state=seed)
        base["warnings"].append(
            f"down-sampled from {n:,} to {max_sample:,} values (seed={seed}) for Shapiro-Wilk"
        )

    result = stats_mod.shapiro(sample.to_numpy(dtype=float))
    statistic = float(result.statistic)
    p_value = float(result.pvalue)
    base["method"] = "shapiro_wilk"
    base["statistic"] = round(statistic, 6)
    base["p_value"] = round(p_value, 6)
    base["sample_size"] = int(sample.size)
    if p_value < alpha:
        base["interpretation"] = (
            f"p={p_value:.4g} < alpha={alpha:g}: evidence against normality "
            "(the data may not be normally distributed)."
        )
    else:
        base["interpretation"] = (
            f"p={p_value:.4g} >= alpha={alpha:g}: no strong evidence against normality."
        )
    return base


# ---------------------------------------------------------------------------
# Two-sample machinery (shared by two-group and A/B)
# ---------------------------------------------------------------------------


def _two_group_base(group_col: str, metric: str, alpha: float) -> dict[str, Any]:
    return {
        "status": "ok",
        "reason": None,
        "alpha": alpha,
        "scipy_available": True,
        "group_col": group_col,
        "metric": metric,
        "group_a": None,
        "group_b": None,
        "n_a": 0,
        "n_b": 0,
        "mean_a": None,
        "mean_b": None,
        "median_a": None,
        "median_b": None,
        "std_a": None,
        "std_b": None,
        "delta_mean": None,
        "percent_lift": None,
        "cohens_d": None,
        "effect_size_label": _EFFECT_SIZE_LABEL,
        "welch": None,
        "mann_whitney": None,
        "interpretation": "",
        "warnings": [],
    }


def _mark(base: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    base["status"] = status
    base["reason"] = reason
    base["interpretation"] = reason
    return base


def _mark_unavailable(base: dict[str, Any]) -> dict[str, Any]:
    base["status"] = "unavailable"
    base["scipy_available"] = False
    base["reason"] = _UNAVAILABLE_REASON
    base["interpretation"] = _UNAVAILABLE_REASON
    return base


def _interpret_two_sample(base: dict[str, Any], alpha: float) -> str:
    delta = base["delta_mean"]
    direction = "higher" if delta > 0 else ("lower" if delta < 0 else "equal")
    head = (
        f"Mean of '{base['group_a']}' is {direction} than '{base['group_b']}' "
        f"(delta_mean={delta:+.4g})."
    )
    welch_sig = base["welch"]["significant"]
    mw_sig = base["mann_whitney"]["significant"]
    if welch_sig and mw_sig:
        body = (
            f" Both Welch t-test and Mann-Whitney U indicate a statistically "
            f"significant difference at alpha={alpha:g}."
        )
    elif welch_sig or mw_sig:
        which = "Welch t-test" if welch_sig else "Mann-Whitney U"
        body = f" Only the {which} is significant at alpha={alpha:g}; interpret with caution."
    else:
        body = (
            f" Neither test is significant at alpha={alpha:g}; "
            "no strong evidence of a difference."
        )
    return head + body


def _fill_two_sample(
    base: dict[str, Any],
    stats_mod: Any,
    a_vals: pd.Series,
    b_vals: pd.Series,
    group_a: Any,
    group_b: Any,
    alpha: float,
) -> dict[str, Any]:
    a = a_vals.to_numpy(dtype=float)
    b = b_vals.to_numpy(dtype=float)
    mean_a = float(np.mean(a))
    mean_b = float(np.mean(b))
    base.update(
        group_a=str(group_a),
        group_b=str(group_b),
        n_a=int(a.size),
        n_b=int(b.size),
        mean_a=round(mean_a, 6),
        mean_b=round(mean_b, 6),
        median_a=round(float(np.median(a)), 6),
        median_b=round(float(np.median(b)), 6),
        std_a=round(float(np.std(a, ddof=1)), 6) if a.size > 1 else 0.0,
        std_b=round(float(np.std(b, ddof=1)), 6) if b.size > 1 else 0.0,
        delta_mean=round(mean_a - mean_b, 6),
        percent_lift=(round((mean_a - mean_b) / abs(mean_b) * 100, 4) if mean_b != 0 else None),
        cohens_d=round(_cohens_d(a, b), 6),
    )
    welch = stats_mod.ttest_ind(a, b, equal_var=False)
    mann = stats_mod.mannwhitneyu(a, b, alternative="two-sided")
    base["welch"] = {
        "method": "welch_t",
        "statistic": float(welch.statistic),
        "p_value": float(welch.pvalue),
        "significant": bool(welch.pvalue < alpha),
    }
    base["mann_whitney"] = {
        "method": "mann_whitney_u",
        "statistic": float(mann.statistic),
        "p_value": float(mann.pvalue),
        "significant": bool(mann.pvalue < alpha),
    }
    base["interpretation"] = _interpret_two_sample(base, alpha)
    return base


def _prepare_frame(
    df: pd.DataFrame,
    metric: str,
    group_col: str,
    *,
    max_rows: int,
    seed: int,
) -> tuple[pd.DataFrame | None, str | None]:
    """Validate columns and return a cleaned, row-bounded two-column frame."""
    if metric not in df.columns:
        return None, f"metric column not found: {metric!r}"
    if group_col not in df.columns:
        return None, f"group column not found: {group_col!r}"
    if metric == group_col:
        return None, "metric and group column must be different"
    if not _is_numeric(df[metric]):
        return None, f"metric column {metric!r} is not numeric"
    clean = df[[metric, group_col]].dropna()
    if len(clean) > max_rows:
        clean = clean.sample(n=max_rows, random_state=seed)
    return clean, None


def compare_two_groups(
    df: pd.DataFrame,
    metric: str,
    group_col: str,
    *,
    alpha: float = 0.05,
    max_rows: int = MAX_ROWS,
    min_group_n: int = MIN_GROUP_N,
    seed: int = 0,
) -> dict[str, Any]:
    """Welch t-test + Mann-Whitney U for a numeric metric split by a 2-level group.

    Statuses: ``ok`` / ``unavailable`` / ``invalid_type`` / ``too_few_groups`` /
    ``too_many_groups`` / ``insufficient_data``.
    """
    _validate_alpha(alpha)
    base = _two_group_base(group_col, metric, alpha)

    stats_mod = _import_scipy_stats()
    if stats_mod is None:
        return _mark_unavailable(base)

    clean, err = _prepare_frame(df, metric, group_col, max_rows=max_rows, seed=seed)
    if err is not None or clean is None:
        return _mark(base, "invalid_type", err or "invalid input")

    counts = clean[group_col].astype(str).value_counts()
    if len(counts) < 2:
        return _mark(base, "too_few_groups", "need exactly two groups; found fewer than two")
    if len(counts) > 2:
        return _mark(
            base,
            "too_many_groups",
            f"found {len(counts)} groups; use multi-group comparison or pick two via A/B",
        )

    group_a, group_b = sorted(counts.index.tolist())
    a_vals = clean.loc[clean[group_col].astype(str) == group_a, metric]
    b_vals = clean.loc[clean[group_col].astype(str) == group_b, metric]
    if len(a_vals) < min_group_n or len(b_vals) < min_group_n:
        base["n_a"] = int(len(a_vals))
        base["n_b"] = int(len(b_vals))
        base["group_a"] = str(group_a)
        base["group_b"] = str(group_b)
        return _mark(
            base,
            "insufficient_data",
            f"each group needs at least {min_group_n} non-null values",
        )

    return _fill_two_sample(base, stats_mod, a_vals, b_vals, group_a, group_b, alpha)


def ab_compare(
    df: pd.DataFrame,
    group_col: str,
    a_value: Any,
    b_value: Any,
    metric: str,
    *,
    alpha: float = 0.05,
    max_rows: int = MAX_ROWS,
    min_group_n: int = MIN_GROUP_N,
    seed: int = 0,
) -> dict[str, Any]:
    """Compare a numeric metric between two chosen group values (A vs B).

    Statuses: ``ok`` / ``unavailable`` / ``invalid_type`` / ``insufficient_data``.
    """
    _validate_alpha(alpha)
    base = _two_group_base(group_col, metric, alpha)

    stats_mod = _import_scipy_stats()
    if stats_mod is None:
        return _mark_unavailable(base)

    clean, err = _prepare_frame(df, metric, group_col, max_rows=max_rows, seed=seed)
    if err is not None or clean is None:
        return _mark(base, "invalid_type", err or "invalid input")
    if str(a_value) == str(b_value):
        return _mark(base, "invalid_type", "A and B values must be different")

    as_str = clean[group_col].astype(str)
    a_vals = clean.loc[as_str == str(a_value), metric]
    b_vals = clean.loc[as_str == str(b_value), metric]
    base["group_a"] = str(a_value)
    base["group_b"] = str(b_value)
    base["n_a"] = int(len(a_vals))
    base["n_b"] = int(len(b_vals))
    if len(a_vals) < min_group_n or len(b_vals) < min_group_n:
        return _mark(
            base,
            "insufficient_data",
            f"each of A and B needs at least {min_group_n} non-null values for the chosen metric",
        )

    return _fill_two_sample(base, stats_mod, a_vals, b_vals, a_value, b_value, alpha)


# ---------------------------------------------------------------------------
# Multi-group
# ---------------------------------------------------------------------------


def _multi_base(group_col: str, metric: str, alpha: float) -> dict[str, Any]:
    return {
        "status": "ok",
        "reason": None,
        "alpha": alpha,
        "scipy_available": True,
        "group_col": group_col,
        "metric": metric,
        "n_groups": 0,
        "groups": [],
        "truncated": False,
        "anova": None,
        "kruskal": None,
        "interpretation": "",
        "warnings": [],
    }


def compare_multi_group(
    df: pd.DataFrame,
    metric: str,
    group_col: str,
    *,
    alpha: float = 0.05,
    max_groups: int = MAX_GROUPS,
    max_rows: int = MAX_ROWS,
    min_group_n: int = MIN_GROUP_N,
    seed: int = 0,
) -> dict[str, Any]:
    """One-way ANOVA + Kruskal-Wallis across bounded groups.

    Truncates to the ``max_groups`` most frequent groups (with a warning) when
    more exist. Statuses: ``ok`` / ``unavailable`` / ``invalid_type`` /
    ``too_few_groups`` / ``insufficient_data``.
    """
    _validate_alpha(alpha)
    base = _multi_base(group_col, metric, alpha)

    stats_mod = _import_scipy_stats()
    if stats_mod is None:
        return _mark_unavailable(base)

    clean, err = _prepare_frame(df, metric, group_col, max_rows=max_rows, seed=seed)
    if err is not None or clean is None:
        return _mark(base, "invalid_type", err or "invalid input")

    counts = clean[group_col].astype(str).value_counts()
    if len(counts) < 2:
        return _mark(base, "too_few_groups", "need at least two groups for a comparison")

    kept = counts.index.tolist()
    if len(kept) > max_groups:
        kept = list(counts.index[:max_groups])
        base["truncated"] = True
        base["warnings"].append(
            f"found {len(counts)} groups; truncated to the {max_groups} most frequent"
        )

    as_str = clean[group_col].astype(str)
    groups_summary: list[dict[str, Any]] = []
    arrays: list[np.ndarray] = []
    for name in kept:
        values = clean.loc[as_str == name, metric].to_numpy(dtype=float)
        groups_summary.append(
            {
                "group": str(name),
                "n": int(values.size),
                "mean": round(float(np.mean(values)), 6) if values.size else None,
                "median": round(float(np.median(values)), 6) if values.size else None,
                "std": round(float(np.std(values, ddof=1)), 6) if values.size > 1 else 0.0,
            }
        )
        if values.size >= min_group_n:
            arrays.append(values)

    base["groups"] = groups_summary
    base["n_groups"] = len(groups_summary)

    if len(arrays) < 2:
        return _mark(
            base,
            "insufficient_data",
            f"need at least two groups with >= {min_group_n} non-null values each",
        )

    anova = stats_mod.f_oneway(*arrays)
    kruskal = stats_mod.kruskal(*arrays)
    base["anova"] = {
        "method": "one_way_anova",
        "statistic": float(anova.statistic),
        "p_value": float(anova.pvalue),
        "significant": bool(anova.pvalue < alpha),
    }
    base["kruskal"] = {
        "method": "kruskal_wallis",
        "statistic": float(kruskal.statistic),
        "p_value": float(kruskal.pvalue),
        "significant": bool(kruskal.pvalue < alpha),
    }
    anova_sig = base["anova"]["significant"]
    kruskal_sig = base["kruskal"]["significant"]
    if anova_sig and kruskal_sig:
        base["interpretation"] = (
            f"Both ANOVA and Kruskal-Wallis indicate at least one group mean/distribution "
            f"differs at alpha={alpha:g}."
        )
    elif anova_sig or kruskal_sig:
        which = "ANOVA" if anova_sig else "Kruskal-Wallis"
        base["interpretation"] = (
            f"Only {which} is significant at alpha={alpha:g}; interpret with caution."
        )
    else:
        base["interpretation"] = (
            f"Neither ANOVA nor Kruskal-Wallis is significant at alpha={alpha:g}; "
            "no strong evidence that groups differ."
        )
    return base
