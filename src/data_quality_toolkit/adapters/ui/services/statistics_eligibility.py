"""Statistics Lab categorical eligibility and rendering-bound policy (DQT 2.10.0 F2).

This module owns the permanent high-cardinality safety policy for the Statistics
Lab categorical workflows (goodness of fit, contingency, proportion, grouping):

* **L1 semantic eligibility** - which columns may enter a categorical statistical
  workflow at all, and a concise operator-facing reason when one may not.
* **L2 computation safety** - the hard dimensionality ceiling the Streamlit-free
  statistics service applies independently of any page selector.
* **L3 bounded browser rendering** - a deterministic result-table preview bound
  that never changes the complete result handed to a download or a workspace save.
* **L4 bounded category text** - one reusable bounded label summary so no caption,
  info state, warning, or service reason can enumerate an unbounded label set.

The ceiling is a product safety and interaction bound, not a statement of
statistical validity: a 50-level goodness-of-fit test or a 50x50 contingency table
may still be statistically inappropriate, and the existing assumption and
expected-count diagnostics remain authoritative. No statistical formula, expected
proportion, alpha, tolerance, or decision rule lives here.

Architecture: Streamlit-free, filesystem-free, session-state-free. It depends only
on the standard library, pandas, and the shared constants kernel; it imports no UI
page module, no ``adapters/ui/eda.py`` helper, and not ``services/statistics.py``
(which depends on it), so no import cycle is possible.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from data_quality_toolkit.shared.constants import DEFAULT_HIGH_CARDINALITY_THRESHOLD

# -- accepted policy constants ------------------------------------------------
#
# STATS_CATEGORICAL_MAX_LEVELS is a hard product safety and interaction ceiling
# for every categorical Statistics Lab pathway. It bounds how large a category or
# contingency structure may become before it is built, and it is deliberately not
# a claim that every admissible input is statistically appropriate.

STATS_CATEGORICAL_MAX_LEVELS = 50
STATS_IDENTIFIER_LIKE_RATIO = DEFAULT_HIGH_CARDINALITY_THRESHOLD
STATS_IDENTIFIER_LIKE_MIN_LEVELS = 50
STATS_LABEL_PREVIEW_MAX = 10
STATS_TABLE_PREVIEW_MAX_ROWS = 500
GOF_CUSTOM_PROPORTION_MAX_CATEGORIES = 40

# -- eligibility classifications ----------------------------------------------

ELIGIBLE = "eligible"
EMPTY = "empty"
CONSTANT = "constant"
TOO_MANY_LEVELS = "too_many_levels"
IDENTIFIER_LIKE = "identifier_like"
NOT_BINARY = "not_binary"
UNSUPPORTED = "unsupported"

CLASSIFICATIONS = (
    ELIGIBLE,
    EMPTY,
    CONSTANT,
    TOO_MANY_LEVELS,
    IDENTIFIER_LIKE,
    NOT_BINARY,
    UNSUPPORTED,
)

_EMPTY_REASON = "This field has no valid values."
_CONSTANT_REASON = "This field has only one distinct value."
_IDENTIFIER_LIKE_REASON = (
    "This field has too many distinct values and appears identifier-like. Choose a "
    "categorical field with repeated levels."
)
_TOO_MANY_LEVELS_REASON = (
    f"This field has more than {STATS_CATEGORICAL_MAX_LEVELS} distinct values and is "
    "not available for this categorical analysis."
)
_UNSUPPORTED_REASON = "The values in this field cannot be compared as categories."
_MISSING_COLUMN_REASON = "This field is not present in the loaded dataset."

CUSTOM_PROPORTION_BOUND_REASON = (
    "Custom expected proportions are available for up to "
    f"{GOF_CUSTOM_PROPORTION_MAX_CATEGORIES} categories. Equal proportions can still be "
    "tested for this field."
)

# Short phrases used when several excluded columns are summarized together.
_STATUS_SUMMARIES = {
    EMPTY: "no valid values",
    CONSTANT: "only one level",
    TOO_MANY_LEVELS: f"more than {STATS_CATEGORICAL_MAX_LEVELS} distinct levels",
    IDENTIFIER_LIKE: "effectively identifier-like",
    NOT_BINARY: "not binary (three or more levels)",
    UNSUPPORTED: "values not usable as categories",
}

_INFINITIES = (float("inf"), float("-inf"))


@dataclass(frozen=True)
class ColumnEligibility:
    """One column's categorical eligibility verdict.

    ``reason`` is bounded, operator-facing text and never enumerates category
    labels; it is an empty string for an eligible column.
    """

    column: str
    status: str
    level_count: int
    valid_rows: int
    reason: str

    @property
    def eligible(self) -> bool:
        """True when the column may enter the workflow it was classified for."""
        return self.status == ELIGIBLE


@dataclass(frozen=True)
class TablePreview:
    """A deterministic browser-rendering preview of a result table.

    ``frame`` is what a browser table widget should receive; ``total_rows`` is the
    complete row count that a download or workspace save must still receive.
    """

    frame: pd.DataFrame
    total_rows: int
    truncated: bool

    @property
    def disclosure(self) -> str:
        """Bounded disclosure line, or an empty string when nothing was withheld."""
        if not self.truncated:
            return ""
        return (
            f"Showing the first {len(self.frame):,} of {self.total_rows:,} rows. "
            "Download or save the analysis for the complete table."
        )


# -- level counting -----------------------------------------------------------


def _valid_values(series: pd.Series) -> pd.Series:
    """Drop missing values and non-finite numbers, preserving order and dtype."""
    cleaned = series.dropna()
    if cleaned.empty:
        return cleaned
    try:
        numeric = pd.to_numeric(cleaned, errors="coerce")
        infinite = numeric.isin(_INFINITIES)
    except (TypeError, ValueError):
        return cleaned
    if bool(infinite.any()):
        return cleaned[~infinite]
    return cleaned


def level_profile(values: pd.Series | Sequence[Any] | Iterable[Any]) -> tuple[int | None, int]:
    """Return ``(distinct valid level count, valid row count)`` for a column of values.

    The level count is ``None`` when the values cannot be compared as categories at
    all (an unhashable scalar, for example); the caller treats that as ineligible
    rather than guessing a count. Missing values and non-finite numbers are excluded,
    matching the statistics service's notion of a valid category value.
    """
    series = values if isinstance(values, pd.Series) else pd.Series(list(values), dtype=object)
    valid = _valid_values(series)
    valid_rows = int(len(valid))
    try:
        return int(valid.nunique(dropna=True)), valid_rows
    except TypeError:
        return None, valid_rows


def distinct_level_count(values: pd.Series | Sequence[Any] | Iterable[Any]) -> int | None:
    """Distinct valid (non-missing, finite) level count, or ``None`` when uncountable."""
    return level_profile(values)[0]


def exceeds_level_ceiling(
    values: pd.Series | Sequence[Any] | Iterable[Any],
    *,
    max_levels: int = STATS_CATEGORICAL_MAX_LEVELS,
) -> int | None:
    """Return the distinct level count when it exceeds *max_levels*, else ``None``.

    A cheap pre-allocation guard: it answers "is this input already too wide?"
    without building category labels, option objects, or any matrix.
    """
    levels = distinct_level_count(values)
    if levels is None or levels <= max_levels:
        return None
    return levels


# -- classification -----------------------------------------------------------


def _is_identifier_like(levels: int, valid_rows: int) -> bool:
    """Identifier-like only for wide columns whose values are near-unique.

    The minimum level count keeps a tiny all-unique dataset (3 rows, 3 values) from
    being described as identifier-like.
    """
    if levels < STATS_IDENTIFIER_LIKE_MIN_LEVELS or valid_rows <= 0:
        return False
    return bool(levels / valid_rows >= STATS_IDENTIFIER_LIKE_RATIO)


def _classify(
    column: str,
    levels: int | None,
    valid_rows: int,
    *,
    max_levels: int,
    binary: bool,
) -> ColumnEligibility:
    """Shared classification ladder for the categorical and binary contracts."""
    if levels is None:
        return ColumnEligibility(column, UNSUPPORTED, 0, valid_rows, _UNSUPPORTED_REASON)
    if valid_rows <= 0 or levels <= 0:
        return ColumnEligibility(column, EMPTY, levels, valid_rows, _EMPTY_REASON)
    if levels == 1:
        return ColumnEligibility(column, CONSTANT, levels, valid_rows, _CONSTANT_REASON)
    if _is_identifier_like(levels, valid_rows):
        return ColumnEligibility(
            column, IDENTIFIER_LIKE, levels, valid_rows, _IDENTIFIER_LIKE_REASON
        )
    if levels > max_levels:
        return ColumnEligibility(
            column, TOO_MANY_LEVELS, levels, valid_rows, _TOO_MANY_LEVELS_REASON
        )
    if binary and levels != 2:
        return ColumnEligibility(
            column,
            NOT_BINARY,
            levels,
            valid_rows,
            f"This field contains {levels:,} distinct values and is not binary.",
        )
    return ColumnEligibility(column, ELIGIBLE, levels, valid_rows, "")


def classify_categorical_column(
    df: pd.DataFrame,
    column: str,
    *,
    max_levels: int = STATS_CATEGORICAL_MAX_LEVELS,
) -> ColumnEligibility:
    """Classify one column for a categorical statistical workflow."""
    name = str(column)
    if column not in df.columns:
        return ColumnEligibility(name, UNSUPPORTED, 0, 0, _MISSING_COLUMN_REASON)
    levels, valid_rows = level_profile(df[column])
    return _classify(name, levels, valid_rows, max_levels=max_levels, binary=False)


def classify_binary_outcome_column(
    df: pd.DataFrame,
    column: str,
    *,
    max_levels: int = STATS_CATEGORICAL_MAX_LEVELS,
) -> ColumnEligibility:
    """Classify one column as a binary (exactly two valid levels) outcome."""
    name = str(column)
    if column not in df.columns:
        return ColumnEligibility(name, UNSUPPORTED, 0, 0, _MISSING_COLUMN_REASON)
    levels, valid_rows = level_profile(df[column])
    return _classify(name, levels, valid_rows, max_levels=max_levels, binary=True)


def categorical_candidates(
    df: pd.DataFrame, columns: Sequence[str] | None = None
) -> list[ColumnEligibility]:
    """Classify every candidate column for a categorical workflow, in column order."""
    names = [str(column) for column in df.columns.tolist()] if columns is None else list(columns)
    return [classify_categorical_column(df, name) for name in names]


def binary_outcome_candidates(
    df: pd.DataFrame, columns: Sequence[str] | None = None
) -> list[ColumnEligibility]:
    """Classify every candidate column as a binary outcome, in column order."""
    names = [str(column) for column in df.columns.tolist()] if columns is None else list(columns)
    return [classify_binary_outcome_column(df, name) for name in names]


def eligible_columns(classifications: Sequence[ColumnEligibility]) -> list[str]:
    """The column names of the eligible classifications, order preserved."""
    return [item.column for item in classifications if item.eligible]


def exclusion_summary(classifications: Sequence[ColumnEligibility]) -> str:
    """Bounded explanation of why the remaining columns were excluded.

    Groups excluded columns by reason and lists at most ``STATS_LABEL_PREVIEW_MAX``
    column names per reason, so a very wide dataset can never produce an unbounded
    explanation. Returns an empty string when nothing was excluded.
    """
    grouped: dict[str, list[str]] = {}
    for item in classifications:
        if item.eligible:
            continue
        grouped.setdefault(item.status, []).append(item.column)
    if not grouped:
        return ""
    parts = [
        f"{_STATUS_SUMMARIES.get(status, status)}: {summarize_labels(columns)}"
        for status, columns in sorted(grouped.items())
    ]
    return "Excluded columns - " + "; ".join(parts) + "."


# -- bounded category text ----------------------------------------------------


def summarize_labels(
    labels: Sequence[Any] | None,
    *,
    total: int | None = None,
    max_labels: int = STATS_LABEL_PREVIEW_MAX,
    max_enumerated: int = STATS_CATEGORICAL_MAX_LEVELS,
) -> str:
    """Bounded, deterministic summary of a category-label collection.

    Behaviour by size: at most ``max_labels`` labels are listed in full; between
    ``max_labels`` and ``max_enumerated`` the first ``max_labels`` are listed with a
    remainder count; above ``max_enumerated`` only a count is reported and no label
    is read at all. The bound is applied *before* any join, so the oversized text
    this helper exists to prevent is never constructed. Nothing is mutated.
    """
    known_total = int(total) if total is not None else (0 if labels is None else len(labels))
    if known_total <= 0:
        return "none"
    if known_total > max_enumerated or labels is None:
        return f"{known_total:,} distinct values (labels not listed)"
    shown = [str(label) for label in labels[:max_labels]]
    remainder = known_total - len(shown)
    if remainder <= 0:
        return ", ".join(shown)
    return f"{', '.join(shown)} (+{remainder:,} more)"


def describe_level_count(levels: int) -> str:
    """Bounded count-only description of a level count."""
    return f"{int(levels):,} distinct values"


# -- bounded browser rendering ------------------------------------------------


def bounded_table_preview(
    frame: pd.DataFrame, *, max_rows: int = STATS_TABLE_PREVIEW_MAX_ROWS
) -> TablePreview:
    """Bound what a browser table widget receives without altering *frame*.

    The preview keeps the result's existing deterministic order and takes the
    leading rows only: nothing is sampled, ranked, reordered, or written back. The
    caller must keep handing the complete ``frame`` to downloads and workspace saves.
    """
    total_rows = int(len(frame))
    if total_rows <= max_rows:
        return TablePreview(frame, total_rows, False)
    return TablePreview(frame.head(max_rows), total_rows, True)


def custom_proportions_available(
    level_count: int, *, max_categories: int = GOF_CUSTOM_PROPORTION_MAX_CATEGORIES
) -> bool:
    """True when per-category expected-proportion controls may be instantiated."""
    return int(level_count) <= int(max_categories)


__all__ = [
    "CLASSIFICATIONS",
    "CONSTANT",
    "CUSTOM_PROPORTION_BOUND_REASON",
    "ELIGIBLE",
    "EMPTY",
    "GOF_CUSTOM_PROPORTION_MAX_CATEGORIES",
    "IDENTIFIER_LIKE",
    "NOT_BINARY",
    "STATS_CATEGORICAL_MAX_LEVELS",
    "STATS_IDENTIFIER_LIKE_MIN_LEVELS",
    "STATS_IDENTIFIER_LIKE_RATIO",
    "STATS_LABEL_PREVIEW_MAX",
    "STATS_TABLE_PREVIEW_MAX_ROWS",
    "TOO_MANY_LEVELS",
    "UNSUPPORTED",
    "ColumnEligibility",
    "TablePreview",
    "binary_outcome_candidates",
    "bounded_table_preview",
    "categorical_candidates",
    "classify_binary_outcome_column",
    "classify_categorical_column",
    "custom_proportions_available",
    "describe_level_count",
    "distinct_level_count",
    "eligible_columns",
    "exceeds_level_ceiling",
    "exclusion_summary",
    "level_profile",
    "summarize_labels",
]
