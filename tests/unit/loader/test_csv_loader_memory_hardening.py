"""Tests for memory-hardening loader behavior: read-time sampling and max_rows_in_memory guard."""

from __future__ import annotations

import pytest

from data_quality_toolkit.adapters.loaders.file.csv_loader import load_csv

# ---------------------------------------------------------------------------
# Read-time sampling (SAMPLE_SIZE)
# ---------------------------------------------------------------------------


def test_default_full_load_no_sampling(tmp_path, monkeypatch):
    monkeypatch.delenv("SAMPLE_SIZE", raising=False)
    f = tmp_path / "data.csv"
    f.write_text("id\n1\n2\n3\n4\n5\n", encoding="utf-8")
    df, meta = load_csv(str(f))
    assert len(df) == 5
    assert meta["sample_applied"] is False
    assert meta["sample_size"] is None


def test_sample_size_env_reduces_loaded_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMPLE_SIZE", "2")
    f = tmp_path / "data.csv"
    f.write_text("id\n1\n2\n3\n4\n5\n", encoding="utf-8")
    df, meta = load_csv(str(f))
    assert len(df) == 2
    assert meta["sample_applied"] is True
    assert meta["sample_size"] == 2


def test_sample_size_returns_n_representative_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMPLE_SIZE", "3")
    f = tmp_path / "data.csv"
    f.write_text("id\n10\n20\n30\n40\n50\n", encoding="utf-8")
    df, meta = load_csv(str(f))
    assert len(df) == 3
    assert meta["sample_applied"] is True
    # All returned values come from the original population (not necessarily first 3)
    assert set(df["id"]).issubset({10, 20, 30, 40, 50})


def test_sample_size_larger_than_file_loads_all(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMPLE_SIZE", "1000")
    f = tmp_path / "data.csv"
    f.write_text("id\n1\n2\n3\n", encoding="utf-8")
    df, meta = load_csv(str(f))
    assert len(df) == 3
    assert meta["sample_applied"] is False
    assert meta["sample_size"] is None


def test_sample_size_deterministic_across_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMPLE_SIZE", "2")
    f = tmp_path / "data.csv"
    f.write_text("id\n1\n2\n3\n4\n5\n", encoding="utf-8")
    df1, _ = load_csv(str(f))
    df2, _ = load_csv(str(f))
    assert list(df1["id"]) == list(df2["id"])


# ---------------------------------------------------------------------------
# max_rows_in_memory guard
# ---------------------------------------------------------------------------


def test_max_rows_in_memory_exceeded_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("SAMPLE_SIZE", raising=False)
    monkeypatch.setenv("MAX_ROWS_IN_MEMORY", "2")
    monkeypatch.setenv("EXPORT_BASE_DIR", str(tmp_path / "dist"))
    monkeypatch.setenv("PBI_BASE_FOLDER_PARAMETER", str(tmp_path / "dist"))
    f = tmp_path / "data.csv"
    f.write_text("id\n1\n2\n3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="max_rows_in_memory"):
        load_csv(str(f))


def test_max_rows_in_memory_error_message_contains_counts(tmp_path, monkeypatch):
    monkeypatch.delenv("SAMPLE_SIZE", raising=False)
    monkeypatch.setenv("MAX_ROWS_IN_MEMORY", "2")
    monkeypatch.setenv("EXPORT_BASE_DIR", str(tmp_path / "dist"))
    monkeypatch.setenv("PBI_BASE_FOLDER_PARAMETER", str(tmp_path / "dist"))
    f = tmp_path / "data.csv"
    f.write_text("id\n1\n2\n3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="3"):
        load_csv(str(f))


def test_max_rows_in_memory_not_exceeded_loads_ok(tmp_path, monkeypatch):
    monkeypatch.delenv("SAMPLE_SIZE", raising=False)
    monkeypatch.setenv("MAX_ROWS_IN_MEMORY", "10")
    monkeypatch.setenv("EXPORT_BASE_DIR", str(tmp_path / "dist"))
    monkeypatch.setenv("PBI_BASE_FOLDER_PARAMETER", str(tmp_path / "dist"))
    f = tmp_path / "data.csv"
    f.write_text("id\n1\n2\n3\n", encoding="utf-8")
    df, meta = load_csv(str(f))
    assert len(df) == 3


def test_max_rows_in_memory_exact_limit_loads_ok(tmp_path, monkeypatch):
    """Exactly at the limit (not over) should load without error."""
    monkeypatch.delenv("SAMPLE_SIZE", raising=False)
    monkeypatch.setenv("MAX_ROWS_IN_MEMORY", "3")
    monkeypatch.setenv("EXPORT_BASE_DIR", str(tmp_path / "dist"))
    monkeypatch.setenv("PBI_BASE_FOLDER_PARAMETER", str(tmp_path / "dist"))
    f = tmp_path / "data.csv"
    f.write_text("id\n1\n2\n3\n", encoding="utf-8")
    df, meta = load_csv(str(f))
    assert len(df) == 3


# ---------------------------------------------------------------------------
# Regressions: existing error behavior unchanged
# ---------------------------------------------------------------------------


def test_missing_file_still_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_csv(str(tmp_path / "missing.csv"))


def test_empty_file_still_raises_value_error(tmp_path):
    f = tmp_path / "empty.csv"
    f.write_bytes(b"")
    with pytest.raises(ValueError, match="empty or has no columns"):
        load_csv(str(f))
