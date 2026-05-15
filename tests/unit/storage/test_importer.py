from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from data_quality_toolkit.storage.connection import connect
from data_quality_toolkit.storage.importer import import_jsonl_history
from data_quality_toolkit.storage.schema import ensure_db


def _open_db(db_path: Path) -> sqlite3.Connection:
    ensure_db(db_path)
    return connect(db_path)


def _write_jsonl(path: Path, records: list) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def test_missing_file_returns_0(tmp_path: Path) -> None:
    con = _open_db(tmp_path / "dqt.db")
    try:
        assert import_jsonl_history(con, tmp_path / "nonexistent.jsonl") == 0
    finally:
        con.close()


def test_valid_jsonl_imports_records(tmp_path: Path) -> None:
    history = tmp_path / "quality_history.jsonl"
    _write_jsonl(
        history,
        [
            {
                "run_id": "r1",
                "dataset_id": "d1",
                "ts": "2026-01-01T00:00:00Z",
                "score": 0.9,
                "issues_total": 0,
                "issues_by_severity": {},
                "issues_by_category": {},
                "duration_secs": 1.0,
            },
        ],
    )
    con = _open_db(tmp_path / "dqt.db")
    try:
        assert import_jsonl_history(con, history) == 1
        count = con.execute("SELECT COUNT(*) FROM runs WHERE run_id='r1'").fetchone()[0]
        assert count == 1
    finally:
        con.close()


def test_malformed_line_skipped(tmp_path: Path) -> None:
    history = tmp_path / "quality_history.jsonl"
    history.write_text(
        '{"run_id": "r1", "dataset_id": "d1", "ts": "2026-01-01T00:00:00Z",'
        ' "score": 0.9, "issues_total": 0, "issues_by_severity": {},'
        ' "issues_by_category": {}, "duration_secs": 1.0}\n'
        "NOT_JSON\n",
        encoding="utf-8",
    )
    con = _open_db(tmp_path / "dqt.db")
    try:
        assert import_jsonl_history(con, history) == 1
    finally:
        con.close()


def test_missing_run_id_skipped(tmp_path: Path) -> None:
    history = tmp_path / "quality_history.jsonl"
    _write_jsonl(
        history,
        [
            {
                "dataset_id": "d1",
                "ts": "2026-01-01T00:00:00Z",
                "score": 0.9,
                "issues_total": 0,
                "issues_by_severity": {},
                "issues_by_category": {},
                "duration_secs": 0.1,
            },
        ],
    )
    con = _open_db(tmp_path / "dqt.db")
    try:
        assert import_jsonl_history(con, history) == 0
    finally:
        con.close()


def test_missing_dataset_id_skipped(tmp_path: Path) -> None:
    history = tmp_path / "quality_history.jsonl"
    _write_jsonl(
        history,
        [
            {
                "run_id": "r1",
                "ts": "2026-01-01T00:00:00Z",
                "score": 0.9,
                "issues_total": 0,
                "issues_by_severity": {},
                "issues_by_category": {},
                "duration_secs": 0.1,
            },
        ],
    )
    con = _open_db(tmp_path / "dqt.db")
    try:
        assert import_jsonl_history(con, history) == 0
    finally:
        con.close()


def test_repeated_import_no_duplicates(tmp_path: Path) -> None:
    history = tmp_path / "quality_history.jsonl"
    _write_jsonl(
        history,
        [
            {
                "run_id": "r1",
                "dataset_id": "d1",
                "ts": "2026-01-01T00:00:00Z",
                "score": 0.9,
                "issues_total": 0,
                "issues_by_severity": {},
                "issues_by_category": {},
                "duration_secs": 1.0,
            },
        ],
    )
    con = _open_db(tmp_path / "dqt.db")
    try:
        import_jsonl_history(con, history)
        import_jsonl_history(con, history)
        count = con.execute("SELECT COUNT(*) FROM runs WHERE run_id='r1'").fetchone()[0]
        assert count == 1
    finally:
        con.close()
