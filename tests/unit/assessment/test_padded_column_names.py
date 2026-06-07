"""Tests for leading/trailing whitespace column name detection."""

from typing import Any

from data_quality_toolkit.domain.assessment.issue_detector import (
    _detect_padded_column_names,
    detect_issues,
)


def test_no_padding():
    cols = [{"name": "a"}, {"name": "my_col"}, {"name": "123"}]
    assert _detect_padded_column_names(cols) == []


def test_leading_space():
    issues = _detect_padded_column_names([{"name": " id"}])
    assert len(issues) == 1
    assert issues[0]["type"] == "padded_column_name"
    assert issues[0]["suggested"] == "id"
    assert issues[0]["severity"] == "medium"


def test_trailing_space():
    issues = _detect_padded_column_names([{"name": "id "}])
    assert len(issues) == 1
    assert issues[0]["type"] == "padded_column_name"
    assert issues[0]["suggested"] == "id"


def test_both_sides():
    issues = _detect_padded_column_names([{"name": "  col  "}])
    assert len(issues) == 1
    assert issues[0]["suggested"] == "col"


def test_tab_and_newline_padding():
    for padded in ["\tcol", "col\n", "\t col \t"]:
        issues = _detect_padded_column_names([{"name": padded}])
        assert len(issues) == 1, f"Expected issue for {repr(padded)}"
        assert issues[0]["type"] == "padded_column_name"


def test_whitespace_only_not_flagged_here():
    # Blank names are handled by _detect_blank_column_names, not this detector
    issues = _detect_padded_column_names([{"name": "   "}])
    assert issues == []


def test_non_string_ignored():
    issues = _detect_padded_column_names([{"name": None}, {"name": 42}])
    assert issues == []


def test_missing_name_key_ignored():
    issues = _detect_padded_column_names([{}])
    assert issues == []


def test_detect_issues_includes_padded():
    profile: dict[str, Any] = {"columns": [{"name": " price"}, {"name": "qty"}]}
    issues = detect_issues(profile)
    types = [i["type"] for i in issues]
    assert "padded_column_name" in types


def test_detect_issues_all_three_detectors():
    profile: dict[str, Any] = {
        "columns": [
            {"name": " id"},  # padded
            {"name": ""},  # blank
            {"name": "x"},
            {"name": "X"},  # duplicate of "x"
        ]
    }
    issues = detect_issues(profile)
    types = [i["type"] for i in issues]
    assert "padded_column_name" in types
    assert "blank_column_name" in types
    assert "duplicate_column_name" in types
