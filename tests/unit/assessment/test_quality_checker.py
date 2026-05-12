from __future__ import annotations

import uuid
from datetime import UTC, datetime

from data_quality_toolkit.assessment.quality_checker import assess, compute_score, detect_issues


def _ts() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _base_profile(rows: int, columns):
    return {
        "run_id": str(uuid.uuid4()),
        "dataset_id": "sha1:test",
        "rows": rows,
        "cols": len(columns),
        "memory_mb": 0.0,
        "ts": _ts(),
        "columns": columns,
    }


def test_compute_score_and_detect_issues_basic():
    # rows=10; colA has 1 null (10%), colB has 9 nulls (90%)
    prof = _base_profile(
        10,
        [
            {"name": "a", "dtype": "int64", "nulls": 1, "unique": 9},
            {"name": "b", "dtype": "int64", "nulls": 9, "unique": 1},
        ],
    )
    score = compute_score(prof)
    # completeness: (1-0.1)=0.9 and (1-0.9)=0.1 → avg = 0.5
    assert score == 0.5

    issues = detect_issues(prof)  # default threshold=0.2
    assert len(issues) == 1
    assert issues[0]["type"] == "missing"
    assert issues[0]["column"] == "b"
    assert issues[0]["severity"] == "critical"  # >= 0.5 is critical
    assert issues[0]["pct"] == 0.9


def test_detect_issues_threshold_edge_and_severity():
    # 20% nulls equals default threshold → should trigger "high"
    prof = _base_profile(
        10,
        [{"name": "x", "dtype": "int64", "nulls": 2, "unique": 8}],
    )
    issues = detect_issues(prof)  # threshold=0.2 default
    assert len(issues) == 1
    assert issues[0]["severity"] == "high"
    assert issues[0]["pct"] == 0.2


def test_compute_score_empty_columns_is_zero():
    prof = _base_profile(10, [])
    assert compute_score(prof) == 0.0


def test_assess_returns_expected_shape():
    prof = _base_profile(
        5,
        [{"name": "c", "dtype": "float64", "nulls": 0, "unique": 5}],
    )
    out = assess(prof)
    assert out["run_id"] == prof["run_id"]
    assert out["dataset_id"] == prof["dataset_id"]
    assert isinstance(out["score"], float)
    assert isinstance(out["issues"], list)
    assert out["ts"] == prof["ts"]
