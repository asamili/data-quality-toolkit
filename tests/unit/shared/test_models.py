# mypy: warn_unused_ignores=False
from __future__ import annotations

from dataclasses import replace

import pytest

from data_quality_toolkit.shared import models


def test_run_ids_dataclass():
    r = models.RunIds(run_id="00000000-0000-0000-0000-000000000000", dataset_id="sha1:deadbeef")
    assert r.run_id.startswith("0")
    assert r.dataset_id.startswith("sha1:")

    # frozen dataclass should prevent mutation; type: ignore[misc] is required because
    # mypy correctly flags read-only property assignment — the intent is to test the runtime guard
    with pytest.raises((AttributeError, TypeError)):
        r.run_id = "x"  # type: ignore[misc]

    # if mutation is desired, use replace to create a new instance
    r2 = replace(r, run_id="x")
    assert r2.run_id == "x"
    assert r2.dataset_id == r.dataset_id


def test_column_and_profile_result_typed_dicts():
    col: models.ColumnProfile = {
        "name": "age",
        "dtype": "int64",
        "nulls": 0,
        "unique": 50,
        "min": 18,
        "max": 70,
    }
    assert col["name"] == "age"
    assert col["dtype"] == "int64"

    profile: models.ProfileResult = {
        "run_id": "r1",
        "dataset_id": "sha1:abc",
        "rows": 100,
        "cols": 5,
        "memory_mb": 0.12,
        "ts": "2025-01-01T00:00:00Z",
        "columns": [col],
    }
    assert profile["rows"] == 100
    assert isinstance(profile["columns"], list)

    # "max" is NotRequired in ColumnProfile → access via get()
    max_val = profile["columns"][0].get("max")
    assert max_val == 70


def test_assessment_result_typed_dict():
    issue: models.Issue = {
        "type": "missing_values",
        "column": "age",
        "pct": 0.0,
        "severity": "low",
    }
    assess: models.AssessmentResult = {
        "run_id": "r1",
        "dataset_id": "sha1:abc",
        "score": 0.95,
        "completeness_score": 0.95,
        "quality_score": 0.95,
        "issues": [issue],
        "ts": "2025-01-01T00:00:00Z",
    }
    assert assess["score"] >= 0.0
    assert len(assess["issues"]) == 1
