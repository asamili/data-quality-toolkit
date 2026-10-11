"""Typed local contracts for hypothesis-test selection and p-value results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "Alternative",
    "GroupStructure",
    "HypothesisSetup",
    "PValueResult",
    "SelectionResult",
    "TestKey",
    "VariableType",
    "coerce_alternative",
    "coerce_group_structure",
    "coerce_test_key",
    "coerce_variable_type",
]


class _DQTEnum(StrEnum):
    """String-valued enum with a compact repr and stable JSON-facing value."""

    def __str__(self) -> str:
        return self.value


class VariableType(_DQTEnum):
    NUMERIC = "numeric"
    PROPORTION = "proportion"
    CATEGORICAL = "categorical"
    VARIANCE = "variance"
    COUNT = "count"


class GroupStructure(_DQTEnum):
    ONE_SAMPLE = "one_sample"
    TWO_INDEPENDENT = "two_independent"
    PAIRED = "paired"
    MULTI_GROUP = "multi_group"
    GOODNESS_OF_FIT = "goodness_of_fit"
    CONTINGENCY = "contingency"


class Alternative(_DQTEnum):
    TWO_SIDED = "two-sided"
    GREATER = "greater"
    LESS = "less"


class TestKey(_DQTEnum):
    __test__ = False

    ONE_Z = "ONE_Z"
    ONE_T = "ONE_T"
    TWO_Z = "TWO_Z"
    TWO_T_EQ = "TWO_T_EQ"
    TWO_T_WELCH = "TWO_T_WELCH"
    PAIRED_T = "PAIRED_T"
    ANOVA = "ANOVA"
    ONE_PROP_Z = "ONE_PROP_Z"
    TWO_PROP_Z = "TWO_PROP_Z"
    ONE_VAR_CHI = "ONE_VAR_CHI"
    F_VAR = "F_VAR"
    CHI_GOF = "CHI_GOF"
    CHI_IND = "CHI_IND"
    CHI_HOMOG = "CHI_HOMOG"
    UNKNOWN = "UNKNOWN"


def coerce_variable_type(value: VariableType | str) -> VariableType:
    """Return a ``VariableType`` from an enum or exact string value."""
    if isinstance(value, VariableType):
        return value
    return VariableType(value)


def coerce_group_structure(value: GroupStructure | str) -> GroupStructure:
    """Return a ``GroupStructure`` from an enum or exact string value."""
    if isinstance(value, GroupStructure):
        return value
    return GroupStructure(value)


def coerce_alternative(value: Alternative | str) -> Alternative:
    """Return an ``Alternative`` from an enum or exact string value."""
    if isinstance(value, Alternative):
        return value
    return Alternative(value)


def coerce_test_key(value: TestKey | str) -> TestKey:
    """Return a ``TestKey`` from an enum or exact string value."""
    if isinstance(value, TestKey):
        return value
    return TestKey(value)


@dataclass(frozen=True)
class HypothesisSetup:
    """Serializable hypothesis-test setup chosen by the domain selector."""

    variable_type: VariableType
    group_structure: GroupStructure
    test_key: TestKey = TestKey.UNKNOWN
    alternative: Alternative = Alternative.TWO_SIDED
    alpha: float = 0.05
    sigma_known: bool | None = None
    equal_variance_assumed: bool | None = None
    paired: bool | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "variable_type": self.variable_type.value,
            "group_structure": self.group_structure.value,
            "test_key": self.test_key.value,
            "alternative": self.alternative.value,
            "alpha": self.alpha,
            "sigma_known": self.sigma_known,
            "equal_variance_assumed": self.equal_variance_assumed,
            "paired": self.paired,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class SelectionResult:
    """Structured result returned by the selection matrix."""

    status: str
    test_key: TestKey
    alpha: float
    alternative: Alternative
    method: str
    explanation: str
    warnings: tuple[str, ...] = field(default_factory=tuple)
    messages: tuple[str, ...] = field(default_factory=tuple)
    assumptions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "test_key": self.test_key.value,
            "alpha": self.alpha,
            "alternative": self.alternative.value,
            "method": self.method,
            "explanation": self.explanation,
            "warnings": list(self.warnings),
            "messages": list(self.messages),
            "assumptions": dict(self.assumptions),
        }


@dataclass(frozen=True)
class PValueResult:
    """Structured result contract for explicit p-value calculations."""

    status: str
    test_key: TestKey
    statistic: float | None
    p_value: float | None
    alpha: float
    reject_null: bool | None
    method: str
    reason: str | None = None
    alternative: Alternative = Alternative.TWO_SIDED
    warnings: tuple[str, ...] = field(default_factory=tuple)
    messages: tuple[str, ...] = field(default_factory=tuple)
    assumptions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "test_key": self.test_key.value,
            "statistic": self.statistic,
            "p_value": self.p_value,
            "alpha": self.alpha,
            "reject_null": self.reject_null,
            "method": self.method,
            "reason": self.reason,
            "alternative": self.alternative.value,
            "warnings": list(self.warnings),
            "messages": list(self.messages),
            "assumptions": dict(self.assumptions),
        }
