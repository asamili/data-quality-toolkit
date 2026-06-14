from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from data_quality_toolkit.adapters.storage.connection import connect
from data_quality_toolkit.adapters.storage.importer import import_drift_history
from data_quality_toolkit.adapters.storage.schema import ensure_db


def _open_db(db_path: Path) -> sqlite3.Connection:
    ensure_db(db_path)
    return connect(db_path)


def _write_jsonl(path: Path, records: list) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _drift_record(**kwargs) -> dict:
    base = {
        "schema_version": "1",
        "kind": "drift_history_record",
        "run_id": "dr1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "baseline_path": "b.csv",
        "current_path": "c.csv",
        "baseline_dataset_id": "bd1",
        "current_dataset_id": "cd1",
        "status": "ok",
        "alpha": 0.05,
        "columns_tested": 2,
        "columns_skipped": 0,
        "columns_drifted": 1,
        "drift_detected": True,
        "report_path": None,
    }
    base.update(kwargs)
    return base


def test_missing_file_returns_0(tmp_path: Path) -> None:
    con = _open_db(tmp_path / "dqt.db")
    try:
        assert import_drift_history(con, tmp_path / "nonexistent.jsonl") == 0
    finally:
        con.close()


def test_valid_drift_jsonl_imports_row(tmp_path: Path) -> None:
    history = tmp_path / "drift_history.jsonl"
    _write_jsonl(history, [_drift_record()])
    con = _open_db(tmp_path / "dqt.db")
    try:
        assert import_drift_history(con, history) == 1
        count = con.execute("SELECT COUNT(*) FROM drift_runs WHERE run_id='dr1'").fetchone()[0]
        assert count == 1
    finally:
        con.close()


def test_malformed_line_skipped_valid_rows_import(tmp_path: Path) -> None:
    history = tmp_path / "drift_history.jsonl"
    history.write_text(
        json.dumps(_drift_record(run_id="dr1")) + "\n"
        "NOT_JSON\n" + json.dumps(_drift_record(run_id="dr2")) + "\n",
        encoding="utf-8",
    )
    con = _open_db(tmp_path / "dqt.db")
    try:
        assert import_drift_history(con, history) == 2
    finally:
        con.close()


def test_missing_run_id_skipped(tmp_path: Path) -> None:
    history = tmp_path / "drift_history.jsonl"
    rec = _drift_record()
    del rec["run_id"]
    _write_jsonl(history, [rec])
    con = _open_db(tmp_path / "dqt.db")
    try:
        assert import_drift_history(con, history) == 0
    finally:
        con.close()


def test_repeated_import_no_duplicates(tmp_path: Path) -> None:
    history = tmp_path / "drift_history.jsonl"
    _write_jsonl(history, [_drift_record()])
    con = _open_db(tmp_path / "dqt.db")
    try:
        import_drift_history(con, history)
        import_drift_history(con, history)
        count = con.execute("SELECT COUNT(*) FROM drift_runs WHERE run_id='dr1'").fetchone()[0]
        assert count == 1
    finally:
        con.close()


def test_repeated_import_returns_0_on_second_call(tmp_path: Path) -> None:
    history = tmp_path / "drift_history.jsonl"
    _write_jsonl(history, [_drift_record()])
    con = _open_db(tmp_path / "dqt.db")
    try:
        assert import_drift_history(con, history) == 1
        assert import_drift_history(con, history) == 0
    finally:
        con.close()


def test_drift_detected_stored_as_integer(tmp_path: Path) -> None:
    history = tmp_path / "drift_history.jsonl"
    _write_jsonl(history, [_drift_record(drift_detected=True)])
    con = _open_db(tmp_path / "dqt.db")
    try:
        import_drift_history(con, history)
        row = con.execute("SELECT drift_detected FROM drift_runs WHERE run_id='dr1'").fetchone()
        assert row is not None
        assert row[0] == 1
        assert isinstance(row[0], int)
    finally:
        con.close()


def test_non_drift_kinds_filtered_out(tmp_path: Path) -> None:
    history = tmp_path / "drift_history.jsonl"
    _write_jsonl(
        history,
        [
            {"kind": "quality_history_record", "run_id": "qr1", "dataset_id": "d1"},
            {"kind": "other", "run_id": "or1"},
        ],
    )
    con = _open_db(tmp_path / "dqt.db")
    try:
        assert import_drift_history(con, history) == 0
        count = con.execute("SELECT COUNT(*) FROM drift_runs").fetchone()[0]
        assert count == 0
    finally:
        con.close()
