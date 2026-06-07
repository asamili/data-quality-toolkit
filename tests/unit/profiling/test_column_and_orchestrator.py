from __future__ import annotations

import pandas as pd

from data_quality_toolkit.domain.profiling.core.column_profiler import profile_columns
from data_quality_toolkit.domain.profiling.profiling_orchestrator import run_profiling


def test_profile_columns_basic():
    df = pd.DataFrame(
        {
            "id": [1, 2, 2, None],
            "name": ["a", "b", "b", None],
            "x": [10.0, None, 30.0, 40.0],
        }
    )
    cols = profile_columns(df)
    by = {c["name"]: c for c in cols}
    assert by["id"]["nulls"] == 1 and by["id"]["unique"] == 2
    assert by["name"]["nulls"] == 1 and by["name"]["unique"] == 2
    # numeric min/max present
    assert by["x"]["min"] == 10.0 and by["x"]["max"] == 40.0


def test_run_profiling_shapes_and_keys():
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    pr = run_profiling(df, dataset_id="sha1:test")
    assert pr["rows"] == 3 and pr["cols"] == 2
    assert isinstance(pr["memory_mb"], float)
    assert isinstance(pr["run_id"], str) and pr["run_id"]
    assert pr["dataset_id"] == "sha1:test"
    assert isinstance(pr["ts"], str) and pr["ts"].endswith("Z")
    assert isinstance(pr["columns"], list) and pr["columns"]
    assert pr["dataset_id"] == "sha1:test"
    assert isinstance(pr["ts"], str) and pr["ts"].endswith("Z")
    assert isinstance(pr["columns"], list) and pr["columns"]
