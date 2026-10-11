"""Tests for the proportion z-test wrappers in the Statistics Lab service.

The service stays streamlit-free and identifies outcome and group categories by
type-aware identity (runtime type plus native value), never by text: int ``1`` and
str ``"1"``, bool ``True`` and str ``"True"``, bool ``True`` and int ``1``, and
float ``1.0`` and int ``1`` stay distinct. Missing and non-finite (±inf) values are
excluded before category determination, and non-finite numeric group rows count only
as invalid rows. Computation routes through the public ``run_statistical_test`` seam
(``ONE_PROP_Z`` / ``TWO_PROP_Z``). Includes non-mocked kernel executions and the
structured scipy-unavailable degradation path.
"""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.services import statistics as svc

# ── shared ────────────────────────────────────────────────────────────────────


def _outcome_options(df: pd.DataFrame, column: str) -> list:
    options, error = svc.outcome_category_options(df, column)
    assert error is None
    return options


def _group_options(df: pd.DataFrame, column: str) -> list:
    options, error = svc.group_category_options(df, column)
    assert error is None
    return options


def test_service_stays_streamlit_free() -> None:
    assert "import streamlit" not in inspect.getsource(svc)


def test_category_option_helpers_are_type_safe() -> None:
    df = pd.DataFrame({"outcome": pd.Series([1, "1", 1], dtype=object), "grp": ["A", "B", "A"]})
    out = _outcome_options(df, "outcome")
    assert [o.label for o in out] == ["1 [int]", "1 [str]"]
    assert [o.value for o in out] == [1, "1"]
    assert svc.outcome_category_options(df, "missing") == ([], None)
    grp = _group_options(df, "grp")
    assert [o.label for o in grp] == ["A [str]", "B [str]"]


# ── ONE_PROP_Z ────────────────────────────────────────────────────────────────


def _one_prop_df(successes: int = 70, failures: int = 30) -> pd.DataFrame:
    return pd.DataFrame({"outcome": ["yes"] * successes + ["no"] * failures})


def test_one_prop_missing_column_invalid() -> None:
    result = svc.run_one_proportion_z_test(_one_prop_df(), "nope", "yes", null_proportion=0.5)
    assert result["status"] == "invalid_input"
    assert result["test_key"] == "ONE_PROP_Z"
    assert "not found" in str(result["reason"])


def test_one_prop_no_valid_rows_insufficient() -> None:
    df = pd.DataFrame({"outcome": [None, np.nan]})
    result = svc.run_one_proportion_z_test(df, "outcome", "yes", null_proportion=0.5)
    assert result["status"] == "insufficient_data"
    assert result["valid_rows"] == 0
    assert result["excluded_rows"] == 2


def test_one_prop_single_value_only_rejected() -> None:
    df = pd.DataFrame({"outcome": ["yes", "yes", "yes"]})
    result = svc.run_one_proportion_z_test(df, "outcome", "yes", null_proportion=0.5)
    assert result["status"] == "invalid_input"
    assert "exactly two distinct" in str(result["reason"])


def test_one_prop_more_than_two_values_not_collapsed() -> None:
    df = pd.DataFrame({"outcome": ["a", "b", "c", "a"]})
    result = svc.run_one_proportion_z_test(df, "outcome", "a", null_proportion=0.5)
    assert result["status"] == "invalid_input"
    assert "exactly two distinct" in str(result["reason"])


def test_one_prop_invalid_success_value() -> None:
    result = svc.run_one_proportion_z_test(_one_prop_df(), "outcome", "maybe", null_proportion=0.5)
    assert result["status"] == "invalid_input"
    assert "success value" in str(result["reason"])


@pytest.mark.parametrize("bad_null", [0.0, 1.0, -0.1, 1.5, np.nan, np.inf])
def test_one_prop_invalid_null_proportion(bad_null: float) -> None:
    result = svc.run_one_proportion_z_test(
        _one_prop_df(), "outcome", "yes", null_proportion=bad_null
    )
    assert result["status"] == "invalid_input"
    assert "null proportion" in str(result["reason"]).lower()


