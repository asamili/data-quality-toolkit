"""Tests that every issue from assess() satisfies the minimum common contract."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from data_quality_toolkit.assessment.quality_checker import assess, detect_issues


def _ts() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _profile(rows: int, columns: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4()),
        "dataset_id": "sha1:contract-test",
        "rows": rows,
        "cols": len(columns),
        "memory_mb": 0.0,
        "ts": _ts(),
        "columns": columns,
    }


_COMMON_FIELDS = {"type", "column", "severity", "category", "message"}


# --- common contract on every issue from assess() ---


def test_null_issue_has_all_common_fields():
    prof = _profile(10, [{"name": "score", "dtype": "float64", "nulls": 8, "unique": 2}])
    issues = assess(prof)["issues"]
    null_issues = [i for i in issues if i["type"] == "missing"]
    assert null_issues, "Expected at least one missing issue"
    for issue in null_issues:
        missing = _COMMON_FIELDS - issue.keys()
        assert not missing, f"missing issue missing fields: {missing}"


def test_schema_issues_have_all_common_fields():
    prof = _profile(
        5,
        [
            {"name": "", "dtype": "object", "nulls": 0, "unique": 0},  # blank
            {"name": " price ", "dtype": "float64", "nulls": 0, "unique": 5},  # padded
            {"name": "null", "dtype": "object", "nulls": 0, "unique": 5},  # placeholder
            {"name": "id", "dtype": "int64", "nulls": 0, "unique": 5},
            {"name": "ID", "dtype": "int64", "nulls": 0, "unique": 5},  # duplicate
        ],
    )
    issues = assess(prof)["issues"]
    schema_types = {
        "blank_column_name",
        "padded_column_name",
        "placeholder_column_name",
        "duplicate_column_name",
    }
    for issue in issues:
        if issue["type"] in schema_types:
            missing = _COMMON_FIELDS - issue.keys()
            assert not missing, f"{issue['type']} missing fields: {missing}"


def test_all_issues_from_mixed_profile_satisfy_contract():
    """Regression: every single issue in a mixed profile has the common fields."""
    prof = _profile(
        10,
        [
            {"name": "null", "dtype": "object", "nulls": 9, "unique": 1},  # placeholder + high null
            {"name": " id ", "dtype": "int64", "nulls": 0, "unique": 10},  # padded
        ],
    )
    issues = assess(prof)["issues"]
    assert issues, "Expected at least one issue"
    for issue in issues:
        missing = _COMMON_FIELDS - issue.keys()
        assert not missing, f"Issue {issue['type']!r} is missing fields: {missing}"


# --- null issue specific fields ---


def test_null_issue_category_is_completeness():
    prof = _profile(10, [{"name": "age", "dtype": "int64", "nulls": 5, "unique": 5}])
    null_issues = [i for i in assess(prof)["issues"] if i["type"] == "missing"]
    assert null_issues
    assert dict(null_issues[0])["category"] == "Completeness"


def test_null_issue_message_contains_column_name_and_percentage():
    prof = _profile(10, [{"name": "revenue", "dtype": "float64", "nulls": 9, "unique": 1}])
    null_issues = [i for i in assess(prof)["issues"] if i["type"] == "missing"]
    assert null_issues
    msg: str = str(dict(null_issues[0])["message"])
    assert "revenue" in msg
    assert "90" in msg  # 9/10 = 90%


def test_null_issue_still_has_pct():
    """pct must still be present — additive normalization must not remove existing fields."""
    prof = _profile(10, [{"name": "x", "dtype": "int64", "nulls": 3, "unique": 7}])
    null_issues = [i for i in assess(prof)["issues"] if i["type"] == "missing"]
    assert null_issues
    issue_d = dict(null_issues[0])
    assert "pct" in issue_d
    assert issue_d["pct"] == pytest.approx(0.3)


# --- detect_issues() unit-level contract ---


def test_detect_issues_direct_has_common_fields():
    """The inner detect_issues() function also produces conforming issues."""
    prof = _profile(10, [{"name": "col", "dtype": "int64", "nulls": 3, "unique": 7}])
    issues = detect_issues(prof)
    for issue in issues:
        missing = _COMMON_FIELDS - issue.keys()
        assert not missing, f"detect_issues() issue missing fields: {missing}"
