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
from typing import Any

import pandas as pd

from data_quality_toolkit.domain.statistics import inferential as _inferential

# Bound the number of numeric columns summarized so wide frames stay responsive.
MAX_DESCRIBE_COLUMNS = 100


def numeric_descriptive_stats(
    df: pd.DataFrame, max_columns: int = MAX_DESCRIBE_COLUMNS
) -> pd.DataFrame | None:
    """Return per-column descriptive statistics for numeric columns.

    Columns: count, mean, median, std, min, max, skew, kurtosis. Returns None
    when the frame has no numeric columns. Skew/kurtosis are NaN when pandas
    cannot compute them (too few values); this is surfaced, not hidden.
    """
    numeric = df.select_dtypes(include="number")
    numeric = numeric.iloc[:, : max(0, max_columns)]
    if numeric.shape[1] == 0:
        return None
    stats = pd.DataFrame(
        {
            "count": numeric.count(),
            "mean": numeric.mean(),
            "median": numeric.median(),
            "std": numeric.std(),
            "min": numeric.min(),
            "max": numeric.max(),
            "skew": numeric.skew(),
            "kurtosis": numeric.kurt(),
        }
    )
    return stats.round(4)


def column_type_overview(df: pd.DataFrame) -> dict[str, int]:
    """Return a compact count of numeric vs categorical/other columns."""
    numeric = df.select_dtypes(include="number").shape[1]
    total = df.shape[1]
    return {
        "total_columns": int(total),
        "numeric_columns": int(numeric),
        "categorical_or_other_columns": int(total - numeric),
    }


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
