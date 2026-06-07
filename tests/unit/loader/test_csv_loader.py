# tests/unit/test_csv_loader.py
from __future__ import annotations

import pytest

from data_quality_toolkit.adapters.loaders.file.csv_loader import load_csv


def test_csv_loader_smoke(tmp_path):
    f = tmp_path / "tiny.csv"
    f.write_text("id,name,age\n1,Alice,30\n2,Bob,35\n", encoding="utf-8")
    df, meta = load_csv(str(f))
    assert len(df) == 2
    assert meta["source_path"].endswith("tiny.csv")
    assert meta["rows"] == 2 and meta["cols"] == 3
    assert meta["dataset_id"].startswith("sha1:")
    assert meta["file_size_bytes"] > 0
    assert meta["modified_ts"].endswith("Z")
    assert meta["sample_applied"] in (True, False)


def test_csv_loader_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_csv(str(tmp_path / "missing.csv"))


def test_csv_loader_respects_sampling(tmp_path, monkeypatch):
    # Force SAMPLE_SIZE=1
    monkeypatch.setenv("SAMPLE_SIZE", "1")
    f = tmp_path / "tiny.csv"
    f.write_text("id\n1\n2\n3\n", encoding="utf-8")

    df1, meta1 = load_csv(str(f))
    df2, meta2 = load_csv(str(f))

    # Deterministic & enforced sample
    assert len(df1) == len(df2) == 1
    assert meta1["sample_applied"] is True and meta2["sample_applied"] is True
    # Same sampled row across repeated loads
    assert df1.iloc[0]["id"] == df2.iloc[0]["id"]
