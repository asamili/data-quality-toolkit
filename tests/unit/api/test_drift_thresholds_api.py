"""API-seam tests for evaluate_drift_rate_threshold and evaluate_psi_threshold (v2.6.1)."""

from __future__ import annotations

from data_quality_toolkit.api import evaluate_drift_rate_threshold, evaluate_psi_threshold


def test_evaluate_drift_rate_threshold_importable():
    result = evaluate_drift_rate_threshold({"drift_rate": 0.4}, max_drift_rate=0.3)
    assert result["breached"] is True
    assert result["drift_rate"] == 0.4
    assert result["threshold"] == 0.3


def test_evaluate_drift_rate_threshold_not_breached():
    result = evaluate_drift_rate_threshold({"drift_rate": 0.2}, max_drift_rate=0.3)
    assert result["breached"] is False


def test_evaluate_drift_rate_threshold_missing_db_zero_summary():
    result = evaluate_drift_rate_threshold({"drift_rate": 0.0}, max_drift_rate=0.3)
    assert result["breached"] is False


def test_evaluate_psi_threshold_importable():
    result = evaluate_psi_threshold([{"column_name": "a", "psi": 0.25}], max_psi=0.2)
    assert result["breached"] is True
    assert result["offenders"] == [{"column_name": "a", "psi": 0.25}]


def test_evaluate_psi_threshold_not_breached():
    result = evaluate_psi_threshold([{"column_name": "a", "psi": 0.1}], max_psi=0.2)
    assert result["breached"] is False
    assert result["offenders"] == []


def test_evaluate_psi_threshold_none_skipped():
    result = evaluate_psi_threshold([{"column_name": "a", "psi": None}], max_psi=0.2)
    assert result["breached"] is False


def test_evaluate_psi_threshold_empty_columns():
    result = evaluate_psi_threshold([], max_psi=0.2)
    assert result["breached"] is False
    assert result["offenders"] == []
