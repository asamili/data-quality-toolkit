"""End-to-end test for the SQLite -> DuckDB drift-history mirror.

Builds and populates a real monitoring SQLite database, exports it to DuckDB
through the public API, and verifies the mirrored tables and row counts. Gated
behind the optional [duckdb] extra.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from data_quality_toolkit import export_monitoring_duckdb

pytestmark = pytest.mark.integration

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


def _populate(db: Path, *, runs: int, cols_per_run: int, bins_per_col: int) -> None:
    con = sqlite3.connect(str(db))
    try:
        con.executescript(_CREATE)
        for i in range(runs):
            con.execute(
                "INSERT INTO drift_runs (run_id, created_at, status, alpha, columns_tested, "
                "columns_drifted, drift_detected, current_dataset_id) VALUES (?,?,?,?,?,?,?,?)",
                (f"r{i}", f"2026-06-{10 + i:02d}T00:00:00Z", "ok", 0.05, cols_per_run, 1, 1, "cd1"),
            )
            for c in range(cols_per_run):
                con.execute(
                    "INSERT INTO drift_columns (run_id, column_name, kind, test, psi, "
                    "drift_detected) VALUES (?,?,?,?,?,?)",
                    (f"r{i}", f"col{c}", "numeric", "ks", 0.2 + c / 100, 1),
                )
                for b in range(bins_per_col):
                    con.execute(
                        "INSERT INTO drift_column_distributions (run_id, column_name, kind, "
                        "bin_index, bin_label, reference_prob, current_prob) VALUES (?,?,?,?,?,?,?)",
                        (f"r{i}", f"col{c}", "numeric", b, f"bin{b}", 0.25, 0.3),
                    )
        con.commit()
    finally:
        con.close()


def test_export_duckdb_end_to_end(tmp_path: Path) -> None:
    duckdb = pytest.importorskip("duckdb")
    db = tmp_path / "monitoring.db"
    _populate(db, runs=2, cols_per_run=3, bins_per_col=4)
    out = tmp_path / "monitoring.duckdb"

    result = export_monitoring_duckdb(db, out)

    expected = {
        "drift_runs": 2,
        "drift_columns": 6,  # 2 runs * 3 cols
        "drift_column_distributions": 24,  # 6 cols * 4 bins
    }
    assert result["row_counts"] == expected
    assert result["overwritten"] is False
    assert out.exists()

    con = duckdb.connect(str(out))
    try:
        for table, count in expected.items():
            got = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
            assert got == count, table
        # spot-check a mirrored value round-trips intact
        psi = con.execute(
            "SELECT psi FROM drift_columns WHERE run_id='r0' AND column_name='col1'"
        ).fetchone()[0]
        assert psi == pytest.approx(0.21)
    finally:
        con.close()
