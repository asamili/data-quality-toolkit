"""TDD tests for penalty-weighted quality_score (DQT-LOGIC-003)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

import pytest

from data_quality_toolkit.domain.assessment.quality_checker import (
    assess,
    compute_quality_score,
    compute_score,
)
from data_quality_toolkit.shared.models import Issue


def _ts() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _profile(rows: int, columns: list) -> dict:
    return {
        "run_id": str(uuid.uuid4()),
        "dataset_id": "sha1:test",
        "rows": rows,
        "cols": len(columns),
        "memory_mb": 0.0,
        "ts": _ts(),
        "columns": columns,
    }


def _issue(itype: str, severity: str, category: str, column: str = "col") -> Issue:
    return cast(
        Issue,
        {
            "type": itype,
            "column": column,
            "severity": severity,
            "category": category,
            "message": f"{itype} on {column}",
        },
    )


# ---------------------------------------------------------------------------
# compute_quality_score unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_clean_dataset_quality_equals_completeness():
    quality = compute_quality_score(1.0, [])
    assert quality == 1.0


@pytest.mark.unit
def test_missing_not_penalized():
    issues = [_issue("missing", "critical", "Completeness")]
    quality = compute_quality_score(1.0, issues)
    assert quality == 1.0


@pytest.mark.unit
def test_all_null_column_not_penalized():
    issues = [_issue("all_null_column", "high", "Completeness")]
    quality = compute_quality_score(1.0, issues)
    assert quality == 1.0


@pytest.mark.unit
def test_blank_column_high_penalty():
    issues = [_issue("blank_column_name", "high", "Schema")]
    quality = compute_quality_score(1.0, issues)
    assert quality == pytest.approx(0.97, abs=1e-4)


@pytest.mark.unit
def test_placeholder_medium_penalty():
    issues = [_issue("placeholder_column_name", "medium", "Schema")]
    quality = compute_quality_score(1.0, issues)
    assert quality == pytest.approx(0.98, abs=1e-4)


@pytest.mark.unit
def test_duplicate_high_penalty():
    issues = [_issue("duplicate_column_name", "high", "Schema")]
    quality = compute_quality_score(1.0, issues)
    assert quality == pytest.approx(0.97, abs=1e-4)


@pytest.mark.unit
def test_schema_penalty_capped_at_0_30():
    # 20 high-severity schema issues → raw penalty 20*0.03=0.60, capped at 0.30
    issues = [_issue("blank_column_name", "high", "Schema", f"col{i}") for i in range(20)]
    quality = compute_quality_score(1.0, issues)
    assert quality == pytest.approx(0.70, abs=1e-4)


@pytest.mark.unit
def test_high_cardinality_medium_penalty():
    issues = [_issue("high_cardinality", "medium", "Cardinality")]
    quality = compute_quality_score(1.0, issues)
    assert quality == pytest.approx(0.98, abs=1e-4)


@pytest.mark.unit
def test_numeric_outlier_low_penalty():
    issues = [_issue("numeric_outliers", "low", "Distribution")]
    quality = compute_quality_score(1.0, issues)
    assert quality == pytest.approx(0.99, abs=1e-4)


@pytest.mark.unit
def test_distribution_penalty_capped_at_0_15():
    # 20 medium cardinality issues → raw 20*0.02=0.40, capped at 0.15
    issues = [_issue("high_cardinality", "medium", "Cardinality", f"col{i}") for i in range(20)]
    quality = compute_quality_score(1.0, issues)
    assert quality == pytest.approx(0.85, abs=1e-4)


@pytest.mark.unit
def test_quality_score_never_negative():
    # Extreme: both caps hit + low completeness
    issues = [_issue("blank_column_name", "high", "Schema", f"s{i}") for i in range(20)] + [
        _issue("high_cardinality", "medium", "Cardinality", f"d{i}") for i in range(20)
    ]
    quality = compute_quality_score(0.0, issues)
    assert quality >= 0.0


@pytest.mark.unit
def test_quality_score_never_exceeds_1():
    quality = compute_quality_score(1.0, [])
    assert quality <= 1.0


# ---------------------------------------------------------------------------
# assess() integration tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_assessment_result_has_quality_score():
    prof = _profile(5, [{"name": "c", "dtype": "float64", "nulls": 0, "unique": 5}])
    result = assess(prof)
    assert "quality_score" in result
    assert isinstance(result["quality_score"], float)


@pytest.mark.unit
def test_completeness_score_equals_score():
    prof = _profile(10, [{"name": "a", "dtype": "int64", "nulls": 2, "unique": 8}])
    result = assess(prof)
    assert result["completeness_score"] == result["score"]


@pytest.mark.unit
def test_existing_score_unchanged():
    prof = _profile(
        10,
        [
            {"name": "a", "dtype": "int64", "nulls": 1, "unique": 9},
            {"name": "b", "dtype": "int64", "nulls": 9, "unique": 1},
        ],
    )
    result = assess(prof)
    expected_score = compute_score(prof)
    assert result["score"] == pytest.approx(expected_score, abs=1e-6)


@pytest.mark.unit
def test_structural_issues_make_quality_less_than_completeness():
    # Dataset with no nulls but blank column name → quality_score < completeness_score
    prof = _profile(5, [{"name": "", "dtype": "int64", "nulls": 0, "unique": 5}])
    result = assess(prof)
    assert result["quality_score"] < result["completeness_score"]


@pytest.mark.unit
def test_example3_quality_score_equals_0_85():
    # completeness=1.0, 5 duplicate_column_name (high) → schema_penalty=5*0.03=0.15
    # quality_score = 1.0 - 0.15 = 0.85
    issues = [_issue("duplicate_column_name", "high", "Schema", f"col{i}") for i in range(5)]
    quality = compute_quality_score(1.0, issues)
    assert quality == pytest.approx(0.85, abs=1e-4)
