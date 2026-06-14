from __future__ import annotations

import sqlite3
from pathlib import Path

from data_quality_toolkit.adapters.storage.connection import connect
from data_quality_toolkit.adapters.storage.queries import read_drift_runs
from data_quality_toolkit.adapters.storage.schema import ensure_db

_EXPECTED_KEYS = {
    "run_id",
    "created_at",
    "baseline_path",
    "current_path",
    "baseline_dataset_id",
    "current_dataset_id",
    "status",
    "alpha",
    "columns_tested",
    "columns_skipped",
    "columns_drifted",
    "drift_detected",
    "report_path",
    "schema_version",
}


def _insert_run(
    con: sqlite3.Connection,
    run_id: str,
    *,
    created_at: str,
    current_dataset_id: str = "cd1",
    status: str = "ok",
    drift_detected: int = 0,
) -> None:
    con.execute(
        """
        INSERT INTO drift_runs(
            run_id, created_at, baseline_path, current_path,
            baseline_dataset_id, current_dataset_id, status, alpha,
            columns_tested, columns_skipped, columns_drifted,
            drift_detected, report_path, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            created_at,
            "b.csv",
            "c.csv",
            "bd1",
            current_dataset_id,
            status,
            0.05,
            2,
            0,
            1,
            drift_detected,
            None,
            "1",
        ),
    )
    con.commit()


def test_missing_db_returns_empty(tmp_path: Path) -> None:
    assert read_drift_runs(tmp_path / "nonexistent.db") == []


def test_empty_table_returns_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    assert read_drift_runs(db_path) == []


def test_returns_all_rows_newest_first(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        _insert_run(con, "r1", created_at="2026-01-01T00:00:00+00:00")
        _insert_run(con, "r2", created_at="2026-03-01T00:00:00+00:00")
        _insert_run(con, "r3", created_at="2026-02-01T00:00:00+00:00")
    finally:
        con.close()

    rows = read_drift_runs(db_path)
    assert [r["run_id"] for r in rows] == ["r2", "r3", "r1"]


def test_stable_run_id_tiebreak_on_equal_created_at(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    ts = "2026-01-01T00:00:00+00:00"
    con = connect(db_path)
    try:
        _insert_run(con, "rb", created_at=ts)
        _insert_run(con, "ra", created_at=ts)
        _insert_run(con, "rc", created_at=ts)
    finally:
        con.close()

    rows = read_drift_runs(db_path)
    assert [r["run_id"] for r in rows] == ["ra", "rb", "rc"]


def test_limit_caps_result_count(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        _insert_run(con, "r1", created_at="2026-01-01T00:00:00+00:00")
        _insert_run(con, "r2", created_at="2026-02-01T00:00:00+00:00")
        _insert_run(con, "r3", created_at="2026-03-01T00:00:00+00:00")
    finally:
        con.close()

    rows = read_drift_runs(db_path, limit=2)
    assert [r["run_id"] for r in rows] == ["r3", "r2"]


def test_current_dataset_id_filter(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        _insert_run(con, "r1", created_at="2026-01-01T00:00:00+00:00", current_dataset_id="A")
        _insert_run(con, "r2", created_at="2026-02-01T00:00:00+00:00", current_dataset_id="B")
    finally:
        con.close()

    rows = read_drift_runs(db_path, current_dataset_id="A")
    assert [r["run_id"] for r in rows] == ["r1"]


def test_drift_detected_filter(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        _insert_run(con, "r1", created_at="2026-01-01T00:00:00+00:00", drift_detected=1)
        _insert_run(con, "r2", created_at="2026-02-01T00:00:00+00:00", drift_detected=0)
    finally:
        con.close()

    detected = read_drift_runs(db_path, drift_detected=True)
    assert [r["run_id"] for r in detected] == ["r1"]
    not_detected = read_drift_runs(db_path, drift_detected=False)
    assert [r["run_id"] for r in not_detected] == ["r2"]


def test_status_filter(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        _insert_run(con, "r1", created_at="2026-01-01T00:00:00+00:00", status="ok")
        _insert_run(con, "r2", created_at="2026-02-01T00:00:00+00:00", status="unavailable")
    finally:
        con.close()

    rows = read_drift_runs(db_path, status="unavailable")
    assert [r["run_id"] for r in rows] == ["r2"]


def test_rows_are_json_ready_dicts(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        _insert_run(con, "r1", created_at="2026-01-01T00:00:00+00:00", drift_detected=1)
    finally:
        con.close()

    rows = read_drift_runs(db_path)
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, dict)
    assert set(row.keys()) == _EXPECTED_KEYS
    assert isinstance(row["drift_detected"], int)
