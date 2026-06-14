from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit.adapters.storage.connection import connect
from data_quality_toolkit.adapters.storage.importer import import_drift_columns
from data_quality_toolkit.adapters.storage.queries import read_drift_columns
from data_quality_toolkit.adapters.storage.schema import ensure_db


def _open_db(db_path: Path) -> sqlite3.Connection:
    ensure_db(db_path)
    return connect(db_path)


def _column(**kwargs: Any) -> dict[str, Any]:
    base = {
        "column": "age",
        "kind": "numeric",
        "test": "ks",
        "statistic": 0.42,
        "p_value": 0.001,
        "drift_detected": True,
        "reference_n": 60,
        "current_n": 60,
        "status": "tested",
        "skip_reason": None,
        "interpretation": "drift detected",
        "psi": 0.31,
        "js_distance": 0.22,
        "wasserstein": 1.5,
    }
    base.update(kwargs)
    return base


def _write_report(path: Path, columns: list[dict[str, Any]], *, run_id: str = "dr1") -> None:
    envelope = {
        "schema_version": "2",
        "kind": "drift_report",
        "run_id": run_id,
        "created_at": "2026-01-01T00:00:00+00:00",
        "baseline_path": "b.csv",
        "current_path": "c.csv",
        "result": {
            "status": "ok",
            "reason": None,
            "alpha": 0.05,
            "scipy_available": True,
            "columns": columns,
            "summary": {"columns_tested": len(columns)},
        },
    }
    path.write_text(json.dumps(envelope), encoding="utf-8")


def _insert_run(con: sqlite3.Connection, run_id: str, report_path: str | None) -> None:
    con.execute(
        "INSERT INTO drift_runs(run_id, report_path) VALUES (?, ?)",
        (run_id, report_path),
    )
    con.commit()


def test_import_inserts_one_row_per_column(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write_report(report, [_column(column="age"), _column(column="city", kind="categorical")])
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report))
        assert import_drift_columns(con) == 2
        count = con.execute("SELECT COUNT(*) FROM drift_columns WHERE run_id='dr1'").fetchone()[0]
        assert count == 2
    finally:
        con.close()


def test_column_key_maps_to_column_name(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write_report(report, [_column(column="age")])
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report))
        import_drift_columns(con)
        row = con.execute(
            "SELECT column_name, psi, js_distance, wasserstein FROM drift_columns"
        ).fetchone()
        assert row["column_name"] == "age"
        assert row["psi"] == pytest.approx(0.31)
        assert row["js_distance"] == pytest.approx(0.22)
        assert row["wasserstein"] == pytest.approx(1.5)
    finally:
        con.close()


def test_drift_detected_stored_as_integer(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write_report(report, [_column(drift_detected=True), _column(column="x", drift_detected=False)])
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report))
        import_drift_columns(con)
        rows = read_drift_columns(tmp_path / "dqt.db")
        by_name = {r["column_name"]: r for r in rows}
        assert by_name["age"]["drift_detected"] == 1
        assert isinstance(by_name["age"]["drift_detected"], int)
        assert by_name["x"]["drift_detected"] == 0
    finally:
        con.close()


def test_drift_detected_none_preserved(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write_report(report, [_column(status="skipped", drift_detected=None, skip_reason="all_null")])
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report))
        import_drift_columns(con)
        row = read_drift_columns(tmp_path / "dqt.db")[0]
        assert row["drift_detected"] is None
        assert row["skip_reason"] == "all_null"
    finally:
        con.close()


def test_read_filters_by_run_id(tmp_path: Path) -> None:
    report1 = tmp_path / "r1.json"
    report2 = tmp_path / "r2.json"
    _write_report(report1, [_column(column="a")], run_id="dr1")
    _write_report(report2, [_column(column="b")], run_id="dr2")
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report1))
        _insert_run(con, "dr2", str(report2))
        import_drift_columns(con)
        rows = read_drift_columns(tmp_path / "dqt.db", run_id="dr2")
        assert len(rows) == 1
        assert rows[0]["run_id"] == "dr2"
        assert rows[0]["column_name"] == "b"
    finally:
        con.close()


def test_read_filters_by_column_name(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write_report(report, [_column(column="age"), _column(column="city")])
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report))
        import_drift_columns(con)
        rows = read_drift_columns(tmp_path / "dqt.db", column_name="city")
        assert len(rows) == 1
        assert rows[0]["column_name"] == "city"
    finally:
        con.close()


def test_read_filters_by_drift_detected(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write_report(
        report,
        [_column(column="a", drift_detected=True), _column(column="b", drift_detected=False)],
    )
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report))
        import_drift_columns(con)
        rows = read_drift_columns(tmp_path / "dqt.db", drift_detected=True)
        assert len(rows) == 1
        assert rows[0]["column_name"] == "a"
    finally:
        con.close()


def test_missing_db_returns_empty(tmp_path: Path) -> None:
    assert read_drift_columns(tmp_path / "nope.db") == []


def test_empty_table_returns_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    assert read_drift_columns(db_path) == []


def test_null_report_path_skipped(tmp_path: Path) -> None:
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", None)
        assert import_drift_columns(con) == 0
        assert read_drift_columns(tmp_path / "dqt.db") == []
    finally:
        con.close()


def test_missing_report_file_skipped(tmp_path: Path) -> None:
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(tmp_path / "does_not_exist.json"))
        assert import_drift_columns(con) == 0
        assert read_drift_columns(tmp_path / "dqt.db") == []
    finally:
        con.close()


def test_unreadable_report_skipped(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("NOT JSON", encoding="utf-8")
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(bad))
        assert import_drift_columns(con) == 0
    finally:
        con.close()


def test_report_without_columns_skipped(tmp_path: Path) -> None:
    no_cols = tmp_path / "nocols.json"
    no_cols.write_text(json.dumps({"result": {"status": "unavailable"}}), encoding="utf-8")
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(no_cols))
        assert import_drift_columns(con) == 0
    finally:
        con.close()


def test_reimport_idempotent(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write_report(report, [_column(column="a"), _column(column="b")])
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report))
        import_drift_columns(con)
        import_drift_columns(con)
        count = con.execute("SELECT COUNT(*) FROM drift_columns WHERE run_id='dr1'").fetchone()[0]
        assert count == 2
    finally:
        con.close()


def test_drift_schema_version_is_3(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        value = con.execute(
            "SELECT value FROM schema_meta WHERE key='drift_schema_version'"
        ).fetchone()[0]
        assert value == "3"
    finally:
        con.close()


def test_existing_v1_db_upgraded_to_3(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    # Simulate a legacy DB pinned at drift_schema_version '1'.
    con = connect(db_path)
    try:
        con.execute("UPDATE schema_meta SET value='1' WHERE key='drift_schema_version'")
        con.commit()
    finally:
        con.close()
    ensure_db(db_path)  # re-run migration
    con = connect(db_path)
    try:
        value = con.execute(
            "SELECT value FROM schema_meta WHERE key='drift_schema_version'"
        ).fetchone()[0]
        assert value == "3"
    finally:
        con.close()
