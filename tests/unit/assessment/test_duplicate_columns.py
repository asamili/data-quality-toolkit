"""Tests for duplicate column name detection."""

from typing import Any

from data_quality_toolkit.domain.assessment.issue_detector import (
    _detect_duplicate_column_names,
    detect_issues,
)


def test_no_duplicates():
    cols = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
    assert _detect_duplicate_column_names(cols) == []


def test_exact_duplicate():
    cols = [{"name": "id"}, {"name": "id"}]
    issues = _detect_duplicate_column_names(cols)
    assert len(issues) == 1
    assert issues[0]["type"] == "duplicate_column_name"
    assert issues[0]["column"] == "id"
    assert issues[0]["first_seen_as"] == "id"
    assert issues[0]["severity"] == "high"


def test_case_insensitive_duplicate():
    cols = [{"name": "Name"}, {"name": "name"}]
    issues = _detect_duplicate_column_names(cols)
    assert len(issues) == 1
    assert issues[0]["column"] == "name"
    assert issues[0]["first_seen_as"] == "Name"


def test_multiple_duplicates():
    cols = [{"name": "a"}, {"name": "A"}, {"name": "b"}, {"name": "B"}]
    issues = _detect_duplicate_column_names(cols)
    assert len(issues) == 2


def test_detect_issues_delegates():
    profile: dict[str, Any] = {"columns": [{"name": "x"}, {"name": "X"}]}
    issues = detect_issues(profile)
    assert len(issues) == 1
    assert issues[0]["type"] == "duplicate_column_name"


def test_detect_issues_empty():
    assert detect_issues({}) == []
    assert detect_issues({"columns": []}) == []
