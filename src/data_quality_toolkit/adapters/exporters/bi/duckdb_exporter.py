"""Drift-history SQLite -> DuckDB export/mirror (v2.7.0).

Local, opt-in, one-shot mirror behind the optional ``[duckdb]`` extra. Reads an
existing drift-monitoring SQLite database **read-only** and writes a standalone
DuckDB database file containing the drift-history tables (``drift_runs``,
``drift_columns``, ``drift_column_distributions``).

Scope guarantees (DQT-v2.7.0-G20):
- DuckDB is export/mirror only — never a live monitoring backend.
- The source SQLite database is never mutated: it is opened with the
  ``mode=ro`` URI flag, and only ``SELECT`` / ``PRAGMA`` statements run against it.
- No SQLite schema changes, no network, no ``.env`` reads, no migrate command.

A missing or unreadable source database raises ``DuckdbExportError``. Drift-history
tables absent from the source are mirrored as empty tables (stable schema).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from data_quality_toolkit.shared.exceptions import DQTError
from data_quality_toolkit.shared.path_guard import PathGuardError, validate_output_dir
from data_quality_toolkit.utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "DuckdbExportError",
    "export_monitoring_duckdb",
]

_DUCKDB_HINT = (
    "duckdb is not installed; install the duckdb extra: " "pip install data-quality-toolkit[duckdb]"
)

# Mirrored drift-history tables, with column order + DuckDB types as the single
# source of truth. Column names/order mirror adapters/storage/schema.py (and the
# stable headers used by xlsx_drift_exporter); the surrogate ``id`` keys are
# intentionally excluded — this mirrors monitoring history, not row identity.
_TABLE_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "drift_runs": (
        ("run_id", "VARCHAR"),
        ("created_at", "VARCHAR"),
        ("baseline_path", "VARCHAR"),
        ("current_path", "VARCHAR"),
        ("baseline_dataset_id", "VARCHAR"),
        ("current_dataset_id", "VARCHAR"),
        ("status", "VARCHAR"),
        ("alpha", "DOUBLE"),
        ("columns_tested", "BIGINT"),
        ("columns_skipped", "BIGINT"),
        ("columns_drifted", "BIGINT"),
        ("drift_detected", "BIGINT"),
        ("report_path", "VARCHAR"),
        ("schema_version", "VARCHAR"),
    ),
    "drift_columns": (
        ("run_id", "VARCHAR"),
        ("column_name", "VARCHAR"),
        ("kind", "VARCHAR"),
        ("test", "VARCHAR"),
        ("statistic", "DOUBLE"),
        ("p_value", "DOUBLE"),
        ("drift_detected", "BIGINT"),
        ("reference_n", "BIGINT"),
        ("current_n", "BIGINT"),
        ("status", "VARCHAR"),
        ("skip_reason", "VARCHAR"),
        ("psi", "DOUBLE"),
        ("js_distance", "DOUBLE"),
        ("wasserstein", "DOUBLE"),
    ),
    "drift_column_distributions": (
        ("run_id", "VARCHAR"),
        ("column_name", "VARCHAR"),
        ("kind", "VARCHAR"),
        ("bin_index", "BIGINT"),
        ("bin_label", "VARCHAR"),
        ("reference_prob", "DOUBLE"),
        ("current_prob", "DOUBLE"),
    ),
}


class DuckdbExportError(DQTError):
    """Raised when the drift-history DuckDB export/mirror fails."""


def _import_duckdb() -> Any:
    """Return the duckdb module, or raise DuckdbExportError with an install hint.

    Isolated so callers and tests can simulate the missing-dependency path
    without installing or uninstalling duckdb. Never imported at package import
    time — duckdb stays fully optional.
    """
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch in tests
        raise DuckdbExportError(_DUCKDB_HINT, hint=_DUCKDB_HINT) from exc
    return duckdb


def _validate_output_path(out_path: str | Path, *, overwrite: bool) -> Path:
    """Validate the ``.duckdb`` output path; refuse overwrite unless ``overwrite``.

    Enforces a non-empty path, the ``.duckdb`` extension, and reuses path_guard
    traversal/symlink rules against the parent directory. Returns the resolved
    Path. Raises DuckdbExportError on any violation.
    """
    raw = str(out_path).strip()
    if not raw:
        raise DuckdbExportError("Output path must not be empty.")

    p = Path(raw)
    if p.suffix.lower() != ".duckdb":
        raise DuckdbExportError(f"Output path must end with .duckdb, got: {p.name}")

    try:
        validate_output_dir(p.parent, must_be_absolute=False)
    except PathGuardError as exc:
        raise DuckdbExportError(str(exc)) from exc

    resolved = p.resolve()
    if resolved.exists():
        if resolved.is_dir():
            raise DuckdbExportError(f"Output path is an existing directory: {resolved}")
        if not overwrite:
            raise DuckdbExportError(
                f"Output file already exists; pass --overwrite to replace it: {resolved}"
            )
    return resolved


def _open_sqlite_readonly(db_path: str | Path) -> sqlite3.Connection:
    """Open the source SQLite DB read-only so the export can never mutate it.

    Validates the file exists first (read-only mode cannot create it), then opens
    with the ``mode=ro`` URI flag. Raises DuckdbExportError on a missing/unreadable
    source.
    """
    src = Path(db_path)
    if not src.exists():
        raise DuckdbExportError(f"Source SQLite database not found: {src}")
    if src.is_dir():
        raise DuckdbExportError(f"Source path is a directory, not a database file: {src}")
    try:
        uri = f"{src.resolve().as_uri()}?mode=ro"
        return sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        raise DuckdbExportError(f"Failed to open source database read-only: {src} ({exc})") from exc


def _sqlite_has_table(con: sqlite3.Connection, table: str) -> bool:
    """Return True if *table* exists in the source SQLite database."""
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def export_monitoring_duckdb(
    db_path: str | Path,
    out_path: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Mirror drift-history monitoring tables from SQLite into a DuckDB file.

    Opens an existing monitoring SQLite database **read-only** (never mutating it)
    and writes a standalone DuckDB database containing the drift-history tables
    ``drift_runs``, ``drift_columns``, and ``drift_column_distributions`` with a
    stable schema. Tables absent from the source are mirrored as empty tables.

    Requires the optional ``[duckdb]`` extra; raises DuckdbExportError with a
    "pip install data-quality-toolkit[duckdb]" hint when it is absent. Refuses to
    overwrite an existing output unless ``overwrite`` is True, in which case the
    output is recreated deterministically (the existing file is removed first).

    Returns ``{"input_db_path", "output_path", "tables", "row_counts", "overwritten"}``.
    """
    duckdb = _import_duckdb()  # fail fast before any I/O
    out = _validate_output_path(out_path, overwrite=overwrite)

    overwritten = out.exists()
    if overwritten:
        out.unlink()  # deterministic recreate

    tables: list[str] = []
    row_counts: dict[str, int] = {}

    src = _open_sqlite_readonly(db_path)
    try:
        dst = duckdb.connect(str(out))
        try:
            for table, columns in _TABLE_COLUMNS.items():
                col_defs = ", ".join(f'"{name}" {dtype}' for name, dtype in columns)
                dst.execute(f'CREATE TABLE "{table}" ({col_defs})')

                count = 0
                if _sqlite_has_table(src, table):
                    col_list = ", ".join(f'"{name}"' for name, _ in columns)
                    # table + col_list are fixed literals from _TABLE_COLUMNS (no user input)
                    rows = src.execute(f"SELECT {col_list} FROM {table}").fetchall()  # noqa: S608
                    if rows:
                        placeholders = ", ".join("?" for _ in columns)
                        dst.executemany(
                            f'INSERT INTO "{table}" VALUES ({placeholders})',  # noqa: S608
                            rows,
                        )
                    count = len(rows)

                tables.append(table)
                row_counts[table] = count
        finally:
            dst.close()
    except DuckdbExportError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize backend/IO errors to a clear export error
        raise DuckdbExportError(f"Failed to write DuckDB mirror to {out}: {exc}") from exc
    finally:
        src.close()

    logger.info("DuckDB mirror written: %s (tables=%s)", out, ",".join(tables))
    return {
        "input_db_path": str(db_path),
        "output_path": str(out),
        "tables": tables,
        "row_counts": row_counts,
        "overwritten": overwritten,
    }
