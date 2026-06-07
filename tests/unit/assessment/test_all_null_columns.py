"""Tests for all_null_column detection."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from data_quality_toolkit.domain.assessment.issue_detector import (
    _detect_all_null_columns,
    detect_issues,
)
from data_quality_toolkit.domain.assessment.quality_checker import assess

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _profile(rows: int, columns: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4()),
        "dataset_id": "sha1:test",
        "rows": rows,
        "cols": len(columns),
        "memory_mb": 0.0,
        "ts": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "columns": columns,
    }


# ---------------------------------------------------------------------------
# _detect_all_null_columns — unit
# ---------------------------------------------------------------------------


def test_all_null_column_fires():
    cols = [{"name": "score", "nulls": 5}]
    issues = _detect_all_null_columns(cols, rows=5)
    assert len(issues) == 1
    assert issues[0]["type"] == "all_null_column"
    assert issues[0]["column"] == "score"
    assert issues[0]["severity"] == "high"
    assert issues[0]["category"] == "Completeness"
    assert "score" in issues[0]["message"]
    assert "5" in issues[0]["message"]


def test_partial_null_does_not_fire():
    cols = [{"name": "age", "nulls": 3}]
    assert _detect_all_null_columns(cols, rows=10) == []


def test_zero_nulls_does_not_fire():
    cols = [{"name": "id", "nulls": 0}]
    assert _detect_all_null_columns(cols, rows=5) == []


def test_zero_rows_skipped():
    cols = [{"name": "x", "nulls": 0}]
    assert _detect_all_null_columns(cols, rows=0) == []


def test_missing_nulls_field_skipped():
    cols = [{"name": "no_stats"}]
    assert _detect_all_null_columns(cols, rows=5) == []


def test_only_all_null_columns_flagged():
    cols = [
        {"name": "ok", "nulls": 2},
        {"name": "bad", "nulls": 10},
        {"name": "fine", "nulls": 0},
    ]
    issues = _detect_all_null_columns(cols, rows=10)
    assert len(issues) == 1
    assert issues[0]["column"] == "bad"


# ---------------------------------------------------------------------------
# detect_issues integration
# ---------------------------------------------------------------------------


def test_detect_issues_includes_all_null_column():
    prof = _profile(5, [{"name": "empty", "nulls": 5}])
    issues = detect_issues(prof)
    types = [i["type"] for i in issues]
    assert "all_null_column" in types


def test_detect_issues_no_fire_without_rows_key():
    """Profiles without a rows key must not raise and must not fire the rule."""
    issues = detect_issues({"columns": [{"name": "x", "nulls": 5}]})
    assert all(i["type"] != "all_null_column" for i in issues)


# ---------------------------------------------------------------------------
# suppression: all_null_column replaces missing for the same column
# ---------------------------------------------------------------------------


def test_all_null_suppresses_missing_issue():
    """An all-null column must not also emit a generic missing issue."""
    prof = _profile(5, [{"name": "score", "nulls": 5, "unique": 0}])
    issues = assess(prof)["issues"]
    types = [i["type"] for i in issues]
    assert "all_null_column" in types
    assert "missing" not in types


def test_partial_null_still_emits_missing():
    """Partial-null columns at threshold must still emit missing (not suppressed)."""
    prof = _profile(10, [{"name": "score", "nulls": 8, "unique": 2}])
    issues = assess(prof)["issues"]
    types = [i["type"] for i in issues]
    assert "missing" in types
    assert "all_null_column" not in types


def test_all_null_issue_satisfies_common_contract():
    """all_null_column must carry type, column, severity, category, message."""
    prof = _profile(3, [{"name": "notes", "nulls": 3, "unique": 0}])
    issues = assess(prof)["issues"]
    all_null = [i for i in issues if i["type"] == "all_null_column"]
    assert all_null, "Expected at least one all_null_column issue"
    required = {"type", "column", "severity", "category", "message"}
    for issue in all_null:
        assert required <= issue.keys()