def test_one_prop_missing_and_non_finite_rows_excluded() -> None:
    df = pd.DataFrame({"outcome": [1.0, 0.0, 1.0, np.nan, np.inf, -np.inf]})
    # Success passed as the native float; str "1.0" would be a different typed identity.
    result = svc.run_one_proportion_z_test(df, "outcome", 1.0, null_proportion=0.5)
    assert result["total_rows"] == 6
    assert result["valid_rows"] == 3
    assert result["excluded_rows"] == 3
    assert result["success_count"] == 2
    assert result["failure_count"] == 1


def test_one_prop_boolean_binary_outcome() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame({"outcome": [True] * 8 + [False] * 2})
    result = svc.run_one_proportion_z_test(df, "outcome", True, null_proportion=0.5)
    assert result["status"] == "ok"
    assert result["success_count"] == 8
    assert result["observed_proportion"] == pytest.approx(0.8)


def test_one_prop_string_binary_outcome_counts_and_proportion() -> None:
    pytest.importorskip("scipy")
    result = svc.run_one_proportion_z_test(_one_prop_df(), "outcome", "yes", null_proportion=0.5)
    assert result["status"] == "ok"
    assert result["success_count"] == 70
    assert result["failure_count"] == 30
    assert result["observed_proportion"] == pytest.approx(0.7)
    assert result["observed_values"] == ["no [str]", "yes [str]"]


def test_one_prop_numeric_binary_outcome() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame({"outcome": [1, 1, 1, 0, 0]})
    result = svc.run_one_proportion_z_test(df, "outcome", 1, null_proportion=0.5)
    assert result["status"] == "ok"
    assert result["success_count"] == 3


def test_one_prop_success_through_real_public_api() -> None:
    pytest.importorskip("scipy")
    result = svc.run_one_proportion_z_test(_one_prop_df(), "outcome", "yes", null_proportion=0.5)
    assert result["status"] == "ok"
    assert result["test_key"] == "ONE_PROP_Z"
    assert result["method"] == "one_proportion_z"
    # phat=0.7, se=sqrt(0.5*0.5/100)=0.05 -> z=4.0
    assert result["statistic"] == pytest.approx(4.0)
    assert result["p_value"] < 0.05
    assert result["reject_null"] is True
    assert result["scipy_available"] is True


def test_one_prop_invalid_alternative_structured() -> None:
    result = svc.run_one_proportion_z_test(
        _one_prop_df(), "outcome", "yes", null_proportion=0.5, alternative="up"
    )
    assert result["status"] == "invalid_input"


def test_one_prop_invalid_alpha_structured() -> None:
    result = svc.run_one_proportion_z_test(
        _one_prop_df(), "outcome", "yes", null_proportion=0.5, alpha=1.5
    )
    assert result["status"] == "invalid_input"


def test_one_prop_scipy_unavailable_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    from data_quality_toolkit.domain.statistics import inference

    monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)
    result = svc.run_one_proportion_z_test(_one_prop_df(), "outcome", "yes", null_proportion=0.5)
    assert result["status"] == "unavailable"
    assert result["scipy_available"] is False
    assert result["success_count"] == 70
    assert result["valid_rows"] == 100


# ── ONE_PROP_Z type-collision ─────────────────────────────────────────────────


def test_one_prop_int_str_zero_are_three_typed_categories() -> None:
    df = pd.DataFrame({"outcome": pd.Series([1, "1", 0], dtype=object)})
    result = svc.run_one_proportion_z_test(df, "outcome", 1, null_proportion=0.5)
    assert result["status"] == "invalid_input"
    assert "exactly two distinct" in str(result["reason"])
    # int 1 and str "1" are not merged: three distinct typed categories.
    assert result["observed_values"] == ["0 [int]", "1 [int]", "1 [str]"]


