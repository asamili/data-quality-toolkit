"""Unit tests for pure drift threshold evaluators (v2.6.1)."""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.application.monitoring.thresholds import (
    evaluate_drift_rate_threshold,
    evaluate_psi_threshold,
)

# ---------------------------------------------------------------------------
# evaluate_drift_rate_threshold
# ---------------------------------------------------------------------------


def test_drift_rate_below_threshold_not_breached():
    result = evaluate_drift_rate_threshold({"drift_rate": 0.2}, max_drift_rate=0.3)
    assert result["breached"] is False
    assert result["drift_rate"] == 0.2
    assert result["threshold"] == 0.3


def test_drift_rate_equal_threshold_not_breached():
    result = evaluate_drift_rate_threshold({"drift_rate": 0.3}, max_drift_rate=0.3)
    assert result["breached"] is False


def test_drift_rate_above_threshold_breached():
    result = evaluate_drift_rate_threshold({"drift_rate": 0.4}, max_drift_rate=0.3)
    assert result["breached"] is True
    assert result["drift_rate"] == 0.4


def test_drift_rate_missing_key_treated_as_zero():
    result = evaluate_drift_rate_threshold({}, max_drift_rate=0.3)
    assert result["breached"] is False
    assert result["drift_rate"] == 0.0


def test_drift_rate_none_treated_as_zero():
    result = evaluate_drift_rate_threshold({"drift_rate": None}, max_drift_rate=0.3)
    assert result["breached"] is False
    assert result["drift_rate"] == 0.0


def test_drift_rate_boundary_zero_threshold_not_breached():
    result = evaluate_drift_rate_threshold({"drift_rate": 0.0}, max_drift_rate=0.0)
    assert result["breached"] is False


def test_drift_rate_boundary_one_threshold():
    result = evaluate_drift_rate_threshold({"drift_rate": 1.0}, max_drift_rate=1.0)
    assert result["breached"] is False


def test_drift_rate_result_is_json_ready():
    result = evaluate_drift_rate_threshold({"drift_rate": 0.5}, max_drift_rate=0.4)
    assert isinstance(result["breached"], bool)
    assert isinstance(result["drift_rate"], float)
    assert isinstance(result["threshold"], float)
    assert set(result.keys()) == {"breached", "drift_rate", "threshold"}


# ---------------------------------------------------------------------------
# evaluate_psi_threshold
# ---------------------------------------------------------------------------


def test_psi_below_threshold_not_breached():
    cols = [{"column_name": "a", "psi": 0.1}]
    result = evaluate_psi_threshold(cols, max_psi=0.2)
    assert result["breached"] is False
    assert result["offenders"] == []


def test_psi_equal_threshold_not_breached():
    cols = [{"column_name": "a", "psi": 0.2}]
    result = evaluate_psi_threshold(cols, max_psi=0.2)
    assert result["breached"] is False
    assert result["offenders"] == []


def test_psi_above_threshold_breached():
    cols = [{"column_name": "a", "psi": 0.25}]
    result = evaluate_psi_threshold(cols, max_psi=0.2)
    assert result["breached"] is True
    assert len(result["offenders"]) == 1
    assert result["offenders"][0] == {"column_name": "a", "psi": 0.25}


def test_psi_none_skipped_safely():
    cols = [{"column_name": "a", "psi": None}]
    result = evaluate_psi_threshold(cols, max_psi=0.2)
    assert result["breached"] is False
    assert result["offenders"] == []


def test_psi_empty_columns_not_breached():
    result = evaluate_psi_threshold([], max_psi=0.2)
    assert result["breached"] is False
    assert result["offenders"] == []


def test_psi_mixed_none_and_above():
    cols: list[dict[str, Any]] = [
        {"column_name": "a", "psi": None},
        {"column_name": "b", "psi": 0.3},
        {"column_name": "c", "psi": 0.1},
    ]
    result = evaluate_psi_threshold(cols, max_psi=0.2)
    assert result["breached"] is True
    assert result["offenders"] == [{"column_name": "b", "psi": 0.3}]


def test_psi_offender_ordering_matches_input():
    cols: list[dict[str, Any]] = [
        {"column_name": "z", "psi": 0.5},
        {"column_name": "a", "psi": 0.4},
        {"column_name": "m", "psi": 0.6},
    ]
    result = evaluate_psi_threshold(cols, max_psi=0.3)
    names = [o["column_name"] for o in result["offenders"]]
    assert names == ["z", "a", "m"]


def test_psi_threshold_zero_boundary():
    cols = [{"column_name": "a", "psi": 0.0}]
    result = evaluate_psi_threshold(cols, max_psi=0.0)
    assert result["breached"] is False


def test_psi_result_is_json_ready():
    cols = [{"column_name": "a", "psi": 0.25}]
    result = evaluate_psi_threshold(cols, max_psi=0.2)
    assert isinstance(result["breached"], bool)
    assert isinstance(result["threshold"], float)
    assert isinstance(result["offenders"], list)
    assert set(result.keys()) == {"breached", "threshold", "offenders"}
    offender = result["offenders"][0]
    assert set(offender.keys()) == {"column_name", "psi"}
