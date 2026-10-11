"""Tests for the explicit p-value engine."""

from __future__ import annotations

import pytest

from data_quality_toolkit.domain.statistics import inference
from data_quality_toolkit.domain.statistics.contracts import Alternative, TestKey


def test_scipy_missing_returns_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)
    result = inference.calculate_p_value(TestKey.ONE_T, sample=[1.0, 2.0, 3.0])
    assert result["status"] == "unavailable"
    assert result["scipy_available"] is False


def test_invalid_alpha_returns_invalid_input() -> None:
    result = inference.calculate_p_value(TestKey.ONE_T, sample=[1.0, 2.0, 3.0], alpha=0.0)
    assert result["status"] == "invalid_input"
    assert result["test_key"] == TestKey.ONE_T.value


def test_invalid_alternative_returns_invalid_input() -> None:
    result = inference.calculate_p_value(
        TestKey.ONE_T,
        sample=[1.0, 2.0, 3.0],
        alternative="sideways",
    )
    assert result["status"] == "invalid_input"


def test_unknown_test_key_returns_unsupported() -> None:
    result = inference.calculate_p_value(TestKey.UNKNOWN)
    assert result["status"] == "unsupported"
    assert result["test_key"] == TestKey.UNKNOWN.value


class TestRealScipyBranches:
    def test_one_z(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(
            TestKey.ONE_Z,
            sample=[1.0, 2.0, 3.0, 4.0, 5.0],
            null_mean=0.0,
            sigma=1.0,
            alternative=Alternative.GREATER,
        )
        assert result["status"] == "ok"
        assert result["statistic"] > 0
        assert result["p_value"] < 0.001

    def test_one_t(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(
            TestKey.ONE_T,
            sample=[2.0, 3.0, 4.0, 5.0, 6.0],
            null_mean=0.0,
            alternative=Alternative.GREATER,
        )
        assert result["status"] == "ok"
        assert result["reject_null"] is True

    def test_two_z(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(
            TestKey.TWO_Z,
            sample_a=[5.0, 6.0, 7.0, 8.0],
            sample_b=[1.0, 2.0, 3.0, 4.0],
            sigma=1.0,
            alternative=Alternative.GREATER,
        )
        assert result["status"] == "ok"
        assert result["p_value"] < 0.001

    def test_two_t_equal_variance(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(
            TestKey.TWO_T_EQ,
            sample_a=[10.0, 11.0, 12.0, 13.0, 14.0],
            sample_b=[1.0, 2.0, 3.0, 4.0, 5.0],
            alternative=Alternative.GREATER,
        )
        assert result["status"] == "ok"
        assert result["reject_null"] is True

    def test_two_t_welch(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(
            TestKey.TWO_T_WELCH,
            sample_a=[20.0, 22.0, 24.0, 26.0, 28.0],
            sample_b=[1.0, 2.0, 2.0, 3.0, 4.0],
            alternative=Alternative.GREATER,
        )
        assert result["status"] == "ok"
        assert result["method"] == "two_sample_t_welch"
        assert result["p_value"] < 0.01

    def test_paired_t(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(
            TestKey.PAIRED_T,
            sample_a=[10.0, 11.0, 12.0, 13.0, 14.0],
            sample_b=[1.0, 2.0, 3.0, 4.0, 5.0],
            alternative=Alternative.GREATER,
        )
        assert result["status"] == "invalid_input"

        result = inference.calculate_p_value(
            TestKey.PAIRED_T,
            sample_a=[10.0, 12.0, 13.0, 15.0, 16.0],
            sample_b=[1.0, 2.0, 4.0, 6.0, 8.0],
            alternative=Alternative.GREATER,
        )
        assert result["status"] == "ok"
        assert result["reject_null"] is True

    def test_anova_forces_two_sided(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(
            TestKey.ANOVA,
            groups=[
                [1.0, 1.1, 1.2, 1.3],
                [5.0, 5.1, 5.2, 5.3],
                [9.0, 9.1, 9.2, 9.3],
            ],
            alternative=Alternative.GREATER,
        )
        assert result["status"] == "ok"
        assert result["alternative"] == Alternative.TWO_SIDED.value
        assert result["warnings"]
        assert result["p_value"] < 0.001

    def test_one_prop_z_one_sided(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(
            TestKey.ONE_PROP_Z,
            successes=70,
            n=100,
            null_proportion=0.5,
            alternative=Alternative.GREATER,
        )
        assert result["status"] == "ok"
        assert result["p_value"] < 0.001

    def test_two_prop_z_one_sided(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(
            TestKey.TWO_PROP_Z,
            successes_a=70,
            n_a=100,
            successes_b=50,
            n_b=100,
            alternative=Alternative.GREATER,
        )
        assert result["status"] == "ok"
        assert result["p_value"] < 0.01

    def test_one_var_chi(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(
            TestKey.ONE_VAR_CHI,
            sample=[0.0, 3.0, 6.0, 9.0, 12.0],
            null_variance=1.0,
            alternative=Alternative.GREATER,
        )
        assert result["status"] == "ok"
        assert result["p_value"] < 0.001

    def test_f_var(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(
            TestKey.F_VAR,
            sample_a=[0.0, 4.0, 8.0, 12.0, 16.0, 20.0],
            sample_b=[9.0, 10.0, 11.0, 10.0, 9.0, 11.0],
            alternative=Alternative.GREATER,
        )
        assert result["status"] == "ok"
        assert result["p_value"] < 0.01

    def test_chi_gof(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(
            TestKey.CHI_GOF,
            observed=[30, 10, 10],
            expected=[10, 20, 20],
        )
        assert result["status"] == "ok"
        assert result["p_value"] < 0.001

    def test_chi_ind(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(
            TestKey.CHI_IND,
            table=[[30, 10], [10, 30]],
            alternative=Alternative.LESS,
        )
        assert result["status"] == "ok"
        assert result["alternative"] == Alternative.TWO_SIDED.value
        assert result["p_value"] < 0.001

    def test_chi_homog(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(TestKey.CHI_HOMOG, table=[[30, 10], [10, 30]])
        assert result["status"] == "ok"
        assert result["method"] == "chi_square_homogeneity"
        assert result["p_value"] < 0.001


def test_one_prop_z_invalid_input() -> None:
    pytest.importorskip("scipy")
    result = inference.calculate_p_value(
        TestKey.ONE_PROP_Z,
        successes=11,
        n=10,
        null_proportion=0.5,
    )
    assert result["status"] == "invalid_input"


def test_paired_t_requires_equal_length_after_cleaning() -> None:
    pytest.importorskip("scipy")
    result = inference.calculate_p_value(
        TestKey.PAIRED_T,
        sample_a=[1.0, 2.0, 3.0],
        sample_b=[1.0, 2.0],
    )
    assert result["status"] == "invalid_input"


# ── chi-square expected-count diagnostics (domain-owned, informational) ───────


class TestChiSquareExpectedCountDiagnostics:
    """The engine, not any surface, classifies expected-count reliability."""

    def test_gof_expected_below_one_warns(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(
            TestKey.CHI_GOF,
            observed=[1, 0, 0, 99],
            expected=[0.5, 0.5, 0.5, 98.5],
        )
        assert result["status"] == "ok"
        assert "below 1" in " ".join(result["warnings"]).lower()
        assert result["assumptions"]["expected_counts"]["any_below_1"] is True

    def test_gof_more_than_20pct_below_5_warns_without_below_one(self) -> None:
        pytest.importorskip("scipy")
        # Expected [2.5, 7.5, 7.5, 22.5]: min 2.5 (>=1) but 25% of cells are below 5.
        result = inference.calculate_p_value(
            TestKey.CHI_GOF,
            observed=[5, 5, 5, 25],
            expected=[2.5, 7.5, 7.5, 22.5],
        )
        joined = " ".join(result["warnings"]).lower()
        assert "below 5" in joined
        assert "below 1" not in joined
        diagnostics = result["assumptions"]["expected_counts"]
        assert diagnostics["any_below_1"] is False
        assert diagnostics["over_20pct_below_5"] is True

    def test_gof_equal_expected_counts_are_diagnosed_when_omitted(self) -> None:
        pytest.importorskip("scipy")
        # No f_exp: scipy spreads the total equally, so every expected count is 0.75.
        result = inference.calculate_p_value(TestKey.CHI_GOF, observed=[1, 1, 0, 1])
        assert result["status"] == "ok"
        assert "below 1" in " ".join(result["warnings"]).lower()
        assert result["assumptions"]["expected_counts"]["min_expected"] == pytest.approx(0.75)

    def test_gof_healthy_table_has_no_diagnostics(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(TestKey.CHI_GOF, observed=[30, 10, 10])
        assert result["warnings"] == []
        assert result["assumptions"]["expected_counts"]["sparse"] is False

    @pytest.mark.parametrize("key", [TestKey.CHI_IND, TestKey.CHI_HOMOG])
    def test_contingency_expected_below_one_warns(self, key: TestKey) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(key, table=[[1, 0], [0, 99]])
        assert result["status"] == "ok"
        assert "below 1" in " ".join(result["warnings"]).lower()
        assert result["assumptions"]["expected_counts"]["any_below_1"] is True

    @pytest.mark.parametrize("key", [TestKey.CHI_IND, TestKey.CHI_HOMOG])
    def test_contingency_more_than_20pct_below_5_warns(self, key: TestKey) -> None:
        pytest.importorskip("scipy")
        # Expected [[2.5, 7.5], [7.5, 22.5]]: min 2.5 (>=1) but 25% of cells below 5.
        result = inference.calculate_p_value(key, table=[[5, 5], [5, 25]])
        joined = " ".join(result["warnings"]).lower()
        assert "below 5" in joined
        assert "below 1" not in joined
        assert result["assumptions"]["expected_counts"]["fraction_below_5"] == pytest.approx(0.25)

    @pytest.mark.parametrize("key", [TestKey.CHI_IND, TestKey.CHI_HOMOG])
    def test_contingency_healthy_table_has_no_false_warning(self, key: TestKey) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(key, table=[[25, 25], [25, 25]])
        assert result["warnings"] == []
        assert result["assumptions"]["expected_counts"]["sparse"] is False

    def test_exactly_20pct_below_5_does_not_warn(self) -> None:
        pytest.importorskip("scipy")
        # 1 of 5 expected counts below 5 is exactly 20%, and the rule warns above 20%.
        result = inference.calculate_p_value(
            TestKey.CHI_GOF,
            observed=[4, 10, 10, 10, 10],
            expected=[4.0, 10.0, 10.0, 10.0, 10.0],
        )
        assert result["warnings"] == []
        assert result["assumptions"]["expected_counts"]["fraction_below_5"] == pytest.approx(0.2)

    def test_diagnostics_do_not_change_the_statistic_or_p_value(self) -> None:
        stats = pytest.importorskip("scipy.stats")
        table = [[1, 0], [0, 99]]
        reference = stats.chi2_contingency(table)
        result = inference.calculate_p_value(TestKey.CHI_IND, table=table)
        assert result["statistic"] == pytest.approx(float(reference.statistic))
        assert result["p_value"] == pytest.approx(float(reference.pvalue))
        assert result["test_key"] == TestKey.CHI_IND.value
        assert result["method"] == "chi_square_independence"


# ── 2x2 continuity-correction disclosure (behaviour preserved, not changed) ───


class TestContinuityCorrectionDisclosure:
    """scipy applies Yates' correction at dof == 1; the result must say so."""

    @pytest.mark.parametrize("key", [TestKey.CHI_IND, TestKey.CHI_HOMOG])
    def test_2x2_discloses_the_applied_correction(self, key: TestKey) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(key, table=[[10, 20], [30, 40]])
        assert result["assumptions"]["dof"] == 1
        assert result["assumptions"]["continuity_correction"] is True
        joined = " ".join(result["messages"]).lower()
        assert "continuity correction" in joined

    def test_2x2_statistic_still_matches_scipy_corrected_default(self) -> None:
        stats = pytest.importorskip("scipy.stats")
        table = [[10, 20], [30, 40]]
        corrected = stats.chi2_contingency(table)
        uncorrected = stats.chi2_contingency(table, correction=False)
        result = inference.calculate_p_value(TestKey.CHI_IND, table=table)
        assert result["statistic"] == pytest.approx(float(corrected.statistic))
        assert result["statistic"] != pytest.approx(float(uncorrected.statistic))

    def test_larger_table_does_not_falsely_claim_correction(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(TestKey.CHI_IND, table=[[10, 20, 5], [30, 40, 5]])
        assert result["assumptions"]["dof"] == 2
        assert result["assumptions"]["continuity_correction"] is False
        assert result["messages"] == []

    def test_goodness_of_fit_never_claims_a_continuity_correction(self) -> None:
        pytest.importorskip("scipy")
        result = inference.calculate_p_value(TestKey.CHI_GOF, observed=[30, 10, 10])
        assert result["assumptions"]["continuity_correction"] is False
        assert result["messages"] == []
