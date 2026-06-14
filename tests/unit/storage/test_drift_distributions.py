from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from data_quality_toolkit.adapters.storage.connection import connect
from data_quality_toolkit.adapters.storage.importer import (
    import_drift_distributions,
    import_drift_history,
)
from data_quality_toolkit.adapters.storage.queries import read_drift_distributions
from data_quality_toolkit.adapters.storage.schema import ensure_db


def _open_db(db_path: Path) -> sqlite3.Connection:
    ensure_db(db_path)
    return connect(db_path)


def _numeric_distribution() -> dict[str, Any]:
    return {
        "kind": "numeric",
        "bins": [
            {"label": "[-inf, 1.5)", "reference": 0.6, "current": 0.4},
            {"label": "[1.5, inf)", "reference": 0.4, "current": 0.6},
        ],
    }


def _column(**kwargs: Any) -> dict[str, Any]:
    base = {
        "column": "age",
        "kind": "numeric",
        "test": "ks",
        "statistic": 0.42,
        "p_value": 0.001,
        "drift_detected": True,
        "reference_n": 60,
        "current_n": 60,
        "status": "tested",
        "skip_reason": None,
        "interpretation": "drift detected",
        "psi": 0.31,
        "js_distance": 0.22,
        "wasserstein": 1.5,
        "distribution": _numeric_distribution(),
    }
    base.update(kwargs)
    return base


def _write_report(
    path: Path,
    columns: list[dict[str, Any]],
    *,
    run_id: str = "dr1",
    schema_version: str = "3",
) -> None:
    envelope = {
        "schema_version": schema_version,
        "kind": "drift_report",
        "run_id": run_id,
        "created_at": "2026-01-01T00:00:00+00:00",
        "baseline_path": "b.csv",
        "current_path": "c.csv",
        "result": {
            "status": "ok",
            "columns": columns,
            "summary": {"columns_tested": len(columns)},
        },
    }
    path.write_text(json.dumps(envelope), encoding="utf-8")


def _insert_run(con: sqlite3.Connection, run_id: str, report_path: str | None) -> None:
    con.execute(
        "INSERT INTO drift_runs(run_id, report_path) VALUES (?, ?)",
        (run_id, report_path),
    )
    con.commit()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_distribution_table_exists(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='drift_column_distributions'"
        ).fetchone()
        assert row is not None
    finally:
        con.close()


def test_distribution_index_exists(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_drift_col_dist_run'"
        ).fetchone()
        assert row is not None
    finally:
        con.close()


def test_fresh_db_drift_schema_version_is_3(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        value = con.execute(
            "SELECT value FROM schema_meta WHERE key='drift_schema_version'"
        ).fetchone()[0]
        assert value == "3"
    finally:
        con.close()


def test_legacy_v2_db_upgraded_to_3(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    con = connect(db_path)
    try:
        con.execute("UPDATE schema_meta SET value='2' WHERE key='drift_schema_version'")
        con.commit()
    finally:
        con.close()
    ensure_db(db_path)  # re-run migration
    con = connect(db_path)
    try:
        value = con.execute(
            "SELECT value FROM schema_meta WHERE key='drift_schema_version'"
        ).fetchone()[0]
        assert value == "3"
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------


def test_import_inserts_one_row_per_bin(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write_report(report, [_column(column="age")])
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report))
        assert import_drift_distributions(con) == 2
        count = con.execute(
            "SELECT COUNT(*) FROM drift_column_distributions WHERE run_id='dr1'"
        ).fetchone()[0]
        assert count == 2
    finally:
        con.close()


def test_import_persists_bin_fields(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write_report(report, [_column(column="age")])
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report))
        import_drift_distributions(con)
    finally:
        con.close()
    rows = read_drift_distributions(tmp_path / "dqt.db")
    assert [r["bin_index"] for r in rows] == [0, 1]
    first = rows[0]
    assert first["column_name"] == "age"
    assert first["kind"] == "numeric"
    assert first["bin_label"] == "[-inf, 1.5)"
    assert first["reference_prob"] == 0.6
    assert first["current_prob"] == 0.4


def test_column_without_distribution_skipped(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write_report(report, [_column(column="age", distribution=None)])
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report))
        assert import_drift_distributions(con) == 0
    finally:
        con.close()


