"""Contracts for the domain-native hypothesis testing layer."""

from __future__ import annotations

from data_quality_toolkit.domain.statistics.contracts import (
    Alternative,
    GroupStructure,
    HypothesisSetup,
    PValueResult,
    SelectionResult,
    TestKey,
    VariableType,
    coerce_alternative,
    coerce_group_structure,
    coerce_test_key,
    coerce_variable_type,
)


def test_enum_values_are_stable() -> None:
    assert VariableType.NUMERIC.value == "numeric"
    assert GroupStructure.TWO_INDEPENDENT.value == "two_independent"
    assert Alternative.TWO_SIDED.value == "two-sided"
    assert TestKey.TWO_T_WELCH.value == "TWO_T_WELCH"


def test_coercion_accepts_exact_string_values() -> None:
    assert coerce_variable_type("proportion") is VariableType.PROPORTION
    assert coerce_group_structure("paired") is GroupStructure.PAIRED
    assert coerce_alternative("greater") is Alternative.GREATER
    assert coerce_test_key("ONE_PROP_Z") is TestKey.ONE_PROP_Z


def test_hypothesis_setup_to_dict_is_serializable() -> None:
    setup = HypothesisSetup(
        variable_type=VariableType.NUMERIC,
        group_structure=GroupStructure.TWO_INDEPENDENT,
        test_key=TestKey.TWO_T_WELCH,
        alternative=Alternative.LESS,
        alpha=0.01,
        sigma_known=False,
        equal_variance_assumed=False,
        notes=("welch",),
    )
    assert setup.to_dict() == {
        "variable_type": "numeric",
        "group_structure": "two_independent",
        "test_key": "TWO_T_WELCH",
        "alternative": "less",
        "alpha": 0.01,
        "sigma_known": False,
        "equal_variance_assumed": False,
        "paired": None,
        "notes": ["welch"],
    }


def test_selection_result_to_dict_contract() -> None:
    result = SelectionResult(
        status="ok",
        test_key=TestKey.CHI_IND,
        alpha=0.05,
        alternative=Alternative.TWO_SIDED,
        method="selection_matrix",
        explanation="categorical contingency",
        warnings=("forced two-sided",),
        assumptions={"cells": "counts"},
    ).to_dict()
    assert result["status"] == "ok"
    assert result["test_key"] == "CHI_IND"
    assert result["warnings"] == ["forced two-sided"]
    assert result["assumptions"] == {"cells": "counts"}


def test_p_value_result_to_dict_contract() -> None:
    result = PValueResult(
        status="ok",
        test_key=TestKey.ONE_T,
        statistic=2.0,
        p_value=0.04,
        alpha=0.05,
        reject_null=True,
        method="one_sample_t",
        alternative=Alternative.GREATER,
    ).to_dict()
    assert result["status"] == "ok"
    assert result["test_key"] == "ONE_T"
    assert result["reject_null"] is True
    assert result["alternative"] == "greater"
