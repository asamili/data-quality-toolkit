"""Tests for domain-native A/B orchestration."""

from __future__ import annotations

import pytest

from data_quality_toolkit.domain.statistics import ab
from data_quality_toolkit.domain.statistics.contracts import GroupStructure, TestKey, VariableType


def test_ab_scipy_missing_returns_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ab._inference, "import_scipy_stats", lambda: None)
    result = ab.compare_ab(
        [10.0, 11.0, 12.0],
        [1.0, 2.0, 3.0],
        variable_type=VariableType.NUMERIC,
        alternative="greater",
    )
    assert result["status"] == "unavailable"
    assert result["selection"]["test_key"] == TestKey.TWO_T_WELCH.value


def test_ab_unknown_selection_returns_unsupported() -> None:
    result = ab.compare_ab(variable_type=VariableType.COUNT)
    assert result["status"] == "unsupported"
    assert result["test_key"] == TestKey.UNKNOWN.value


class TestRealScipyAb:
    def test_numeric_welch_ab(self) -> None:
        pytest.importorskip("scipy")
        result = ab.compare_ab(
            [20.0, 22.0, 24.0, 26.0, 28.0],
            [1.0, 2.0, 2.0, 3.0, 4.0],
            variable_type=VariableType.NUMERIC,
            equal_variance_assumed=False,
            alternative="greater",
        )
        assert result["status"] == "ok"
        assert result["test_key"] == TestKey.TWO_T_WELCH.value
        assert result["p_value"] < 0.01

    def test_proportion_ab(self) -> None:
        pytest.importorskip("scipy")
        result = ab.compare_ab(
            variable_type=VariableType.PROPORTION,
            successes_a=70,
            n_a=100,
            successes_b=50,
            n_b=100,
            alternative="greater",
        )
        assert result["status"] == "ok"
        assert result["test_key"] == TestKey.TWO_PROP_Z.value
        assert result["reject_null"] is True

    def test_variance_ab(self) -> None:
        pytest.importorskip("scipy")
        result = ab.compare_ab(
            [0.0, 4.0, 8.0, 12.0, 16.0, 20.0],
            [9.0, 10.0, 11.0, 10.0, 9.0, 11.0],
            variable_type=VariableType.VARIANCE,
            alternative="greater",
        )
        assert result["status"] == "ok"
        assert result["test_key"] == TestKey.F_VAR.value

    def test_categorical_contingency_ab(self) -> None:
        pytest.importorskip("scipy")
        result = ab.compare_ab(
            variable_type=VariableType.CATEGORICAL,
            group_structure=GroupStructure.CONTINGENCY,
            table=[[30, 10], [10, 30]],
        )
        assert result["status"] == "ok"
        assert result["test_key"] == TestKey.CHI_IND.value
        assert result["p_value"] < 0.001

    def test_categorical_homogeneity_ab(self) -> None:
        pytest.importorskip("scipy")
        result = ab.compare_ab(
            variable_type=VariableType.CATEGORICAL,
            group_structure=GroupStructure.MULTI_GROUP,
            table=[[30, 10], [10, 30]],
        )
        assert result["status"] == "ok"
        assert result["test_key"] == TestKey.CHI_HOMOG.value
