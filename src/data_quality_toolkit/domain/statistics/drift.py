# src/data_quality_toolkit/domain/statistics/drift.py
"""Statistical drift detection between two datasets.

Compares a reference (baseline) DataFrame against a current DataFrame:
- Numeric columns: two-sample Kolmogorov-Smirnov test + PSI / JS / Wasserstein.
- Categorical columns: chi-square test of homogeneity + PSI / JS distance.

Requires scipy, shipped as the optional ``[stats]`` extra. When scipy is not
installed the entry point returns ``status="unavailable"`` instead of raising.
JS distance and Wasserstein are scipy-guarded (None when scipy absent). PSI is
dependency-free.

p-values are reported uncorrected for multiple testing (stated in the result summary).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

__all__ = ["detect_drift_frames"]

OTHER_BUCKET = "__other__"
MIN_EXPECTED_FREQUENCY = 5.0

_UNAVAILABLE_REASON = (
    "scipy is not installed; install the stats extra: pip install data-quality-toolkit[stats]"
)
_UNCORRECTED_NOTE = "p-values are uncorrected for multiple testing"

_PSI_EPSILON = 1e-6
_PSI_N_BINS = 10


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
        "psi": None,
        "js_distance": None,
        "wasserstein": None,
        "distribution": None,
    }


# ---------------------------------------------------------------------------
# Advanced metric helpers (PSI / JS / Wasserstein)
# ---------------------------------------------------------------------------


def _fmt_edge(value: float) -> str:
    """Human-readable, deterministic numeric edge label (±inf handled)."""
    if value == -np.inf:
        return "-inf"
    if value == np.inf:
        return "inf"
    return f"{value:.4g}"


def _numeric_bin_labels(edges: np.ndarray) -> list[str]:
    """Half-open ``[lo, hi)`` labels for each bin defined by *edges*."""
    return [f"[{_fmt_edge(lo)}, {_fmt_edge(hi)})" for lo, hi in zip(edges[:-1], edges[1:])]


def _prob_vectors_numeric(
    ref: np.ndarray, cur: np.ndarray
) -> tuple[np.ndarray, np.ndarray, list[str]] | None:
    """Quantile-based probability vectors and bin labels for numeric arrays.

    Uses reference quantiles to define bins so PSI / JS measure shift relative
    to the baseline distribution. Returns None for degenerate input (all identical
    reference values). Both vectors are epsilon-smoothed to avoid log-of-zero. The
    third element is the deterministic per-bin label list (same length as the
    probability vectors), reused for distribution capture.
    """
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, _PSI_N_BINS + 1)))
    if len(edges) < 2:
        return None
    # Replace outer edges with ±inf so all cur values are captured.
    edges = np.concatenate([[-np.inf], edges[1:-1], [np.inf]])
    ref_raw = np.histogram(ref, bins=edges)[0].astype(float)
    cur_raw = np.histogram(cur, bins=edges)[0].astype(float)
    ref_p = (ref_raw + _PSI_EPSILON) / (ref_raw + _PSI_EPSILON).sum()
    cur_p = (cur_raw + _PSI_EPSILON) / (cur_raw + _PSI_EPSILON).sum()
    return ref_p, cur_p, _numeric_bin_labels(edges)


def _prob_vectors_categorical(
    ref: pd.Series, cur: pd.Series, max_categories: int
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Category probability vectors and labels using the same bucketing as _contingency_table.

    The third element is the category label list (including ``OTHER_BUCKET`` when
    rare categories are bucketed), aligned with the probability vectors.
    """
    table = _contingency_table(ref, cur, max_categories)
    ref_raw = table.loc["reference"].to_numpy(dtype=float)
    cur_raw = table.loc["current"].to_numpy(dtype=float)
    ref_p = (ref_raw + _PSI_EPSILON) / (ref_raw + _PSI_EPSILON).sum()
    cur_p = (cur_raw + _PSI_EPSILON) / (cur_raw + _PSI_EPSILON).sum()
    return ref_p, cur_p, [str(c) for c in table.columns]


def _distribution(
    kind: str, labels: list[str], ref_p: np.ndarray, cur_p: np.ndarray
) -> dict[str, Any]:
    """Build the nullable per-column distribution payload from probability vectors.

    Probabilities are floats and (by construction of the smoothed vectors) sum to
    ~1.0 for both reference and current.
    """
    bins = [
        {"label": label, "reference": float(ref), "current": float(cur)}
        for label, ref, cur in zip(labels, ref_p, cur_p)
    ]
    return {"kind": kind, "bins": bins}


def _psi(ref_p: np.ndarray, cur_p: np.ndarray) -> float:
    """Population Stability Index from pre-smoothed probability vectors."""
    return float(np.sum((cur_p - ref_p) * np.log(cur_p / ref_p)))


def _js_distance(ref_p: np.ndarray, cur_p: np.ndarray, stats_mod: Any) -> float | None:
    """Jensen-Shannon distance (range [0,1]).

    Uses scipy.spatial.distance.jensenshannon. Gated on stats_mod being non-None
    (so that the same scipy availability check covers this function). Returns None
    when scipy is unavailable or cannot be imported.
    """
    if stats_mod is None:
        return None
    try:
        from scipy.spatial.distance import jensenshannon

        return float(jensenshannon(ref_p, cur_p, base=2))
    except ImportError:
        return None


def _wasserstein(ref_vals: np.ndarray, cur_vals: np.ndarray, stats_mod: Any) -> float | None:
    """1-D Wasserstein distance via scipy.stats.wasserstein_distance. Numeric only.

    Returns None when stats_mod is None (scipy unavailable).
    """
    if stats_mod is None:
        return None
    return float(stats_mod.wasserstein_distance(ref_vals, cur_vals))


def _attach_metrics(
    stats_mod: Any,
    entry: dict[str, Any],
    kind: str,
    ref_vals: pd.Series,
    cur_vals: pd.Series,
    max_categories: int,
) -> None:
    """Compute PSI / JS / Wasserstein and write them into *entry* in place.

    Called only after early-exit skip checks pass (both sides present, same kind,
    sufficient samples). PSI is always computed (dependency-free). JS and Wasserstein
    require scipy (gated on stats_mod). Wasserstein is numeric-only.
    """
    if kind == "numeric":
        vecs = _prob_vectors_numeric(ref_vals.to_numpy(), cur_vals.to_numpy())
        if vecs is not None:
            ref_p, cur_p, labels = vecs
            entry["psi"] = _psi(ref_p, cur_p)
            entry["js_distance"] = _js_distance(ref_p, cur_p, stats_mod)
            entry["distribution"] = _distribution("numeric", labels, ref_p, cur_p)
        # Degenerate numeric input leaves distribution=None.
        entry["wasserstein"] = _wasserstein(ref_vals.to_numpy(), cur_vals.to_numpy(), stats_mod)
    else:
        ref_p, cur_p, labels = _prob_vectors_categorical(ref_vals, cur_vals, max_categories)
        entry["psi"] = _psi(ref_p, cur_p)
        entry["js_distance"] = _js_distance(ref_p, cur_p, stats_mod)
        entry["distribution"] = _distribution("categorical", labels, ref_p, cur_p)
        # Wasserstein requires ordered numeric values; remains None for categorical.


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

    # Compute advanced metrics for all columns that reach the test phase.
    _attach_metrics(stats_mod, entry, ref_kind, ref_vals, cur_vals, max_categories)

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
