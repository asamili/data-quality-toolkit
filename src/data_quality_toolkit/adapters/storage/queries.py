from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from data_quality_toolkit.adapters.storage.connection import StorageError, connect

_DRIFT_RUN_COLUMNS = (
    "run_id, created_at, baseline_path, current_path,"
    " baseline_dataset_id, current_dataset_id, status, alpha,"
    " columns_tested, columns_skipped, columns_drifted,"
    " drift_detected, report_path, schema_version"
)


def read_drift_runs(
    db_path: Path,
    *,
    limit: int | None = None,
    current_dataset_id: str | None = None,
    drift_detected: bool | int | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Return drift_runs rows as JSON-ready dicts, newest first.

    Ordered by created_at descending with a stable run_id ascending tie-break.
    Optional filters narrow the result; when omitted, all rows are returned.
    drift_detected is matched against the stored 0/1 integer.

    Returns [] if the DB does not exist or the drift_runs table has no matching
    rows. Raises StorageError on DB read failure.
    """
    if not db_path.exists():
        return []

    clauses: list[str] = []
    params: list[Any] = []
    if current_dataset_id is not None:
        clauses.append("current_dataset_id = ?")
        params.append(current_dataset_id)
    if drift_detected is not None:
        clauses.append("drift_detected = ?")
        params.append(int(bool(drift_detected)))
    if status is not None:
        clauses.append("status = ?")
        params.append(status)

    sql = f"SELECT {_DRIFT_RUN_COLUMNS} FROM drift_runs"  # noqa: S608 - columns are a fixed literal
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC, run_id ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    try:
        con = connect(db_path)
        try:
            rows = con.execute(sql, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            con.close()
    except sqlite3.Error as exc:
        raise StorageError(str(exc)) from exc


_DRIFT_COLUMN_COLUMNS = (
    "run_id, column_name, kind, test, statistic, p_value, drift_detected,"
    " reference_n, current_n, status, skip_reason, psi, js_distance, wasserstein"
)


def read_drift_columns(
    db_path: Path,
    *,
    run_id: str | None = None,
    column_name: str | None = None,
    drift_detected: bool | int | None = None,
) -> list[dict[str, Any]]:
    """Return drift_columns rows as JSON-ready dicts.

    Ordered by run_id ascending then column_name ascending. Optional filters
    narrow the result; when omitted, all rows are returned. drift_detected is
    matched against the stored 0/1 integer.

    Returns [] if the DB does not exist or the drift_columns table has no
    matching rows. Raises StorageError on DB read failure.
    """
    if not db_path.exists():
        return []

    clauses: list[str] = []
    params: list[Any] = []
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if column_name is not None:
        clauses.append("column_name = ?")
        params.append(column_name)
    if drift_detected is not None:
        clauses.append("drift_detected = ?")
        params.append(int(bool(drift_detected)))

    sql = f"SELECT {_DRIFT_COLUMN_COLUMNS} FROM drift_columns"  # noqa: S608 - columns are a fixed literal
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY run_id ASC, column_name ASC"

    try:
        con = connect(db_path)
        try:
            rows = con.execute(sql, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            con.close()
    except sqlite3.Error as exc:
        raise StorageError(str(exc)) from exc


_DRIFT_DISTRIBUTION_COLUMNS = (
    "run_id, column_name, kind, bin_index, bin_label, reference_prob, current_prob"
)


def read_drift_distributions(
    db_path: Path,
    *,
    run_id: str | None = None,
    column_name: str | None = None,
) -> list[dict[str, Any]]:
    """Return drift_column_distributions rows as JSON-ready dicts.

    Ordered by run_id ascending, then column_name ascending, then bin_index
    ascending. Optional filters narrow the result; when omitted, all rows are
    returned.

    Returns [] if the DB does not exist or the drift_column_distributions table
    has no matching rows. Raises StorageError on DB read failure.
    """
    if not db_path.exists():
        return []

    clauses: list[str] = []
    params: list[Any] = []
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if column_name is not None:
        clauses.append("column_name = ?")
        params.append(column_name)

    sql = f"SELECT {_DRIFT_DISTRIBUTION_COLUMNS} FROM drift_column_distributions"  # noqa: S608 - columns are a fixed literal
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY run_id ASC, column_name ASC, bin_index ASC"

    try:
        con = connect(db_path)
        try:
            rows = con.execute(sql, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            con.close()
    except sqlite3.Error as exc:
        raise StorageError(str(exc)) from exc
