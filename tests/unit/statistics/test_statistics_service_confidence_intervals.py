"""Tests for the confidence-interval wrappers in the Statistics Lab UI service.

The service stays streamlit-free and delegates to the domain interval/bootstrap
kernel; these tests pin the delegation, the CI-shaped contract, the bounded
confidence choices, the interpretation string, and the scipy/no-scipy paths.
"""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.services import statistics as svc

_CI_KEYS = {"status", "reason", "method", "confidence", "point", "lower", "upper", "n"}


def _df(n: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame({"metric": rng.normal(5.0, 2.0, n), "label": ["a"] * n})


def test_service_stays_streamlit_free() -> None:
    src = inspect.getsource(svc)
    assert "import streamlit" not in src


def test_confidence_interval_choices_are_bounded() -> None:
    choices = svc.confidence_interval_choices()
    assert choices == (0.95, 0.90, 0.99)
    assert all(0.0 < c < 1.0 for c in choices)


def test_mean_confidence_interval_contract_keys() -> None:
    result = svc.mean_confidence_interval(_df(), "metric", confidence=0.95)
    assert _CI_KEYS <= set(result)
    assert result["status"] in {"ok", "unavailable"}
    assert result["confidence"] == 0.95


def test_mean_confidence_interval_ok_bounds_and_interpretation() -> None:
    pytest.importorskip("scipy")
    result = svc.mean_confidence_interval(_df(), "metric", confidence=0.95)
    assert result["status"] == "ok"
    assert result["method"] == "t"
    assert result["lower"] <= result["point"] <= result["upper"]
    assert "95% confident" in result["interpretation"]


def test_mean_confidence_interval_invalid_metric_is_ci_shaped() -> None:
    result = svc.mean_confidence_interval(pd.DataFrame({"name": ["a", "b"]}), "name")
    assert result["status"] == "invalid_input"
    assert _CI_KEYS <= set(result)
    assert "not numeric" in str(result["reason"])


def test_mean_confidence_interval_missing_column_is_ci_shaped() -> None:
    result = svc.mean_confidence_interval(_df(), "does_not_exist")
    assert result["status"] == "invalid_input"
    assert "not found" in str(result["reason"])


def test_bootstrap_percentile_is_pure_numpy_and_deterministic() -> None:
    first = svc.bootstrap_mean_confidence_interval(
        _df(), "metric", confidence=0.90, n_bootstrap=2000, method="percentile"
    )
    second = svc.bootstrap_mean_confidence_interval(
        _df(), "metric", confidence=0.90, n_bootstrap=2000, method="percentile"
    )
    assert first["status"] == "ok"
    assert first["method"] == "percentile"
    assert first["n_bootstrap"] == 2000
    assert first["lower"] <= first["point"] <= first["upper"]
    assert first["lower"] == second["lower"] and first["upper"] == second["upper"]
    assert "90% confident" in first["interpretation"]


def test_bootstrap_resamples_are_clamped_to_domain_max() -> None:
    result = svc.bootstrap_mean_confidence_interval(
        _df(), "metric", n_bootstrap=10_000_000, method="percentile"
    )
    assert result["status"] == "ok"
    assert result["n_bootstrap"] <= 100_000


def test_bootstrap_bca_path() -> None:
    pytest.importorskip("scipy")
    result = svc.bootstrap_mean_confidence_interval(
        _df(), "metric", confidence=0.95, n_bootstrap=2000, method="bca"
    )
    assert result["status"] == "ok"
    assert result["method"] == "bca"
    assert result["lower"] <= result["point"] <= result["upper"]


def test_bootstrap_invalid_metric_is_ci_shaped() -> None:
    result = svc.bootstrap_mean_confidence_interval(pd.DataFrame({"name": ["a", "b"]}), "name")
    assert result["status"] == "invalid_input"
    assert _CI_KEYS <= set(result)
    assert result["method"] == "percentile"
