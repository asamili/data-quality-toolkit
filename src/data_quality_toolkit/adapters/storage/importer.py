from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from data_quality_toolkit.adapters.storage.jsonl import read_drift_history

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


def import_drift_history(con: sqlite3.Connection, history_path: Path) -> int:
    records = read_drift_history(history_path)
    imported = 0
    for record in records:
        run_id = record.get("run_id")
        if not run_id:
            continue
        drift_detected = record.get("drift_detected")
        cur = con.execute(
            """
            INSERT OR IGNORE INTO drift_runs(
                run_id, created_at, baseline_path, current_path,
                baseline_dataset_id, current_dataset_id,
                status, alpha,
                columns_tested, columns_skipped, columns_drifted,
                drift_detected, report_path, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                record.get("created_at"),
                record.get("baseline_path"),
                record.get("current_path"),
                record.get("baseline_dataset_id"),
                record.get("current_dataset_id"),
                record.get("status"),
                record.get("alpha"),
                record.get("columns_tested"),
                record.get("columns_skipped"),
                record.get("columns_drifted"),
                int(bool(drift_detected)) if drift_detected is not None else None,
                record.get("report_path"),
                record.get("schema_version"),
            ),
        )
        imported += cur.rowcount
    con.commit()
    # Populate per-column drift results from referenced evidence reports.
    import_drift_columns(con)
    # Populate per-column distribution bins from the same evidence reports.
    import_drift_distributions(con)
    return imported


def _load_report_columns(report_path: str | None) -> list[dict]:
    """Return result.columns[] from an evidence report, or [] on any failure.

    Never raises: a null, missing, unreadable, non-JSON, or malformed report
    yields an empty list so that run-level import is not affected by a missing
    or broken report artifact.
    """
    if not report_path:
        return []
    path = Path(report_path)
    if not path.exists():
        return []
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        columns = envelope["result"]["columns"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        logger.warning("Skipping unreadable drift report %s", report_path)
        return []
    if not isinstance(columns, list):
        return []
    return columns


def import_drift_columns(con: sqlite3.Connection) -> int:
    """Import per-column drift results from drift_runs.report_path evidence reports.

    For each drift_runs row with a report_path, loads the evidence report and
    inserts one drift_columns row per result.columns[] entry. Idempotent via
    delete-then-insert per run_id. Missing/unreadable reports are skipped without
    failing. Returns the number of column rows inserted.
    """
    rows = con.execute(
        "SELECT run_id, report_path FROM drift_runs WHERE report_path IS NOT NULL"
    ).fetchall()
    imported = 0
    for run_id, report_path in rows:
        columns = _load_report_columns(report_path)
        if not columns:
            continue
        con.execute("DELETE FROM drift_columns WHERE run_id = ?", (run_id,))
        for col in columns:
            drift_detected = col.get("drift_detected")
            con.execute(
                """
                INSERT INTO drift_columns(
                    run_id, column_name, kind, test, statistic, p_value,
                    drift_detected, reference_n, current_n, status, skip_reason,
                    psi, js_distance, wasserstein
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    col.get("column"),  # evidence report key is "column"
                    col.get("kind"),
                    col.get("test"),
                    col.get("statistic"),
                    col.get("p_value"),
                    int(bool(drift_detected)) if drift_detected is not None else None,
                    col.get("reference_n"),
                    col.get("current_n"),
                    col.get("status"),
                    col.get("skip_reason"),
                    col.get("psi"),
                    col.get("js_distance"),
                    col.get("wasserstein"),
                ),
            )
            imported += 1
    con.commit()
    return imported


def _insert_column_distribution(con: sqlite3.Connection, run_id: str, col: dict) -> int:
    """Insert distribution bins for one evidence-report column entry; return row count.

    Returns 0 when the column carries no usable distribution (None, missing, or a
    non-list ``bins``). The evidence report key for the column name is "column".
    """
    distribution = col.get("distribution")
    if not isinstance(distribution, dict):
        return 0
    bins = distribution.get("bins")
    if not isinstance(bins, list):
        return 0
    column_name = col.get("column")
    kind = distribution.get("kind")
    inserted = 0
    for bin_index, b in enumerate(bins):
        if not isinstance(b, dict):
            continue
        con.execute(
            """
            INSERT INTO drift_column_distributions(
                run_id, column_name, kind, bin_index, bin_label,
                reference_prob, current_prob
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                column_name,
                kind,
                bin_index,
                b.get("label"),
                b.get("reference"),
                b.get("current"),
            ),
        )
        inserted += 1
    return inserted


def import_drift_distributions(con: sqlite3.Connection) -> int:
    """Import per-column distribution bins from drift_runs.report_path evidence reports.

    For each drift_runs row with a report_path, loads the evidence report and
    inserts one drift_column_distributions row per bin in each
    result.columns[].distribution.bins entry. Idempotent via delete-then-insert
    per run_id. Columns without a usable distribution are skipped; missing or
    unreadable reports are skipped without failing. Returns the number of
    distribution-bin rows inserted.
    """
    rows = con.execute(
        "SELECT run_id, report_path FROM drift_runs WHERE report_path IS NOT NULL"
    ).fetchall()
    imported = 0
    for run_id, report_path in rows:
        columns = _load_report_columns(report_path)
        if not columns:
            continue
        con.execute("DELETE FROM drift_column_distributions WHERE run_id = ?", (run_id,))
        for col in columns:
            imported += _insert_column_distribution(con, run_id, col)
    con.commit()
    return imported
