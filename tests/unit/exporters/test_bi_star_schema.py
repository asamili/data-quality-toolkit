from __future__ import annotations

from typing import Any, cast

import pandas as pd
import pytest

from data_quality_toolkit.exporters.bi_star_schema import (
    StarTables,
    build_star,
    validate_relationships,
)
from data_quality_toolkit.shared.models import ProfileResult


def _profile() -> ProfileResult:
    return {
        "run_id": "run-123",
        "dataset_id": "sha1:abc",
        "ts": "1970-01-01T00:00:00Z",
        "rows": 10,
        "cols": 2,
        "memory_mb": 0.0,
        "columns": [
            {"name": "a", "dtype": "int64", "nulls": 2, "unique": 8},
            {"name": "b", "dtype": "object", "nulls": 0, "unique": 10},
        ],
    }


def test_build_star_shapes_and_values():
    # include a None to exercise null_pct/completeness
    df = pd.DataFrame({"a": [1, None] + list(range(2, 10)), "b": list("abcdefghij")})

    tables = build_star(_profile(), df)

    # expected tables
    assert set(tables.keys()) == {
        "dim_dataset",
        "dim_column",
        "fact_profile_runs",
        "fact_quality_metrics",
    }

    dim_dataset = tables["dim_dataset"]
    dim_column = tables["dim_column"]
    fact_runs = tables["fact_profile_runs"]
    fact_q = tables["fact_quality_metrics"]

    # shapes
    assert len(dim_dataset) == 1
    assert len(dim_column) == 2
    assert len(fact_runs) == 1
    assert len(fact_q) == 2

    # key columns exist
    assert {"dataset_id"}.issubset(dim_dataset.columns)
    assert {"column_id", "dataset_id", "column_name", "dtype"}.issubset(dim_column.columns)
    assert {"run_id", "dataset_id", "ts", "rows", "cols", "memory_mb"}.issubset(fact_runs.columns)
    assert {"run_id", "column_id", "null_pct", "distinct_count", "completeness"}.issubset(
        fact_q.columns
    )

    # quality metrics correctness
    rec_a = fact_q[fact_q["column_id"].str.endswith(":a")].iloc[0]
    assert rec_a["null_pct"] == pytest.approx(0.2)  # 2/10
    assert rec_a["distinct_count"] == 8
    assert rec_a["completeness"] == pytest.approx(0.8)  # 1 - 0.2

    # column_id convention sanity
    assert dim_column["column_id"].str.startswith("sha1:abc:").all()


def test_build_star_source_path_propagates():
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    tables = build_star(_profile(), df, source_path="/data/test.csv")
    assert tables["dim_dataset"]["source_path"].iloc[0] == "/data/test.csv"


def test_build_star_source_path_default_empty():
    df = pd.DataFrame({"a": [1], "b": ["x"]})
    tables = build_star(_profile(), df)
    assert tables["dim_dataset"]["source_path"].iloc[0] == ""


def test_validate_relationships_happy_and_error():
    tables: StarTables = build_star(_profile(), pd.DataFrame({"a": [1], "b": ["x"]}))

    # happy path should not raise
    validate_relationships(tables)

    # missing table → error
    # make a plain dict copy while preserving DataFrame types
    missing: dict[str, pd.DataFrame] = dict(cast(dict[str, pd.DataFrame], tables))
    del missing["dim_dataset"]
    with pytest.raises(ValueError, match="Missing required table"):
        # cast to Any because we're intentionally violating StarTables shape
        validate_relationships(cast(Any, missing))

    # missing required column → error
    bad: dict[str, pd.DataFrame] = dict(cast(dict[str, pd.DataFrame], tables))
    bad["fact_quality_metrics"] = bad["fact_quality_metrics"].drop(columns=["column_id"])
    with pytest.raises(ValueError, match="missing columns"):
        validate_relationships(cast(Any, bad))
