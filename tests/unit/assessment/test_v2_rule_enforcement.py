"""Tests for v2.0.0 column rule enforcement: dtype, accepted_values, unique."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from data_quality_toolkit.assessment import issue_detector as mod
from data_quality_toolkit.assessment.quality_checker import assess

_COMMON_FIELDS = {"type", "column", "severity", "category", "message"}


def _columns(*entries: dict[str, Any]) -> list[dict[str, Any]]:
    return list(entries)


def _col(name: str, dtype: str = "object") -> dict[str, Any]:
    return {"name": name, "dtype": dtype, "nulls": 0, "unique": 1}


# ---------------------------------------------------------------------------
# _detect_dtype_mismatch
# ---------------------------------------------------------------------------


def test_dtype_config_absent_no_issue():
    cols = _columns(_col("age", "int64"))
    assert mod._detect_dtype_mismatch(cols, config=None) == []
    assert mod._detect_dtype_mismatch(cols, config={}) == []
    assert mod._detect_dtype_mismatch(cols, config={"columns": {}}) == []


def test_dtype_match_no_issue():
    cols = _columns(_col("age", "int64"))
    config = {"columns": {"age": {"dtype": "int64"}}}
    assert mod._detect_dtype_mismatch(cols, config=config) == []


def test_dtype_match_case_insensitive_no_issue():
    cols = _columns(_col("flag", "OBJECT"))
    config = {"columns": {"flag": {"dtype": "object"}}}
    assert mod._detect_dtype_mismatch(cols, config=config) == []


def test_dtype_mismatch_emits_issue():
    cols = _columns(_col("age", "object"))
    config = {"columns": {"age": {"dtype": "int64"}}}
    issues = mod._detect_dtype_mismatch(cols, config=config)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["type"] == "dtype_mismatch"
    assert issue["column"] == "age"
    assert issue["severity"] == "high"
    assert issue["category"] == "Schema"
    assert "int64" in issue["message"]
    assert "object" in issue["message"]


def test_dtype_mismatch_has_expected_and_actual_fields():
    cols = _columns(_col("score", "float64"))
    config = {"columns": {"score": {"dtype": "int64"}}}
    issues = mod._detect_dtype_mismatch(cols, config=config)
    assert issues[0]["expected_dtype"] == "int64"
    assert issues[0]["actual_dtype"] == "float64"


def test_dtype_mismatch_column_absent_from_profile_no_crash():
    cols = _columns(_col("other", "object"))
    config = {"columns": {"missing_col": {"dtype": "int64"}}}
    assert mod._detect_dtype_mismatch(cols, config=config) == []


def test_dtype_mismatch_satisfies_common_fields():
    cols = _columns(_col("x", "object"))
    config = {"columns": {"x": {"dtype": "int64"}}}
    issues = mod._detect_dtype_mismatch(cols, config=config)
    assert issues
    missing = _COMMON_FIELDS - issues[0].keys()
    assert not missing, f"Missing fields: {missing}"


def test_dtype_mismatch_wired_into_detect_issues():
    profile = {
        "run_id": "r1",
        "dataset_id": "d1",
        "ts": "2026-01-01T00:00:00Z",
        "rows": 10,
        "cols": 1,
        "columns": [_col("age", "object")],
    }
    config = {"columns": {"age": {"dtype": "int64"}}}
    issues = mod.detect_issues(profile, config=config)
    types = [i["type"] for i in issues]
    assert "dtype_mismatch" in types


# ---------------------------------------------------------------------------
# _detect_accepted_value_violations
# ---------------------------------------------------------------------------


def test_accepted_values_config_absent_no_issue():
    df = pd.DataFrame({"status": ["active", "inactive", "unknown"]})
    cols = _columns(_col("status"))
    assert mod._detect_accepted_value_violations(df, cols, config=None) == []
    assert mod._detect_accepted_value_violations(df, cols, config={}) == []
    assert mod._detect_accepted_value_violations(df, cols, config={"columns": {}}) == []


def test_accepted_values_all_valid_no_issue():
    df = pd.DataFrame({"status": ["active", "inactive", "active"]})
    cols = _columns(_col("status"))
    config = {"columns": {"status": {"accepted_values": ["active", "inactive"]}}}
    assert mod._detect_accepted_value_violations(df, cols, config=config) == []


def test_accepted_values_violation_emits_issue():
    df = pd.DataFrame({"status": ["active", "inactive", "unknown"]})
    cols = _columns(_col("status"))
    config = {"columns": {"status": {"accepted_values": ["active", "inactive"]}}}
    issues = mod._detect_accepted_value_violations(df, cols, config=config)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["type"] == "accepted_values_violation"
    assert issue["column"] == "status"
    assert issue["severity"] == "high"
    assert issue["category"] == "Schema"
    assert issue["violation_count"] == 1
    assert "unknown" in issue["message"] or "unknown" in str(issue["examples"])


def test_accepted_values_nulls_ignored():
    df = pd.DataFrame({"status": ["active", None, "active"]})
    cols = _columns(_col("status"))
    config = {"columns": {"status": {"accepted_values": ["active"]}}}
    assert mod._detect_accepted_value_violations(df, cols, config=config) == []


def test_accepted_values_column_missing_from_df_no_crash():
    df = pd.DataFrame({"other": ["x"]})
    cols = _columns(_col("status"))
    config = {"columns": {"status": {"accepted_values": ["active"]}}}
    assert mod._detect_accepted_value_violations(df, cols, config=config) == []


def test_accepted_values_satisfies_common_fields():
    df = pd.DataFrame({"grade": ["A", "B", "Z"]})
    cols = _columns(_col("grade"))
    config = {"columns": {"grade": {"accepted_values": ["A", "B", "C"]}}}
    issues = mod._detect_accepted_value_violations(df, cols, config=config)
    assert issues
    missing = _COMMON_FIELDS - issues[0].keys()
    assert not missing, f"Missing fields: {missing}"


def test_accepted_values_wired_into_detect_advanced_issues():
    df = pd.DataFrame({"status": ["active", "bogus"]})
    cols = _columns(_col("status"))
    profile = {"rows": 2, "columns": cols}
    config = {"columns": {"status": {"accepted_values": ["active", "inactive"]}}}
    issues = mod.detect_advanced_issues(df, profile, config=config)
    types = [i["type"] for i in issues]
    assert "accepted_values_violation" in types


# ---------------------------------------------------------------------------
# _detect_uniqueness_violation
# ---------------------------------------------------------------------------


def test_unique_config_absent_no_issue():
    df = pd.DataFrame({"id": [1, 1, 2]})
    cols = _columns(_col("id", "int64"))
    assert mod._detect_uniqueness_violation(df, cols, config=None) == []
    assert mod._detect_uniqueness_violation(df, cols, config={}) == []
    assert mod._detect_uniqueness_violation(df, cols, config={"columns": {}}) == []


def test_unique_false_no_issue():
    df = pd.DataFrame({"id": [1, 1, 2]})
    cols = _columns(_col("id", "int64"))
    config = {"columns": {"id": {"unique": False}}}
    assert mod._detect_uniqueness_violation(df, cols, config=config) == []


def test_unique_true_and_values_are_unique_no_issue():
    df = pd.DataFrame({"id": [1, 2, 3]})
    cols = _columns(_col("id", "int64"))
    config = {"columns": {"id": {"unique": True}}}
    assert mod._detect_uniqueness_violation(df, cols, config=config) == []


def test_unique_true_and_duplicates_emits_issue():
    df = pd.DataFrame({"id": [1, 2, 2, 3]})
    cols = _columns(_col("id", "int64"))
    config = {"columns": {"id": {"unique": True}}}
    issues = mod._detect_uniqueness_violation(df, cols, config=config)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["type"] == "uniqueness_violation"
    assert issue["column"] == "id"
    assert issue["severity"] == "medium"
    assert issue["category"] == "Schema"
    assert issue["duplicate_count"] == 1


def test_unique_nulls_excluded_from_duplicate_check():
    # Two nulls + all distinct non-null values → no violation (nulls not counted as duplicates)
    df = pd.DataFrame({"id": [1, 2, None, None]})
    cols = _columns(_col("id", "float64"))
    config = {"columns": {"id": {"unique": True}}}
    assert mod._detect_uniqueness_violation(df, cols, config=config) == []


def test_unique_column_missing_from_df_no_crash():
    df = pd.DataFrame({"other": [1, 2]})
    cols = _columns(_col("id", "int64"))
    config = {"columns": {"id": {"unique": True}}}
    assert mod._detect_uniqueness_violation(df, cols, config=config) == []


def test_unique_satisfies_common_fields():
    df = pd.DataFrame({"id": [1, 1, 2]})
    cols = _columns(_col("id", "int64"))
    config = {"columns": {"id": {"unique": True}}}
    issues = mod._detect_uniqueness_violation(df, cols, config=config)
    assert issues
    missing = _COMMON_FIELDS - issues[0].keys()
    assert not missing, f"Missing fields: {missing}"


def test_unique_wired_into_detect_advanced_issues():
    df = pd.DataFrame({"id": [1, 2, 2]})
    cols = _columns(_col("id", "int64"))
    profile = {"rows": 3, "columns": cols}
    config = {"columns": {"id": {"unique": True}}}
    issues = mod.detect_advanced_issues(df, profile, config=config)
    types = [i["type"] for i in issues]
    assert "uniqueness_violation" in types


# ---------------------------------------------------------------------------
# None / empty config does not crash
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("config", [None, {}, {"columns": {}}])
def test_detect_issues_empty_config_no_crash(config: Any):
    profile = {
        "run_id": "r1",
        "dataset_id": "d1",
        "ts": "2026-01-01T00:00:00Z",
        "rows": 5,
        "cols": 1,
        "columns": [_col("x", "object")],
    }
    issues = mod.detect_issues(profile, config=config)
    assert isinstance(issues, list)


@pytest.mark.parametrize("config", [None, {}, {"columns": {}}])
def test_detect_advanced_issues_empty_config_no_crash(config: Any):
    df = pd.DataFrame({"x": [1, 2, 3]})
    profile = {"rows": 3, "columns": [_col("x", "int64")]}
    issues = mod.detect_advanced_issues(df, profile, config=config)
    assert isinstance(issues, list)


# ---------------------------------------------------------------------------
# assess() integration: all three v2 rule keys in a single call
# ---------------------------------------------------------------------------


def test_assess_v2_contract_end_to_end():
    df = pd.DataFrame(
        {
            "age": ["thirty", "forty"],  # object dtype; config expects int64 → dtype_mismatch
            "status": [
                "active",
                "bogus",
            ],  # 'bogus' outside accepted set → accepted_values_violation
            "id": [1, 1],  # duplicate non-null values → uniqueness_violation
        }
    )
    profile = {
        "run_id": "gate-001-d",
        "dataset_id": "test-ds",
        "ts": "2026-01-01T00:00:00Z",
        "rows": 2,
        "cols": 3,
        "columns": [
            {"name": "age", "dtype": "object", "nulls": 0, "unique": 2},
            {"name": "status", "dtype": "object", "nulls": 0, "unique": 2},
            {"name": "id", "dtype": "int64", "nulls": 0, "unique": 1},
        ],
    }
    config = {
        "columns": {
            "age": {"dtype": "int64"},
            "status": {"accepted_values": ["active", "inactive"]},
            "id": {"unique": True},
        }
    }
    result = assess(profile, df=df, config=config)
    issue_types = {i["type"] for i in result["issues"]}

    assert "dtype_mismatch" in issue_types
    assert "accepted_values_violation" in issue_types
    assert "uniqueness_violation" in issue_types

    for issue in result["issues"]:
        if issue["type"] in {"dtype_mismatch", "accepted_values_violation", "uniqueness_violation"}:
            missing = _COMMON_FIELDS - issue.keys()
            assert not missing, f"{issue['type']} missing fields: {missing}"
