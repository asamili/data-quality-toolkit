"""Tests for per-column rules in assessment."""

from typing import Any

import pandas as pd

from data_quality_toolkit.domain.assessment import issue_detector
from data_quality_toolkit.domain.assessment.quality_checker import (
    assess,
    detect_issues,
)


def test_per_column_null_threshold_override():
    profile = {
        "run_id": "test-run",
        "dataset_id": "test-ds",
        "ts": "2026-01-01T00:00:00Z",
        "rows": 100,
        "cols": 2,
        "columns": [
            {"name": "col_strict", "nulls": 5, "dtype": "int"},  # 5% null
            {"name": "col_lenient", "nulls": 30, "dtype": "int"},  # 30% null
        ],
    }

    # Case 1: Global threshold 0.2
    # col_strict (0.05) < 0.2 -> OK
    # col_lenient (0.3) > 0.2 -> ISSUE
    config_none: dict[str, Any] = {"columns": {}}
    issues = detect_issues(profile, null_threshold=0.2, config=config_none)
    assert len(issues) == 1
    assert issues[0]["column"] == "col_lenient"

    # Case 2: Per-column override
    # col_strict: null_threshold=0.01 -> ISSUE (0.05 > 0.01)
    # col_lenient: null_threshold=0.4 -> OK (0.3 < 0.4)
    config_override = {
        "columns": {"col_strict": {"null_threshold": 0.01}, "col_lenient": {"null_threshold": 0.4}}
    }
    issues_override = detect_issues(profile, null_threshold=0.2, config=config_override)
    assert len(issues_override) == 1
    assert issues_override[0]["column"] == "col_strict"


def test_required_column_check():
    profile = {
        "run_id": "test-run",
        "dataset_id": "test-ds",
        "ts": "2026-01-01T00:00:00Z",
        "rows": 100,
        "cols": 1,
        "columns": [
            {"name": "present_col", "nulls": 0, "dtype": "int"},
        ],
    }

    # Case 1: Required column is present -> OK
    config_ok = {"columns": {"present_col": {"required": True}}}
    issues_ok = issue_detector.detect_issues(profile, config=config_ok)
    assert not any(i["type"] == "missing_required_column" for i in issues_ok)

    # Case 2: Required column is missing -> ISSUE
    config_missing = {"columns": {"missing_col": {"required": True}}}
    issues_missing = issue_detector.detect_issues(profile, config=config_missing)
    required_issues = [i for i in issues_missing if i["type"] == "missing_required_column"]
    assert len(required_issues) == 1
    assert required_issues[0]["column"] == "missing_col"
    assert required_issues[0]["severity"] == "critical"

    # Case 3: Optional column is missing -> OK
    config_optional = {"columns": {"optional_col": {"required": False}}}
    issues_optional = issue_detector.detect_issues(profile, config=config_optional)
    assert not any(i["type"] == "missing_required_column" for i in issues_optional)


def test_per_column_high_cardinality_threshold():
    profile = {
        "rows": 100,
        "columns": [
            {"name": "col1", "unique": 95, "dtype": "object"},  # 95% unique
        ],
    }

    # Default threshold is usually 0.9. 0.95 > 0.9 -> ISSUE
    config_none: dict[str, Any] = {"columns": {}}
    issues = issue_detector.detect_advanced_issues(None, profile, config=config_none)
    assert len(issues) == 1
    assert issues[0]["type"] == "high_cardinality"

    # Override to 0.96 -> OK
    config_override = {"columns": {"col1": {"high_cardinality_threshold": 0.96}}}
    issues_override = issue_detector.detect_advanced_issues(None, profile, config=config_override)
    assert not any(i["type"] == "high_cardinality" for i in issues_override)


def test_per_column_outlier_threshold():
    # Mock DataFrame with outliers
    # IQR: Q1=2.75, Q3=8.25, IQR=5.5. Upper=8.25 + 1.5*5.5 = 16.5
    data = {"val": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100]}  # 1/11 = ~9% outliers
    df = pd.DataFrame(data)
    profile = {"rows": 11, "columns": [{"name": "val", "dtype": "float"}]}

    # Default outlier threshold is 0.05. 0.09 > 0.05 -> ISSUE
    config_none: dict[str, Any] = {"columns": {}}
    issues = issue_detector.detect_advanced_issues(df, profile, config=config_none)
    assert any(i["type"] == "numeric_outliers" for i in issues)

    # Override to 0.10 -> OK
    config_override = {"columns": {"val": {"outlier_threshold": 0.10}}}
    issues_override = issue_detector.detect_advanced_issues(df, profile, config=config_override)
    assert not any(i["type"] == "numeric_outliers" for i in issues_override)


