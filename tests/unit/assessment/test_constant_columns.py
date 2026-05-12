"""Tests for constant-column detection."""

from typing import Any

from data_quality_toolkit.assessment.issue_detector import (
    _detect_constant_columns,
    detect_issues,
)


def test_constant_column_fires():
    cols = [{"name": "status", "unique": 1}]
    issues = _detect_constant_columns(cols)
    assert len(issues) == 1
    assert issues[0]["type"] == "constant_column"
    assert issues[0]["column"] == "status"
    assert issues[0]["severity"] == "medium"
    assert issues[0]["category"] == "Completeness"
    assert "status" in issues[0]["message"]


def test_non_constant_column_no_issue():
    cols = [{"name": "city", "unique": 5}]
    assert _detect_constant_columns(cols) == []


def test_all_null_column_skipped():
    # unique == 0 means all values are null; should not fire
    cols = [{"name": "empty_col", "unique": 0}]
    assert _detect_constant_columns(cols) == []


def test_missing_unique_field_skipped():
    # Columns without a 'unique' key should be silently skipped
    cols = [{"name": "no_stats"}]
    assert _detect_constant_columns(cols) == []


def test_multiple_columns_only_constant_flagged():
    cols = [
        {"name": "id", "unique": 100},
        {"name": "flag", "unique": 1},
        {"name": "score", "unique": 50},
    ]
    issues = _detect_constant_columns(cols)
    assert len(issues) == 1
    assert issues[0]["column"] == "flag"


def test_detect_issues_includes_constant_column():
    profile: dict[str, Any] = {"columns": [{"name": "region", "unique": 1}]}
    issues = detect_issues(profile)
    types = [i["type"] for i in issues]
    assert "constant_column" in types
