"""Tests for the domain-native hypothesis-test selection matrix."""

from __future__ import annotations

from typing import Any

import pytest

from data_quality_toolkit.domain.statistics.contracts import (
    Alternative,
    GroupStructure,
    TestKey,
    VariableType,
)
from data_quality_toolkit.domain.statistics.selection import select_test, suggest_tests


@pytest.mark.parametrize(
    ("variable_type", "group_structure", "kwargs", "expected"),
    [
        (VariableType.NUMERIC, GroupStructure.ONE_SAMPLE, {"sigma_known": True}, TestKey.ONE_Z),
        (VariableType.NUMERIC, GroupStructure.ONE_SAMPLE, {"sigma_known": False}, TestKey.ONE_T),
        (
            VariableType.NUMERIC,
            GroupStructure.TWO_INDEPENDENT,
            {"sigma_known": True},
            TestKey.TWO_Z,
        ),
        (
            VariableType.NUMERIC,
            GroupStructure.TWO_INDEPENDENT,
            {"sigma_known": False, "equal_variance_assumed": True},
            TestKey.TWO_T_EQ,
        ),
        (
            VariableType.NUMERIC,
            GroupStructure.TWO_INDEPENDENT,
            {"sigma_known": False, "equal_variance_assumed": False},
            TestKey.TWO_T_WELCH,
        ),
        (VariableType.NUMERIC, GroupStructure.PAIRED, {}, TestKey.PAIRED_T),
        (VariableType.NUMERIC, GroupStructure.MULTI_GROUP, {}, TestKey.ANOVA),
        (VariableType.PROPORTION, GroupStructure.ONE_SAMPLE, {}, TestKey.ONE_PROP_Z),
        (VariableType.PROPORTION, GroupStructure.TWO_INDEPENDENT, {}, TestKey.TWO_PROP_Z),
        (VariableType.VARIANCE, GroupStructure.ONE_SAMPLE, {}, TestKey.ONE_VAR_CHI),
        (VariableType.VARIANCE, GroupStructure.TWO_INDEPENDENT, {}, TestKey.F_VAR),
        (VariableType.CATEGORICAL, GroupStructure.GOODNESS_OF_FIT, {}, TestKey.CHI_GOF),
        (VariableType.CATEGORICAL, GroupStructure.CONTINGENCY, {}, TestKey.CHI_IND),
        (VariableType.CATEGORICAL, GroupStructure.MULTI_GROUP, {}, TestKey.CHI_HOMOG),
    ],
)
def test_all_first_wave_matrix_mappings(
    variable_type: VariableType,
    group_structure: GroupStructure,
    kwargs: dict[str, Any],
    expected: TestKey,
) -> None:
    result = select_test(variable_type, group_structure, **kwargs)
    assert result["status"] == "ok"
    assert result["test_key"] == expected.value


def test_unknown_combination_returns_status_not_exception() -> None:
    result = select_test(VariableType.COUNT, GroupStructure.TWO_INDEPENDENT)
    assert result["status"] == "unsupported"
    assert result["test_key"] == TestKey.UNKNOWN.value


def test_underspecified_numeric_mapping_returns_unknown() -> None:
    result = select_test(VariableType.NUMERIC, GroupStructure.TWO_INDEPENDENT)
    assert result["status"] == "unsupported"
    assert result["test_key"] == TestKey.UNKNOWN.value
    assert "sigma_known" in result["messages"][0]


def test_invalid_alpha_returns_invalid_input() -> None:
    result = select_test(VariableType.NUMERIC, GroupStructure.ONE_SAMPLE, alpha=0.0)
    assert result["status"] == "invalid_input"
    assert result["test_key"] == TestKey.UNKNOWN.value


def test_anova_forces_two_sided_alternative() -> None:
    result = select_test(
        VariableType.NUMERIC,
        GroupStructure.MULTI_GROUP,
        alternative=Alternative.GREATER,
    )
    assert result["status"] == "ok"
    assert result["test_key"] == TestKey.ANOVA.value
    assert result["alternative"] == Alternative.TWO_SIDED.value
    assert result["warnings"]


def test_suggest_tests_returns_assumption_variants() -> None:
    suggestions = suggest_tests(VariableType.NUMERIC, GroupStructure.TWO_INDEPENDENT)
    assert [item["test_key"] for item in suggestions] == [
        TestKey.TWO_Z.value,
        TestKey.TWO_T_EQ.value,
        TestKey.TWO_T_WELCH.value,
    ]
