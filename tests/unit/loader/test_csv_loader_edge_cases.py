from __future__ import annotations

import pytest

from data_quality_toolkit.loaders.file.csv_loader import load_csv


@pytest.mark.unit
def test_single_row_csv_shape(tmp_path):
    f = tmp_path / "one.csv"
    f.write_text("id,value\n1,hello\n", encoding="utf-8")
    df, meta = load_csv(str(f))
    assert df.shape == (1, 2)
    assert meta["rows"] == 1
    assert meta["cols"] == 2


@pytest.mark.unit
def test_single_row_metadata_no_sampling(tmp_path, monkeypatch):
    monkeypatch.delenv("SAMPLE_SIZE", raising=False)
    f = tmp_path / "one.csv"
    f.write_text("id\n42\n", encoding="utf-8")
    _, meta = load_csv(str(f))
    assert meta["rows"] == 1
    assert meta["sample_applied"] is False


@pytest.mark.unit
def test_oversized_random_sample_behavior(tmp_path, monkeypatch):
    # SAMPLE_SIZE=3 with 5-row file → 3 rows chosen by deterministic random sample,
    # not simply the first 3 rows. All returned values must come from the population.
    monkeypatch.setenv("SAMPLE_SIZE", "3")
    f = tmp_path / "five.csv"
    f.write_text("n\n10\n20\n30\n40\n50\n", encoding="utf-8")
    df, meta = load_csv(str(f))
    assert meta["rows"] == 3
    assert meta["sample_applied"] is True
    assert set(df["n"]).issubset({10, 20, 30, 40, 50})
    # Deterministic: same file → same sample on repeated calls
    df2, _ = load_csv(str(f))
    assert list(df["n"]) == list(df2["n"])


@pytest.mark.unit
def test_encoding_kwarg_passthrough(tmp_path):
    # Explicit encoding="utf-8" kwarg forwarded to pandas read_csv unchanged
    f = tmp_path / "utf8.csv"
    f.write_text("id,label\n1,hello\n2,world\n", encoding="utf-8")
    df, meta = load_csv(str(f), encoding="utf-8")
    assert meta["rows"] == 2
    assert list(df["label"]) == ["hello", "world"]


@pytest.mark.unit
def test_latin1_file_with_encoding_kwarg(tmp_path):
    # File with latin-1 bytes (café, brûlée); must load cleanly with encoding="latin-1"
    f = tmp_path / "latin1.csv"
    f.write_bytes(b"name\ncaf\xe9\nbr\xfbl\xe9e\n")
    df, meta = load_csv(str(f), encoding="latin-1")
    assert meta["rows"] == 2
    assert "café" in df["name"].values
