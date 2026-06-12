# src/data_quality_toolkit/domain/statistics/drift.py
"""Statistical drift detection between two datasets (v1).

Compares a reference (baseline) DataFrame against a current DataFrame:
- Numeric columns: two-sample Kolmogorov-Smirnov test.
- Categorical columns: chi-square test of homogeneity on a 2xK contingency table.

Requires scipy, shipped as the optional ``[stats]`` extra. When scipy is not
installed the entry point returns ``status="unavailable"`` instead of raising.

p-values are reported uncorrected for multiple testing (v1 limitation, stated
in the result summary).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

__all__ = ["detect_drift_frames"]

OTHER_BUCKET = "__other__"
MIN_EXPECTED_FREQUENCY = 5.0

_UNAVAILABLE_REASON = (
    "scipy is not installed; install the stats extra: pip install data-quality-toolkit[stats]"
)
_UNCORRECTED_NOTE = "p-values are uncorrected for multiple testing"


def _import_scipy_stats() -> Any | None:
    """Return scipy.stats, or None when scipy is not installed."""
    try:
        from scipy import stats
    except ImportError:
        return None
    return stats


def _column_kind(series: pd.Series) -> str | None:
    """Classify a column as 'numeric', 'categorical', or None (unsupported)."""
    if pd.api.types.is_bool_dtype(series):
        return "categorical"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if isinstance(series.dtype, pd.CategoricalDtype):
        return "categorical"
    if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
        return "categorical"
    return None


def _entry(
    column: str,
    kind: str | None,
    *,
    reference_n: int = 0,
    current_n: int = 0,
) -> dict[str, Any]:
    """Base per-column result entry with stable keys."""
    return {
        "column": column,
        "kind": kind,
        "test": None,
        "statistic": None,
        "p_value": None,
        "drift_detected": None,
        "reference_n": reference_n,
        "current_n": current_n,
        "status": "skipped",
        "skip_reason": None,
        "interpretation": "",
    }


def _skip(entry: dict[str, Any], reason: str) -> dict[str, Any]:
    entry["status"] = "skipped"
    entry["skip_reason"] = reason
    entry["interpretation"] = f"skipped: {reason}"
    return entry


def _finish_tested(
    entry: dict[str, Any], test: str, statistic: float, p_value: float, alpha: float
) -> dict[str, Any]:
    drifted = bool(p_value < alpha)
    entry["test"] = test
    entry["statistic"] = float(statistic)
    entry["p_value"] = float(p_value)
    entry["drift_detected"] = drifted
    entry["status"] = "tested"
    entry["skip_reason"] = None
    if drifted:
        entry["interpretation"] = (
            f"p={p_value:.4g} < alpha={alpha:g} -> distributions differ (drift detected)"
        )
    else:
        entry["interpretation"] = f"p={p_value:.4g} >= alpha={alpha:g} -> no significant drift"
    return entry


def _contingency_table(ref: pd.Series, cur: pd.Series, max_categories: int) -> pd.DataFrame:
    """Build a 2xK contingency table; rare categories bucketed into OTHER_BUCKET."""
    ref_counts = ref.astype(str).value_counts()
    cur_counts = cur.astype(str).value_counts()
    combined = ref_counts.add(cur_counts, fill_value=0).sort_values(ascending=False)
    keep = list(combined.index[:max_categories])

    def bucketed(counts: pd.Series) -> dict[str, int]:
        out = {k: int(counts.get(k, 0)) for k in keep}
        other = int(counts.sum()) - sum(out.values())
        if other > 0:
            out[OTHER_BUCKET] = out.get(OTHER_BUCKET, 0) + other
        return out

    ref_row = bucketed(ref_counts)
    cur_row = bucketed(cur_counts)
    table = pd.DataFrame([ref_row, cur_row], index=["reference", "current"]).fillna(0).astype(int)
    # Drop categories absent from both sides (defensive; shouldn't occur)
    return table.loc[:, table.sum(axis=0) > 0]


def _test_categorical(
    stats_mod: Any,
    entry: dict[str, Any],
    ref: pd.Series,
    cur: pd.Series,
    alpha: float,
    max_categories: int,
) -> dict[str, Any]:
    table = _contingency_table(ref, cur, max_categories)
    if table.shape[1] < 2:
        return _skip(entry, "single_category")
    result = stats_mod.chi2_contingency(table.to_numpy())
    expected_min = float(pd.DataFrame(result.expected_freq).min().min())
    if expected_min < MIN_EXPECTED_FREQUENCY:
        return _skip(entry, "expected_frequency_too_low")
    return _finish_tested(entry, "chi_square", result.statistic, result.pvalue, alpha)


def _drift_for_column(
    stats_mod: Any,
    column: str,
    reference: pd.DataFrame,
    current: pd.DataFrame,
    *,
    alpha: float,
    min_samples: int,
    max_categories: int,
) -> dict[str, Any]:
    in_ref = column in reference.columns
    in_cur = column in current.columns
    if not (in_ref and in_cur):
        side = reference[column] if in_ref else current[column]
        return _skip(_entry(column, _column_kind(side)), "column_missing")

    ref_kind = _column_kind(reference[column])
    cur_kind = _column_kind(current[column])
    if ref_kind is None or cur_kind is None:
        return _skip(_entry(column, ref_kind or cur_kind), "unsupported_dtype")
    if ref_kind != cur_kind:
        return _skip(_entry(column, ref_kind), "dtype_mismatch")

    ref_vals = reference[column].dropna()
    cur_vals = current[column].dropna()
    entry = _entry(column, ref_kind, reference_n=int(len(ref_vals)), current_n=int(len(cur_vals)))

    if len(ref_vals) == 0 or len(cur_vals) == 0:
        return _skip(entry, "all_null")
    if len(ref_vals) < min_samples or len(cur_vals) < min_samples:
        return _skip(entry, "insufficient_samples")

    if ref_kind == "numeric":
        result = stats_mod.ks_2samp(ref_vals.to_numpy(), cur_vals.to_numpy())
        return _finish_tested(entry, "ks", result.statistic, result.pvalue, alpha)
    return _test_categorical(stats_mod, entry, ref_vals, cur_vals, alpha, max_categories)


def _summarize(columns: list[dict[str, Any]]) -> dict[str, Any]:
    tested = [c for c in columns if c["status"] == "tested"]
    drifted = [c for c in tested if c["drift_detected"]]
    return {
        "columns_tested": len(tested),
        "columns_skipped": len(columns) - len(tested),
        "columns_drifted": len(drifted),
        "drift_detected": bool(drifted),
        "note": _UNCORRECTED_NOTE,
    }


def detect_drift_frames(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    *,
    alpha: float = 0.05,
    min_samples: int = 30,
    max_categories: int = 20,
) -> dict[str, Any]:
    """Detect distribution drift between *reference* (baseline) and *current*.

    Numeric columns use the two-sample KS test; categorical columns use the
    chi-square test of homogeneity. Returns a plain dict; see module docstring.
    When scipy is unavailable returns ``status="unavailable"`` without raising.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if min_samples < 2:
        raise ValueError(f"min_samples must be >= 2, got {min_samples}")
    if max_categories < 2:
        raise ValueError(f"max_categories must be >= 2, got {max_categories}")

    base: dict[str, Any] = {
        "status": "ok",
        "reason": None,
        "alpha": alpha,
        "scipy_available": True,
        "reference_rows": int(len(reference)),
        "current_rows": int(len(current)),
        "columns": [],
        "summary": _summarize([]),
    }

    stats_mod = _import_scipy_stats()
    if stats_mod is None:
        base["status"] = "unavailable"
        base["reason"] = _UNAVAILABLE_REASON
        base["scipy_available"] = False
        return base

    seen = list(reference.columns) + [c for c in current.columns if c not in reference.columns]
    columns = [
        _drift_for_column(
            stats_mod,
            col,
            reference,
            current,
            alpha=alpha,
            min_samples=min_samples,
            max_categories=max_categories,
        )
        for col in seen
    ]
    base["columns"] = columns
    base["summary"] = _summarize(columns)
    return base
