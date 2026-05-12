"""Tests for suspicious placeholder column name detection."""

from typing import Any

import pytest

from data_quality_toolkit.assessment.issue_detector import (
    _detect_placeholder_column_names,
    detect_issues,
)


@pytest.mark.parametrize(
    "name",
    [
        "unnamed",
        "Unnamed",
        "UNNAMED",
        "unnamed: 0",
        "unnamed: 12",
        "unknown",
        "Unknown",
        "n/a",
        "N/A",
        "na",
        "NA",
        "none",
        "None",
        "NONE",
        "null",
        "NULL",
    ],
)
def test_placeholder_flagged(name: str):
    issues = _detect_placeholder_column_names([{"name": name}])
    assert len(issues) == 1, f"Expected issue for {repr(name)}"
    assert issues[0]["type"] == "placeholder_column_name"
    assert issues[0]["severity"] == "medium"
    assert issues[0]["column"] == name


@pytest.mark.parametrize(
    "name",
    [
        "id",
        "price",
        "customer_name",
        "na_flag",  # starts with "na" but is not exactly "na"
        "unnamed_col",  # starts with "unnamed" but no colon — not a pattern match
        "is_null",  # contains "null" but is not exactly "null"
    ],
)
def test_legitimate_names_not_flagged(name: str):
    issues = _detect_placeholder_column_names([{"name": name}])
    assert issues == [], f"Did not expect issue for {repr(name)}"


def test_blank_name_not_flagged_here():
    # Blank names are handled by _detect_blank_column_names
    issues = _detect_placeholder_column_names([{"name": ""}, {"name": "   "}])
    assert issues == []


def test_non_string_ignored():
    issues = _detect_placeholder_column_names([{"name": None}, {"name": 0}])
    assert issues == []


def test_missing_name_key_ignored():
    issues = _detect_placeholder_column_names([{}])
    assert issues == []


def test_multiple_placeholders():
    cols = [{"name": "null"}, {"name": "n/a"}, {"name": "real_col"}]
    issues = _detect_placeholder_column_names(cols)
    assert len(issues) == 2
    flagged = {i["column"] for i in issues}
    assert flagged == {"null", "n/a"}


def test_detect_issues_includes_placeholder():
    profile: dict[str, Any] = {"columns": [{"name": "unnamed: 0"}, {"name": "qty"}]}
    issues = detect_issues(profile)
    types = [i["type"] for i in issues]
    assert "placeholder_column_name" in types


def test_detect_issues_all_four_detectors():
    profile: dict[str, Any] = {
        "columns": [
            {"name": "null"},  # placeholder
            {"name": ""},  # blank
            {"name": " price"},  # padded
            {"name": "id"},
            {"name": "ID"},  # duplicate of "id"
        ]
    }
    issues = detect_issues(profile)
    types = [i["type"] for i in issues]
    assert "placeholder_column_name" in types
    assert "blank_column_name" in types
    assert "padded_column_name" in types
    assert "duplicate_column_name" in types
