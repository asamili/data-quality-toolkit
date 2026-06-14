from data_quality_toolkit import import_drift_history_sqlite, read_drift_runs_sqlite
from data_quality_toolkit.adapters.storage.schema import ensure_db

_RECORD = (
    '{"schema_version": "1", "kind": "drift_history_record", "run_id": "1",'
    ' "created_at": "2026-06-13T00:00:00", "baseline_path": "a", "current_path": "b",'
    ' "baseline_dataset_id": "1", "current_dataset_id": "2", "status": "detected",'
    ' "alpha": 0.05, "columns_tested": 1, "columns_skipped": 0, "columns_drifted": 0,'
    ' "drift_detected": false, "report_path": null}\n'
)


def test_read_drift_runs_sqlite_api(tmp_path):
    db_path = tmp_path / "drift.db"
    ensure_db(db_path)
    history_path = tmp_path / "history.jsonl"
    with open(history_path, "w") as f:
        f.write(_RECORD)
    assert import_drift_history_sqlite(db_path, history_path) == 1

    rows = read_drift_runs_sqlite(db_path)

    assert len(rows) == 1
    assert rows[0]["run_id"] == "1"
    assert rows[0]["current_dataset_id"] == "2"


def test_read_drift_runs_sqlite_missing_db_returns_empty(tmp_path):
    assert read_drift_runs_sqlite(tmp_path / "nope.db") == []
