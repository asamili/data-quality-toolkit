from __future__ import annotations

import sqlite3
from pathlib import Path

from data_quality_toolkit.adapters.storage.connection import connect
from data_quality_toolkit.adapters.storage.importer import import_jsonl_history

_CREATE_TABLES = """\
CREATE TABLE IF NOT EXISTS datasets (
    dataset_id  TEXT PRIMARY KEY,
    source_path TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS columns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id  TEXT NOT NULL REFERENCES datasets(dataset_id),
    name        TEXT NOT NULL,
    dtype       TEXT,
    ordinal     INTEGER
);
CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    dataset_id          TEXT NOT NULL REFERENCES datasets(dataset_id),
    ts                  TEXT,
    score               REAL,
    rows                INTEGER,
    cols                INTEGER,
    memory_mb           REAL,
    null_threshold      REAL,
    issues_total        INTEGER,
    issues_by_severity  TEXT,
    issues_by_category  TEXT,
    duration_secs       REAL
);
CREATE TABLE IF NOT EXISTS quality_metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    column_id   TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value       REAL
);
CREATE TABLE IF NOT EXISTS issues (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    column_name TEXT,
    severity    TEXT,
    category    TEXT,
    message     TEXT
);
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_CREATE_INDEXES = """\
CREATE INDEX IF NOT EXISTS idx_runs_dataset ON runs(dataset_id);
CREATE INDEX IF NOT EXISTS idx_columns_dataset ON columns(dataset_id);
CREATE INDEX IF NOT EXISTS idx_metrics_run ON quality_metrics(run_id);
CREATE INDEX IF NOT EXISTS idx_issues_run ON issues(run_id);
"""


def ensure_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = connect(db_path)
    try:
        con.executescript(_CREATE_TABLES)
        con.executescript(_CREATE_INDEXES)
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', '1')")
        for _col, _typ in [("completeness_score", "REAL"), ("quality_score", "REAL")]:
            try:
                con.execute(f"ALTER TABLE runs ADD COLUMN {_col} {_typ}")
            except sqlite3.OperationalError:
                pass  # column already exists in existing DBs
        con.commit()
        count = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        if count == 0:
            history_path = db_path.parent / "star" / "quality_history.jsonl"
            import_jsonl_history(con, history_path)
    finally:
        con.close()
