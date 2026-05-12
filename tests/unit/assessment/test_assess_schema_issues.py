"""Tests that assess() surfaces schema issues alongside null/missing issues."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from data_quality_toolkit.assessment.quality_checker import assess


def _ts() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _profile(rows: int, columns: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4()),
        "dataset_id": "sha1:test",
        "rows": rows,
        "cols": len(columns),
        "memory_mb": 0.0,
        "ts": _ts(),
        "columns": columns,
    }


# --- schema issues surface through assess() ---


def test_blank_column_name_appears_in_issues():
    prof = _profile(5, [{"name": "", "dtype": "int64", "nulls": 0, "unique": 5}])
    out = assess(prof)
    types = [i["type"] for i in out["issues"]]
    assert "blank_column_name" in types


def test_placeholder_column_name_appears_in_issues():
    prof = _profile(5, [{"name": "null", "dtype": "int64", "nulls": 0, "unique": 5}])
    out = assess(prof)
    types = [i["type"] for i in out["issues"]]
    assert "placeholder_column_name" in types


def test_padded_column_name_appears_in_issues():
    prof = _profile(5, [{"name": " price ", "dtype": "float64", "nulls": 0, "unique": 5}])
    out = assess(prof)
    types = [i["type"] for i in out["issues"]]
    assert "padded_column_name" in types


def test_duplicate_column_name_appears_in_issues():
    prof = _profile(
        5,
        [
            {"name": "id", "dtype": "int64", "nulls": 0, "unique": 5},
            {"name": "id", "dtype": "int64", "nulls": 0, "unique": 5},
        ],
    )
    out = assess(prof)
    types = [i["type"] for i in out["issues"]]
    assert "duplicate_column_name" in types


# --- both null and schema issues coexist ---


def test_null_and_schema_issues_coexist():
    prof = _profile(
        10,
        [
            {"name": "null", "dtype": "int64", "nulls": 9, "unique": 1},  # placeholder + high null
        ],
    )
    out = assess(prof)
    types = [i["type"] for i in out["issues"]]
    assert "placeholder_column_name" in types
    assert "missing" in types


# --- regression: clean profile produces no issues ---


def test_clean_profile_no_issues():
    prof = _profile(
        10,
        [
            {"name": "id", "dtype": "int64", "nulls": 0, "unique": 10},
            {"name": "value", "dtype": "float64", "nulls": 0, "unique": 10},
        ],
    )
    out = assess(prof)
    assert out["issues"] == []


# --- regression: null-only issues still work after integration ---


def test_null_issue_still_detected():
    prof = _profile(
        10,
        [{"name": "amount", "dtype": "float64", "nulls": 8, "unique": 2}],
    )
    out = assess(prof)
    types = [i["type"] for i in out["issues"]]
    assert "missing" in types
    assert out["score"] < 1.0
