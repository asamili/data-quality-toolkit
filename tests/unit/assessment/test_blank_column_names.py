"""Tests for blank/whitespace-only column name detection."""

from typing import Any

from data_quality_toolkit.domain.assessment.issue_detector import (
    _detect_blank_column_names,
    detect_issues,
)


def test_no_blank_names():
    cols = [{"name": "a"}, {"name": "b"}]
    assert _detect_blank_column_names(cols) == []


def test_empty_string_name():
    issues = _detect_blank_column_names([{"name": ""}])
    assert len(issues) == 1
    assert issues[0]["type"] == "blank_column_name"
    assert issues[0]["severity"] == "high"


def test_whitespace_only_name():
    for blank in ["   ", "\t", "\n", " \t "]:
        issues = _detect_blank_column_names([{"name": blank}])
        assert len(issues) == 1, f"Expected issue for {repr(blank)}"
        assert issues[0]["type"] == "blank_column_name"


def test_non_string_name_ignored():
    # Non-string names (e.g. None, int) are not flagged by this detector
    issues = _detect_blank_column_names([{"name": None}, {"name": 0}])
    assert issues == []


def test_missing_name_key_flagged():
    # Missing "name" key defaults to "" which is blank — should be flagged
    issues = _detect_blank_column_names([{}])
    assert len(issues) == 1
    assert issues[0]["type"] == "blank_column_name"


def test_detect_issues_includes_blank():
    profile: dict[str, Any] = {"columns": [{"name": ""}, {"name": "valid"}]}
    issues = detect_issues(profile)
    types = [i["type"] for i in issues]
    assert "blank_column_name" in types


def test_detect_issues_both_detectors():
    profile: dict[str, Any] = {"columns": [{"name": ""}, {"name": "id"}, {"name": "id"}]}
    issues = detect_issues(profile)
    types = [i["type"] for i in issues]
    assert "blank_column_name" in types
    assert "duplicate_column_name" in types
