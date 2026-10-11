"""Tests for the power/sample-size wrappers in the Statistics Lab UI service.

The service stays streamlit-free and delegates to the closed-form
``domain.statistics.power`` kernel; these tests pin the delegation, the bounded
target-power choices, the invalid-input status handling (no exceptions leak),
and the scipy/no-scipy paths.
"""

from __future__ import annotations

import inspect

import pytest

from data_quality_toolkit.adapters.ui.services import statistics as svc
from data_quality_toolkit.domain.statistics import power


def test_service_stays_streamlit_free() -> None:
    src = inspect.getsource(svc)
    assert "import streamlit" not in src


def test_power_target_choices_are_bounded() -> None:
    choices = svc.power_target_choices()
    assert choices == (0.80, 0.90, 0.95)
    assert all(0.0 < c < 1.0 for c in choices)


def test_power_mean_ok_path() -> None:
    pytest.importorskip("scipy")
    result = svc.power_mean(50, 0.5, 1.0, alpha=0.05)
    assert result["status"] == "ok"
    assert result["method"] == "normal_power_mean"
    assert 0.0 <= result["power"] <= 1.0


def test_power_prop_ok_path() -> None:
    pytest.importorskip("scipy")
    result = svc.power_prop(100, 0.5, 0.6, alpha=0.05)
    assert result["status"] == "ok"
    assert result["method"] == "normal_power_prop"
    assert 0.0 <= result["power"] <= 1.0


def test_required_n_mean_known_value() -> None:
    pytest.importorskip("scipy")
    result = svc.required_n_mean(0.5, 1.0, alpha=0.05, power=0.8)
    assert result["status"] == "ok"
    assert result["method"] == "normal_n_mean"
    assert result["n"] == 32


def test_required_n_prop_ok_path() -> None:
    pytest.importorskip("scipy")
    result = svc.required_n_prop(0.5, 0.6, alpha=0.05, power=0.8)
    assert result["status"] == "ok"
    assert result["method"] == "normal_n_prop"
    assert result["n1"] > 0 and result["n2"] > 0


def test_required_n_variance_ok_and_invalid() -> None:
    pytest.importorskip("scipy")
    ok = svc.required_n_variance(2.0, alpha=0.05, power=0.8)
    assert ok["status"] == "ok"
    assert ok["method"] == "normal_n_variance"
    assert ok["n"] > 0
    invalid = svc.required_n_variance(1.0)
    assert invalid["status"] == "invalid_input"


def test_required_n_cohend_ok_scalar_and_invalid() -> None:
    pytest.importorskip("scipy")
    ok = svc.required_n_cohend(0.5, alpha=0.05, power=0.8)
    assert ok["status"] == "ok"
    assert ok["method"] == "normal_n_cohend"
    assert isinstance(ok["n_per_group"], int) and ok["n_per_group"] > 0
    # Guard against the extracted tuple-return bug: n1/n2 must not appear.
    assert "n1" not in ok and "n2" not in ok
    invalid = svc.required_n_cohend(0.0)
    assert invalid["status"] == "invalid_input"


def test_invalid_numeric_returns_status_not_exception() -> None:
    result = svc.required_n_mean(0.0, 1.0)
    assert result["status"] == "invalid_input"
    assert "delta" in str(result["reason"])


def test_bad_alpha_is_caught_as_invalid_input() -> None:
    # The domain raises ValueError on out-of-range alpha; the service converts it
    # to an invalid_input status dict rather than letting it propagate.
    result = svc.power_mean(50, 0.5, 1.0, alpha=1.5)
    assert result["status"] == "invalid_input"
    assert "alpha" in str(result["reason"])


def test_bad_alternative_is_caught_as_invalid_input() -> None:
    result = svc.required_n_mean(0.5, 1.0, alternative="sideways")
    assert result["status"] == "invalid_input"
    assert "alternative" in str(result["reason"])


def test_scipy_absent_degrades_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(power, "import_scipy_stats", lambda: None)
    for result in (
        svc.power_mean(50, 0.5, 1.0),
        svc.power_prop(100, 0.5, 0.6),
        svc.required_n_mean(0.5, 1.0),
        svc.required_n_prop(0.5, 0.6),
        svc.required_n_variance(2.0),
        svc.required_n_cohend(0.5),
    ):
        assert result["status"] == "unavailable"