def test_one_prop_bool_str_false_are_three_typed_categories() -> None:
    df = pd.DataFrame({"outcome": pd.Series([True, "True", False], dtype=object)})
    result = svc.run_one_proportion_z_test(df, "outcome", True, null_proportion=0.5)
    assert result["status"] == "invalid_input"
    assert "exactly two distinct" in str(result["reason"])
    assert result["observed_values"] == ["False [bool]", "True [bool]", "True [str]"]


def test_one_prop_bool_true_and_int_one_stay_distinct() -> None:
    df = pd.DataFrame({"outcome": pd.Series([True, 1, False], dtype=object)})
    result = svc.run_one_proportion_z_test(df, "outcome", True, null_proportion=0.5)
    assert result["status"] == "invalid_input"
    assert "exactly two distinct" in str(result["reason"])
    # True (bool) and 1 (int) are different categories, so three in total.
    assert result["observed_values"] == ["1 [int]", "False [bool]", "True [bool]"]


def test_one_prop_valid_mixed_type_binary_selects_by_identity() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame({"outcome": pd.Series([1, "1", 1, "1"], dtype=object)})
    options = _outcome_options(df, "outcome")
    assert [o.label for o in options] == ["1 [int]", "1 [str]"]
    # Selecting the int identity counts only the two int rows.
    as_int = svc.run_one_proportion_z_test(df, "outcome", 1, null_proportion=0.5)
    assert as_int["status"] == "ok"
    assert as_int["success_count"] == 2
    assert as_int["success_label"] == "1 [int]"
    # Selecting the str identity counts only the two str rows.
    as_str = svc.run_one_proportion_z_test(df, "outcome", "1", null_proportion=0.5)
    assert as_str["status"] == "ok"
    assert as_str["success_count"] == 2
    assert as_str["success_label"] == "1 [str]"


def test_one_prop_duplicate_occurrences_count_as_one_category() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame({"outcome": pd.Series([1, 1, 1, "1"], dtype=object)})
    options = _outcome_options(df, "outcome")
    # int 1 appears three times but is a single typed category.
    assert [o.label for o in options] == ["1 [int]", "1 [str]"]
    result = svc.run_one_proportion_z_test(df, "outcome", 1, null_proportion=0.5)
    assert result["status"] == "ok"
    assert result["success_count"] == 3


# ── TWO_PROP_Z ────────────────────────────────────────────────────────────────


def _two_prop_df() -> pd.DataFrame:
    """Two clean groups: A (n=30, 20 success), B (n=40, 10 success)."""
    outcome = ["yes"] * 20 + ["no"] * 10 + ["yes"] * 10 + ["no"] * 30
    group = ["A"] * 30 + ["B"] * 40
    return pd.DataFrame({"outcome": outcome, "grp": group})


def test_two_prop_missing_outcome_column_invalid() -> None:
    result = svc.run_two_proportion_z_test(_two_prop_df(), "nope", "yes", "grp", "A", "B")
    assert result["status"] == "invalid_input"
    assert "not found" in str(result["reason"])


def test_two_prop_missing_group_column_invalid() -> None:
    result = svc.run_two_proportion_z_test(_two_prop_df(), "outcome", "yes", "nope", "A", "B")
    assert result["status"] == "invalid_input"
    assert "not found" in str(result["reason"])


def test_two_prop_same_outcome_and_group_column_invalid() -> None:
    result = svc.run_two_proportion_z_test(_two_prop_df(), "outcome", "yes", "outcome", "A", "B")
    assert result["status"] == "invalid_input"
    assert "different" in str(result["reason"])


def test_two_prop_non_binary_outcome_rejected() -> None:
    df = _two_prop_df()
    df.loc[0, "outcome"] = "maybe"  # third category
    result = svc.run_two_proportion_z_test(df, "outcome", "yes", "grp", "A", "B")
    assert result["status"] == "invalid_input"
    assert "exactly two distinct" in str(result["reason"])


