from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from data_quality_toolkit.assessment.quality_checker import compute_score


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
def test_all_null_column_scores_zero():
    # nulls == rows → null_pct=1.0, completeness=0.0
    prof = _profile(5, [{"name": "a", "dtype": "int64", "nulls": 5, "unique": 0}])
    assert compute_score(prof) == 0.0


@pytest.mark.unit
def test_zero_rows_guard_treats_as_one():
    # rows=0: guard fires: max(int(0) if 0 else 1, 1) = 1
    # 0 nulls / 1 row = 0%, completeness = 1.0
    prof = _profile(0, [{"name": "a", "dtype": "int64", "nulls": 0, "unique": 1}])
    assert compute_score(prof) == 1.0


@pytest.mark.unit
def test_missing_rows_key_defaults_to_one():
    # No "rows" key → profile.get("rows", 1) = 1
    prof = {
        "run_id": str(uuid.uuid4()),
        "dataset_id": "sha1:test",
        "cols": 1,
        "memory_mb": 0.0,
        "ts": _ts(),
        "columns": [{"name": "a", "dtype": "int64", "nulls": 0, "unique": 1}],
    }
    assert compute_score(prof) == 1.0


@pytest.mark.unit
def test_single_row_no_nulls():
    prof = _profile(1, [{"name": "a", "dtype": "int64", "nulls": 0, "unique": 1}])
    assert compute_score(prof) == 1.0


@pytest.mark.unit
def test_single_row_one_null():
    # rows=1, nulls=1 → null_pct=1.0, completeness=0.0
    prof = _profile(1, [{"name": "a", "dtype": "int64", "nulls": 1, "unique": 0}])
    assert compute_score(prof) == 0.0


@pytest.mark.unit
def test_mixed_completeness_average():
    # 4 cols, 4 rows: nulls = 0, 0, 1, 2
    # completeness = 1.0, 1.0, 0.75, 0.5 → avg = 0.8125
    prof = _profile(
        4,
        [
            {"name": "a", "dtype": "int64", "nulls": 0, "unique": 4},
            {"name": "b", "dtype": "int64", "nulls": 0, "unique": 4},
            {"name": "c", "dtype": "int64", "nulls": 1, "unique": 3},
            {"name": "d", "dtype": "int64", "nulls": 2, "unique": 2},
        ],
    )
    assert compute_score(prof) == 0.8125


@pytest.mark.unit
def test_empty_columns_list_returns_zero():
    prof = _profile(10, [])
    assert compute_score(prof) == 0.0
