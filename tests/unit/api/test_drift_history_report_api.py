# tests/unit/api/test_drift_history_report_api.py
"""Unit tests for the `drift_history_report` public API wrapper."""

from __future__ import annotations

from pathlib import Path

from data_quality_toolkit import drift_history_report, import_drift_history_sqlite
from data_quality_toolkit.adapters.storage.schema import ensure_db

_RECORDS = (
    '{"schema_version": "1", "kind": "drift_history_record", "run_id": "1",'
    ' "created_at": "2026-06-13T00:00:00", "baseline_path": "a", "current_path": "b",'
    ' "baseline_dataset_id": "1", "current_dataset_id": "2", "status": "detected",'
    ' "alpha": 0.05, "columns_tested": 4, "columns_skipped": 0, "columns_drifted": 2,'
    ' "drift_detected": true, "report_path": null}\n'
)


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "drift.db"
    ensure_db(db_path)
    history_path = tmp_path / "history.jsonl"
    history_path.write_text(_RECORDS, encoding="utf-8")
    assert import_drift_history_sqlite(db_path, history_path) == 1
    return db_path


def test_report_markdown_for_imported_db(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    report = drift_history_report(db_path)
    assert isinstance(report, str)
    assert report.startswith("# Drift History Monitoring Report")
    assert "total_runs:** 1" in report
    assert "drifted_runs:** 1" in report
    assert "| 1 |" in report  # run_id row


def test_report_html_for_imported_db(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    report = drift_history_report(db_path, fmt="html")
    assert report.startswith("<!DOCTYPE html>")
    assert "<table>" in report


def test_report_missing_db_zero_report(tmp_path: Path) -> None:
    missing = tmp_path / "nope.db"
    report = drift_history_report(missing)
    assert "total_runs:** 0" in report
    assert "_(no runs)_" in report


def test_report_current_dataset_id_filter(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    # matching dataset id includes the run; non-matching yields zero
    matched = drift_history_report(db_path, current_dataset_id="2")
    assert "total_runs:** 1" in matched
    unmatched = drift_history_report(db_path, current_dataset_id="nope")
    assert "total_runs:** 0" in unmatched
    assert "_(no runs)_" in unmatched
