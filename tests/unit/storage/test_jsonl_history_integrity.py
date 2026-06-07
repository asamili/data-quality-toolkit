import json
import logging
import sqlite3

from data_quality_toolkit.adapters.storage.importer import import_jsonl_history
from data_quality_toolkit.adapters.storage.jsonl import append_jsonl_record


def test_append_jsonl_record(tmp_path):
    path = tmp_path / "test.jsonl"
    record = {"a": 1, "b": "test"}
    append_jsonl_record(path, record)

    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == record


def test_importer_skips_malformed(tmp_path, caplog):
    path = tmp_path / "corrupt.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"run_id": "1", "dataset_id": "d1"}\n')
        f.write('{"malformed": }\n')
        f.write('{"run_id": "2", "dataset_id": "d2"}\n')

    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE datasets(dataset_id TEXT, source_path TEXT)")
    con.execute("""
        CREATE TABLE runs(
            run_id TEXT, dataset_id TEXT, ts TEXT, score REAL,
            rows INTEGER, cols INTEGER, memory_mb REAL, null_threshold REAL,
            issues_total INTEGER, issues_by_severity TEXT, issues_by_category TEXT,
            duration_secs REAL
        )
    """)

    with caplog.at_level(logging.WARNING):
        import_jsonl_history(con, path)
        assert "Skipping malformed JSONL line 2" in caplog.text

    # Check if valid records were still imported
    res = con.execute("SELECT count(*) FROM datasets").fetchone()[0]
    assert res == 2
