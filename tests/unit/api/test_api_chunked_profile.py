from __future__ import annotations

from pathlib import Path

import pytest

from data_quality_toolkit.api import profile_csv


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    p = tmp_path / "data.csv"
    p.write_text("id,val,name\n1,10,Alice\n2,20,\n3,30,Bob\n4,40,Carol\n", encoding="utf-8")
    return p


# --- chunked mode envelope ---


def test_chunked_profile_has_approximate_flag(csv_file: Path) -> None:
    out = profile_csv(csv_file, chunksize=2)
    assert out["approximate"] is True


def test_chunked_profile_has_unsupported_metrics(csv_file: Path) -> None:
    out = profile_csv(csv_file, chunksize=2)
    assert "unsupported_metrics" in out
    for field in ("unique", "memory_mb"):
        assert field in out["unsupported_metrics"]


def test_chunked_profile_dtype_not_in_unsupported_metrics(csv_file: Path) -> None:
    out = profile_csv(csv_file, chunksize=2)
    assert "dtype" not in out.get("unsupported_metrics", [])


def test_chunked_profile_dtype_is_inferred(csv_file: Path) -> None:
    out = profile_csv(csv_file, chunksize=2)
    for col_prof in out["profile"]["columns"]:
        assert col_prof["dtype"] != "unknown"
        assert isinstance(col_prof["dtype"], str)


def test_chunked_profile_dtype_matches_full_load(csv_file: Path) -> None:
    full = profile_csv(csv_file)
    chunked = profile_csv(csv_file, chunksize=2)
    full_dtypes = {c["name"]: c["dtype"] for c in full["profile"]["columns"]}
    chunked_dtypes = {c["name"]: c["dtype"] for c in chunked["profile"]["columns"]}
    assert chunked_dtypes == full_dtypes


def test_chunked_profile_memory_mb_is_none(csv_file: Path) -> None:
    out = profile_csv(csv_file, chunksize=2)
    assert out["profile"]["memory_mb"] is None


def test_chunked_profile_meta_has_chunksize(csv_file: Path) -> None:
    out = profile_csv(csv_file, chunksize=2)
    assert out["meta"]["chunksize"] == 2


# --- parity with full profile ---


def test_chunked_profile_row_count_matches_full(csv_file: Path) -> None:
    full = profile_csv(csv_file)
    chunked = profile_csv(csv_file, chunksize=2)
    assert chunked["profile"]["rows"] == full["profile"]["rows"]


def test_chunked_profile_col_count_matches_full(csv_file: Path) -> None:
    full = profile_csv(csv_file)
    chunked = profile_csv(csv_file, chunksize=2)
    assert chunked["profile"]["cols"] == full["profile"]["cols"]


def test_chunked_profile_null_counts_match_full(csv_file: Path) -> None:
    full = profile_csv(csv_file)
    chunked = profile_csv(csv_file, chunksize=2)
    full_nulls = {c["name"]: c.get("nulls", 0) for c in full["profile"]["columns"]}
    chunked_nulls = {c["name"]: c.get("nulls", 0) for c in chunked["profile"]["columns"]}
    assert chunked_nulls == full_nulls


def test_chunked_profile_numeric_min_max_match_full(csv_file: Path) -> None:
    full = profile_csv(csv_file)
    chunked = profile_csv(csv_file, chunksize=2)
    full_by_name = {c["name"]: c for c in full["profile"]["columns"]}
    for col_prof in chunked["profile"]["columns"]:
        name = col_prof["name"]
        if "min" in col_prof:
            assert col_prof["min"] == full_by_name[name].get("min")
        if "max" in col_prof:
            assert col_prof["max"] == full_by_name[name].get("max")


# --- backward compatibility ---


def test_full_profile_no_approximate_key(csv_file: Path) -> None:
    """Full-load path must NOT add approximate flag."""
    out = profile_csv(csv_file)
    assert "approximate" not in out


def test_full_profile_memory_mb_is_float(csv_file: Path) -> None:
    out = profile_csv(csv_file)
    assert isinstance(out["profile"]["memory_mb"], float)


# --- edge cases ---


def test_chunked_profile_chunksize_zero_raises(csv_file: Path) -> None:
    with pytest.raises(ValueError, match="chunksize must be a positive integer"):
        profile_csv(csv_file, chunksize=0)


def test_chunked_profile_chunksize_negative_raises(csv_file: Path) -> None:
    with pytest.raises(ValueError, match="chunksize must be a positive integer"):
        profile_csv(csv_file, chunksize=-1)