def test_two_prop_fewer_than_two_groups_rejected() -> None:
    df = pd.DataFrame({"outcome": ["yes", "no", "yes"], "grp": ["A", "A", "A"]})
    result = svc.run_two_proportion_z_test(df, "outcome", "yes", "grp", "A", "B")
    assert result["status"] == "invalid_input"


def test_two_prop_identical_group_selection_rejected() -> None:
    result = svc.run_two_proportion_z_test(_two_prop_df(), "outcome", "yes", "grp", "A", "A")
    assert result["status"] == "invalid_input"
    assert "different" in str(result["reason"])


def test_two_prop_unknown_group_rejected() -> None:
    result = svc.run_two_proportion_z_test(_two_prop_df(), "outcome", "yes", "grp", "A", "Z")
    assert result["status"] == "invalid_input"
    assert "unknown selected group" in str(result["reason"])


def test_two_prop_invalid_success_value_rejected() -> None:
    result = svc.run_two_proportion_z_test(_two_prop_df(), "outcome", "maybe", "grp", "A", "B")
    assert result["status"] == "invalid_input"
    assert "success value" in str(result["reason"])


def test_two_prop_partition_counts_missing_and_outside_groups() -> None:
    df = pd.DataFrame(
        {
            "outcome": [
                "yes",
                "yes",
                "no",  # A: n=3, succ=2
                "yes",
                "no",
                "no",
                "no",  # B: n=4, succ=1
                "yes",  # C: outside selected groups
                np.nan,  # A but outcome missing -> invalid
                "yes",  # group missing -> invalid
            ],
            "grp": ["A", "A", "A", "B", "B", "B", "B", "C", "A", None],
        }
    )
    result = svc.run_two_proportion_z_test(df, "outcome", "yes", "grp", "A", "B")
    assert result["total_rows"] == 10
    assert result["invalid_or_missing_rows"] == 2
    assert result["rows_outside_groups"] == 1
    assert result["n_a"] == 3
    assert result["n_b"] == 4
    assert result["successes_a"] == 2
    assert result["successes_b"] == 1
    # Partition invariant.
    assert (
        result["invalid_or_missing_rows"]
        + result["rows_outside_groups"]
        + result["n_a"]
        + result["n_b"]
        == result["total_rows"]
    )


def test_two_prop_success_through_real_public_api() -> None:
    pytest.importorskip("scipy")
    result = svc.run_two_proportion_z_test(_two_prop_df(), "outcome", "yes", "grp", "A", "B")
    assert result["status"] == "ok"
    assert result["test_key"] == "TWO_PROP_Z"
    assert result["method"] == "two_proportion_z"
    assert result["n_a"] == 30
    assert result["n_b"] == 40
    assert result["successes_a"] == 20
    assert result["successes_b"] == 10
    assert result["proportion_a"] == pytest.approx(20 / 30)
    assert result["proportion_b"] == pytest.approx(0.25)
    assert result["proportion_difference"] == pytest.approx(20 / 30 - 0.25)
    assert result["reject_null"] is True
    assert result["scipy_available"] is True


def test_two_prop_direction_is_first_minus_second() -> None:
    pytest.importorskip("scipy")
    forward = svc.run_two_proportion_z_test(_two_prop_df(), "outcome", "yes", "grp", "A", "B")
    reverse = svc.run_two_proportion_z_test(_two_prop_df(), "outcome", "yes", "grp", "B", "A")
    assert forward["proportion_difference"] == pytest.approx(-reverse["proportion_difference"])
    assert forward["statistic"] == pytest.approx(-reverse["statistic"])


def test_two_prop_one_group_with_no_valid_rows_insufficient() -> None:
    df = pd.DataFrame(
        {
            "outcome": ["yes", "no", "yes", np.nan, np.nan],
            "grp": ["A", "A", "B", "D", "D"],
        }
    )
    result = svc.run_two_proportion_z_test(df, "outcome", "yes", "grp", "A", "D")
    assert result["status"] == "insufficient_data"
    assert result["n_b"] == 0
    assert "D" in str(result["reason"])


