from __future__ import annotations

import pandas as pd
import pytest

from data_quality_toolkit.domain.profiling.core.column_profiler import profile_columns


@pytest.mark.unit
def test_dtype_int_column():
    df = pd.DataFrame({"x": pd.array([1, 2, 3], dtype="int64")})
    cols = profile_columns(df)
    assert cols[0]["dtype"].startswith("int")


@pytest.mark.unit
def test_dtype_float_column():
    df = pd.DataFrame({"x": pd.array([1.0, 2.0, 3.0], dtype="float64")})
    cols = profile_columns(df)
    assert cols[0]["dtype"].startswith("float")


@pytest.mark.unit
def test_dtype_object_column():
    df = pd.DataFrame({"x": ["a", "b", "c"]})
    cols = profile_columns(df)
    assert cols[0]["dtype"] == "object"


@pytest.mark.unit
def test_all_null_column_stats():
    # All-null object column: nulls == len(df), unique == 0, no min/max keys
    df = pd.DataFrame({"x": [None, None, None]})
    cols = profile_columns(df)
    col = cols[0]
    assert col["nulls"] == 3
    assert col["unique"] == 0


@pytest.mark.unit
def test_all_null_numeric_min_max_none():
    # All-null numeric column: min and max must be None (no non-null values)
    df = pd.DataFrame({"x": pd.array([float("nan"), float("nan"), float("nan")], dtype="float64")})
    cols = profile_columns(df)
    col = cols[0]
    assert col["nulls"] == 3
    assert col.get("min") is None
    assert col.get("max") is None


@pytest.mark.unit
def test_numeric_column_min_max():
    df = pd.DataFrame({"x": [3, 1, 4, 1, 5, 9, 2, 6]})
    cols = profile_columns(df)
    col = cols[0]
    assert col["min"] == 1.0
    assert col["max"] == 9.0


@pytest.mark.unit
def test_categorical_unique_count():
    df = pd.DataFrame({"cat": ["apple", "banana", "cherry", "banana", "apple"]})
    cols = profile_columns(df)
    assert cols[0]["unique"] == 3


@pytest.mark.unit
def test_single_row_dataset():
    df = pd.DataFrame({"a": [42], "b": ["hello"]})
    cols = profile_columns(df)
    by = {c["name"]: c for c in cols}
    assert by["a"]["nulls"] == 0
    assert by["a"]["unique"] == 1
    assert by["a"]["min"] == 42.0
    assert by["a"]["max"] == 42.0
    assert by["b"]["nulls"] == 0
    assert by["b"]["unique"] == 1


@pytest.mark.unit
def test_sample_used_for_min_max_not_full():
    # Full df range: 1–100; sample range: 1–5
    # min/max must reflect sample; nulls/unique must reflect full df
    full_df = pd.DataFrame({"x": list(range(1, 101))})
    sample_df = pd.DataFrame({"x": [1, 2, 3, 4, 5]})
    cols = profile_columns(full_df, sample=sample_df)
    col = cols[0]
    assert col["min"] == 1.0
    assert col["max"] == 5.0
    assert col["nulls"] == 0
    assert col["unique"] == 100
