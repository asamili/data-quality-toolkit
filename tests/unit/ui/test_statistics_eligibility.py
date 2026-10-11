"""Tests for the Statistics Lab categorical eligibility and render-bound policy (F2).

The policy module is the single owner of the accepted high-cardinality constants,
the semantic eligibility ladder, the bounded category-label summary, and the
deterministic browser table preview. These tests pin the classification boundaries
(including the boundaries that must *not* move), prove that a pathological label
collection is never joined in full, and prove that the preview bound never mutates
or reorders the result it previews.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from typing import Any, cast

import numpy as np
import pandas as pd

from data_quality_toolkit.adapters.ui.services import statistics_eligibility as policy


def _levels_df(levels: int, *, repeats: int = 4, column: str = "cat") -> pd.DataFrame:
    """A column with exactly *levels* distinct values, each repeated *repeats* times."""
    values = [f"level_{index:05d}" for index in range(levels) for _ in range(repeats)]
    return pd.DataFrame({column: values})


def _near_unique_df(levels: int, *, column: str = "cat") -> pd.DataFrame:
    """A column whose every row is a distinct value (unique ratio 1.0)."""
    return pd.DataFrame({column: [f"id_{index:06d}" for index in range(levels)]})


# ── accepted policy constants ─────────────────────────────────────────────────


def test_accepted_policy_constants() -> None:
    assert policy.STATS_CATEGORICAL_MAX_LEVELS == 50
    assert policy.STATS_IDENTIFIER_LIKE_RATIO == 0.9
    assert policy.STATS_IDENTIFIER_LIKE_MIN_LEVELS == 50
    assert policy.STATS_LABEL_PREVIEW_MAX == 10
    assert policy.STATS_TABLE_PREVIEW_MAX_ROWS == 500
    assert policy.GOF_CUSTOM_PROPORTION_MAX_CATEGORIES == 40


def test_identifier_like_ratio_reuses_the_shared_constant() -> None:
    from data_quality_toolkit.shared.constants import DEFAULT_HIGH_CARDINALITY_THRESHOLD

    assert policy.STATS_IDENTIFIER_LIKE_RATIO == DEFAULT_HIGH_CARDINALITY_THRESHOLD


# ── categorical eligibility ladder ────────────────────────────────────────────


def test_two_levels_are_eligible() -> None:
    verdict = policy.classify_categorical_column(_levels_df(2), "cat")
    assert verdict.status == policy.ELIGIBLE
    assert verdict.eligible
    assert verdict.level_count == 2
    assert verdict.reason == ""


def test_forty_nine_levels_are_eligible() -> None:
    verdict = policy.classify_categorical_column(_levels_df(49), "cat")
    assert verdict.status == policy.ELIGIBLE
    assert verdict.level_count == 49


def test_fifty_levels_are_eligible() -> None:
    verdict = policy.classify_categorical_column(_levels_df(50), "cat")
    assert verdict.status == policy.ELIGIBLE
    assert verdict.level_count == 50


def test_fifty_one_levels_below_the_identifier_ratio_are_too_many_levels() -> None:
    frame = _levels_df(51, repeats=4)
    verdict = policy.classify_categorical_column(frame, "cat")
    assert verdict.level_count / verdict.valid_rows < policy.STATS_IDENTIFIER_LIKE_RATIO
    assert verdict.status == policy.TOO_MANY_LEVELS
    assert not verdict.eligible
    assert "more than 50 distinct values" in verdict.reason


def test_near_unique_wide_column_is_identifier_like() -> None:
    verdict = policy.classify_categorical_column(_near_unique_df(74_111), "cat")
    assert verdict.level_count == 74_111
    assert verdict.level_count / verdict.valid_rows >= policy.STATS_IDENTIFIER_LIKE_RATIO
    assert verdict.status == policy.IDENTIFIER_LIKE
    assert "identifier-like" in verdict.reason


def test_identifier_like_needs_the_minimum_level_count() -> None:
    """Three rows with three distinct values must never be called identifier-like."""
    verdict = policy.classify_categorical_column(pd.DataFrame({"cat": ["a", "b", "c"]}), "cat")
    assert verdict.level_count == 3
    assert verdict.valid_rows == 3
    assert verdict.status == policy.ELIGIBLE


def test_identifier_like_boundary_at_the_minimum_level_count() -> None:
    at_minimum = policy.classify_categorical_column(_near_unique_df(50), "cat")
    below_minimum = policy.classify_categorical_column(_near_unique_df(49), "cat")
    assert at_minimum.status == policy.IDENTIFIER_LIKE
    assert below_minimum.status == policy.ELIGIBLE


def test_empty_column_classification() -> None:
    frame = pd.DataFrame({"cat": [None, np.nan, pd.NA]})
    verdict = policy.classify_categorical_column(frame, "cat")
    assert verdict.status == policy.EMPTY
    assert verdict.valid_rows == 0
    assert "no valid values" in verdict.reason


def test_constant_column_classification() -> None:
    verdict = policy.classify_categorical_column(pd.DataFrame({"cat": ["a"] * 6}), "cat")
    assert verdict.status == policy.CONSTANT
    assert verdict.level_count == 1
    assert "one distinct value" in verdict.reason


def test_non_finite_numbers_are_not_counted_as_levels() -> None:
    frame = pd.DataFrame({"cat": [1.0, 2.0, np.inf, -np.inf]})
    verdict = policy.classify_categorical_column(frame, "cat")
    assert verdict.level_count == 2
    assert verdict.valid_rows == 2


def test_missing_column_is_not_eligible() -> None:
    verdict = policy.classify_categorical_column(pd.DataFrame({"cat": ["a", "b"]}), "absent")
    assert verdict.status == policy.UNSUPPORTED
    assert not verdict.eligible


def test_uncountable_values_are_not_eligible() -> None:
    frame = pd.DataFrame({"cat": pd.Series([[1], [2], [1]], dtype=object)})
    verdict = policy.classify_categorical_column(frame, "cat")
    assert verdict.status == policy.UNSUPPORTED
    assert not verdict.eligible


# ── binary outcome eligibility ────────────────────────────────────────────────


def test_binary_eligible_at_exactly_two_levels() -> None:
    verdict = policy.classify_binary_outcome_column(_levels_df(2), "cat")
    assert verdict.status == policy.ELIGIBLE
    assert verdict.eligible


def test_binary_selector_excludes_one_three_and_fifty_one_level_fields() -> None:
    frame = pd.DataFrame(
        {
            "constant": ["a"] * 204,
            "binary": ["yes", "no"] * 102,
            "three": ["a", "b", "c"] * 68,
            "wide": [f"level_{index % 51:05d}" for index in range(204)],
        }
    )
    classifications = policy.binary_outcome_candidates(frame)
    assert policy.eligible_columns(classifications) == ["binary"]
    by_column = {item.column: item for item in classifications}
    assert by_column["constant"].status == policy.CONSTANT
    assert by_column["three"].status == policy.NOT_BINARY
    assert by_column["wide"].status == policy.TOO_MANY_LEVELS


def test_non_binary_reason_is_a_bounded_count_statement() -> None:
    verdict = policy.classify_binary_outcome_column(_levels_df(3), "cat")
    assert verdict.status == policy.NOT_BINARY
    assert verdict.reason == "This field contains 3 distinct values and is not binary."


def test_eligible_categorical_selection_keeps_column_order() -> None:
    frame = pd.DataFrame(
        {
            "wide": [f"id_{index:05d}" for index in range(204)],
            "binary": ["yes", "no"] * 102,
            "three": ["a", "b", "c"] * 68,
        }
    )
    assert policy.eligible_columns(policy.categorical_candidates(frame)) == ["binary", "three"]


def test_exclusion_summary_is_grouped_and_bounded() -> None:
    frame = pd.DataFrame({f"const_{index}": ["a"] * 3 for index in range(15)})
    summary = policy.exclusion_summary(policy.categorical_candidates(frame))
    assert "only one level" in summary
    assert "(+5 more)" in summary
    assert summary.count("const_") == policy.STATS_LABEL_PREVIEW_MAX


def test_exclusion_summary_is_empty_when_nothing_was_excluded() -> None:
    frame = pd.DataFrame({"binary": ["yes", "no"] * 5})
    assert policy.exclusion_summary(policy.categorical_candidates(frame)) == ""


# ── cheap pre-allocation ceiling ──────────────────────────────────────────────


def test_exceeds_level_ceiling_reports_only_above_the_ceiling() -> None:
    assert policy.exceeds_level_ceiling(_levels_df(50)["cat"]) is None
    assert policy.exceeds_level_ceiling(_levels_df(51)["cat"]) == 51
    assert policy.exceeds_level_ceiling(_near_unique_df(74_111)["cat"]) == 74_111


def test_exceeds_level_ceiling_accepts_a_plain_sequence() -> None:
    assert policy.exceeds_level_ceiling(["a", "b", "a"]) is None
    assert policy.exceeds_level_ceiling([f"v{index}" for index in range(51)]) == 51


# ── bounded label summary ─────────────────────────────────────────────────────


def _labels(count: int) -> list[str]:
    return [f"label_{index:05d} [str]" for index in range(count)]


def test_label_summary_lists_every_label_at_the_preview_bound() -> None:
    summary = policy.summarize_labels(_labels(10))
    assert summary.count(",") == 9
    assert "more)" not in summary
    assert "label_00009 [str]" in summary


def test_label_summary_truncates_just_above_the_preview_bound() -> None:
    summary = policy.summarize_labels(_labels(11))
    assert summary.count(",") == 9
    assert summary.endswith("(+1 more)")
    assert "label_00010" not in summary


def test_label_summary_truncates_at_the_categorical_ceiling() -> None:
    summary = policy.summarize_labels(_labels(50))
    assert summary.count(",") == 9
    assert summary.endswith("(+40 more)")


def test_label_summary_is_count_only_above_the_categorical_ceiling() -> None:
    summary = policy.summarize_labels(_labels(51))
    assert summary == "51 distinct values (labels not listed)"


def test_label_summary_for_the_reproduced_pathological_cardinality() -> None:
    summary = policy.summarize_labels(_labels(74_111))
    assert summary == "74,111 distinct values (labels not listed)"
    assert "label_" not in summary
    assert len(summary) < 80


class _Exploding:
    """A label collection that reports its size but fails if anything reads it."""

    def __len__(self) -> int:
        return 74_111

    def __getitem__(self, item: Any) -> Any:  # pragma: no cover - must not run
        raise AssertionError("labels were read above the ceiling")

    def __iter__(self) -> Any:  # pragma: no cover - must not run
        raise AssertionError("labels were iterated above the ceiling")


def test_label_summary_never_reads_labels_above_the_ceiling() -> None:
    """A count-only summary must not touch the collection it is protecting against."""
    labels = cast(Sequence[Any], _Exploding())
    assert policy.summarize_labels(labels) == "74,111 distinct values (labels not listed)"
    assert (
        policy.summarize_labels(labels, total=74_111)
        == "74,111 distinct values (labels not listed)"
    )


def test_label_summary_handles_an_empty_or_absent_collection() -> None:
    assert policy.summarize_labels([]) == "none"
    assert policy.summarize_labels(None) == "none"
    assert policy.summarize_labels(None, total=3) == "3 distinct values (labels not listed)"


def test_label_summary_accepts_typed_non_string_labels() -> None:
    summary = policy.summarize_labels([1, True, 2.5])
    assert summary == "1, True, 2.5"


def test_describe_level_count_is_count_only() -> None:
    assert policy.describe_level_count(74_111) == "74,111 distinct values"


# ── bounded browser table preview ─────────────────────────────────────────────


def _numbered_frame(rows: int) -> pd.DataFrame:
    return pd.DataFrame(
        {"n": list(range(rows)), "label": [f"row_{index}" for index in range(rows)]}
    )


def test_preview_passes_through_below_the_bound() -> None:
    frame = _numbered_frame(499)
    preview = policy.bounded_table_preview(frame)
    assert not preview.truncated
    assert len(preview.frame) == 499
    assert preview.total_rows == 499
    assert preview.disclosure == ""


def test_preview_passes_through_exactly_at_the_bound() -> None:
    preview = policy.bounded_table_preview(_numbered_frame(500))
    assert not preview.truncated
    assert len(preview.frame) == 500
    assert preview.disclosure == ""


def test_preview_bounds_one_row_above_the_bound() -> None:
    preview = policy.bounded_table_preview(_numbered_frame(501))
    assert preview.truncated
    assert len(preview.frame) == 500
    assert preview.total_rows == 501
    assert preview.disclosure == (
        "Showing the first 500 of 501 rows. Download or save the analysis for the complete table."
    )


def test_preview_disclosure_reports_the_complete_row_count() -> None:
    preview = policy.bounded_table_preview(_numbered_frame(1_200))
    assert preview.disclosure == (
        "Showing the first 500 of 1,200 rows. Download or save the analysis for the "
        "complete table."
    )


def test_preview_preserves_the_leading_deterministic_order() -> None:
    frame = _numbered_frame(1_200)
    preview = policy.bounded_table_preview(frame)
    assert list(preview.frame["n"]) == list(range(500))
    assert list(preview.frame["label"])[:3] == ["row_0", "row_1", "row_2"]


def test_preview_does_not_mutate_the_input_frame() -> None:
    frame = _numbered_frame(1_200)
    before = frame.copy(deep=True)
    policy.bounded_table_preview(frame)
    pd.testing.assert_frame_equal(frame, before)
    assert len(frame) == 1_200


def test_custom_proportion_bound() -> None:
    assert policy.custom_proportions_available(40)
    assert not policy.custom_proportions_available(41)


# ── architecture ──────────────────────────────────────────────────────────────


def test_policy_module_is_framework_and_cycle_free() -> None:
    source = inspect.getsource(policy)
    assert "streamlit" not in source
    assert "adapters.ui.eda" not in source
    assert "services.statistics import" not in source
    assert "adapters.ui.pages" not in source
    assert "open(" not in source
    assert "Path" not in source
