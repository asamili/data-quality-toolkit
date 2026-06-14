from data_quality_toolkit import import_drift_history_sqlite, summarize_drift_trends_sqlite
from data_quality_toolkit.adapters.storage.schema import ensure_db

_RECORDS = (
    '{"schema_version": "1", "kind": "drift_history_record", "run_id": "1",'
    ' "created_at": "2026-06-13T00:00:00", "baseline_path": "a", "current_path": "b",'
    ' "baseline_dataset_id": "1", "current_dataset_id": "2", "status": "detected",'
    ' "alpha": 0.05, "columns_tested": 4, "columns_skipped": 0, "columns_drifted": 2,'
    ' "drift_detected": true, "report_path": null}\n'
    '{"schema_version": "1", "kind": "drift_history_record", "run_id": "2",'
    ' "created_at": "2026-06-12T00:00:00", "baseline_path": "a", "current_path": "b",'
    ' "baseline_dataset_id": "1", "current_dataset_id": "2", "status": "clear",'
    ' "alpha": 0.05, "columns_tested": 4, "columns_skipped": 0, "columns_drifted": 0,'
    ' "drift_detected": false, "report_path": null}\n'
)


def test_summarize_drift_trends_sqlite_api(tmp_path):
    db_path = tmp_path / "drift.db"
    ensure_db(db_path)
    history_path = tmp_path / "history.jsonl"
    with open(history_path, "w") as f:
        f.write(_RECORDS)
    assert import_drift_history_sqlite(db_path, history_path) == 2

    summary = summarize_drift_trends_sqlite(db_path)

    assert summary["total_runs"] == 2
    assert summary["drifted_runs"] == 1
    assert summary["non_drifted_runs"] == 1
    assert summary["drift_rate"] == 0.5
    assert summary["latest_run_id"] == "1"
    assert summary["latest_created_at"] == "2026-06-13T00:00:00"
    assert summary["latest_drift_detected"] is True
    assert summary["columns_tested_total"] == 8
    assert summary["columns_drifted_total"] == 2


def test_summarize_drift_trends_sqlite_missing_db_returns_zero_summary(tmp_path):
    summary = summarize_drift_trends_sqlite(tmp_path / "nope.db")
    assert summary["total_runs"] == 0
    assert summary["drift_rate"] == 0.0
    assert summary["latest_run_id"] is None