def test_two_prop_single_group_zero_success_is_valid() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame(
        {"outcome": ["no", "no", "no", "yes", "yes"], "grp": ["A", "A", "A", "C", "C"]}
    )
    result = svc.run_two_proportion_z_test(df, "outcome", "yes", "grp", "A", "C")
    assert result["status"] == "ok"
    assert result["successes_a"] == 0
    assert result["proportion_a"] == pytest.approx(0.0)


def test_two_prop_both_groups_degenerate_structured_invalid() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame(
        {
            "outcome": ["no", "no", "no", "no", "yes", "yes"],
            "grp": ["A", "A", "B", "B", "C", "C"],
        }
    )
    result = svc.run_two_proportion_z_test(df, "outcome", "yes", "grp", "A", "B")
    assert result["status"] == "invalid_input"
    assert "standard error" in str(result["reason"])
    assert result["successes_a"] == 0
    assert result["successes_b"] == 0


def test_two_prop_invalid_alternative_structured() -> None:
    result = svc.run_two_proportion_z_test(
        _two_prop_df(), "outcome", "yes", "grp", "A", "B", alternative="up"
    )
    assert result["status"] == "invalid_input"


def test_two_prop_invalid_alpha_structured() -> None:
    result = svc.run_two_proportion_z_test(
        _two_prop_df(), "outcome", "yes", "grp", "A", "B", alpha=1.5
    )
    assert result["status"] == "invalid_input"


def test_two_prop_scipy_unavailable_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    from data_quality_toolkit.domain.statistics import inference

    monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)
    result = svc.run_two_proportion_z_test(_two_prop_df(), "outcome", "yes", "grp", "A", "B")
    assert result["status"] == "unavailable"
    assert result["scipy_available"] is False
    assert result["n_a"] == 30
    assert result["n_b"] == 40


# ── TWO_PROP_Z group type-collision ───────────────────────────────────────────


def test_two_prop_int_and_str_group_are_distinct() -> None:
    df = pd.DataFrame(
        {
            "outcome": ["yes", "no", "yes", "no", "yes"],
            "grp": pd.Series([1, 1, "1", "1", 2], dtype=object),
        }
    )
    options = _group_options(df, "grp")
    # int 1 and str "1" are separate selectable groups (disambiguated labels).
    assert [o.label for o in options] == ["1 [int]", "1 [str]", "2 [int]"]
    result = svc.run_two_proportion_z_test(df, "outcome", "yes", "grp", 1, "1")
    assert result["n_a"] == 2  # the two int-1 rows
    assert result["n_b"] == 2  # the two str-"1" rows
    assert result["successes_a"] == 1
    assert result["successes_b"] == 1
    assert result["rows_outside_groups"] == 1  # the int-2 row
    assert result["group_a_label"] == "1 [int]"
    assert result["group_b_label"] == "1 [str]"


def test_two_prop_bool_true_and_int_one_group_are_distinct() -> None:
    df = pd.DataFrame(
        {
            "outcome": ["yes", "no", "yes", "no"],
            "grp": pd.Series([True, True, 1, 1], dtype=object),
        }
    )
    options = _group_options(df, "grp")
    assert [o.label for o in options] == ["1 [int]", "True [bool]"]
    result = svc.run_two_proportion_z_test(df, "outcome", "yes", "grp", True, 1)
    assert result["n_a"] == 2  # the two bool-True rows
    assert result["n_b"] == 2  # the two int-1 rows