def test_assess_backward_compatibility():
    # Ensure assess still works without config (should load dqt.yaml or use empty)
    profile = {
        "run_id": "test-run",
        "dataset_id": "test-ds",
        "ts": "2026-01-01T00:00:00Z",
        "rows": 100,
        "cols": 1,
        "columns": [
            {"name": "col1", "nulls": 0, "dtype": "int"},
        ],
    }
    result = assess(profile)
    assert "quality_score" in result
    assert result["score"] == 1.0


# ---------------------------------------------------------------------------
# Column-level fail_under
# ---------------------------------------------------------------------------

_BASE_PROFILE: dict[str, Any] = {
    "run_id": "test-run",
    "dataset_id": "test-ds",
    "ts": "2026-01-01T00:00:00Z",
    "rows": 100,
    "cols": 1,
    "columns": [],
}


def _profile_with(nulls: int) -> dict[str, Any]:
    return {**_BASE_PROFILE, "columns": [{"name": "revenue", "nulls": nulls, "dtype": "float"}]}


def test_column_fail_under_absent_no_issue():
    # No fail_under configured → no gate issue regardless of completeness
    config: dict[str, Any] = {"columns": {}}
    result = assess(_profile_with(nulls=50), config=config)
    gate_issues = [i for i in result["issues"] if i["type"] == "column_quality_gate_failed"]
    assert gate_issues == []


def test_column_fail_under_completeness_above_gate_no_issue():
    # 5% null → completeness 0.95; gate 0.90 → 0.95 >= 0.90 → no issue
    config: dict[str, Any] = {"columns": {"revenue": {"fail_under": 0.90}}}
    result = assess(_profile_with(nulls=5), config=config)
    gate_issues = [i for i in result["issues"] if i["type"] == "column_quality_gate_failed"]
    assert gate_issues == []


def test_column_fail_under_completeness_equal_gate_no_issue():
    # 10% null → completeness 0.90; gate 0.90 → 0.90 < 0.90 is False → no issue (strict <)
    config: dict[str, Any] = {"columns": {"revenue": {"fail_under": 0.90}}}
    result = assess(_profile_with(nulls=10), config=config)
    gate_issues = [i for i in result["issues"] if i["type"] == "column_quality_gate_failed"]
    assert gate_issues == []


def test_column_fail_under_completeness_below_gate_fires():
    # 20% null → completeness 0.80; gate 0.90 → 0.80 < 0.90 → issue
    config: dict[str, Any] = {"columns": {"revenue": {"fail_under": 0.90}}}
    result = assess(_profile_with(nulls=20), config=config)
    gate_issues = [i for i in result["issues"] if i["type"] == "column_quality_gate_failed"]
    assert len(gate_issues) == 1
    assert gate_issues[0]["column"] == "revenue"


def test_column_fail_under_issue_severity_is_critical():
    config: dict[str, Any] = {"columns": {"revenue": {"fail_under": 0.90}}}
    result = assess(_profile_with(nulls=20), config=config)
    gate_issues = [i for i in result["issues"] if i["type"] == "column_quality_gate_failed"]
    assert gate_issues[0]["severity"] == "critical"


def test_column_fail_under_issue_message_contains_percentages():
    config: dict[str, Any] = {"columns": {"revenue": {"fail_under": 0.90}}}
    result = assess(_profile_with(nulls=20), config=config)
    gate_issues = [i for i in result["issues"] if i["type"] == "column_quality_gate_failed"]
    msg = gate_issues[0]["message"]
    assert "80.0%" in msg
    assert "90.0%" in msg


def test_column_fail_under_issue_penalizes_quality_score():
    # Gate failure generates critical issue → quality_score is reduced
    config: dict[str, Any] = {"columns": {"revenue": {"fail_under": 0.90}}}
    result_with_gate = assess(_profile_with(nulls=20), config=config)
    result_without_gate = assess(_profile_with(nulls=20), config={"columns": {}})
    assert result_with_gate["quality_score"] < result_without_gate["quality_score"]


def test_column_fail_under_critical_flag_doubles_penalty():
    # critical: true + column_quality_gate_failed → 2× critical penalty applied
    config_plain: dict[str, Any] = {"columns": {"revenue": {"fail_under": 0.90}}}
    config_critical: dict[str, Any] = {
        "columns": {"revenue": {"fail_under": 0.90, "critical": True}}
    }
    result_plain = assess(_profile_with(nulls=20), config=config_plain)
    result_critical = assess(_profile_with(nulls=20), config=config_critical)
    assert result_critical["quality_score"] <= result_plain["quality_score"]
