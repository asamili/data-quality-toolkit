from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def import_jsonl_history(con: sqlite3.Connection, history_path: Path) -> int:
    if not history_path.exists():
        return 0

    imported = 0
    with open(history_path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSONL line %d in %s", i, history_path)
                continue

            run_id = record.get("run_id")
            dataset_id = record.get("dataset_id")
            if not run_id or not dataset_id:
                continue

            con.execute(
                "INSERT OR IGNORE INTO datasets(dataset_id, source_path) VALUES (?, ?)",
                (dataset_id, ""),
            )
            con.execute(
                """
                INSERT OR IGNORE INTO runs(
                    run_id, dataset_id, ts, score,
                    rows, cols, memory_mb, null_threshold,
                    issues_total, issues_by_severity, issues_by_category,
                    duration_secs
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    dataset_id,
                    record.get("ts"),
                    record.get("score"),
                    None,
                    None,
                    None,
                    None,
                    record.get("issues_total"),
                    json.dumps(record.get("issues_by_severity") or {}),
                    json.dumps(record.get("issues_by_category") or {}),
                    record.get("duration_secs"),
                ),
            )
            imported += 1

    con.commit()
    return imported