def test_two_prop_same_typed_group_identity_rejected_but_cross_type_allowed() -> None:
    df = pd.DataFrame(
        {
            "outcome": ["yes", "no", "yes", "no"],
            "grp": pd.Series([1, 1, "1", "1"], dtype=object),
        }
    )
    # int 1 vs int 1 -> same typed identity -> rejected.
    same = svc.run_two_proportion_z_test(df, "outcome", "yes", "grp", 1, 1)
    assert same["status"] == "invalid_input"
    assert "different" in str(same["reason"])
    # int 1 vs str "1" -> different typed identity -> not the "must be different" error.
    cross = svc.run_two_proportion_z_test(df, "outcome", "yes", "grp", 1, "1")
    assert "different" not in str(cross.get("reason") or "")
    assert cross["n_a"] == 2  # the two int-1 rows
    assert cross["n_b"] == 2  # the two str-"1" rows


# ── TWO_PROP_Z non-finite groups ──────────────────────────────────────────────


def _non_finite_group_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "outcome": ["yes", "no", "yes", "no", "yes", "no"],
            "grp": [1.0, 1.0, 2.0, 2.0, np.inf, -np.inf],
        }
    )


def test_two_prop_non_finite_groups_excluded_from_options() -> None:
    options = _group_options(_non_finite_group_df(), "grp")
    assert {o.value for o in options} == {1.0, 2.0}
    assert all(np.isfinite(o.value) for o in options)


def test_two_prop_positive_and_negative_inf_groups_count_as_invalid() -> None:
    result = svc.run_two_proportion_z_test(
        _non_finite_group_df(), "outcome", "yes", "grp", 1.0, 2.0
    )
    assert result["total_rows"] == 6
    assert result["invalid_or_missing_rows"] == 2  # +inf and -inf rows
    assert result["rows_outside_groups"] == 0
    assert result["n_a"] == 2
    assert result["n_b"] == 2
    # Partition invariant with non-finite rows accounted for as invalid.
    assert (
        result["invalid_or_missing_rows"]
        + result["rows_outside_groups"]
        + result["n_a"]
        + result["n_b"]
        == result["total_rows"]
    )


def test_two_prop_positive_inf_only_group_invalid() -> None:
    df = pd.DataFrame({"outcome": ["yes", "no", "yes", "no"], "grp": [1.0, 1.0, 2.0, np.inf]})
    result = svc.run_two_proportion_z_test(df, "outcome", "yes", "grp", 1.0, 2.0)
    assert result["invalid_or_missing_rows"] == 1
    assert result["rows_outside_groups"] == 0
    assert result["n_a"] == 2
    assert result["n_b"] == 1


def test_two_prop_negative_inf_only_group_invalid() -> None:
    df = pd.DataFrame({"outcome": ["yes", "no", "yes", "no"], "grp": [1.0, 1.0, 2.0, -np.inf]})
    result = svc.run_two_proportion_z_test(df, "outcome", "yes", "grp", 1.0, 2.0)
    assert result["invalid_or_missing_rows"] == 1
    assert result["n_a"] == 2
    assert result["n_b"] == 1


# ── R2 display-collision safety ───────────────────────────────────────────────


def _status_class(module_name: str) -> type:
    """A tiny hashable value class with a stable __str__ and a settable __module__."""

    class Status:
        def __init__(self, text: str) -> None:
            self._text = text

        def __str__(self) -> str:
            return self._text

        def __eq__(self, other: object) -> bool:
            return isinstance(other, Status) and self._text == other._text

        def __hash__(self) -> int:
            return hash((module_name, self._text))

    Status.__module__ = module_name
    return Status


def _ambiguous_class() -> type:
    """A class whose distinct instances share identical safe text."""

    class Ambiguous:
        def __init__(self, tag: str) -> None:
            self.tag = tag

        def __str__(self) -> str:
            return "same"

        def __eq__(self, other: object) -> bool:
            return isinstance(other, Ambiguous) and self.tag == other.tag

        def __hash__(self) -> int:
            return hash(("ambiguous", self.tag))

    return Ambiguous


