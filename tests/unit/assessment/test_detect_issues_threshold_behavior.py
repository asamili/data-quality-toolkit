from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pandas as pd
import pytest

from data_quality_toolkit.assessment.issue_detector import detect_advanced_issues
from data_quality_toolkit.assessment.quality_checker import detect_issues


def _ts() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _profile(rows, columns):
    return {
        "run_id": str(uuid.uuid4()),
        "dataset_id": "sha1:test",
        "rows": rows,
        "cols": len(columns),
        "memory_mb": 0.0,
        "ts": _ts(),
        "columns": columns,
    }


@pytest.mark.unit
def test_below_threshold_no_issue():
    # 10% null < 20% default threshold → no issue
    prof = _profile(10, [{"name": "a", "dtype": "int64", "nulls": 1, "unique": 9}])
    assert detect_issues(prof) == []


@pytest.mark.unit
def test_at_threshold_fires():
    # 20% null == 20% threshold: condition is >= so boundary fires
    prof = _profile(10, [{"name": "a", "dtype": "int64", "nulls": 2, "unique": 8}])
    issues = detect_issues(prof)
    assert len(issues) == 1
    assert issues[0]["type"] == "missing"
    assert issues[0]["column"] == "a"


@pytest.mark.unit
def test_above_threshold_fires():
    # 30% null > 20% threshold → issue
    prof = _profile(10, [{"name": "a", "dtype": "int64", "nulls": 3, "unique": 7}])
    assert len(detect_issues(prof)) == 1


@pytest.mark.unit
def test_severity_high_below_50pct():
    # 30% null → severity "high" (< 0.5)
    prof = _profile(10, [{"name": "a", "dtype": "int64", "nulls": 3, "unique": 7}])
    issues = detect_issues(prof)
    assert issues[0]["severity"] == "high"


@pytest.mark.unit
def test_severity_critical_at_50pct():
    # 5/10 = exactly 50% null (not all-null) → severity "critical"
    prof = _profile(10, [{"name": "a", "dtype": "int64", "nulls": 5, "unique": 5}])
    issues = detect_issues(prof)
    assert len(issues) == 1
    assert issues[0]["severity"] == "critical"


@pytest.mark.unit
def test_all_null_col_skipped_by_detect_issues():
    # nulls == rows → skipped; reported as all_null_column by issue_detector, not "missing"
    prof = _profile(5, [{"name": "a", "dtype": "int64", "nulls": 5, "unique": 0}])
    assert detect_issues(prof) == []


@pytest.mark.unit
def test_custom_threshold_higher():
    # 30% null with threshold=0.5 → below threshold, no issue
    prof = _profile(10, [{"name": "a", "dtype": "int64", "nulls": 3, "unique": 7}])
    assert detect_issues(prof, null_threshold=0.5) == []


@pytest.mark.unit
def test_high_cardinality_exact_threshold_not_flagged():
    # unique_ratio = 9/10 = 0.9 exactly; condition is > 0.9 (strict), so no issue
    prof = _profile(10, [{"name": "cat", "dtype": "object", "nulls": 0, "unique": 9}])
    df = pd.DataFrame({"cat": [str(i) for i in range(10)]})
    issues = detect_advanced_issues(df, prof)
    cardinality_issues = [i for i in issues if i["type"] == "high_cardinality"]
    assert cardinality_issues == []


@pytest.mark.unit
def test_high_cardinality_above_threshold_flagged():
    # unique_ratio = 10/10 = 1.0 > 0.9 → issue fires for non-numeric column
    prof = _profile(10, [{"name": "cat", "dtype": "object", "nulls": 0, "unique": 10}])
    df = pd.DataFrame({"cat": [str(i) for i in range(10)]})
    issues = detect_advanced_issues(df, prof)
    cardinality_issues = [i for i in issues if i["type"] == "high_cardinality"]
    assert len(cardinality_issues) == 1
    assert cardinality_issues[0]["column"] == "cat"
