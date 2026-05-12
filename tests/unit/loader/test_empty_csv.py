"""Tests for empty / no-column CSV file handling in the loader."""

from __future__ import annotations

import pytest

from data_quality_toolkit.loaders.file.csv_loader import load_csv


def test_zero_byte_file_raises_value_error(tmp_path):
    f = tmp_path / "empty.csv"
    f.write_bytes(b"")
    with pytest.raises(ValueError, match="empty or has no columns"):
        load_csv(str(f))


def test_whitespace_only_file_raises_value_error(tmp_path):
    f = tmp_path / "blank.csv"
    f.write_text("   \n\n  \t  \n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty or has no columns"):
        load_csv(str(f))


def test_error_message_contains_file_path(tmp_path):
    f = tmp_path / "mydata.csv"
    f.write_bytes(b"")
    with pytest.raises(ValueError, match="mydata.csv"):
        load_csv(str(f))


def test_header_only_file_loads_successfully(tmp_path):
    """A CSV with a header but no data rows should load without error."""
    f = tmp_path / "header_only.csv"
    f.write_text("id,name,age\n", encoding="utf-8")
    df, meta = load_csv(str(f))
    assert df.shape == (0, 3)
    assert list(df.columns) == ["id", "name", "age"]
    assert meta["rows"] == 0
    assert meta["cols"] == 3


def test_normal_file_unaffected(tmp_path):
    """Regression: normal CSV still loads correctly."""
    f = tmp_path / "data.csv"
    f.write_text("id,val\n1,a\n2,b\n", encoding="utf-8")
    df, meta = load_csv(str(f))
    assert len(df) == 2
    assert meta["cols"] == 2
