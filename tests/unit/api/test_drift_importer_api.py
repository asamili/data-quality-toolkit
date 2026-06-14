from data_quality_toolkit import import_drift_history_sqlite
from data_quality_toolkit.adapters.storage.schema import ensure_db


def test_import_drift_history_sqlite_api(tmp_path):
    # Setup
    db_path = tmp_path / "drift.db"
    ensure_db(db_path)
    history_path = tmp_path / "history.jsonl"
    with open(history_path, "w") as f:
        f.write(
            '{"schema_version": "1", "kind": "drift_history_record", "run_id": "1", "created_at": "2026-06-13T00:00:00", "baseline_path": "a", "current_path": "b", "baseline_dataset_id": "1", "current_dataset_id": "2", "status": "detected", "alpha": 0.05, "columns_tested": 1, "columns_skipped": 0, "columns_drifted": 0, "drift_detected": false, "report_path": null}\n'
        )

    # Action
    count = import_drift_history_sqlite(db_path, history_path)

    # Assert
    assert count == 1
