"""Tests for closed-form power and sample-size helpers.

Includes a regression test that ``required_n_cohend`` returns an explicit scalar
``n_per_group`` (the extracted notebook returned a tuple — a known bug).
"""

from __future__ import annotations

import pytest

from data_quality_toolkit.domain.statistics import power


class TestPowerRealScipy:
    def setup_method(self) -> None:
        pytest.importorskip("scipy")

    def test_power_mean_in_unit_interval(self) -> None:
        result = power.power_mean(n=50, delta=0.5, sigma=1.0)
        assert result["status"] == "ok"
        assert 0.0 <= result["power"] <= 1.0

    def test_power_mean_increases_with_n(self) -> None:
        low = power.power_mean(n=10, delta=0.5, sigma=1.0)["power"]
        high = power.power_mean(n=200, delta=0.5, sigma=1.0)["power"]
        assert high > low

    def test_power_mean_one_sided_preserves_direction(self) -> None:
        wrong_direction = power.power_mean(n=100, delta=-0.5, sigma=1.0, alternative="greater")
        right_direction = power.power_mean(n=100, delta=0.5, sigma=1.0, alternative="greater")
        opposite_tail = power.power_mean(n=100, delta=0.5, sigma=1.0, alternative="less")

        assert wrong_direction["power"] < 0.001
        assert right_direction["power"] > 0.99
        assert opposite_tail["power"] < 0.001

    def test_power_prop_in_unit_interval(self) -> None:
        result = power.power_prop(n=100, p1=0.5, p2=0.6)
        assert result["status"] == "ok"
        assert 0.0 <= result["power"] <= 1.0

    def test_power_prop_one_sided_preserves_direction(self) -> None:
        wrong_direction = power.power_prop(n=100, p1=0.4, p2=0.6, alternative="greater")
        right_direction = power.power_prop(n=100, p1=0.6, p2=0.4, alternative="greater")

        assert wrong_direction["power"] < 0.001
        assert right_direction["power"] > 0.8

    def test_required_n_mean_positive_and_monotone(self) -> None:
        big_effect = power.required_n_mean(delta=1.0, sigma=1.0)["n"]
        small_effect = power.required_n_mean(delta=0.2, sigma=1.0)["n"]
        assert big_effect > 0
        assert small_effect > big_effect  # smaller effect needs more samples

    def test_required_n_mean_is_one_sample_inverse(self) -> None:
        requested_power = 0.8
        result = power.required_n_mean(delta=0.5, sigma=1.0, alpha=0.05, power=requested_power)
        achieved = power.power_mean(n=result["n"], delta=0.5, sigma=1.0, alpha=0.05)["power"]

        assert result["n"] == 32
        assert requested_power <= achieved < 0.85

    def test_required_n_prop_returns_two_group_sizes(self) -> None:
        result = power.required_n_prop(p1=0.5, p2=0.6)
        assert result["status"] == "ok"
        assert result["n1"] > 0 and result["n2"] > 0

    def test_required_n_variance_ratio_one_invalid(self) -> None:
        assert power.required_n_variance(ratio=1.0)["status"] == "invalid_input"
        assert power.required_n_variance(ratio=2.0)["n"] > 0

    def test_required_n_cohend_returns_scalar_not_tuple(self) -> None:
        # Regression: extracted required_n_cohend returned a tuple (n1, n2).
        result = power.required_n_cohend(delta=0.5)
        assert result["status"] == "ok"
        assert isinstance(result["n_per_group"], int)
        assert result["n_per_group"] > 0
        assert "n1" not in result and "n2" not in result

    def test_required_n_cohend_zero_delta_invalid(self) -> None:
        assert power.required_n_cohend(delta=0.0)["status"] == "invalid_input"


class TestValidation:
    def test_invalid_alpha_raises(self) -> None:
        with pytest.raises(ValueError, match="alpha"):
            power.power_mean(n=10, delta=0.5, sigma=1.0, alpha=1.5)

    def test_invalid_alternative_raises(self) -> None:
        with pytest.raises(ValueError, match="alternative"):
            power.power_mean(n=10, delta=0.5, sigma=1.0, alternative="sideways")

    def test_zero_delta_invalid(self) -> None:
        pytest.importorskip("scipy")
        assert power.required_n_mean(delta=0.0, sigma=1.0)["status"] == "invalid_input"


class TestUnavailable:
    def test_status_unavailable_without_scipy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(power, "import_scipy_stats", lambda: None)
        for result in (
            power.power_mean(n=10, delta=0.5, sigma=1.0),
            power.power_prop(n=10, p1=0.5, p2=0.6),
            power.required_n_mean(delta=0.5, sigma=1.0),
            power.required_n_prop(p1=0.5, p2=0.6),
            power.required_n_variance(ratio=2.0),
            power.required_n_cohend(delta=0.5),
        ):
            assert result["status"] == "unavailable"
