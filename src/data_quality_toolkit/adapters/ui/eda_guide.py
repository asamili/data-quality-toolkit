"""Deterministic Smart Guide recommendations for EDA Explorer."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from data_quality_toolkit.adapters.ui.eda import (
    DATETIME_PARSE_THRESHOLD,
    DEFAULT_HIGH_CARDINALITY_THRESHOLD,
    GUIDE_MAX_RECOMMENDATIONS,
    MAX_CORRELATION_COLUMNS,
    MAX_PLOT_ROWS,
    MAX_SUMMARY_COLUMNS,
    MAX_TOP_CATEGORIES,
    NEAR_UNIQUE_RATIO,
    PARETO_MAX_CATEGORIES,
    QQ_MIN_OBSERVATIONS,
    _correlation_matrix,
    _datetime_candidate_columns,
    _missingness_summary,
    _skew_kurtosis_summary,
)

_MISSINGNESS_WARNING_PCT = 20.0
_STRONG_CORRELATION_THRESHOLD = 0.8
_SKEWNESS_THRESHOLD = 2.0
_DOMINANT_CATEGORY_SHARE = 0.90
_MAX_COLUMNS_IN_MESSAGE = 4

# EDA tab labels a recommendation may point at (mirrors the page tab order).
EDA_TARGET_TABS = ("Overview", "Columns", "Relationships", "Time", "Advanced")

# Shared caveats. Every visual recommendation carries one so an exploratory
# chart is never read as a confirmed finding.
_CAVEAT_SHAPE = (
    "Shape diagnostics are visual only — they describe this sample and are not "
    "a normality test. Use Statistics Lab for formal testing."
)
_CAVEAT_CONCENTRATION = (
    "Concentration shows where rows pile up; it does not mean those categories "
    "are the important ones."
)
_CAVEAT_MISSINGNESS = (
    "Columns going missing together may share a process, but this does not "
    "determine whether data are MCAR, MAR or MNAR."
)
_CAVEAT_CORRELATION = (
    "Correlation describes co-movement in the analyzed rows only; it does not "
    "establish causation and carries no significance claim."
)
_CAVEAT_GROUPS = (
    "Group differences seen here are descriptive. Comparing groups formally "
    "belongs in Statistics Lab."
)
_CAVEAT_ASSOCIATION = (
    "Association strength describes how categories vary together in the "
    "analyzed data; it does not prove causation or statistical significance."
)
_CAVEAT_TIME = (
    "A trend over time reflects the rows present in each bucket; uneven "
    "coverage can create apparent movement."
)
_CAVEAT_IDENTIFIER = (
    "This column looks identifier-like. Charting it directly is rarely "
    "informative and can surface near-unique values."
)


@dataclass(frozen=True)
class EdaRecommendation:
    """A single deterministic EDA next-step recommendation."""

    severity: str
    title: str
    message: str
    target_tab: str
    columns: tuple[str, ...] = ()
    reason: str | None = None


def recommend_eda_actions(
    df: pd.DataFrame,
    *,
    max_recommendations: int = 8,
) -> list[EdaRecommendation]:
    """Return deterministic rules-based EDA recommendations for ``df``.

    The guide is intentionally local and defensive: it reads from the supplied
    DataFrame, catches per-rule data issues, and never mutates the input.
    """
    try:
        limit = max(0, int(max_recommendations))
    except (TypeError, ValueError):
        limit = 8
    if limit == 0 or not isinstance(df, pd.DataFrame) or df.shape[1] == 0:
        return []

    recommendations: list[EdaRecommendation] = []
    rules: tuple[Callable[[pd.DataFrame], Iterable[EdaRecommendation]], ...] = (
        _high_missingness_recommendations,
        _high_cardinality_recommendations,
        _strong_correlation_recommendations,
        _skewed_numeric_recommendations,
        _datetime_recommendations,
        _dominant_category_recommendations,
        _large_dataset_recommendations,
        _wide_numeric_recommendations,
    )
    for rule in rules:
        if len(recommendations) >= limit:
            break
        try:
            rule_recommendations = tuple(rule(df))
        except Exception:
            rule_recommendations = ()
        for recommendation in rule_recommendations:
            recommendations.append(recommendation)
            if len(recommendations) >= limit:
                break
    return recommendations[:limit]


def _high_missingness_recommendations(df: pd.DataFrame) -> list[EdaRecommendation]:
    summary = _missingness_summary(df)
    recommendations: list[EdaRecommendation] = []
    for row in summary.to_dict("records"):
        pct = _safe_float(row.get("missing_pct"))
        if pct is None or pct <= _MISSINGNESS_WARNING_PCT:
            continue
        column = str(row.get("column"))
        recommendations.append(
            EdaRecommendation(
                severity="warning",
                title="Review high missingness",
                message=(
                    f"{column} is {pct:.1f}% missing. Check whether missing values are "
                    "structural before imputing, filtering, or dropping records."
                ),
                target_tab="Overview",
                columns=(column,),
                reason=f"Missing share is above {_MISSINGNESS_WARNING_PCT:.0f}%.",
            )
        )
    return recommendations


def _high_cardinality_recommendations(df: pd.DataFrame) -> list[EdaRecommendation]:
    recommendations: list[EdaRecommendation] = []
    for column in df.columns[:MAX_SUMMARY_COLUMNS]:
        series = _series_for_column(df, column)
        if series is None or not _is_categorical_like(series):
            continue
        non_null = int(series.notna().sum())
        if non_null == 0:
            continue
        unique_count = _safe_unique_count(series)
        unique_ratio = unique_count / non_null if non_null else 0.0
        if unique_count <= MAX_TOP_CATEGORIES and unique_ratio <= float(
            DEFAULT_HIGH_CARDINALITY_THRESHOLD
        ):
            continue
        column_name = str(column)
        recommendations.append(
            EdaRecommendation(
                severity="info",
                title="Check high-cardinality categories",
                message=(
                    f"{column_name} has {unique_count:,} distinct non-missing values. Use "
                    "top-N views and any Other bucket cautiously so uncommon categories "
                    "are not hidden."
                ),
                target_tab="Columns",
                columns=(column_name,),
                reason=(
                    f"Unique ratio is {unique_ratio:.1%}; top-value views cap at "
                    f"{MAX_TOP_CATEGORIES} categories."
                ),
            )
        )
    return recommendations


def _strong_correlation_recommendations(df: pd.DataFrame) -> list[EdaRecommendation]:
    matrix = _correlation_matrix(df, max_columns=MAX_CORRELATION_COLUMNS, method="pearson")
    if matrix is None or matrix.empty:
        return []
    pairs: list[tuple[float, int, int, str, str, float]] = []
    for left_idx, left in enumerate(matrix.columns):
        for right_idx in range(left_idx + 1, len(matrix.columns)):
            right = matrix.columns[right_idx]
            value = _safe_float(matrix.iloc[left_idx, right_idx])
            if value is None or not np.isfinite(value):
                continue
            absolute = abs(value)
            if absolute >= _STRONG_CORRELATION_THRESHOLD:
                pairs.append((absolute, left_idx, right_idx, str(left), str(right), value))
    if not pairs:
        return []
    absolute, _left_idx, _right_idx, left, right, value = sorted(
        pairs, key=lambda item: (-item[0], item[1], item[2])
    )[0]
    direction = "positive" if value >= 0 else "negative"
    return [
        EdaRecommendation(
            severity="suggestion",
            title="Inspect a strong numeric relationship",
            message=(
                f"{left} and {right} have a strong {direction} Pearson correlation "
                f"({value:.2f}). Open Relationships to confirm the pattern and check "
                "for outliers or duplicated signals."
            ),
            target_tab="Relationships",
            columns=(left, right),
            reason=(
                f"Absolute correlation {absolute:.2f} is at least "
                f"{_STRONG_CORRELATION_THRESHOLD:.1f}."
            ),
        )
    ]


def _skewed_numeric_recommendations(df: pd.DataFrame) -> list[EdaRecommendation]:
    summary = _skew_kurtosis_summary(df)
    recommendations: list[EdaRecommendation] = []
    for row in summary.to_dict("records"):
        skewness = _safe_float(row.get("skewness"))
        if skewness is None or abs(skewness) <= _SKEWNESS_THRESHOLD:
            continue
        column = str(row.get("column"))
        finite = _finite_numeric_series(df, column)
        log_hint = (
            " Compare median/IQR and try log-scale exploration where useful."
            if finite is not None and not finite.empty and bool((finite > 0).all())
            else " Compare median/IQR before relying on mean-based summaries."
        )
        recommendations.append(
            EdaRecommendation(
                severity="info",
                title="Review skewed numeric distribution",
                message=f"{column} has skewness {skewness:.2f}.{log_hint}",
                target_tab="Columns",
                columns=(column,),
                reason=f"Absolute skewness is above {_SKEWNESS_THRESHOLD:.0f}.",
            )
        )
    return recommendations


def _datetime_recommendations(df: pd.DataFrame) -> list[EdaRecommendation]:
    columns = tuple(_datetime_candidate_columns(df))
    if not columns:
        return []
    display = _format_columns(columns)
    return [
        EdaRecommendation(
            severity="suggestion",
            title="Use the Time tab",
            message=(
                f"{display} look datetime-like. Open Time to review trends by day, "
                "week, or month before drawing conclusions from row order."
            ),
            target_tab="Time",
            columns=columns,
            reason=(
                "Datetime detection uses the existing "
                f"{DATETIME_PARSE_THRESHOLD * 100:.0f}% parse-confidence threshold."
            ),
        )
    ]


def _dominant_category_recommendations(df: pd.DataFrame) -> list[EdaRecommendation]:
    recommendations: list[EdaRecommendation] = []
    for column in df.columns[:MAX_SUMMARY_COLUMNS]:
        series = _series_for_column(df, column)
        if series is None or not (
            _is_categorical_like(series) or pd.api.types.is_bool_dtype(series)
        ):
            continue
        counts = _safe_value_counts(series)
        if counts.empty:
            continue
        total = int(counts.sum())
        if total == 0:
            continue
        top_share = float(counts.iloc[0]) / total
        if top_share <= _DOMINANT_CATEGORY_SHARE:
            continue
        column_name = str(column)
        recommendations.append(
            EdaRecommendation(
                severity="info",
                title="Review categorical imbalance",
                message=(
                    f"One value in {column_name} accounts for {top_share:.1%} of "
                    "non-missing rows. Check whether this imbalance is expected before "
                    "using the column for grouping or segmentation."
                ),
                target_tab="Columns",
                columns=(column_name,),
                reason=f"Dominant value share is above {_DOMINANT_CATEGORY_SHARE:.0%}.",
            )
        )
    return recommendations


def _large_dataset_recommendations(df: pd.DataFrame) -> list[EdaRecommendation]:
    row_count = int(len(df))
    if row_count <= MAX_PLOT_ROWS:
        return []
    return [
        EdaRecommendation(
            severity="info",
            title="Note deterministic chart sampling",
            message=(
                f"This dataset has {row_count:,} rows. Some EDA charts use deterministic "
                f"samples capped at {MAX_PLOT_ROWS:,} plotted rows to stay responsive."
            ),
            target_tab="Relationships",
            reason=f"Row count exceeds MAX_PLOT_ROWS ({MAX_PLOT_ROWS:,}).",
        )
    ]


def _wide_numeric_recommendations(df: pd.DataFrame) -> list[EdaRecommendation]:
    numeric_count = _numeric_column_count(df)
    if numeric_count <= MAX_CORRELATION_COLUMNS:
        return []
    return [
        EdaRecommendation(
            severity="info",
            title="Correlation heatmap is capped",
            message=(
                f"The dataset has {numeric_count:,} numeric columns. The Advanced "
                f"correlation heatmap is capped at the first {MAX_CORRELATION_COLUMNS} "
                "numeric columns."
            ),
            target_tab="Advanced",
            reason=(
                f"Numeric column count exceeds MAX_CORRELATION_COLUMNS "
                f"({MAX_CORRELATION_COLUMNS})."
            ),
        )
    ]


def _series_for_column(df: pd.DataFrame, column: object) -> pd.Series | None:
    try:
        value = df.loc[:, column]
    except Exception:
        return None
    if isinstance(value, pd.DataFrame):
        if value.shape[1] == 0:
            return None
        return value.iloc[:, 0]
    if isinstance(value, pd.Series):
        return value
    return None


def _is_categorical_like(series: pd.Series) -> bool:
    dtype = series.dtype
    return (
        pd.api.types.is_object_dtype(dtype)
        or pd.api.types.is_string_dtype(dtype)
        or isinstance(dtype, pd.CategoricalDtype)
    )


def _safe_unique_count(series: pd.Series) -> int:
    try:
        return int(series.nunique(dropna=True))
    except Exception:
        try:
            return int(series.dropna().astype("string").nunique(dropna=True))
        except Exception:
            return 0


def _safe_value_counts(series: pd.Series) -> pd.Series:
    try:
        return series.value_counts(dropna=True)
    except Exception:
        try:
            return series.dropna().astype("string").value_counts(dropna=True)
        except Exception:
            return pd.Series(dtype="int64")


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def _finite_numeric_series(df: pd.DataFrame, column: str) -> pd.Series | None:
    series = _series_for_column(df, column)
    if series is None:
        return None
    try:
        numeric = pd.to_numeric(series, errors="coerce")
    except Exception:
        return None
    numeric = numeric.replace([np.inf, -np.inf], np.nan).dropna()
    return numeric


def _numeric_column_count(df: pd.DataFrame) -> int:
    count = 0
    for column in df.columns:
        series = _series_for_column(df, column)
        if series is None or pd.api.types.is_bool_dtype(series):
            continue
        if pd.api.types.is_numeric_dtype(series):
            count += 1
    return count


def _format_columns(columns: tuple[str, ...]) -> str:
    visible = columns[:_MAX_COLUMNS_IN_MESSAGE]
    text = ", ".join(visible)
    remaining = len(columns) - len(visible)
    if remaining > 0:
        return f"{text}, and {remaining} more columns"
    return text


# --- Type-aware visual discovery guide (P2) -----------------------------------
#
# A second, complementary guide: where ``recommend_eda_actions`` warns about
# data problems, this one answers "given these column types, what can I look at
# next, and how should I read it?". Every entry is deterministic, capped, points
# at an existing EDA section, and carries a caveat so an exploratory chart is
# never presented as a conclusion. Nothing here selects or runs a statistical
# test, infers a target variable, or claims significance.


@dataclass(frozen=True)
class VisualRecommendation:
    """One deterministic, type-aware visual-exploration suggestion."""

    question: str
    visual: str
    target_tab: str
    reason: str
    caveat: str
    columns: tuple[str, ...] = ()
    available: bool = True


def recommend_visual_explorations(
    df: pd.DataFrame,
    *,
    max_recommendations: int = GUIDE_MAX_RECOMMENDATIONS,
) -> list[VisualRecommendation]:
    """Return deterministic, capped visual-discovery suggestions for ``df``.

    Suggestions are produced in a fixed rule order (univariate first, then
    missingness, then column-pair relationships) so the same DataFrame always
    yields the same list. Reads only the supplied frame; never mutates it and
    never raises.
    """
    try:
        limit = max(0, int(max_recommendations))
    except (TypeError, ValueError):
        limit = GUIDE_MAX_RECOMMENDATIONS
    limit = min(limit, GUIDE_MAX_RECOMMENDATIONS)
    if limit == 0 or not isinstance(df, pd.DataFrame) or df.shape[1] == 0:
        return []
    rules: tuple[Callable[[pd.DataFrame], Iterable[VisualRecommendation]], ...] = (
        _numeric_shape_visuals,
        _skewed_numeric_visuals,
        _categorical_concentration_visuals,
        _identifier_like_visuals,
        _missingness_structure_visuals,
        _numeric_pair_visuals,
        _numeric_categorical_visuals,
        _categorical_pair_visuals,
        _datetime_numeric_visuals,
        _datetime_categorical_visuals,
    )
    found: list[VisualRecommendation] = []
    for rule in rules:
        if len(found) >= limit:
            break
        try:
            produced = tuple(rule(df))
        except Exception:
            produced = ()
        for recommendation in produced:
            found.append(recommendation)
            if len(found) >= limit:
                break
    return found[:limit]


def _numeric_shape_visuals(df: pd.DataFrame) -> list[VisualRecommendation]:
    columns = _guide_numeric_columns(df)
    eligible = [column for column in columns if _qq_eligible(df, column)]
    if not eligible:
        return []
    column = eligible[0]
    return [
        VisualRecommendation(
            question=f"What shape does {column} have, and where do its values concentrate?",
            visual="Histogram, density, box plot, ECDF and a normal Q-Q diagnostic",
            target_tab="Columns",
            reason=(
                f"{column} is numeric with at least {QQ_MIN_OBSERVATIONS} usable finite values."
            ),
            caveat=_CAVEAT_SHAPE,
            columns=(column,),
        )
    ]


def _skewed_numeric_visuals(df: pd.DataFrame) -> list[VisualRecommendation]:
    summary = _skew_kurtosis_summary(df)
    for row in summary.to_dict("records"):
        skewness = _safe_float(row.get("skewness"))
        if skewness is None or skewness <= _SKEWNESS_THRESHOLD:
            continue
        column = str(row.get("column"))
        finite = _finite_numeric_series(df, column)
        if finite is None or finite.empty or not bool((finite > 0).all()):
            continue
        return [
            VisualRecommendation(
                question=f"Does a log-scaled view make the tail of {column} readable?",
                visual="Histogram with the log-scale display option",
                target_tab="Columns",
                reason=f"{column} is strictly positive with skewness {skewness:.2f}.",
                caveat=(
                    "A log scale changes how the same counts are displayed; it does "
                    "not transform or clean the underlying data."
                ),
                columns=(column,),
            )
        ]
    return []


def _categorical_concentration_visuals(df: pd.DataFrame) -> list[VisualRecommendation]:
    columns = [
        column for column in _guide_categorical_columns(df) if not _is_identifier_like(df, column)
    ]
    if not columns:
        return []
    column = columns[0]
    return [
        VisualRecommendation(
            question=f"How concentrated is {column}, and how few values cover most rows?",
            visual="Top-N bar chart and a Pareto (cumulative share) view",
            target_tab="Columns",
            reason=(
                f"{column} is categorical with a workable level count "
                f"(views cap at {PARETO_MAX_CATEGORIES} categories)."
            ),
            caveat=_CAVEAT_CONCENTRATION,
            columns=(column,),
        )
    ]


def _identifier_like_visuals(df: pd.DataFrame) -> list[VisualRecommendation]:
    flagged = tuple(
        column for column in _guide_categorical_columns(df) if _is_identifier_like(df, column)
    )
    if not flagged:
        return []
    return [
        VisualRecommendation(
            question=f"Should {_format_columns(flagged)} be charted as categories at all?",
            visual="No category chart — inspect uniqueness in the Overview summaries instead",
            target_tab="Overview",
            reason="Distinct values approach the row count, so category views are refused.",
            caveat=_CAVEAT_IDENTIFIER,
            columns=flagged,
            available=False,
        )
    ]


def _missingness_structure_visuals(df: pd.DataFrame) -> list[VisualRecommendation]:
    columns = _guide_missing_columns(df)
    if not columns:
        return []
    recommendations = [
        VisualRecommendation(
            question="Do missing values fall in a structural pattern or scatter at random?",
            visual="Anonymous missingness pattern map",
            target_tab="Overview",
            reason=f"{len(columns)} column(s) contain missing values.",
            caveat=(
                "The map shows present/missing state at anonymous row positions "
                "only — no source rows or cell values are displayed."
            ),
            columns=tuple(columns[:_MAX_COLUMNS_IN_MESSAGE]),
        )
    ]
    if len(columns) >= 2:
        recommendations.append(
            VisualRecommendation(
                question="Which columns tend to go missing together?",
                visual="Missingness association heatmap with ranked pairs",
                target_tab="Overview",
                reason="At least two columns have varying missingness.",
                caveat=_CAVEAT_MISSINGNESS,
                columns=tuple(columns[:_MAX_COLUMNS_IN_MESSAGE]),
            )
        )
    return recommendations


def _numeric_pair_visuals(df: pd.DataFrame) -> list[VisualRecommendation]:
    columns = _guide_numeric_columns(df)
    if len(columns) < 2:
        return []
    pair = (columns[0], columns[1])
    return [
        VisualRecommendation(
            question=f"How do {pair[0]} and {pair[1]} move together?",
            visual="Scatter plot, 2D binned density, and the correlation matrix with ranked pairs",
            target_tab="Relationships",
            reason=f"{len(columns)} numeric columns are available for pairwise comparison.",
            caveat=_CAVEAT_CORRELATION,
            columns=pair,
        )
    ]


def _numeric_categorical_visuals(df: pd.DataFrame) -> list[VisualRecommendation]:
    numeric = _guide_numeric_columns(df)
    categorical = [
        column for column in _guide_categorical_columns(df) if not _is_identifier_like(df, column)
    ]
    if not numeric or not categorical:
        return []
    return [
        VisualRecommendation(
            question=f"Does {numeric[0]} differ across the levels of {categorical[0]}?",
            visual="Numeric distribution by category (median, IQR and range per level)",
            target_tab="Relationships",
            reason="The dataset pairs a numeric column with a usable categorical column.",
            caveat=_CAVEAT_GROUPS,
            columns=(numeric[0], categorical[0]),
        )
    ]


def _categorical_pair_visuals(df: pd.DataFrame) -> list[VisualRecommendation]:
    columns = [
        column for column in _guide_categorical_columns(df) if not _is_identifier_like(df, column)
    ]
    if len(columns) < 2:
        return []
    pair = (columns[0], columns[1])
    return [
        VisualRecommendation(
            question=f"Do the categories of {pair[0]} and {pair[1]} vary together?",
            visual=(
                "Crosstab, normalized 100% stacked comparison, and the categorical "
                "association matrix"
            ),
            target_tab="Relationships",
            reason="At least two usable categorical columns are available.",
            caveat=_CAVEAT_ASSOCIATION,
            columns=pair,
        )
    ]


def _datetime_numeric_visuals(df: pd.DataFrame) -> list[VisualRecommendation]:
    datetimes = tuple(_datetime_candidate_columns(df))
    numeric = _guide_numeric_columns(df)
    if not datetimes or not numeric:
        return []
    return [
        VisualRecommendation(
            question=f"How does {numeric[0]} move over {datetimes[0]}?",
            visual="Datetime trend with day/week/month aggregation",
            target_tab="Relationships",
            reason="A confidently parsed datetime column pairs with a numeric column.",
            caveat=_CAVEAT_TIME,
            columns=(datetimes[0], numeric[0]),
        )
    ]


def _datetime_categorical_visuals(df: pd.DataFrame) -> list[VisualRecommendation]:
    datetimes = tuple(_datetime_candidate_columns(df))
    categorical = [
        column
        for column in _guide_categorical_columns(df)
        if column not in datetimes and not _is_identifier_like(df, column)
    ]
    if not datetimes or not categorical:
        return []
    return [
        VisualRecommendation(
            question=f"How does the mix of {categorical[0]} change over {datetimes[0]}?",
            visual="Category counts over time (capped to the most frequent categories)",
            target_tab="Relationships",
            reason="A confidently parsed datetime column pairs with a categorical column.",
            caveat=_CAVEAT_TIME,
            columns=(datetimes[0], categorical[0]),
        )
    ]


def _guide_numeric_columns(df: pd.DataFrame) -> list[str]:
    """Return bounded numeric column names in DataFrame order (booleans excluded)."""
    columns: list[str] = []
    for column in df.columns[:MAX_SUMMARY_COLUMNS]:
        series = _series_for_column(df, column)
        if series is None or pd.api.types.is_bool_dtype(series):
            continue
        if pd.api.types.is_numeric_dtype(series):
            columns.append(str(column))
    return columns


def _guide_categorical_columns(df: pd.DataFrame) -> list[str]:
    """Return bounded categorical-like column names in DataFrame order."""
    columns: list[str] = []
    for column in df.columns[:MAX_SUMMARY_COLUMNS]:
        series = _series_for_column(df, column)
        if series is None or not _is_categorical_like(series):
            continue
        columns.append(str(column))
    return columns


def _guide_missing_columns(df: pd.DataFrame) -> list[str]:
    """Return column names that contain missing values, ranked by missing share."""
    summary = _missingness_summary(df)
    return [
        str(row.get("column"))
        for row in summary.to_dict("records")
        if int(row.get("missing_count") or 0) > 0
    ]


def _is_identifier_like(df: pd.DataFrame, column: str) -> bool:
    """Return True when a categorical column is too close to unique to chart."""
    series = _series_for_column(df, column)
    if series is None:
        return False
    non_null = int(series.notna().sum())
    if non_null == 0:
        return False
    unique_count = _safe_unique_count(series)
    if unique_count <= MAX_TOP_CATEGORIES:
        return False
    return unique_count / non_null >= NEAR_UNIQUE_RATIO


def _qq_eligible(df: pd.DataFrame, column: str) -> bool:
    """Return True when a numeric column has enough varied values for a Q-Q view."""
    finite = _finite_numeric_series(df, column)
    if finite is None or len(finite) < QQ_MIN_OBSERVATIONS:
        return False
    return int(finite.nunique()) >= 2
