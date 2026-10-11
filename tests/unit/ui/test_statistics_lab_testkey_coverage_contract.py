"""Machine tests for the Statistics Lab 14-TestKey execution-coverage contract.

The contract is internal private UI architecture metadata recorded in
``statistics_lab_runners``. These tests pin its shape: exactly the 14 first-wave
TestKeys, bounded classification/disposition vocabulary, honest deferred marking,
the explicit ANOVA disposition, the PAIRED_T disposition, and immutability.
"""

from __future__ import annotations

import dataclasses

import pytest

from data_quality_toolkit.adapters.ui.pages import statistics_lab_runners as runners
from data_quality_toolkit.domain.statistics.contracts import TestKey

_EXPECTED_KEYS = {key.value for key in TestKey if key is not TestKey.UNKNOWN}

_DEFERRED_KEYS = (
    "ONE_Z",
    "TWO_Z",
    "ONE_VAR_CHI",
    "F_VAR",
)


def test_contract_covers_exactly_the_14_testkeys() -> None:
    assert len(_EXPECTED_KEYS) == 14
    assert set(runners.TESTKEY_EXECUTION_COVERAGE) == _EXPECTED_KEYS
    assert len(runners.TESTKEY_EXECUTION_COVERAGE) == 14


def test_no_unknown_key_and_entries_echo_their_key() -> None:
    assert TestKey.UNKNOWN.value not in runners.TESTKEY_EXECUTION_COVERAGE
    for key, entry in runners.TESTKEY_EXECUTION_COVERAGE.items():
        assert entry.test_key == key


def test_bounded_classification_and_disposition_vocabulary() -> None:
    for entry in runners.TESTKEY_EXECUTION_COVERAGE.values():
        assert entry.baseline in runners.BASELINE_CLASSIFICATIONS
        assert entry.disposition in runners.DISPOSITIONS
        # A surface is always stated; NO_SURFACE marks a documented absence.
        assert entry.surface


def test_anova_disposition_is_explicit_equivalent_surface() -> None:
    entry = runners.TESTKEY_EXECUTION_COVERAGE["ANOVA"]
    assert entry.baseline == runners.BASELINE_EQUIVALENT_ELSEWHERE
    assert "Group comparison" in entry.surface
    assert entry.disposition == runners.DISPOSITION_UNCHANGED_EQUIVALENT


def test_paired_t_is_implemented() -> None:
    entry = runners.TESTKEY_EXECUTION_COVERAGE["PAIRED_T"]
    assert entry.baseline == runners.BASELINE_CONFIRMED_MISSING
    assert entry.disposition == runners.DISPOSITION_IMPLEMENTED_PAIRED_T
    assert "parametric t-test" in entry.surface
    # The nonparametric Wilcoxon panel is recorded as distinct, not equivalent.
    assert "Wilcoxon" in entry.surface


def test_proportion_z_tests_are_implemented() -> None:
    for key, service in (
        ("ONE_PROP_Z", "run_one_proportion_z_test"),
        ("TWO_PROP_Z", "run_two_proportion_z_test"),
    ):
        entry = runners.TESTKEY_EXECUTION_COVERAGE[key]
        # Baseline classification is unchanged: no loaded-dataset surface existed
        # before this runner. Only the v2.9.9 disposition and current surface change.
        assert entry.baseline == runners.BASELINE_CONFIRMED_MISSING
        assert entry.disposition == runners.DISPOSITION_IMPLEMENTED_PROPORTION_Z
        assert entry.surface != runners.NO_SURFACE
        assert "Proportion tests" in entry.surface
        assert service in entry.surface
        assert "run_statistical_test" in entry.surface


def test_proportion_z_disposition_is_in_the_bounded_vocabulary() -> None:
    assert runners.DISPOSITION_IMPLEMENTED_PROPORTION_Z in runners.DISPOSITIONS


def test_chi_square_disposition_is_in_the_bounded_vocabulary() -> None:
    assert runners.DISPOSITION_IMPLEMENTED_CHI_SQUARE in runners.DISPOSITIONS


def test_chi_goodness_of_fit_is_implemented() -> None:
    entry = runners.TESTKEY_EXECUTION_COVERAGE["CHI_GOF"]
    # Baseline classification is unchanged: no loaded-dataset surface existed before this runner.
    assert entry.baseline == runners.BASELINE_CONFIRMED_MISSING
    assert entry.disposition == runners.DISPOSITION_IMPLEMENTED_CHI_SQUARE
    assert entry.surface != runners.NO_SURFACE
    assert "Chi-square tests" in entry.surface
    assert "Goodness of fit" in entry.surface
    assert "run_chi_square_gof_test" in entry.surface
    assert "run_statistical_test" in entry.surface


def test_chi_independence_is_implemented() -> None:
    entry = runners.TESTKEY_EXECUTION_COVERAGE["CHI_IND"]
    assert entry.baseline == runners.BASELINE_CONFIRMED_MISSING
    assert entry.disposition == runners.DISPOSITION_IMPLEMENTED_CHI_SQUARE
    assert entry.surface != runners.NO_SURFACE
    assert "Chi-square tests" in entry.surface
    assert "Independence" in entry.surface
    assert "run_chi_square_independence_test" in entry.surface
    assert "run_statistical_test" in entry.surface


def test_chi_homogeneity_is_implemented() -> None:
    entry = runners.TESTKEY_EXECUTION_COVERAGE["CHI_HOMOG"]
    assert entry.baseline == runners.BASELINE_CONFIRMED_MISSING
    assert entry.disposition == runners.DISPOSITION_IMPLEMENTED_CHI_SQUARE
    assert entry.surface != runners.NO_SURFACE
    assert "Chi-square tests" in entry.surface
    assert "Homogeneity" in entry.surface
    assert "run_chi_square_homogeneity_test" in entry.surface
    assert "run_statistical_test" in entry.surface
    # Routed through its own key, never substituting the independence key.
    assert "CHI_HOMOG" in entry.surface


def test_all_three_chi_square_keys_are_implemented() -> None:
    for key in ("CHI_GOF", "CHI_IND", "CHI_HOMOG"):
        entry = runners.TESTKEY_EXECUTION_COVERAGE[key]
        assert entry.disposition == runners.DISPOSITION_IMPLEMENTED_CHI_SQUARE
    # No chi-square key remains deferred.
    assert not any(key.startswith("CHI_") for key in _DEFERRED_KEYS)


def test_already_runnable_keys_name_a_real_surface() -> None:
    for key in ("ONE_T", "TWO_T_EQ", "TWO_T_WELCH"):
        entry = runners.TESTKEY_EXECUTION_COVERAGE[key]
        assert entry.baseline == runners.BASELINE_ALREADY_RUNNABLE
        assert entry.surface != runners.NO_SURFACE
        assert entry.disposition == runners.DISPOSITION_UNCHANGED


def test_deferred_keys_are_marked_honestly() -> None:
    for key in _DEFERRED_KEYS:
        entry = runners.TESTKEY_EXECUTION_COVERAGE[key]
        assert entry.baseline == runners.BASELINE_CONFIRMED_MISSING
        assert entry.surface == runners.NO_SURFACE
        assert entry.disposition == runners.DISPOSITION_DEFERRED


def test_contract_is_immutable() -> None:
    with pytest.raises(TypeError):
        runners.TESTKEY_EXECUTION_COVERAGE["ONE_T"] = None  # type: ignore[index]
    entry = runners.TESTKEY_EXECUTION_COVERAGE["ONE_T"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.baseline = "mutated"  # type: ignore[misc]
