from __future__ import annotations

import json
import sqlite3
from typing import Any

from data_quality_toolkit.storage.connection import StorageError

_METRIC_FIELDS = ("null_pct", "distinct_count", "completeness")


def persist_export_run(
    con: sqlite3.Connection,
    *,
    run_id: str,
    dataset_id: str,
    source_path: str,
    ts: str,
    score: float,
    completeness_score: float,
    quality_score: float,
    rows: int,
    cols: int,
    memory_mb: float,
    null_threshold: float,
    issues_total: int,
    issues_by_severity: dict[str, Any],
    issues_by_category: dict[str, Any],
    duration_secs: float,
    columns: list[dict[str, Any]],
    quality_metrics: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    try:
        con.execute(
            "INSERT OR IGNORE INTO datasets(dataset_id, source_path) VALUES (?, ?)",
            (dataset_id, source_path),
        )
        for ordinal, col in enumerate(columns):
            if not con.execute(
                "SELECT 1 FROM columns WHERE dataset_id=? AND name=?",
                (dataset_id, col["name"]),
            ).fetchone():
                con.execute(
                    "INSERT INTO columns(dataset_id, name, dtype, ordinal) VALUES (?, ?, ?, ?)",
                    (dataset_id, col["name"], col.get("dtype"), ordinal),
                )
        con.execute(
            """INSERT INTO runs(
                run_id, dataset_id, ts, score, completeness_score, quality_score,
                rows, cols, memory_mb,
                null_threshold, issues_total, issues_by_severity, issues_by_category,
                duration_secs
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                dataset_id,
                ts,
                score,
                completeness_score,
                quality_score,
                rows,
                cols,
                memory_mb,
                null_threshold,
                issues_total,
                json.dumps(issues_by_severity or {}),
                json.dumps(issues_by_category or {}),
                duration_secs,
            ),
        )
        for qm in quality_metrics:
            col_id = str(qm.get("column_id", ""))
            for field in _METRIC_FIELDS:
                if field in qm:
                    con.execute(
                        "INSERT INTO quality_metrics(run_id, column_id, metric_name, value)"
                        " VALUES (?, ?, ?, ?)",
                        (run_id, col_id, field, float(qm[field])),
                    )
        for issue in issues:
            con.execute(
                "INSERT INTO issues(run_id, column_name, severity, category, message)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    issue.get("column"),
                    issue.get("severity"),
                    issue.get("category"),
                    issue.get("message"),
                ),
            )
        con.commit()
    except sqlite3.Error as exc:
        try:
            con.rollback()
        except sqlite3.Error:
            pass
        raise StorageError(str(exc)) from exc
