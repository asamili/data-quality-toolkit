from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import data_quality_toolkit
from data_quality_toolkit import import_drift_history_sqlite, read_drift_distributions_sqlite
from data_quality_toolkit.adapters.storage.schema import ensure_db


def _column(column: str) -> dict[str, Any]:
    return {
        "column": column,
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
        "distribution": {
            "kind": "numeric",
            "bins": [
                {"label": "[-inf, 1.5)", "reference": 0.6, "current": 0.4},
                {"label": "[1.5, inf)", "reference": 0.4, "current": 0.6},
            ],
        },
    }


def _write_report(path: Path, columns: list[dict[str, Any]], *, run_id: str) -> None:
    envelope = {
        "schema_version": "3",
        "kind": "drift_report",
        "run_id": run_id,
        "created_at": "2026-06-13T00:00:00+00:00",
        "baseline_path": "a",
        "current_path": "b",
        "result": {"status": "ok", "columns": columns},
    }
    path.write_text(json.dumps(envelope), encoding="utf-8")


def _drift_record(report_path: str, run_id: str) -> str:
    record = {
        "schema_version": "1",
        "kind": "drift_history_record",
        "run_id": run_id,
        "report_path": report_path,
    }
    return json.dumps(record) + "\n"


def _import(db_path: Path, columns: list[dict[str, Any]], *, run_id: str = "r1") -> None:
    ensure_db(db_path)
    report = db_path.parent / f"{run_id}.json"
    _write_report(report, columns, run_id=run_id)
    history = db_path.parent / f"{run_id}.jsonl"
    history.write_text(_drift_record(str(report), run_id), encoding="utf-8")
    import_drift_history_sqlite(db_path, history)


def test_returns_rows_via_full_flow(tmp_path: Path) -> None:
    db_path = tmp_path / "drift.db"
    _import(db_path, [_column("age")])
    rows = read_drift_distributions_sqlite(db_path)
    assert len(rows) == 2
    assert {r["column_name"] for r in rows} == {"age"}
    assert [r["bin_index"] for r in rows] == [0, 1]


def test_filters_by_run_id(tmp_path: Path) -> None:
    db_path = tmp_path / "drift.db"
    _import(db_path, [_column("age")], run_id="r1")
    _import(db_path, [_column("score")], run_id="r2")
    rows = read_drift_distributions_sqlite(db_path, run_id="r2")
    assert {r["run_id"] for r in rows} == {"r2"}
    assert {r["column_name"] for r in rows} == {"score"}


def test_filters_by_column_name(tmp_path: Path) -> None:
    db_path = tmp_path / "drift.db"
    _import(db_path, [_column("age"), _column("city")])
    rows = read_drift_distributions_sqlite(db_path, column_name="city")
    assert {r["column_name"] for r in rows} == {"city"}


def test_missing_db_returns_empty(tmp_path: Path) -> None:
    assert read_drift_distributions_sqlite(tmp_path / "nope.db") == []


def test_exported_from_package() -> None:
    assert hasattr(data_quality_toolkit, "read_drift_distributions_sqlite")
    assert "read_drift_distributions_sqlite" in data_quality_toolkit.__all__
