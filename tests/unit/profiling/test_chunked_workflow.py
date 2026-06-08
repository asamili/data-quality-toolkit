import pandas as pd
import pytest

from data_quality_toolkit.domain.profiling.profiling_orchestrator import (
    run_chunked_profiling,
    run_profiling,
)


@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0],
            "b": [10, 20, 30, 40],
        }
    )


def test_chunked_vs_full_profiling_parity(sample_df):
    dataset_id = "test_dataset"
    columns = ["a", "b"]

    # Full profiling
    full_result = run_profiling(sample_df, dataset_id)

    # Chunked profiling
    def chunk_gen():
        yield sample_df.iloc[:2]
        yield sample_df.iloc[2:]

    chunked_result = run_chunked_profiling(chunk_gen(), dataset_id, columns)

    # Assert parity (only for supported metrics)
    assert chunked_result["rows"] == full_result["rows"]

    for i, col in enumerate(columns):
        assert chunked_result["columns"][i]["name"] == full_result["columns"][i]["name"]
        assert chunked_result["columns"][i]["nulls"] == full_result["columns"][i]["nulls"]

        # Numeric stats check
        if col in ["a", "b"]:
            assert chunked_result["columns"][i]["min"] == full_result["columns"][i].get("min")
            assert chunked_result["columns"][i]["max"] == full_result["columns"][i].get("max")


def test_chunked_profiling_unique_not_present(sample_df):
    """unique must be absent (NotRequired) — not a silent 0."""
    columns = ["a", "b"]

    def chunk_gen():
        yield sample_df

    result = run_chunked_profiling(chunk_gen(), "ds", columns)
    for col_prof in result["columns"]:
        assert "unique" not in col_prof


def test_chunked_profiling_dtype_is_inferred(sample_df):
    """dtype must be an inferred string, not the V1 'unknown' sentinel."""
    columns = ["a", "b"]

    def chunk_gen():
        yield sample_df

    result = run_chunked_profiling(chunk_gen(), "ds", columns)
    for col_prof in result["columns"]:
        assert col_prof["dtype"] != "unknown"
        assert isinstance(col_prof["dtype"], str)
        assert col_prof["dtype"] != ""


def test_chunked_profiling_dtype_matches_pandas(sample_df):
    """Inferred chunked dtype must equal str(pd.Series.dtype) for each column."""
    columns = ["a", "b"]
    expected = {col: str(sample_df[col].dtype) for col in columns}

    def chunk_gen():
        yield sample_df.iloc[:2]
        yield sample_df.iloc[2:]

    result = run_chunked_profiling(chunk_gen(), "ds", columns)
    actual = {col_prof["name"]: col_prof["dtype"] for col_prof in result["columns"]}
    assert actual == expected
