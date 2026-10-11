"""Tests for bootstrap confidence intervals (percentile + BCa)."""

from __future__ import annotations

from typing import cast

import numpy as np
import pytest

from data_quality_toolkit.domain.statistics import bootstrap


def _sample() -> list[float]:
    rng = np.random.default_rng(42)
    return cast(list[float], rng.normal(10.0, 2.0, 200).tolist())


class TestPercentile:
    def test_contains_point_and_ordered(self) -> None:
        result = bootstrap.bootstrap_ci(_sample(), n_bootstrap=2000, seed=0)
        assert result["status"] == "ok"
        assert result["method"] == "percentile"
        assert result["lower"] < result["point"] < result["upper"]
        assert result["point"] == pytest.approx(10.0, abs=0.5)

    def test_deterministic_for_fixed_seed(self) -> None:
        a = bootstrap.bootstrap_ci(_sample(), n_bootstrap=1000, seed=7)
        b = bootstrap.bootstrap_ci(_sample(), n_bootstrap=1000, seed=7)
        assert a["lower"] == b["lower"]
        assert a["upper"] == b["upper"]

    def test_bounded_n_bootstrap(self) -> None:
        result = bootstrap.bootstrap_ci(_sample(), n_bootstrap=10_000_000, seed=0)
        assert result["n_bootstrap"] == bootstrap.MAX_N_BOOTSTRAP

    def test_insufficient_data(self) -> None:
        result = bootstrap.bootstrap_ci([1.0], n_bootstrap=100)
        assert result["status"] == "insufficient_data"


class TestBca:
    def test_bca_runs_with_scipy(self) -> None:
        pytest.importorskip("scipy")
        result = bootstrap.bootstrap_ci(_sample(), method="bca", n_bootstrap=1000, seed=0)
        assert result["status"] == "ok"
        assert result["method"] == "bca"
        assert result["lower"] < result["point"] < result["upper"]

    def test_bca_unavailable_without_scipy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(bootstrap, "import_scipy_stats", lambda: None)
        result = bootstrap.bootstrap_ci([1.0, 2.0, 3.0, 4.0], method="bca", n_bootstrap=100)
        assert result["status"] == "unavailable"

    def test_percentile_works_without_scipy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(bootstrap, "import_scipy_stats", lambda: None)
        result = bootstrap.bootstrap_ci([1.0, 2.0, 3.0, 4.0, 5.0], n_bootstrap=500, seed=1)
        assert result["status"] == "ok"  # percentile never needs scipy


def test_unknown_method_raises() -> None:
    with pytest.raises(ValueError, match="method"):
        bootstrap.bootstrap_ci([1.0, 2.0, 3.0], method="bogus")
