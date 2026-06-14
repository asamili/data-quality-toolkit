from __future__ import annotations

import sqlite3
from pathlib import Path

from data_quality_toolkit.adapters.storage.connection import connect
from data_quality_toolkit.adapters.storage.schema import ensure_db
from data_quality_toolkit.adapters.storage.trends import summarize_drift_trends

_EXPECTED_KEYS = {
    "total_runs",
    "drifted_runs",
    "non_drifted_runs",
    "drift_rate",
    "latest_run_id",
    "latest_created_at",
    "latest_drift_detected",
    "columns_tested_total",
    "columns_tested_average",
    "columns_drifted_total",
    "columns_drifted_average",
}

_ZERO_SUMMARY = {
    "total_runs": 0,
    "drifted_runs": 0,
    "non_drifted_runs": 0,
    "drift_rate": 0.0,
    "latest_run_id": None,
    "latest_created_at": None,
    "latest_drift_detected": None,
    "columns_tested_total": 0,
    "columns_tested_average": 0.0,
    "columns_drifted_total": 0,
    "columns_drifted_average": 0.0,
}


def _insert_run(
    con: sqlite3.Connection,
    run_id: str,
    *,
    created_at: str,
    current_dataset_id: str = "cd1",
    status: str = "ok",
    drift_detected: int = 0,
    columns_tested: int = 2,
    columns_drifted: int = 0,
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
            columns_tested,
            0,
            columns_drifted,
            drift_detected,
            None,
            "1",
        ),
    )
    con.commit()


def test_missing_db_returns_zero_summary(tmp_path: Path) -> None:
    assert summarize_drift_trends(tmp_path / "nonexistent.db") == _ZERO_SUMMARY


def test_empty_table_returns_zero_summary(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    assert summarize_drift_trends(db_path) == _ZERO_SUMMARY


def test_summary_has_expected_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        _insert_run(con, "r1", created_at="2026-01-01T00:00:00+00:00")
    finally:
        con.close()

    assert set(summarize_drift_trends(db_path).keys()) == _EXPECTED_KEYS


def test_aggregates_counts_rate_totals_and_averages(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        _insert_run(
            con,
            "r1",
            created_at="2026-01-01T00:00:00+00:00",
            drift_detected=1,
            columns_tested=4,
            columns_drifted=2,
        )
        _insert_run(
            con,
            "r2",
            created_at="2026-02-01T00:00:00+00:00",
            drift_detected=0,
            columns_tested=6,
            columns_drifted=0,
        )
        _insert_run(
            con,
            "r3",
            created_at="2026-03-01T00:00:00+00:00",
            drift_detected=1,
            columns_tested=2,
            columns_drifted=1,
        )
    finally:
        con.close()

    summary = summarize_drift_trends(db_path)
    assert summary["total_runs"] == 3
    assert summary["drifted_runs"] == 2
    assert summary["non_drifted_runs"] == 1
    assert summary["drift_rate"] == 2 / 3
    assert summary["columns_tested_total"] == 12
    assert summary["columns_tested_average"] == 4.0
    assert summary["columns_drifted_total"] == 3
    assert summary["columns_drifted_average"] == 1.0


def test_latest_fields_track_newest_created_at(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        # inserted out of chronological order
        _insert_run(con, "r1", created_at="2026-01-01T00:00:00+00:00", drift_detected=0)
        _insert_run(con, "r2", created_at="2026-03-01T00:00:00+00:00", drift_detected=1)
        _insert_run(con, "r3", created_at="2026-02-01T00:00:00+00:00", drift_detected=0)
    finally:
        con.close()

    summary = summarize_drift_trends(db_path)
    assert summary["latest_run_id"] == "r2"
    assert summary["latest_created_at"] == "2026-03-01T00:00:00+00:00"
    assert summary["latest_drift_detected"] is True


def test_current_dataset_id_filter_narrows_aggregate(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        _insert_run(
            con,
            "r1",
            created_at="2026-01-01T00:00:00+00:00",
            current_dataset_id="A",
            drift_detected=1,
        )
        _insert_run(
            con,
            "r2",
            created_at="2026-02-01T00:00:00+00:00",
            current_dataset_id="B",
            drift_detected=0,
        )
    finally:
        con.close()

    summary = summarize_drift_trends(db_path, current_dataset_id="A")
    assert summary["total_runs"] == 1
    assert summary["drifted_runs"] == 1
    assert summary["latest_run_id"] == "r1"


def test_limit_caps_runs_aggregated(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        _insert_run(con, "r1", created_at="2026-01-01T00:00:00+00:00", drift_detected=1)
        _insert_run(con, "r2", created_at="2026-02-01T00:00:00+00:00", drift_detected=1)
        _insert_run(con, "r3", created_at="2026-03-01T00:00:00+00:00", drift_detected=0)
    finally:
        con.close()

    # limit keeps the 2 newest (r3, r2) per read_drift_runs ordering
    summary = summarize_drift_trends(db_path, limit=2)
    assert summary["total_runs"] == 2
    assert summary["drifted_runs"] == 1
    assert summary["latest_run_id"] == "r3"
