from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from data_quality_toolkit.adapters.storage.connection import StorageError, connect

_JSON_FIELDS = ("issues_by_severity", "issues_by_category")


def read_run_history(db_path: Path, dataset_id: str) -> list[dict[str, Any]]:
    """Return run records for *dataset_id* ordered by ts ascending.

    Returns [] if the DB does not exist or the dataset has no runs.
    Raises StorageError on DB read failure.
    """
    if not db_path.exists():
        return []
    try:
        con = connect(db_path)
        try:
            rows = con.execute(
                "SELECT run_id, dataset_id, ts, score, completeness_score, quality_score,"
                " rows, cols, memory_mb,"
                " null_threshold, issues_total, issues_by_severity,"
                " issues_by_category, duration_secs"
                " FROM runs WHERE dataset_id = ? ORDER BY ts ASC",
                (dataset_id,),
            ).fetchall()
            records: list[dict[str, Any]] = []
            for row in rows:
                r: dict[str, Any] = dict(row)
                for field in _JSON_FIELDS:
                    raw = r.get(field)
                    try:
                        r[field] = json.loads(raw) if raw else {}
                    except (json.JSONDecodeError, TypeError):
                        r[field] = {}
                records.append(r)
            return records
        finally:
            con.close()
    except sqlite3.Error as exc:
        raise StorageError(str(exc)) from exc
