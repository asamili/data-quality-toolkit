# src/data_quality_toolkit/domain/statistics/multivariate.py
"""Pure multivariate numeric diagnostics for the statistics domain.

pandas/numpy only — no scipy, no sklearn/statsmodels, no plotting, no UI, no
adapters. Provides covariance matrices, variance inflation factors (VIF) for
multicollinearity, and a ranked table of the strongest pairwise correlations.

All functions are deterministic, never mutate the input frame, degrade to an
empty (but well-shaped) DataFrame on insufficient/degenerate input, and never
raise on missing values, non-finite values, constant columns, or perfect
collinearity. Numeric-only: non-numeric columns are ignored. Wide frames are
bounded to the first ``max_columns`` numeric columns to keep compute cheap.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from data_quality_toolkit.domain.statistics.core import import_scipy_stats

__all__ = [
    "covariance_matrix",
    "variance_inflation_factors",
    "top_correlations",
    "categorical_associations",
    "grouped_numeric_by_category_summary",
]

_CORRELATION_METHODS = ("pearson", "spearman", "kendall")
_VIF_COLUMNS = ["column", "vif"]
_TOP_CORR_COLUMNS = [
    "feature_x",
    "feature_y",
    "correlation",
    "abs_correlation",
    "method",
    "n",
]
_CATEGORICAL_ASSOC_COLUMNS = [
    "feature_x",
    "feature_y",
    "cramers_v",
    "chi2",
    "dof",
    "n",
    "p_value",
    "warning",
]
_GROUPED_SUMMARY_COLUMNS = [
    "category_column",
    "category_value",
    "numeric_column",
    "count",
    "missing",
    "mean",
    "median",
    "std",
    "min",
    "max",
]

# Default numeric-column cap, mirroring the EDA correlation surface.
_MAX_COLUMNS = 20
# Bucket label for capped high-cardinality categorical values.
_OTHER_BUCKET = "__other__"
# Below this expected cell count the chi-square approximation is unreliable.
_MIN_EXPECTED_COUNT = 5


def _bounded_finite_numeric(df: pd.DataFrame, max_columns: int) -> pd.DataFrame:
    """Return the first ``max_columns`` numeric columns with +/- inf masked to NaN.

    Does not mutate ``df`` (``select_dtypes``/``replace`` both return copies).
    """
    numeric = df.select_dtypes(include="number").iloc[:, : max(0, max_columns)]
    return numeric.replace([np.inf, -np.inf], np.nan)


def _categorical_like_columns(df: pd.DataFrame) -> list[str]:
    """Return object/string/category/bool column names; exclude numeric and datetime."""
    result: list[str] = []
    for column in df.columns:
        series = df[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            continue
        if (
            pd.api.types.is_bool_dtype(series)
            or isinstance(series.dtype, pd.CategoricalDtype)
            or pd.api.types.is_object_dtype(series)
            or pd.api.types.is_string_dtype(series)
        ):
            result.append(str(column))
    return result


def _cap_categories(series: pd.Series, max_categories: int) -> tuple[pd.Series, bool]:
    """Cap ``series`` to its top ``max_categories`` values by frequency.

    Remaining values are bucketed as ``__other__``; missing values are preserved
    as NA. Returns the transformed string-typed series and whether capping ran.
    """
    values = series.astype("string")
    counts = values.value_counts(dropna=True)
    if len(counts) <= max(0, max_categories):
        return values, False
    keep = set(counts.index[: max(0, max_categories)])
    capped = values.where(values.isin(keep) | values.isna(), other=_OTHER_BUCKET)
    return capped, True


def covariance_matrix(df: pd.DataFrame, *, max_columns: int = _MAX_COLUMNS) -> pd.DataFrame:
    """Pairwise covariance matrix over the numeric columns of ``df``.

    Numeric-only, bounded to the first ``max_columns`` columns. +/- inf are
    masked to NaN and covariance uses pairwise deletion (``min_periods=2``).
    Returns an empty DataFrame when fewer than two numeric columns are present.
    Values are rounded to 6 decimals. Never mutates ``df``; never raises on NaN.
    """
    numeric = _bounded_finite_numeric(df, max_columns)
    if numeric.shape[1] < 2:
        return pd.DataFrame()
    return numeric.cov(min_periods=2).round(6)


def variance_inflation_factors(
    df: pd.DataFrame, *, max_columns: int = _MAX_COLUMNS
) -> pd.DataFrame:
    """Variance inflation factors estimating multicollinearity among numeric columns.

    VIF is read off the diagonal of the inverse Pearson correlation matrix,
    computed on complete-case numeric data after dropping constant/near-constant
    columns. Uses ``numpy.linalg.inv`` and falls back to ``pinv`` when the
    correlation matrix is singular (e.g. duplicate/perfectly collinear columns),
    so it never raises. Returns an empty table with columns ``["column", "vif"]``
    when fewer than two usable numeric columns remain. Sorted by ``vif``
    descending; finite values rounded to 6 decimals; ``inf`` is allowed. Never
    mutates ``df``.
    """
    numeric = _bounded_finite_numeric(df, max_columns)
    usable = [column for column in numeric.columns if int(numeric[column].nunique(dropna=True)) > 1]
    numeric = numeric[usable]
    if numeric.shape[1] < 2:
        return pd.DataFrame(columns=_VIF_COLUMNS)

    complete = numeric.dropna(axis=0, how="any")
    if complete.shape[0] < 2 or complete.shape[1] < 2:
        return pd.DataFrame(columns=_VIF_COLUMNS)

    corr = complete.corr(method="pearson")
    corr_values = corr.to_numpy(dtype=float)
    if not np.isfinite(corr_values).all():
        return pd.DataFrame(columns=_VIF_COLUMNS)

    try:
        inverse = np.linalg.inv(corr_values)
    except np.linalg.LinAlgError:
        inverse = np.linalg.pinv(corr_values)

    result = pd.DataFrame({"column": list(corr.columns), "vif": np.diag(inverse)})
    result["vif"] = result["vif"].round(6)
    return result.sort_values("vif", ascending=False, kind="stable").reset_index(drop=True)


def top_correlations(
    df: pd.DataFrame,
    *,
    method: str = "pearson",
    top_k: int | None = None,
    max_columns: int = _MAX_COLUMNS,
) -> pd.DataFrame:
    """Rank the strongest pairwise numeric relationships by absolute correlation.

    Numeric-only, bounded to the first ``max_columns`` columns. ``method`` is one
    of pearson/spearman/kendall (unknown falls back to pearson); +/- inf are
    masked to NaN and correlation uses pairwise deletion (``min_periods=2``).
    Self-correlations and mirrored duplicate pairs are excluded, and pairs whose
    correlation is undefined (fewer than two overlapping observations) are
    skipped. ``n`` is the pairwise non-null observation count per pair. Returns an
    empty table with the expected columns when fewer than two numeric columns are
    present. Sorted by ``abs_correlation`` descending, then ``feature_x``,
    ``feature_y``; ``correlation``/``abs_correlation`` rounded to 6 decimals.
    ``top_k`` (when given) caps the number of rows. Never mutates ``df``.
    """
    safe_method = method if method in _CORRELATION_METHODS else "pearson"
    numeric = _bounded_finite_numeric(df, max_columns)
    if numeric.shape[1] < 2:
        return pd.DataFrame(columns=_TOP_CORR_COLUMNS)

    corr = numeric.corr(method=safe_method, min_periods=2)
    columns = list(corr.columns)
    records: list[dict[str, object]] = []
    for i in range(len(columns)):
        for j in range(i + 1, len(columns)):
            feature_x, feature_y = columns[i], columns[j]
            value = corr.iat[i, j]
            if pd.isna(value):
                continue
            pair_n = int(numeric[[feature_x, feature_y]].dropna(axis=0, how="any").shape[0])
            correlation = round(float(value), 6)
            records.append(
                {
                    "feature_x": feature_x,
                    "feature_y": feature_y,
                    "correlation": correlation,
                    "abs_correlation": round(abs(correlation), 6),
                    "method": safe_method,
                    "n": pair_n,
                }
            )
    if not records:
        return pd.DataFrame(columns=_TOP_CORR_COLUMNS)

    result = (
        pd.DataFrame(records, columns=_TOP_CORR_COLUMNS)
        .sort_values(
            ["abs_correlation", "feature_x", "feature_y"],
            ascending=[False, True, True],
            kind="stable",
        )
        .reset_index(drop=True)
    )
    if top_k is not None:
        result = result.head(max(0, int(top_k))).reset_index(drop=True)
    return result


def _pair_association(
    pair: pd.DataFrame,
    feature_x: str,
    feature_y: str,
    *,
    max_categories: int,
    scipy_stats: Any,
    include_p_values: bool,
) -> dict[str, object]:
    """Compute one categorical pair's Cramér's V record (see ``categorical_associations``)."""
    flags: list[str] = []
    n = int(pair.shape[0])
    capped_x, capped_x_flag = _cap_categories(pair[feature_x], max_categories)
    capped_y, capped_y_flag = _cap_categories(pair[feature_y], max_categories)
    if capped_x_flag or capped_y_flag:
        flags.append("high_cardinality_capped")

    if n < 1 or capped_x.nunique(dropna=True) < 2 or capped_y.nunique(dropna=True) < 2:
        flags.append("insufficient_categories")
        return {
            "feature_x": feature_x,
            "feature_y": feature_y,
            "cramers_v": None,
            "chi2": None,
            "dof": None,
            "n": n,
            "p_value": None,
            "warning": ";".join(flags),
        }

    observed = pd.crosstab(capped_x, capped_y).to_numpy(dtype=float)
    total = observed.sum()
    expected = observed.sum(axis=1, keepdims=True) @ observed.sum(axis=0, keepdims=True) / total
    with np.errstate(divide="ignore", invalid="ignore"):
        terms = np.where(expected > 0, (observed - expected) ** 2 / expected, 0.0)
    chi2 = float(terms.sum())
    rows, cols = observed.shape
    dof = int((rows - 1) * (cols - 1))
    denominator = n * min(rows - 1, cols - 1)
    cramers_v = float(np.sqrt(chi2 / denominator)) if denominator > 0 else 0.0
    if bool((expected < _MIN_EXPECTED_COUNT).any()):
        flags.append("sparse_expected_counts")

    p_value: float | None = None
    if include_p_values:
        if scipy_stats is not None and dof > 0:
            p_value = float(scipy_stats.chi2.sf(chi2, dof))
        elif scipy_stats is None:
            flags.append("scipy_unavailable")

    return {
        "feature_x": feature_x,
        "feature_y": feature_y,
        "cramers_v": round(cramers_v, 6),
        "chi2": round(chi2, 6),
        "dof": dof,
        "n": n,
        "p_value": (round(p_value, 6) if p_value is not None and np.isfinite(p_value) else None),
        "warning": ";".join(flags),
    }


def categorical_associations(
    df: pd.DataFrame,
    *,
    max_columns: int = _MAX_COLUMNS,
    max_categories: int = _MAX_COLUMNS,
    include_p_values: bool = True,
) -> pd.DataFrame:
    """Pairwise categorical association strength via dependency-free Cramér's V.

    Categorical-like columns only (object/string/category/bool); numeric and
    datetime columns are ignored. Bounded to the first ``max_columns`` columns.
    For each unordered pair, rows missing either value are dropped, high-
    cardinality values are capped to the top ``max_categories`` (rest bucketed as
    ``__other__``), and a contingency table yields the Pearson chi-square
    statistic, degrees of freedom ``(r-1)(c-1)``, and Cramér's V
    ``sqrt(chi2 / (n * min(r-1, c-1)))`` — all computed with pandas/numpy only.
    The chi-square p-value is filled only when scipy is importable *and*
    ``include_p_values`` is True (via the optional-scipy guard); otherwise it is
    None and ``scipy_unavailable`` is flagged. Returns an empty table with the
    expected columns when fewer than two categorical columns are present. Sorted
    by ``cramers_v`` descending, then ``feature_x``, ``feature_y``. Never mutates
    ``df``; never raises; never requires scipy.
    """
    columns = _categorical_like_columns(df)[: max(0, max_columns)]
    if len(columns) < 2:
        return pd.DataFrame(columns=_CATEGORICAL_ASSOC_COLUMNS)

    scipy_stats = import_scipy_stats() if include_p_values else None
    records: list[dict[str, object]] = []
    for i in range(len(columns)):
        for j in range(i + 1, len(columns)):
            feature_x, feature_y = columns[i], columns[j]
            pair = df[[feature_x, feature_y]].dropna(axis=0, how="any")
            records.append(
                _pair_association(
                    pair,
                    feature_x,
                    feature_y,
                    max_categories=max_categories,
                    scipy_stats=scipy_stats,
                    include_p_values=include_p_values,
                )
            )

    if not records:
        return pd.DataFrame(columns=_CATEGORICAL_ASSOC_COLUMNS)
    return (
        pd.DataFrame(records, columns=_CATEGORICAL_ASSOC_COLUMNS)
        .sort_values(
            ["cramers_v", "feature_x", "feature_y"],
            ascending=[False, True, True],
            kind="stable",
            na_position="last",
        )
        .reset_index(drop=True)
    )


def grouped_numeric_by_category_summary(
    df: pd.DataFrame,
    *,
    category: str | None = None,
    max_numeric_columns: int = _MAX_COLUMNS,
    max_categories: int = 50,
) -> pd.DataFrame:
    """Tidy numeric summaries grouped by one categorical column (pandas/numpy only).

    Numeric columns supply the measures (bounded to the first
    ``max_numeric_columns``); categorical-like columns supply the grouping key.
    When ``category`` is None the first categorical-like column is used; when it
    is provided but absent or non-categorical an empty expected table is
    returned. Grouping values are capped to the top ``max_categories`` (rest
    bucketed as ``__other__``); +/- inf are treated as missing. Emits one long-
    form row per (category value, numeric column) with columns
    ``category_column, category_value, numeric_column, count, missing, mean,
    median, std, min, max``. Returns an empty expected table when there are no
    usable categorical or numeric columns. Never mutates ``df``; never requires
    scipy.
    """
    numeric_columns = df.select_dtypes(include="number").columns.tolist()[
        : max(0, max_numeric_columns)
    ]
    categorical_columns = _categorical_like_columns(df)

    if category is None:
        if not categorical_columns:
            return pd.DataFrame(columns=_GROUPED_SUMMARY_COLUMNS)
        category = categorical_columns[0]
    elif category not in categorical_columns:
        return pd.DataFrame(columns=_GROUPED_SUMMARY_COLUMNS)

    if not numeric_columns:
        return pd.DataFrame(columns=_GROUPED_SUMMARY_COLUMNS)

    capped_category, _ = _cap_categories(df[category], max_categories)
    work = df[numeric_columns].replace([np.inf, -np.inf], np.nan).copy()
    work["__category__"] = capped_category
    work = work.dropna(subset=["__category__"])

    records: list[dict[str, object]] = []
    for category_value, group in work.groupby("__category__", sort=True):
        for numeric_column in numeric_columns:
            series = group[numeric_column]
            records.append(
                {
                    "category_column": category,
                    "category_value": str(category_value),
                    "numeric_column": numeric_column,
                    "count": int(series.notna().sum()),
                    "missing": int(series.isna().sum()),
                    "mean": _round_or_none(series.mean()),
                    "median": _round_or_none(series.median()),
                    "std": _round_or_none(series.std()),
                    "min": _round_or_none(series.min()),
                    "max": _round_or_none(series.max()),
                }
            )

    if not records:
        return pd.DataFrame(columns=_GROUPED_SUMMARY_COLUMNS)
    return pd.DataFrame(records, columns=_GROUPED_SUMMARY_COLUMNS)


def _round_or_none(value: Any) -> float | None:
    """Round a finite scalar to 6 decimals; return None for NaN/None."""
    if value is None or pd.isna(value):
        return None
    return round(float(value), 6)