def test_ordinary_scalar_labels_stay_concise() -> None:
    ints = _outcome_options(pd.DataFrame({"outcome": [1, 0]}), "outcome")
    assert [o.label for o in ints] == ["0 [int]", "1 [int]"]
    strs = _outcome_options(pd.DataFrame({"outcome": ["1", "0"]}), "outcome")
    assert {o.label for o in strs} == {"1 [str]", "0 [str]"}
    bools = _outcome_options(pd.DataFrame({"outcome": [True, False]}), "outcome")
    assert {o.label for o in bools} == {"True [bool]", "False [bool]"}
    mixed = _outcome_options(
        pd.DataFrame({"outcome": pd.Series([True, "True"], dtype=object)}), "outcome"
    )
    assert {o.label for o in mixed} == {"True [bool]", "True [str]"}


def test_outcome_different_modules_same_classname_disambiguated() -> None:
    status_a = _status_class("pkg_a.statuses")
    status_b = _status_class("pkg_b.statuses")
    a = status_a("Open")
    b = status_b("Open")
    df = pd.DataFrame({"outcome": pd.Series([a, a, b, b], dtype=object)})
    options = _outcome_options(df, "outcome")
    assert len(options) == 2
    labels = [o.label for o in options]
    assert labels[0] != labels[1]
    joined = " ".join(labels)
    assert "pkg_a.statuses" in joined
    assert "pkg_b.statuses" in joined
    assert "0x" not in joined  # no memory address leaks into labels
    assert {o.value for o in options} == {a, b}
    # Selecting one module's value counts only its rows and labels it distinctly.
    result = svc.run_one_proportion_z_test(df, "outcome", a, null_proportion=0.5)
    assert result["success_count"] == 2
    assert "pkg_a.statuses" in result["success_label"]


def test_outcome_same_type_same_text_unequal_values_rejected() -> None:
    ambiguous = _ambiguous_class()
    x = ambiguous("x")
    y = ambiguous("y")
    df = pd.DataFrame({"outcome": pd.Series([x, y], dtype=object)})
    options, error = svc.outcome_category_options(df, "outcome")
    assert options == []
    assert error is not None
    assert "unambiguously" in error
    assert "0x" not in error and "object at" not in error.lower()
    # The runner-facing service rejects without executing the test.
    result = svc.run_one_proportion_z_test(df, "outcome", x, null_proportion=0.5)
    assert result["status"] == "invalid_input"
    assert result["statistic"] is None
    assert "0x" not in str(result["reason"])


def test_outcome_opaque_object_repr_rejected() -> None:
    df = pd.DataFrame({"outcome": pd.Series([object(), "ok"], dtype=object)})
    options, error = svc.outcome_category_options(df, "outcome")
    assert options == []
    assert error is not None
    assert "0x" not in error
    assert "object at" not in error.lower()
    result = svc.run_one_proportion_z_test(df, "outcome", "ok", null_proportion=0.5)
    assert result["status"] == "invalid_input"
    for value in (result.get("reason"), result.get("success_label")):
        assert "0x" not in str(value)
        assert "object at" not in str(value).lower()


@pytest.mark.parametrize("bad", ["line\nbreak", "tab\tstop", "x" * 250])
def test_outcome_unsafe_text_rejected(bad: str) -> None:
    df = pd.DataFrame({"outcome": pd.Series([bad, "ok"], dtype=object)})
    options, error = svc.outcome_category_options(df, "outcome")
    assert options == []
    assert error is not None
    # The raw unsafe value never leaks into the message and the message stays bounded.
    assert "\n" not in error
    assert "\t" not in error
    assert len(error) < 200


