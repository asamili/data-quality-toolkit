"""DQT-native hypothesis-test selection matrix."""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.domain.statistics.contracts import (
    Alternative,
    GroupStructure,
    SelectionResult,
    TestKey,
    VariableType,
    coerce_alternative,
    coerce_group_structure,
    coerce_variable_type,
)
from data_quality_toolkit.domain.statistics.core import validate_alpha

__all__ = ["select_test", "suggest_tests"]

_TWO_SIDED_ONLY = frozenset(
    {
        TestKey.ANOVA,
        TestKey.CHI_GOF,
        TestKey.CHI_IND,
        TestKey.CHI_HOMOG,
    }
)


def _result(
    *,
    status: str,
    test_key: TestKey,
    alpha: float,
    alternative: Alternative,
    explanation: str,
    warnings: tuple[str, ...] = (),
    messages: tuple[str, ...] = (),
    assumptions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return SelectionResult(
        status=status,
        test_key=test_key,
        alpha=alpha,
        alternative=alternative,
        method="selection_matrix",
        explanation=explanation,
        warnings=warnings,
        messages=messages,
        assumptions=assumptions or {},
    ).to_dict()


def _coerce_inputs(
    variable_type: VariableType | str,
    group_structure: GroupStructure | str,
    alternative: Alternative | str,
) -> tuple[VariableType | None, GroupStructure | None, Alternative | None, str | None]:
    try:
        variable = coerce_variable_type(variable_type)
        group = coerce_group_structure(group_structure)
        alt = coerce_alternative(alternative)
    except ValueError as exc:
        return None, None, None, str(exc)
    return variable, group, alt, None


def select_test(  # noqa: C901
    variable_type: VariableType | str,
    group_structure: GroupStructure | str,
    *,
    sigma_known: bool | None = None,
    equal_variance_assumed: bool | None = None,
    paired: bool | None = None,
    alternative: Alternative | str = Alternative.TWO_SIDED,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Select the first-wave hypothesis test for a typed setup.

    Unknown or underspecified combinations return ``status="unsupported"`` with
    ``test_key="UNKNOWN"`` rather than raising.
    """
    try:
        validate_alpha(alpha)
    except ValueError as exc:
        return _result(
            status="invalid_input",
            test_key=TestKey.UNKNOWN,
            alpha=alpha,
            alternative=Alternative.TWO_SIDED,
            explanation=str(exc),
        )

    variable, group, alt, err = _coerce_inputs(variable_type, group_structure, alternative)
    if err is not None or variable is None or group is None or alt is None:
        return _result(
            status="invalid_input",
            test_key=TestKey.UNKNOWN,
            alpha=alpha,
            alternative=Alternative.TWO_SIDED,
            explanation=err or "invalid hypothesis setup",
        )

    assumptions: dict[str, Any] = {
        "sigma_known": sigma_known,
        "equal_variance_assumed": equal_variance_assumed,
        "paired": paired,
    }
    test_key = TestKey.UNKNOWN
    explanation = "No first-wave test supports this variable/group combination."
    messages: list[str] = []

    if variable == VariableType.NUMERIC:
        if group == GroupStructure.PAIRED or paired is True:
            test_key = TestKey.PAIRED_T
            explanation = "Numeric paired samples map to a paired t-test."
        elif group == GroupStructure.ONE_SAMPLE:
            if sigma_known is True:
                test_key = TestKey.ONE_Z
                explanation = (
                    "Numeric one-sample setup with known sigma maps to a one-sample z-test."
                )
            elif sigma_known is False:
                test_key = TestKey.ONE_T
                explanation = (
                    "Numeric one-sample setup with unknown sigma maps to a one-sample t-test."
                )
            else:
                messages.append("sigma_known must be true or false for a numeric one-sample test.")
        elif group == GroupStructure.TWO_INDEPENDENT:
            if sigma_known is True:
                test_key = TestKey.TWO_Z
                explanation = (
                    "Numeric two-independent setup with known sigma maps to a two-sample z-test."
                )
            elif sigma_known is False and equal_variance_assumed is True:
                test_key = TestKey.TWO_T_EQ
                explanation = (
                    "Numeric two-independent setup with equal variances maps to pooled t-test."
                )
            elif sigma_known is False and equal_variance_assumed is False:
                test_key = TestKey.TWO_T_WELCH
                explanation = (
                    "Numeric two-independent setup with unequal variances maps to Welch t-test."
                )
            elif sigma_known is False:
                messages.append(
                    "equal_variance_assumed must be true or false when sigma is unknown."
                )
            else:
                messages.append("sigma_known must be true or false for two independent samples.")
        elif group == GroupStructure.MULTI_GROUP:
            test_key = TestKey.ANOVA
            explanation = "Numeric multi-group setup maps to one-way ANOVA."
    elif variable == VariableType.PROPORTION:
        if group == GroupStructure.ONE_SAMPLE:
            test_key = TestKey.ONE_PROP_Z
            explanation = "One-sample proportion setup maps to a one-proportion z-test."
        elif group == GroupStructure.TWO_INDEPENDENT:
            test_key = TestKey.TWO_PROP_Z
            explanation = "Two-independent proportion setup maps to a two-proportion z-test."
    elif variable == VariableType.VARIANCE:
        if group == GroupStructure.ONE_SAMPLE:
            test_key = TestKey.ONE_VAR_CHI
            explanation = "One-sample variance setup maps to a chi-square variance test."
        elif group == GroupStructure.TWO_INDEPENDENT:
            test_key = TestKey.F_VAR
            explanation = "Two-independent variance setup maps to an F variance-ratio test."
    elif variable == VariableType.CATEGORICAL:
        if group == GroupStructure.GOODNESS_OF_FIT:
            test_key = TestKey.CHI_GOF
            explanation = "Categorical goodness-of-fit setup maps to chi-square goodness-of-fit."
        elif group == GroupStructure.CONTINGENCY:
            test_key = TestKey.CHI_IND
            explanation = "Categorical contingency setup maps to chi-square independence."
        elif group == GroupStructure.MULTI_GROUP:
            test_key = TestKey.CHI_HOMOG
            explanation = "Categorical multi-group setup maps to chi-square homogeneity."

    if test_key == TestKey.UNKNOWN:
        return _result(
            status="unsupported",
            test_key=TestKey.UNKNOWN,
            alpha=alpha,
            alternative=alt,
            explanation=explanation,
            messages=tuple(messages),
            assumptions=assumptions,
        )

    warnings: list[str] = []
    if test_key in _TWO_SIDED_ONLY and alt != Alternative.TWO_SIDED:
        warnings.append(
            f"{test_key.value} is handled as two-sided in the first-wave statistics engine."
        )
        alt = Alternative.TWO_SIDED

    return _result(
        status="ok",
        test_key=test_key,
        alpha=alpha,
        alternative=alt,
        explanation=explanation,
        warnings=tuple(warnings),
        messages=tuple(messages),
        assumptions=assumptions,
    )


def suggest_tests(
    variable_type: VariableType | str,
    group_structure: GroupStructure | str,
    *,
    alpha: float = 0.05,
    alternative: Alternative | str = Alternative.TWO_SIDED,
) -> list[dict[str, Any]]:
    """Return deterministic suggestions for underspecified setup choices."""
    variable, group, alt, err = _coerce_inputs(variable_type, group_structure, alternative)
    if err is not None or variable is None or group is None or alt is None:
        return [
            _result(
                status="invalid_input",
                test_key=TestKey.UNKNOWN,
                alpha=alpha,
                alternative=Alternative.TWO_SIDED,
                explanation=err or "invalid hypothesis setup",
            )
        ]

    if variable == VariableType.NUMERIC and group == GroupStructure.ONE_SAMPLE:
        return [
            select_test(variable, group, sigma_known=True, alpha=alpha, alternative=alt),
            select_test(variable, group, sigma_known=False, alpha=alpha, alternative=alt),
        ]
    if variable == VariableType.NUMERIC and group == GroupStructure.TWO_INDEPENDENT:
        return [
            select_test(variable, group, sigma_known=True, alpha=alpha, alternative=alt),
            select_test(
                variable,
                group,
                sigma_known=False,
                equal_variance_assumed=True,
                alpha=alpha,
                alternative=alt,
            ),
            select_test(
                variable,
                group,
                sigma_known=False,
                equal_variance_assumed=False,
                alpha=alpha,
                alternative=alt,
            ),
        ]
    return [select_test(variable, group, alpha=alpha, alternative=alt)]
