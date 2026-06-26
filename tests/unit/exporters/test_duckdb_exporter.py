# tests/unit/exporters/test_duckdb_exporter.py
"""Unit tests for the drift-history SQLite -> DuckDB export/mirror.

Path safety and the missing-dependency guard are testable without the optional
[duckdb] extra. On-disk mirror tests (real DuckDB writes) are gated behind
``importorskip("duckdb")``.
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

from data_quality_toolkit.adapters.exporters.bi import duckdb_exporter as de
from data_quality_toolkit.adapters.exporters.bi.duckdb_exporter import (
    DuckdbExportError,
    export_monitoring_duckdb,
)
from data_quality_toolkit.shared.exceptions import DQTError

# --- sample monitoring DB helper (drift-history tables only) ---

_CREATE = """\
CREATE TABLE drift_runs (
    run_id TEXT PRIMARY KEY, created_at TEXT, baseline_path TEXT, current_path TEXT,
    baseline_dataset_id TEXT, current_dataset_id TEXT, status TEXT, alpha REAL,
    columns_tested INTEGER, columns_skipped INTEGER, columns_drifted INTEGER,
    drift_detected INTEGER, report_path TEXT, schema_version TEXT
);
CREATE TABLE drift_columns (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, column_name TEXT NOT NULL,
    kind TEXT, test TEXT, statistic REAL, p_value REAL, drift_detected INTEGER,
    reference_n INTEGER, current_n INTEGER, status TEXT, skip_reason TEXT,
    psi REAL, js_distance REAL, wasserstein REAL
);
CREATE TABLE drift_column_distributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, column_name TEXT NOT NULL,
    kind TEXT, bin_index INTEGER NOT NULL, bin_label TEXT, reference_prob REAL, current_prob REAL
);
"""


def _make_monitoring_db(path: Path, *, n_runs: int = 2) -> None:
    con = sqlite3.connect(str(path))
    try:
        con.executescript(_CREATE)
        for i in range(n_runs):
            con.execute(
                "INSERT INTO drift_runs (run_id, created_at, status, alpha, columns_tested, "
                "drift_detected, current_dataset_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"r{i}", f"2026-06-1{i}T00:00:00Z", "ok", 0.05, 3, i % 2, "cd1"),
            )
            con.execute(
                "INSERT INTO drift_columns (run_id, column_name, kind, test, statistic, "
                "p_value, drift_detected, psi) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"r{i}", "age", "numeric", "ks", 0.12, 0.4, 0, 0.31),
            )
            con.execute(
                "INSERT INTO drift_column_distributions (run_id, column_name, kind, bin_index, "
                "bin_label, reference_prob, current_prob) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"r{i}", "age", "numeric", 0, "[0, 1)", 0.5, 0.4),
            )
        con.commit()
    finally:
        con.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- path validation (no duckdb needed) ---


def test_validate_output_path_rejects_empty() -> None:
    with pytest.raises(DuckdbExportError, match="must not be empty"):
        de._validate_output_path("   ", overwrite=False)


def test_validate_output_path_requires_duckdb_extension(tmp_path: Path) -> None:
    with pytest.raises(DuckdbExportError, match=r"must end with .duckdb"):
        de._validate_output_path(tmp_path / "out.sqlite", overwrite=False)


def test_validate_output_path_rejects_traversal() -> None:
    with pytest.raises(DuckdbExportError):
        de._validate_output_path("../escape.duckdb", overwrite=False)


def test_validate_output_path_refuses_overwrite_without_flag(tmp_path: Path) -> None:
    existing = tmp_path / "out.duckdb"
    existing.write_bytes(b"old")
    with pytest.raises(DuckdbExportError, match="already exists"):
        de._validate_output_path(existing, overwrite=False)


def test_validate_output_path_allows_overwrite_with_flag(tmp_path: Path) -> None:
    existing = tmp_path / "out.duckdb"
    existing.write_bytes(b"old")
    resolved = de._validate_output_path(existing, overwrite=True)
    assert resolved.name == "out.duckdb"


def test_validate_output_path_rejects_directory_target(tmp_path: Path) -> None:
    d = tmp_path / "adir.duckdb"
    d.mkdir()
    with pytest.raises(DuckdbExportError, match="existing directory"):
        de._validate_output_path(d, overwrite=True)


# --- missing-dependency guard ---


def test_missing_duckdb_raises_with_install_hint(monkeypatch, tmp_path: Path) -> None:
    # Force `import duckdb` to fail regardless of install state.
    monkeypatch.setitem(sys.modules, "duckdb", None)
    db = tmp_path / "m.db"
    _make_monitoring_db(db)
    with pytest.raises(DuckdbExportError) as ei:
        export_monitoring_duckdb(db, tmp_path / "out.duckdb")
    msg = str(ei.value)
    assert "duckdb" in msg
    assert isinstance(ei.value, DQTError)


# --- missing source DB ---


def test_missing_source_db_raises(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    with pytest.raises(DuckdbExportError, match="not found"):
        export_monitoring_duckdb(tmp_path / "nope.db", tmp_path / "out.duckdb")


# --- on-disk mirror (requires the [duckdb] extra) ---


def test_export_mirrors_tables_and_row_counts(tmp_path: Path) -> None:
    duckdb = pytest.importorskip("duckdb")
    db = tmp_path / "m.db"
    _make_monitoring_db(db, n_runs=3)
    out = tmp_path / "m.duckdb"

    result = export_monitoring_duckdb(db, out)

    assert result["input_db_path"] == str(db)
    assert result["output_path"] == str(out.resolve())
    assert result["overwritten"] is False
    assert result["tables"] == [
        "drift_runs",
        "drift_columns",
        "drift_column_distributions",
    ]
    assert result["row_counts"] == {
        "drift_runs": 3,
        "drift_columns": 3,
        "drift_column_distributions": 3,
    }

    con = duckdb.connect(str(out))
    try:
        names = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        assert names == {"drift_runs", "drift_columns", "drift_column_distributions"}
        assert con.execute("SELECT COUNT(*) FROM drift_runs").fetchone()[0] == 3
        # data integrity: a known value survives the mirror
        psi = con.execute("SELECT psi FROM drift_columns WHERE run_id = 'r0' LIMIT 1").fetchone()[0]
        assert psi == pytest.approx(0.31)
    finally:
        con.close()


def test_export_does_not_mutate_sqlite(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    db = tmp_path / "m.db"
    _make_monitoring_db(db)
    before = _sha256(db)
    before_mtime = db.stat().st_mtime_ns

    export_monitoring_duckdb(db, tmp_path / "out.duckdb")

    assert _sha256(db) == before
    assert db.stat().st_mtime_ns == before_mtime
    # read-only access must not leave WAL/SHM side files
    assert not (tmp_path / "m.db-wal").exists()
    assert not (tmp_path / "m.db-shm").exists()


def test_export_overwrite_recreates_deterministically(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    db = tmp_path / "m.db"
    _make_monitoring_db(db)
    out = tmp_path / "m.duckdb"
    out.write_bytes(b"stale-not-a-duckdb")

    with pytest.raises(DuckdbExportError, match="already exists"):
        export_monitoring_duckdb(db, out)

    result = export_monitoring_duckdb(db, out, overwrite=True)
    assert result["overwritten"] is True


def test_export_missing_drift_tables_yields_empty_mirror(tmp_path: Path) -> None:
    duckdb = pytest.importorskip("duckdb")
    # A SQLite DB with none of the drift-history tables present.
    db = tmp_path / "bare.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE unrelated (x INTEGER)")
    con.commit()
    con.close()
    out = tmp_path / "bare.duckdb"

    result = export_monitoring_duckdb(db, out)
    assert result["row_counts"] == {
        "drift_runs": 0,
        "drift_columns": 0,
        "drift_column_distributions": 0,
    }
    con = duckdb.connect(str(out))
    try:
        names = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        assert names == {"drift_runs", "drift_columns", "drift_column_distributions"}
    finally:
        con.close()