def test_two_prop_module_qualified_group_selection() -> None:
    pytest.importorskip("scipy")
    status_a = _status_class("pkg_a.groups")
    status_b = _status_class("pkg_b.groups")
    a = status_a("G")
    b = status_b("G")
    df = pd.DataFrame(
        {
            "outcome": ["yes", "yes", "yes", "no"],
            "grp": pd.Series([a, a, b, b], dtype=object),
        }
    )
    options = _group_options(df, "grp")
    labels = [o.label for o in options]
    assert labels[0] != labels[1]
    joined = " ".join(labels)
    assert "pkg_a.groups" in joined and "pkg_b.groups" in joined
    forward = svc.run_two_proportion_z_test(df, "outcome", "yes", "grp", a, b)
    assert forward["n_a"] == 2 and forward["n_b"] == 2
    assert forward["successes_a"] == 2 and forward["successes_b"] == 1
    assert "pkg_a.groups" in forward["group_a_label"]
    assert "pkg_b.groups" in forward["group_b_label"]
    reverse = svc.run_two_proportion_z_test(df, "outcome", "yes", "grp", b, a)
    assert forward["proportion_difference"] == pytest.approx(-reverse["proportion_difference"])


# ── F2: bounded service-side reasons for non-binary and wide inputs ──────────

_PATHOLOGICAL_LEVELS = 74_111


def _identifier_frame(levels: int = _PATHOLOGICAL_LEVELS) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "outcome": ["yes" if index % 2 else "no" for index in range(levels)],
            "identifier": [f"id_{index:06d}" for index in range(levels)],
        }
    )


def test_one_proportion_three_level_reason_is_useful_and_bounded() -> None:
    df = pd.DataFrame({"outcome": ["a", "b", "c", "a"]})
    result = svc.run_one_proportion_z_test(df, "outcome", "a", null_proportion=0.5)
    reason = str(result["reason"])
    assert result["status"] == "invalid_input"
    assert "exactly two distinct" in reason
    assert "a [str], b [str], c [str]" in reason
    assert len(reason) < 300


def test_one_proportion_pathological_outcome_reason_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_a: object, **_k: object) -> object:
        raise AssertionError("typed category construction was reached for a rejected input")

    monkeypatch.setattr(svc, "_typed_categories", forbidden)
    df = _identifier_frame()
    result = svc.run_one_proportion_z_test(df, "identifier", "id_000000", null_proportion=0.5)
    reason = str(result["reason"])
    assert result["status"] == "invalid_input"
    assert "74,111" in reason
    assert "id_000001" not in reason
    assert len(reason) < 200
    assert "observed_values" not in result


def test_two_proportion_pathological_outcome_reason_is_bounded() -> None:
    df = _identifier_frame()
    result = svc.run_two_proportion_z_test(df, "identifier", "id_000000", "outcome", "yes", "no")
    reason = str(result["reason"])
    assert result["status"] == "invalid_input"
    assert "74,111" in reason
    assert "id_000001" not in reason
    assert len(reason) < 200


def test_two_proportion_pathological_group_reason_is_bounded() -> None:
    df = _identifier_frame()
    result = svc.run_two_proportion_z_test(
        df, "outcome", "yes", "identifier", "id_000000", "id_000001"
    )
    reason = str(result["reason"])
    assert result["status"] == "invalid_input"
    assert "grouping column 'identifier'" in reason
    assert "74,111" in reason
    assert "id_000002" not in reason
    assert len(reason) < 200


def test_binary_outcome_reason_above_the_label_bound_is_truncated() -> None:
    labels = [f"value_{index:03d}" for index in range(30)]
    df = pd.DataFrame({"outcome": labels})
    result = svc.run_one_proportion_z_test(df, "outcome", "value_000", null_proportion=0.5)
    reason = str(result["reason"])
    assert result["status"] == "invalid_input"
    assert "exactly two distinct" in reason
    assert "(+20 more)" in reason
    assert "value_010" not in reason


def test_normal_binary_outcome_is_unaffected_by_the_ceiling() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame({"outcome": ["yes"] * 70 + ["no"] * 30})
    result = svc.run_one_proportion_z_test(df, "outcome", "yes", null_proportion=0.5)
    assert result["status"] == "ok"
    assert result["success_count"] == 70
    assert result["observed_values"] == ["no [str]", "yes [str]"]
