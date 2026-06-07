"""Unit tests for issue_export.build_fact_issues."""

from __future__ import annotations

from data_quality_toolkit.adapters.exporters.issue_export import (
    _FACT_ISSUES_COLUMNS,
    build_fact_issues,
)

_COLUMNS = [
    {"name": "a", "dtype": "int64"},
    {"name": "b", "dtype": "object"},
]

_ISSUES = [
    {
        "type": "missing",
        "column": "a",
        "severity": "high",
        "category": "Completeness",
        "message": "Column 'a' has 30% missing values",
    },
    {
        "type": "duplicate_column_name",
        "column": "b",
        "severity": "high",
        "category": "Schema",
        "message": "Duplicate column name 'b'",
    },
]


def test_empty_issues_returns_empty_df():
    df = build_fact_issues("run-1", "ds-1", [], _COLUMNS)
    assert list(df.columns) == _FACT_ISSUES_COLUMNS
    assert len(df) == 0


def test_schema_columns_match():
    df = build_fact_issues("run-1", "ds-1", _ISSUES, _COLUMNS)
    assert list(df.columns) == _FACT_ISSUES_COLUMNS


def test_row_count_matches_issues():
    df = build_fact_issues("run-1", "ds-1", _ISSUES, _COLUMNS)
    assert len(df) == len(_ISSUES)


def test_run_and_dataset_ids_propagated():
    df = build_fact_issues("run-abc", "sha1:xyz", _ISSUES, _COLUMNS)
    assert (df["run_id"] == "run-abc").all()
    assert (df["dataset_id"] == "sha1:xyz").all()


def test_column_id_resolved_for_known_columns():
    df = build_fact_issues("run-1", "sha1:xyz", _ISSUES, _COLUMNS)
    assert df.loc[df["issue_type"] == "missing", "column_id"].iloc[0] == "sha1:xyz:a"
    assert df.loc[df["issue_type"] == "duplicate_column_name", "column_id"].iloc[0] == "sha1:xyz:b"


def test_column_id_is_none_for_unknown_column():
    """Issue whose column name is not in the profiled columns gets column_id=None."""
    issues = [
        {
            "type": "placeholder_column_name",
            "column": "unnamed: 0",
            "severity": "medium",
            "category": "Schema",
            "message": "Column name appears to be a placeholder: 'unnamed: 0'",
        }
    ]
    # _COLUMNS does not include 'unnamed: 0'
    df = build_fact_issues("run-1", "sha1:xyz", issues, _COLUMNS)
    assert len(df) == 1
    assert df.iloc[0]["column_id"] is None


def test_issue_fields_mapped_correctly():
    df = build_fact_issues("run-1", "ds-1", _ISSUES[:1], _COLUMNS)
    row = df.iloc[0]
    assert row["issue_type"] == "missing"
    assert row["severity"] == "high"
    assert row["category"] == "Completeness"
    assert "30%" in row["message"]


def test_no_profiled_columns_all_column_ids_none():
    """When columns list is empty, all column_id values are None."""
    df = build_fact_issues("run-1", "ds-1", _ISSUES, [])
    assert df["column_id"].isna().all()
