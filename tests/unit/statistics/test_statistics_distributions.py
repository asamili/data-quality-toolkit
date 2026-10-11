"""Tests for the scipy-guarded distribution wrappers.

Real-scipy correctness (areas/sums/bounds) behind importorskip, parameter
validation, and the scipy-unavailable path returning ``None``.
"""

from __future__ import annotations

import numpy as np
import pytest

from data_quality_toolkit.domain.statistics import distributions as dist

pytestmark = pytest.mark.filterwarnings("ignore")


class TestRealScipy:
    def setup_method(self) -> None:
        pytest.importorskip("scipy")

    def test_normal_pdf_peak(self) -> None:
        assert dist.normal_pdf(0.0) == pytest.approx(0.3989422804, abs=1e-7)

    def test_normal_cdf_symmetry(self) -> None:
        assert dist.normal_cdf(0.0) == pytest.approx(0.5)

    def test_t_cdf_center(self) -> None:
        assert dist.t_cdf(0.0, df=10) == pytest.approx(0.5)

    def test_chi2_cdf_bounds(self) -> None:
        value = dist.chi2_cdf(5.0, df=3)
        assert value is not None
        assert 0.0 <= value <= 1.0

    def test_f_cdf_bounds(self) -> None:
        value = dist.f_cdf(2.0, df1=3, df2=10)
        assert value is not None
        assert 0.0 <= value <= 1.0

    def test_binom_pmf_sums_to_one(self) -> None:
        values = [dist.binom_pmf(k, n=10, p=0.3) for k in range(11)]
        assert all(value is not None for value in values)
        total = sum(value for value in values if value is not None)
        assert total == pytest.approx(1.0, abs=1e-9)

    def test_binom_cdf_reaches_one(self) -> None:
        assert dist.binom_cdf(10, n=10, p=0.3) == pytest.approx(1.0, abs=1e-9)

    def test_poisson_pmf_sums_to_one(self) -> None:
        values = [dist.poisson_pmf(k, lam=3.0) for k in range(60)]
        assert all(value is not None for value in values)
        total = sum(value for value in values if value is not None)
        assert total == pytest.approx(1.0, abs=1e-6)

    def test_uniform_pdf_height(self) -> None:
        assert dist.uniform_pdf(0.5, a=0.0, b=2.0) == pytest.approx(0.5)

    def test_exponential_cdf_at_mean(self) -> None:
        # rate lam=1 -> cdf(1) = 1 - e^-1
        assert dist.exponential_cdf(1.0, lam=1.0) == pytest.approx(1 - np.e**-1, abs=1e-9)


class TestValidation:
    def test_normal_rejects_nonpositive_sigma(self) -> None:
        with pytest.raises(ValueError, match="sigma"):
            dist.normal_pdf(0.0, sigma=0.0)

    def test_t_rejects_nonpositive_df(self) -> None:
        with pytest.raises(ValueError, match="df"):
            dist.t_pdf(0.0, df=0)

    def test_binom_rejects_bad_p(self) -> None:
        with pytest.raises(ValueError, match="p"):
            dist.binom_pmf(1, n=5, p=1.5)

    def test_poisson_rejects_nonpositive_lam(self) -> None:
        with pytest.raises(ValueError, match="lam"):
            dist.poisson_pmf(1, lam=0.0)

    def test_uniform_rejects_bad_bounds(self) -> None:
        with pytest.raises(ValueError, match="a < b"):
            dist.uniform_pdf(0.5, a=1.0, b=0.0)


class TestUnavailable:
    def test_returns_none_without_scipy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dist, "import_scipy_stats", lambda: None)
        assert dist.normal_pdf(0.0) is None
        assert dist.t_cdf(0.0, df=10) is None
        assert dist.binom_pmf(1, n=5, p=0.3) is None
        # Validation still happens before the scipy check.
        with pytest.raises(ValueError, match="sigma"):
            dist.normal_pdf(0.0, sigma=-1.0)