def test_v2_report_without_distribution_key_imports_zero_rows(tmp_path: Path) -> None:
    # Legacy v2 evidence report: column entries have no "distribution" key at all.
    legacy_col = _column(column="age")
    legacy_col.pop("distribution")
    report = tmp_path / "report.json"
    _write_report(report, [legacy_col], schema_version="2")
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report))
        assert import_drift_distributions(con) == 0
        assert read_drift_distributions(tmp_path / "dqt.db") == []
    finally:
        con.close()


def test_bins_not_a_list_skipped(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write_report(report, [_column(distribution={"kind": "numeric", "bins": "oops"})])
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report))
        assert import_drift_distributions(con) == 0
    finally:
        con.close()


def test_null_report_path_skipped(tmp_path: Path) -> None:
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", None)
        assert import_drift_distributions(con) == 0
    finally:
        con.close()


def test_missing_report_file_skipped(tmp_path: Path) -> None:
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(tmp_path / "nope.json"))
        assert import_drift_distributions(con) == 0
    finally:
        con.close()


def test_unreadable_report_skipped(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("NOT JSON", encoding="utf-8")
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(bad))
        assert import_drift_distributions(con) == 0
    finally:
        con.close()


def test_reimport_idempotent(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write_report(report, [_column(column="age"), _column(column="score")])
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report))
        import_drift_distributions(con)
        import_drift_distributions(con)
        count = con.execute(
            "SELECT COUNT(*) FROM drift_column_distributions WHERE run_id='dr1'"
        ).fetchone()[0]
        assert count == 4  # 2 columns x 2 bins, stable across re-import
    finally:
        con.close()


def test_full_flow_return_value_unchanged_and_distributions_populated(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    report = tmp_path / "report.json"
    _write_report(report, [_column(column="age")], run_id="r1")
    history = tmp_path / "history.jsonl"
    record = {
        "schema_version": "1",
        "kind": "drift_history_record",
        "run_id": "r1",
        "report_path": str(report),
    }
    history.write_text(json.dumps(record) + "\n", encoding="utf-8")

    con = connect(db_path)
    try:
        # Run-level import return value is the number of drift_runs rows inserted.
        assert import_drift_history(con, history) == 1
    finally:
        con.close()
    assert len(read_drift_distributions(db_path)) == 2


# ---------------------------------------------------------------------------
# Query helper
# ---------------------------------------------------------------------------


def test_read_filters_by_run_id(tmp_path: Path) -> None:
    r1 = tmp_path / "r1.json"
    r2 = tmp_path / "r2.json"
    _write_report(r1, [_column(column="a")], run_id="dr1")
    _write_report(r2, [_column(column="b")], run_id="dr2")
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(r1))
        _insert_run(con, "dr2", str(r2))
        import_drift_distributions(con)
    finally:
        con.close()
    rows = read_drift_distributions(tmp_path / "dqt.db", run_id="dr2")
    assert {r["run_id"] for r in rows} == {"dr2"}
    assert {r["column_name"] for r in rows} == {"b"}


def test_read_filters_by_column_name(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write_report(report, [_column(column="age"), _column(column="city")])
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report))
        import_drift_distributions(con)
    finally:
        con.close()
    rows = read_drift_distributions(tmp_path / "dqt.db", column_name="city")
    assert {r["column_name"] for r in rows} == {"city"}


def test_read_ordered_by_run_column_bin(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _write_report(report, [_column(column="zeta"), _column(column="alpha")])
    con = _open_db(tmp_path / "dqt.db")
    try:
        _insert_run(con, "dr1", str(report))
        import_drift_distributions(con)
    finally:
        con.close()
    rows = read_drift_distributions(tmp_path / "dqt.db")
    keys = [(r["column_name"], r["bin_index"]) for r in rows]
    assert keys == [("alpha", 0), ("alpha", 1), ("zeta", 0), ("zeta", 1)]


def test_missing_db_returns_empty(tmp_path: Path) -> None:
    assert read_drift_distributions(tmp_path / "nope.db") == []


def test_empty_table_returns_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "dqt.db"
    ensure_db(db_path)
    assert read_drift_distributions(db_path) == []
