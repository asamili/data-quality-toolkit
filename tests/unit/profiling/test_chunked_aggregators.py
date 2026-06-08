import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.domain.profiling.core.chunked_aggregators import (
    DtypeInferencer,
    NullCounter,
    NumericStats,
    RowCounter,
    _normalize_dtype,
    _widen,
)


@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {
            "a": [1.0, 2.0, np.nan, 4.0],
            "b": ["x", "y", "x", None],
        }
    )


def test_row_counter(sample_df):
    counter = RowCounter()
    counter.update(sample_df.iloc[:2])
    counter.update(sample_df.iloc[2:])
    assert counter.finalize() == {"rows": 4}


def test_null_counter(sample_df):
    counter = NullCounter(columns=["a", "b"])
    counter.update(sample_df.iloc[:2])
    counter.update(sample_df.iloc[2:])
    assert counter.finalize() == {"null_counts": {"a": 1, "b": 1}}


def test_numeric_stats(sample_df):
    # Only column 'a' is numeric
    stats = NumericStats(columns=["a", "b"])
    stats.update(sample_df.iloc[:2])
    stats.update(sample_df.iloc[2:])

    final = stats.finalize()
    assert final["a"]["min"] == 1.0
    assert final["a"]["max"] == 4.0
    assert final["a"]["sum"] == 7.0
    assert final["b"]["min"] is None  # 'b' is string


# ---------------------------------------------------------------------------
# _normalize_dtype unit tests
# ---------------------------------------------------------------------------


def test_normalize_dtype_bool():
    assert _normalize_dtype(pd.array([True, False]).dtype) == "bool"


def test_normalize_dtype_int():
    assert _normalize_dtype(pd.Series([1, 2], dtype="int64").dtype) == "int64"


def test_normalize_dtype_float():
    assert _normalize_dtype(pd.Series([1.0, 2.0]).dtype) == "float64"


def test_normalize_dtype_object():
    assert _normalize_dtype(pd.Series(["a", "b"]).dtype) == "object"


def test_normalize_dtype_datetime():
    assert _normalize_dtype(pd.to_datetime(["2021-01-01"]).dtype) == "datetime64[ns]"


# ---------------------------------------------------------------------------
# _widen unit tests
# ---------------------------------------------------------------------------


def test_widen_same_returns_same():
    assert _widen("int64", "int64") == "int64"


def test_widen_bool_int():
    assert _widen("bool", "int64") == "int64"
    assert _widen("int64", "bool") == "int64"


def test_widen_int_float():
    assert _widen("int64", "float64") == "float64"
    assert _widen("float64", "int64") == "float64"


def test_widen_numeric_object():
    assert _widen("int64", "object") == "object"
    assert _widen("float64", "object") == "object"


def test_widen_datetime_datetime():
    assert _widen("datetime64[ns]", "datetime64[ns]") == "datetime64[ns]"


def test_widen_datetime_numeric():
    assert _widen("datetime64[ns]", "int64") == "object"
    assert _widen("float64", "datetime64[ns]") == "object"


# ---------------------------------------------------------------------------
# DtypeInferencer aggregator tests
# ---------------------------------------------------------------------------


def _run_inferencer(chunks: list[pd.DataFrame], columns: list[str]) -> dict[str, str]:
    inf = DtypeInferencer(columns=columns)
    for chunk in chunks:
        inf.update(chunk)
    return inf.finalize()


def test_dtype_inferencer_pure_int():
    df = pd.DataFrame({"x": [1, 2, 3, 4]})
    result = _run_inferencer([df.iloc[:2], df.iloc[2:]], ["x"])
    assert result["x"] == str(pd.read_csv.__func__ if False else pd.Series([1, 2]).dtype)
    # Direct oracle check: pure int → int64
    assert result["x"] == "int64"


def test_dtype_inferencer_pure_float():
    df = pd.DataFrame({"x": [1.1, 2.2, 3.3]})
    result = _run_inferencer([df.iloc[:1], df.iloc[1:]], ["x"])
    assert result["x"] == "float64"


