"""Tests for the confidence-interval bank.

Coverage/containment checks behind importorskip, the status contract, parameter
validation, and the scipy-unavailable degradation path.
"""

from __future__ import annotations

import pytest

from data_quality_toolkit.domain.statistics import intervals


class TestRealScipy:
    def setup_method(self) -> None:
        pytest.importorskip("scipy")

    def test_ci_mean_known_sigma_contains_true_mean(self) -> None:
        data = [10.0, 12.0, 9.0, 11.0, 10.5, 9.5]
        result = intervals.ci_mean(data, confidence=0.95, known_sigma=1.0)
        assert result["status"] == "ok"
        assert result["method"] == "z"
        assert result["lower"] < result["point"] < result["upper"]
        assert result["n"] == 6

    def test_ci_mean_t_interval_default(self) -> None:
        result = intervals.ci_mean([1.0, 2.0, 3.0, 4.0, 5.0])
        assert result["status"] == "ok"
        assert result["method"] == "t"
        assert result["point"] == pytest.approx(3.0)

    def test_ci_mean_insufficient_data(self) -> None:
        result = intervals.ci_mean([1.0])
        assert result["status"] == "insufficient_data"

    def test_ci_mean_diff_welch(self) -> None:
        a = [5.0, 6.0, 7.0, 8.0]
        b = [1.0, 2.0, 3.0, 4.0]
        result = intervals.ci_mean_diff(a, b, equal_var=False)
        assert result["status"] == "ok"
        assert result["method"] == "welch"
        assert result["point"] == pytest.approx(4.0)

    def test_ci_mean_diff_paired_requires_equal_length(self) -> None:
        result = intervals.ci_mean_diff([1.0, 2.0, 3.0], [1.0, 2.0], paired=True)
        assert result["status"] == "invalid_input"

    @pytest.mark.parametrize("method", ["wald", "wilson", "jeffreys"])
    def test_ci_prop_methods_contain_phat(self, method: str) -> None:
        result = intervals.ci_prop(30, 100, method=method)
        assert result["status"] == "ok"
        assert result["point"] == pytest.approx(0.3)
        assert result["lower"] <= 0.3 <= result["upper"]
        assert 0.0 <= result["lower"] <= result["upper"] <= 1.0

    def test_ci_prop_jeffreys_edge_zero_successes(self) -> None:
        result = intervals.ci_prop(0, 50, method="jeffreys")
        assert result["status"] == "ok"
        assert result["lower"] == 0.0

    def test_ci_prop_invalid_successes(self) -> None:
        result = intervals.ci_prop(60, 50)
        assert result["status"] == "invalid_input"

    def test_ci_prop_diff(self) -> None:
        result = intervals.ci_prop_diff(30, 100, 20, 100)
        assert result["status"] == "ok"
        assert result["point"] == pytest.approx(0.1)

    def test_ci_var_requires_min_n(self) -> None:
        assert intervals.ci_var(4.0, n=2)["status"] == "insufficient_data"
        ok = intervals.ci_var(4.0, n=20)
        assert ok["status"] == "ok"
        assert ok["lower"] < ok["point"] < ok["upper"]

    def test_ci_var_ratio(self) -> None:
        result = intervals.ci_var_ratio(4.0, 20, 2.0, 20)
        assert result["status"] == "ok"
        assert result["point"] == pytest.approx(2.0)


class TestValidation:
    def test_invalid_confidence_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            intervals.ci_mean([1.0, 2.0, 3.0], confidence=1.5)

    def test_unknown_prop_method_raises(self) -> None:
        with pytest.raises(ValueError, match="method"):
            intervals.ci_prop(5, 10, method="bogus")


class TestUnavailable:
    def test_status_unavailable_without_scipy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(intervals, "import_scipy_stats", lambda: None)
        for result in (
            intervals.ci_mean([1.0, 2.0, 3.0]),
            intervals.ci_prop(5, 10),
            intervals.ci_var(4.0, n=10),
            intervals.ci_var_ratio(4.0, 10, 2.0, 10),
            intervals.ci_prop_diff(5, 10, 3, 10),
        ):
            assert result["status"] == "unavailable"
            assert "data-quality-toolkit[stats]" in result["reason"]
