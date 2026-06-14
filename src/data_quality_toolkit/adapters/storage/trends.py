from __future__ import annotations

from pathlib import Path
from typing import Any

from data_quality_toolkit.adapters.storage.queries import read_drift_runs


def _zero_summary() -> dict[str, Any]:
    """Stable zero-valued trend summary for empty/missing drift history."""
    return {
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


def summarize_drift_trends(
    db_path: Path,
    *,
    current_dataset_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Summarize drift history over imported drift_runs as a JSON-ready dict.

    Aggregates rows returned by read_drift_runs (newest first, deterministically
    ordered by created_at descending with a run_id ascending tie-break). The
    optional current_dataset_id and limit filters are forwarded to read_drift_runs.

    Returns total_runs, drifted_runs, non_drifted_runs, drift_rate, the latest
    run's run_id/created_at/drift_detected, and columns_tested/columns_drifted
    totals and averages. A missing DB, an empty table, or no matching rows yields
    a stable zero-summary rather than raising. Raises StorageError on DB read
    failure (propagated from read_drift_runs).
    """
    rows = read_drift_runs(db_path, current_dataset_id=current_dataset_id, limit=limit)
    if not rows:
        return _zero_summary()

    total = len(rows)
    drifted = sum(1 for r in rows if int(r["drift_detected"] or 0) == 1)
    tested_total = sum(int(r["columns_tested"] or 0) for r in rows)
    drifted_total = sum(int(r["columns_drifted"] or 0) for r in rows)
    latest = rows[0]  # newest first by read_drift_runs ordering

    return {
        "total_runs": total,
        "drifted_runs": drifted,
        "non_drifted_runs": total - drifted,
        "drift_rate": drifted / total,
        "latest_run_id": latest["run_id"],
        "latest_created_at": latest["created_at"],
        "latest_drift_detected": bool(latest["drift_detected"]),
        "columns_tested_total": tested_total,
        "columns_tested_average": tested_total / total,
        "columns_drifted_total": drifted_total,
        "columns_drifted_average": drifted_total / total,
    }
