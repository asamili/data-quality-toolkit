from __future__ import annotations

import json
from pathlib import Path

from data_quality_toolkit import import_drift_history_sqlite, read_drift_columns_sqlite
from data_quality_toolkit.adapters.storage.schema import ensure_db


def _write_report(path: Path, *, run_id: str) -> None:
    envelope = {
        "schema_version": "2",
        "kind": "drift_report",
        "run_id": run_id,
        "created_at": "2026-06-13T00:00:00+00:00",
        "baseline_path": "a",
        "current_path": "b",
        "result": {
            "status": "ok",
            "columns": [
                {
                    "column": "age",
                    "kind": "numeric",
                    "test": "ks",
                    "statistic": 0.4,
                    "p_value": 0.001,
                    "drift_detected": True,
                    "reference_n": 60,
                    "current_n": 60,
                    "status": "tested",
                    "skip_reason": None,
                    "interpretation": "drift",
                    "psi": 0.3,
                    "js_distance": 0.2,
                    "wasserstein": 1.1,
                },
                {
                    "column": "city",
                    "kind": "categorical",
                    "test": "chi_square",
                    "statistic": 1.0,
                    "p_value": 0.9,
                    "drift_detected": False,
                    "reference_n": 60,
                    "current_n": 60,
                    "status": "tested",
                    "skip_reason": None,
                    "interpretation": "no drift",
                    "psi": 0.01,
                    "js_distance": 0.02,
                    "wasserstein": None,
                },
            ],
        },
    }
    path.write_text(json.dumps(envelope), encoding="utf-8")


def _drift_record(report_path: str) -> str:
    record = {
        "schema_version": "1",
        "kind": "drift_history_record",
        "run_id": "r1",
        "created_at": "2026-06-13T00:00:00+00:00",
        "baseline_path": "a",
        "current_path": "b",
        "baseline_dataset_id": "1",
        "current_dataset_id": "2",
        "status": "detected",
        "alpha": 0.05,
        "columns_tested": 2,
        "columns_skipped": 0,
        "columns_drifted": 1,
        "drift_detected": True,
        "report_path": report_path,
    }
    return json.dumps(record) + "\n"


def test_import_populates_columns_via_full_flow(tmp_path: Path) -> None:
    db_path = tmp_path / "drift.db"
    ensure_db(db_path)
    report = tmp_path / "report.json"
    _write_report(report, run_id="r1")
    history = tmp_path / "history.jsonl"
    history.write_text(_drift_record(str(report)), encoding="utf-8")

    # Run-level import returns the number of drift_runs rows, unchanged by columns.
    assert import_drift_history_sqlite(db_path, history) == 1

    rows = read_drift_columns_sqlite(db_path)
    assert len(rows) == 2
    names = {r["column_name"] for r in rows}
    assert names == {"age", "city"}


def test_read_drift_columns_sqlite_filters(tmp_path: Path) -> None:
    db_path = tmp_path / "drift.db"
    ensure_db(db_path)
    report = tmp_path / "report.json"
    _write_report(report, run_id="r1")
    history = tmp_path / "history.jsonl"
    history.write_text(_drift_record(str(report)), encoding="utf-8")
    import_drift_history_sqlite(db_path, history)

    drifted = read_drift_columns_sqlite(db_path, drift_detected=True)
    assert len(drifted) == 1
    assert drifted[0]["column_name"] == "age"

    by_col = read_drift_columns_sqlite(db_path, column_name="city")
    assert len(by_col) == 1
    assert by_col[0]["column_name"] == "city"

    by_run = read_drift_columns_sqlite(db_path, run_id="r1")
    assert len(by_run) == 2


def test_read_drift_columns_sqlite_missing_db_returns_empty(tmp_path: Path) -> None:
    assert read_drift_columns_sqlite(tmp_path / "nope.db") == []