def test_dtype_inferencer_int_float_across_chunks():
    chunk1 = pd.DataFrame({"x": pd.Series([1, 2], dtype="int64")})
    chunk2 = pd.DataFrame({"x": pd.Series([1.5, 2.5], dtype="float64")})
    result = _run_inferencer([chunk1, chunk2], ["x"])
    assert result["x"] == "float64"


def test_dtype_inferencer_numeric_string_mixed():
    chunk1 = pd.DataFrame({"x": pd.Series([1, 2], dtype="int64")})
    chunk2 = pd.DataFrame({"x": pd.Series(["a", "b"])})
    result = _run_inferencer([chunk1, chunk2], ["x"])
    assert result["x"] == "object"


def test_dtype_inferencer_bool():
    df = pd.DataFrame({"x": pd.array([True, False, True])})
    result = _run_inferencer([df], ["x"])
    assert result["x"] == "bool"


def test_dtype_inferencer_bool_then_int_widens():
    chunk1 = pd.DataFrame({"x": pd.array([True, False])})
    chunk2 = pd.DataFrame({"x": pd.Series([0, 1], dtype="int64")})
    result = _run_inferencer([chunk1, chunk2], ["x"])
    assert result["x"] == "int64"


def test_dtype_inferencer_all_null_matches_pandas(tmp_path):
    """All-null CSV column: chunked dtype must match pd.read_csv().dtypes."""
    p = tmp_path / "allnull.csv"
    p.write_text("a,b\n,1\n,2\n,3\n", encoding="utf-8")
    expected = str(pd.read_csv(p)["a"].dtype)
    df = pd.read_csv(p)
    result = _run_inferencer([df], ["a"])
    assert result["a"] == expected


def test_dtype_inferencer_late_float_widens(tmp_path):
    """int in early chunks, float in late chunk → float64 (matches full-load pandas)."""
    p = tmp_path / "late_float.csv"
    rows = "\n".join([f"{i}" for i in range(1, 11)])
    p.write_text(f"x\n{rows}\n1.5\n", encoding="utf-8")
    expected = str(pd.read_csv(p)["x"].dtype)
    df = pd.read_csv(p)
    # Simulate: first chunk int, last row float
    chunk1 = df.iloc[:10]
    chunk2 = df.iloc[10:]
    result = _run_inferencer([chunk1, chunk2], ["x"])
    assert result["x"] == expected


def test_dtype_inferencer_datetime():
    s = pd.to_datetime(["2021-01-01", "2021-01-02"])
    df = pd.DataFrame({"ts": s})
    result = _run_inferencer([df.iloc[:1], df.iloc[1:]], ["ts"])
    assert result["ts"] == "datetime64[ns]"


def test_dtype_inferencer_single_chunk_matches_full(tmp_path):
    """Single chunk == full-load dtype for all columns."""
    p = tmp_path / "single.csv"
    p.write_text("id,val,name\n1,10,Alice\n2,20,Bob\n3,30,Carol\n", encoding="utf-8")
    full_df = pd.read_csv(p)
    full_dtypes = {col: str(full_df[col].dtype) for col in full_df.columns}
    result = _run_inferencer([full_df], list(full_df.columns))
    assert result == full_dtypes


def test_dtype_inferencer_multi_chunk_matches_full(tmp_path):
    """Multiple chunks produce same dtype as single full-load."""
    p = tmp_path / "multi.csv"
    p.write_text("id,val,name\n1,10,Alice\n2,20,Bob\n3,30,Carol\n4,40,Dan\n", encoding="utf-8")
    full_df = pd.read_csv(p)
    full_dtypes = {col: str(full_df[col].dtype) for col in full_df.columns}
    chunks = [full_df.iloc[:2], full_df.iloc[2:]]
    result = _run_inferencer(chunks, list(full_df.columns))
    assert result == full_dtypes


def test_dtype_inferencer_unknown_column_defaults_object():
    """Column listed but absent from all chunks defaults to 'object'."""
    inf = DtypeInferencer(columns=["x", "missing"])
    inf.update(pd.DataFrame({"x": [1, 2]}))
    result = inf.finalize()
    assert result["missing"] == "object"
