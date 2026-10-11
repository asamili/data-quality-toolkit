# src/data_quality_toolkit/domain/statistics/descriptive.py
"""Pure descriptive statistics for the statistics domain.

pandas/numpy only — no scipy, no plotting, no UI. Adapted from the extracted
``summary_stats`` / ``quick_profile`` / ``correlation_matrix`` helpers into
deterministic, test-friendly functions. Skew/kurtosis use pandas' built-in
moment estimators (no scipy dependency).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "numeric_summary",
    "quick_profile",
    "correlation_matrix",
]

_CORRELATION_METHODS = frozenset({"pearson", "spearman", "kendall"})


def _as_frame(data: pd.DataFrame | pd.Series | Any) -> pd.DataFrame:
    """Coerce a DataFrame / Series / array-like into a DataFrame."""
    if isinstance(data, pd.DataFrame):
        return data
    if isinstance(data, pd.Series):
        return data.to_frame()
    return pd.DataFrame(np.asarray(data))


def numeric_summary(data: pd.DataFrame | pd.Series | Any) -> pd.DataFrame:
    """Per-column descriptive statistics for the numeric columns of ``data``.

    Columns: count, missing, missing_pct, mean, median, std, min, max, skew,
    kurtosis. Returns an empty DataFrame when there are no numeric columns.
    Values are rounded to 6 decimals for stable comparisons; skew/kurtosis are
    NaN when pandas cannot compute them (too few values) — surfaced, not hidden.
    """
    frame = _as_frame(data)
    numeric = frame.select_dtypes(include="number")
    if numeric.shape[1] == 0:
        return pd.DataFrame()
    summary = pd.DataFrame(
        {
            "count": numeric.count(),
            "missing": numeric.isna().sum(),
            "missing_pct": (numeric.isna().mean() * 100.0).round(4),
            "mean": numeric.mean(),
            "median": numeric.median(),
            "std": numeric.std(),
            "min": numeric.min(),
            "max": numeric.max(),
            "skew": numeric.skew(),
            "kurtosis": numeric.kurt(),
        }
    )
    return summary.round(6)


def quick_profile(df: pd.DataFrame) -> dict[str, Any]:
    """Compact, JSON-ready profile of a DataFrame.

    Returns shape, deep memory in MB, a dtype histogram, and the non-zero
    missing-value counts per column.
    """
    missing = df.isna().sum()
    return {
        "n_rows": int(df.shape[0]),
        "n_columns": int(df.shape[1]),
        "memory_mb": round(float(df.memory_usage(deep=True).sum()) / 1_000_000.0, 6),
        "dtypes": {str(dtype): int(count) for dtype, count in df.dtypes.value_counts().items()},
        "missing": {str(col): int(n) for col, n in missing.items() if int(n) > 0},
    }


def correlation_matrix(df: pd.DataFrame, method: str = "pearson") -> pd.DataFrame:
    """Correlation matrix over the numeric columns of ``df``.

    ``method`` is one of pearson / spearman / kendall. Returns an empty
    DataFrame when fewer than two numeric columns are present.
    """
    if method not in _CORRELATION_METHODS:
        raise ValueError(f"method must be one of {sorted(_CORRELATION_METHODS)}, got {method!r}")
    numeric = df.select_dtypes(include="number")
    if numeric.shape[1] < 2:
        return pd.DataFrame()
    return numeric.corr(method=method).round(6)
