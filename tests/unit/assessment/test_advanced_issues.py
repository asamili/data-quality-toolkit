"""Tests for Candidate C: Advanced Issue Detection (high_cardinality + numeric_outliers)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from data_quality_toolkit.assessment import issue_detector as mod
from data_quality_toolkit.assessment.quality_checker import assess

_COMMON_FIELDS = {"type", "column", "severity", "category", "message"}


def _profile(rows: int, columns: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4()),
        "dataset_id": "sha1:advanced-test",
        "rows": rows,
        "cols": len(columns),
        "memory_mb": 0.0,
        "ts": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "columns": columns,
    }


# ---------------------------------------------------------------------------
# High cardinality
# ---------------------------------------------------------------------------


def test_high_cardinality_flagged_for_string_column():
    columns = [{"name": "id", "dtype": "object", "nulls": 0, "unique": 10}]
    issues = mod._detect_high_cardinality(columns, rows=10)
    assert len(issues) == 1
    assert issues[0]["type"] == "high_cardinality"
    assert issues[0]["column"] == "id"


def test_high_cardinality_not_flagged_for_int_column():
    columns = [{"name": "id", "dtype": "int64", "nulls": 0, "unique": 10}]
    issues = mod._detect_high_cardinality(columns, rows=10)
    assert issues == []


def test_high_cardinality_not_flagged_when_below_threshold():
    # 5/10 = 0.5, below 0.9 threshold
    columns = [{"name": "category", "dtype": "object", "nulls": 0, "unique": 5}]
    issues = mod._detect_high_cardinality(columns, rows=10)
    assert issues == []


def test_high_cardinality_not_flagged_when_rows_lte_1():
    columns = [{"name": "id", "dtype": "object", "nulls": 0, "unique": 1}]
    assert mod._detect_high_cardinality(columns, rows=0) == []
    assert mod._detect_high_cardinality(columns, rows=1) == []


def test_high_cardinality_null_unique_skipped():
    columns = [{"name": "id", "dtype": "object", "nulls": 0, "unique": None}]
    issues = mod._detect_high_cardinality(columns, rows=10)
    assert issues == []


def test_high_cardinality_issue_satisfies_common_fields():
    columns = [{"name": "uid", "dtype": "object", "nulls": 0, "unique": 10}]
    issues = mod._detect_high_cardinality(columns, rows=10)
    assert issues
    missing = _COMMON_FIELDS - issues[0].keys()
    assert not missing, f"Missing fields: {missing}"


# ---------------------------------------------------------------------------
# Numeric outliers
# ---------------------------------------------------------------------------


def _df_with_outliers() -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    # 90 values spread 1-10 (nonzero IQR) + 10 extreme outliers at 1000 → ~10% outlier fraction
    normal = list(range(1, 91))  # 1..90
    extreme = [1000] * 10
    df = pd.DataFrame({"val": normal + extreme})
    columns = [{"name": "val", "dtype": "float64", "nulls": 0, "unique": 91}]
    return df, columns


def test_numeric_outliers_flagged():
    df, columns = _df_with_outliers()
    issues = mod._detect_numeric_outliers(df, columns)
    assert len(issues) == 1
    assert issues[0]["type"] == "numeric_outliers"
    assert issues[0]["column"] == "val"


def test_numeric_outliers_not_flagged_when_no_outliers():
    df = pd.DataFrame({"val": list(range(100))})
    columns = [{"name": "val", "dtype": "int64", "nulls": 0, "unique": 100}]
    issues = mod._detect_numeric_outliers(df, columns)
    assert issues == []


def test_numeric_outliers_skips_non_numeric():
    df = pd.DataFrame({"name": ["a", "b", "c", "d", "e"]})
    columns = [{"name": "name", "dtype": "object", "nulls": 0, "unique": 5}]
    issues = mod._detect_numeric_outliers(df, columns)
    assert issues == []


def test_numeric_outliers_skips_small_series():
    df = pd.DataFrame({"val": [1.0, 2.0, 3.0]})
    columns = [{"name": "val", "dtype": "float64", "nulls": 0, "unique": 3}]
    issues = mod._detect_numeric_outliers(df, columns)
    assert issues == []


def test_numeric_outliers_skips_zero_iqr():
    # All same value → iqr == 0
    df = pd.DataFrame({"val": [5.0] * 20})
    columns = [{"name": "val", "dtype": "float64", "nulls": 0, "unique": 1}]
    issues = mod._detect_numeric_outliers(df, columns)
    assert issues == []


def test_numeric_outliers_skips_column_not_in_df():
    df = pd.DataFrame({"other": [1.0, 2.0, 3.0, 4.0, 5.0]})
    columns = [{"name": "missing_col", "dtype": "float64", "nulls": 0, "unique": 5}]
    issues = mod._detect_numeric_outliers(df, columns)
    assert issues == []


def test_numeric_outliers_issue_satisfies_common_fields():
    df, columns = _df_with_outliers()
    issues = mod._detect_numeric_outliers(df, columns)
    assert issues
    missing = _COMMON_FIELDS - issues[0].keys()
    assert not missing, f"Missing fields: {missing}"


# ---------------------------------------------------------------------------
# assess() integration
# ---------------------------------------------------------------------------


def test_assess_advanced_issues_included_when_df_passed():
    # 10/10 unique strings → high_cardinality
    columns = [{"name": "uid", "dtype": "object", "nulls": 0, "unique": 10}]
    prof = _profile(10, columns)
    df = pd.DataFrame({"uid": [str(i) for i in range(10)]})
    result = assess(prof, df=df)
    types = [i["type"] for i in result["issues"]]
    assert "high_cardinality" in types


def test_assess_no_advanced_issues_when_df_none():
    columns = [{"name": "uid", "dtype": "object", "nulls": 0, "unique": 10}]
    prof = _profile(10, columns)
    result = assess(prof, df=None)
    types = [i["type"] for i in result["issues"]]
    assert "high_cardinality" not in types
    assert "numeric_outliers" not in types


def test_assess_advanced_issues_satisfy_common_fields_contract():
    columns = [{"name": "uid", "dtype": "object", "nulls": 0, "unique": 10}]
    prof = _profile(10, columns)
    df = pd.DataFrame({"uid": [str(i) for i in range(10)]})
    result = assess(prof, df=df)
    advanced = [
        i for i in result["issues"] if i["type"] in ("high_cardinality", "numeric_outliers")
    ]
    assert advanced, "Expected at least one advanced issue"
    for issue in advanced:
        missing = _COMMON_FIELDS - issue.keys()
        assert not missing, f"Advanced issue {issue['type']!r} missing fields: {missing}"
