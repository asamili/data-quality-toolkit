"""DQT-native A/B comparison orchestration for first-wave tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from data_quality_toolkit.domain.statistics import inference as _inference
from data_quality_toolkit.domain.statistics.contracts import (
    Alternative,
    GroupStructure,
    TestKey,
    VariableType,
    coerce_group_structure,
    coerce_variable_type,
)
from data_quality_toolkit.domain.statistics.selection import select_test

__all__ = ["compare_ab"]


def _unsupported(selection: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "unsupported",
        "reason": selection.get("explanation"),
        "test_key": selection.get("test_key", TestKey.UNKNOWN.value),
        "statistic": None,
        "p_value": None,
        "alpha": selection.get("alpha"),
        "reject_null": None,
        "method": "ab_compare",
        "warnings": list(selection.get("warnings", [])),
        "messages": list(selection.get("messages", [])),
        "assumptions": dict(selection.get("assumptions", {})),
        "selection": selection,
    }


def compare_ab(  # noqa: C901
    sample_a: Any = None,
    sample_b: Any = None,
    *,
    variable_type: VariableType | str = VariableType.NUMERIC,
    group_structure: GroupStructure | str = GroupStructure.TWO_INDEPENDENT,
    groups: Sequence[Any] | None = None,
    successes_a: int | None = None,
    n_a: int | None = None,
    successes_b: int | None = None,
    n_b: int | None = None,
    observed: Any = None,
    expected: Any = None,
    table: Any = None,
    alpha: float = 0.05,
    alternative: Alternative | str = Alternative.TWO_SIDED,
    sigma_known: bool | None = False,
    equal_variance_assumed: bool | None = False,
    sigma: float | None = None,
    sigma_a: float | None = None,
    sigma_b: float | None = None,
    null_mean: float = 0.0,
    null_difference: float = 0.0,
    null_proportion: float | None = None,
    null_variance: float | None = None,
) -> dict[str, Any]:
    """Select and run a first-wave A/B-style hypothesis test.

    This domain helper intentionally does not alter the existing UI-facing
    ``inferential.ab_compare`` facade.
    """
    selection = select_test(
        variable_type,
        group_structure,
        sigma_known=sigma_known,
        equal_variance_assumed=equal_variance_assumed,
        paired=group_structure in {GroupStructure.PAIRED, GroupStructure.PAIRED.value},
        alpha=alpha,
        alternative=alternative,
    )
    if selection["status"] != "ok":
        return _unsupported(selection)

    variable = coerce_variable_type(variable_type)
    group = coerce_group_structure(group_structure)
    key = TestKey(selection["test_key"])

    kwargs: dict[str, Any] = {
        "alpha": alpha,
        "alternative": selection["alternative"],
        "null_difference": null_difference,
    }
    if variable == VariableType.NUMERIC:
        if key == TestKey.ONE_Z:
            kwargs.update(sample=sample_a, null_mean=null_mean, sigma=sigma)
        elif key == TestKey.ONE_T:
            kwargs.update(sample=sample_a, null_mean=null_mean)
        elif key == TestKey.TWO_Z:
            kwargs.update(
                sample_a=sample_a,
                sample_b=sample_b,
                sigma=sigma,
                sigma_a=sigma_a,
                sigma_b=sigma_b,
            )
        elif key in {TestKey.TWO_T_EQ, TestKey.TWO_T_WELCH, TestKey.PAIRED_T}:
            kwargs.update(sample_a=sample_a, sample_b=sample_b)
        elif key == TestKey.ANOVA:
            kwargs.update(groups=groups)
    elif variable == VariableType.PROPORTION:
        if key == TestKey.ONE_PROP_Z:
            kwargs.update(successes=successes_a, n=n_a, null_proportion=null_proportion)
        elif key == TestKey.TWO_PROP_Z:
            kwargs.update(
                successes_a=successes_a,
                n_a=n_a,
                successes_b=successes_b,
                n_b=n_b,
            )
    elif variable == VariableType.VARIANCE:
        if key == TestKey.ONE_VAR_CHI:
            kwargs.update(sample=sample_a, null_variance=null_variance)
        elif key == TestKey.F_VAR:
            kwargs.update(sample_a=sample_a, sample_b=sample_b)
    elif variable == VariableType.CATEGORICAL:
        if key == TestKey.CHI_GOF:
            kwargs.update(observed=observed, expected=expected)
        elif key in {TestKey.CHI_IND, TestKey.CHI_HOMOG}:
            kwargs.update(table=table)

    result = _inference.calculate_p_value(key, **kwargs)
    result["selection"] = selection
    result["variable_type"] = variable.value
    result["group_structure"] = group.value
    return result
