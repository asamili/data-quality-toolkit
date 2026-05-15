from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from data_quality_toolkit.storage.connection import connect
from data_quality_toolkit.storage.reader import read_run_history
from data_quality_toolkit.storage.schema import ensure_db


def _insert_run(
    con: sqlite3.Connection,
    run_id: str,
    dataset_id: str,
    ts: str,
    score: float = 0.9,
    rows: int = 100,
    issues_by_severity: str = "{}",
    issues_by_category: str = "{}",
) -> None:
    con.execute(
        "INSERT OR IGNORE INTO datasets(dataset_id, source_path) VALUES (?, ?)",
        (dataset_id, "/f.csv"),
    )
    con.execute(
        "INSERT INTO runs(run_id, dataset_id, ts, score, rows, cols, memory_mb,"
        " null_threshold, issues_total, issues_by_severity, issues_by_category,"
        " duration_secs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            dataset_id,
            ts,
            score,
            rows,
            2,
            1.0,
            0.1,
            0,
            issues_by_severity,
            issues_by_category,
            1.0,
        ),
    )
    con.commit()


def test_read_run_history_missing_db_returns_empty(tmp_path: Path) -> None:
    result = read_run_history(tmp_path / "nonexistent.db", "d1")
    assert result == []


def test_read_run_history_empty_db_returns_empty(tmp_path: Path) -> None:
    db = tmp_path / "dqt.db"
    ensure_db(db)
    assert read_run_history(db, "d1") == []


def test_read_run_history_wrong_dataset_returns_empty(tmp_path: Path) -> None:
    db = tmp_path / "dqt.db"
    ensure_db(db)
    con = connect(db)
    try:
        _insert_run(con, "r1", "d1", "2026-01-01T00:00:00Z")
    finally:
        con.close()
    assert read_run_history(db, "other-dataset") == []


def test_read_run_history_returns_runs_ordered_by_ts(tmp_path: Path) -> None:
    db = tmp_path / "dqt.db"
    ensure_db(db)
    con = connect(db)
    try:
        _insert_run(con, "r2", "d1", "2026-01-02T00:00:00Z")  # later ts, inserted first
        _insert_run(con, "r1", "d1", "2026-01-01T00:00:00Z")
    finally:
        con.close()
    result = read_run_history(db, "d1")
    assert len(result) == 2
    assert result[0]["run_id"] == "r1"
    assert result[1]["run_id"] == "r2"


def test_read_run_history_parses_json_fields(tmp_path: Path) -> None:
    db = tmp_path / "dqt.db"
    ensure_db(db)
    con = connect(db)
    try:
        _insert_run(
            con,
            "r1",
            "d1",
            "2026-01-01T00:00:00Z",
            issues_by_severity='{"high": 1}',
            issues_by_category='{"Completeness": 2}',
        )
    finally:
        con.close()
    result = read_run_history(db, "d1")
    assert len(result) == 1
    assert result[0]["issues_by_severity"] == {"high": 1}
    assert result[0]["issues_by_category"] == {"Completeness": 2}


def test_read_run_history_returns_expected_fields(tmp_path: Path) -> None:
    db = tmp_path / "dqt.db"
    ensure_db(db)
    con = connect(db)
    try:
        _insert_run(con, "r1", "d1", "2026-01-01T00:00:00Z", score=0.95, rows=50)
    finally:
        con.close()
    result = read_run_history(db, "d1")
    assert len(result) == 1
    r = result[0]
    assert r["run_id"] == "r1"
    assert r["dataset_id"] == "d1"
    assert r["ts"] == "2026-01-01T00:00:00Z"
    assert r["score"] == pytest.approx(0.95)
    assert r["rows"] == 50
    assert isinstance(r["issues_by_severity"], dict)
    assert isinstance(r["issues_by_category"], dict)
