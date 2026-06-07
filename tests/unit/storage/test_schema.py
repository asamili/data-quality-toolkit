from __future__ import annotations

import sqlite3
from pathlib import Path

from data_quality_toolkit.adapters.storage.schema import ensure_db

_EXPECTED_TABLES = {"datasets", "columns", "runs", "quality_metrics", "issues", "schema_meta"}
_EXPECTED_INDEXES = {"idx_runs_dataset", "idx_columns_dataset", "idx_metrics_run", "idx_issues_run"}


def _table_names(db_path: Path) -> set[str]:
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {r[0] for r in rows}
    finally:
        con.close()


def _index_names(db_path: Path) -> set[str]:
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        return {r[0] for r in rows}
    finally:
        con.close()


def test_ensure_db_creates_tables(tmp_path: Path) -> None:
    ensure_db(tmp_path / "dqt.db")
    assert _EXPECTED_TABLES.issubset(_table_names(tmp_path / "dqt.db"))


def test_ensure_db_creates_indexes(tmp_path: Path) -> None:
    ensure_db(tmp_path / "dqt.db")
    assert _EXPECTED_INDEXES.issubset(_index_names(tmp_path / "dqt.db"))


def test_ensure_db_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    ensure_db(db_path)
    assert _EXPECTED_TABLES.issubset(_table_names(db_path))


def test_schema_version_is_1(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = sqlite3.connect(str(db_path))
    try:
        row = con.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        assert row is not None
        assert row[0] == "1"
    finally:
        con.close()


def test_wal_mode_enabled(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = sqlite3.connect(str(db_path))
    try:
        row = con.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"
    finally:
        con.close()


def test_no_jsonl_means_empty_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = sqlite3.connect(str(db_path))
    try:
        count = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        assert count == 0
    finally:
        con.close()
