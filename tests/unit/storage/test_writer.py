from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from data_quality_toolkit.adapters.storage.connection import StorageError, connect
from data_quality_toolkit.adapters.storage.schema import ensure_db
from data_quality_toolkit.adapters.storage.writer import persist_export_run

_COLUMNS = [{"name": "id", "dtype": "int64"}, {"name": "age", "dtype": "float64"}]
_QUALITY_METRICS = [
    {
        "run_id": "r1",
        "column_id": "col_id",
        "null_pct": 0.0,
        "distinct_count": 10,
        "completeness": 1.0,
    },
    {
        "run_id": "r1",
        "column_id": "col_age",
        "null_pct": 0.1,
        "distinct_count": 8,
        "completeness": 0.9,
    },
]


def _run_kwargs(run_id: str = "r1", dataset_id: str = "d1", source_path: str = "/data/f.csv"):
    return dict(
        run_id=run_id,
        dataset_id=dataset_id,
        source_path=source_path,
        ts="2026-01-01T00:00:00Z",
        score=0.95,
        completeness_score=0.95,
        quality_score=0.92,
        rows=100,
        cols=2,
        memory_mb=1.0,
        null_threshold=0.1,
        issues_total=0,
        issues_by_severity={},
        issues_by_category={},
        duration_secs=1.0,
        columns=_COLUMNS,
        quality_metrics=_QUALITY_METRICS,
        issues=[],
    )


def _open_db(db_path: Path) -> sqlite3.Connection:
    ensure_db(db_path)
    return connect(db_path)


def test_persist_export_run_inserts_all_tables(tmp_path: Path) -> None:
    con = _open_db(tmp_path / "dqt.db")
    try:
        persist_export_run(con, **_run_kwargs())
        assert con.execute("SELECT COUNT(*) FROM datasets WHERE dataset_id='d1'").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM columns WHERE dataset_id='d1'").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM runs WHERE run_id='r1'").fetchone()[0] == 1
        assert (
            con.execute("SELECT COUNT(*) FROM quality_metrics WHERE run_id='r1'").fetchone()[0] == 6
        )
        assert con.execute("SELECT COUNT(*) FROM issues WHERE run_id='r1'").fetchone()[0] == 0
    finally:
        con.close()


def test_persist_export_run_repeated_dataset_no_duplicates(tmp_path: Path) -> None:
    con = _open_db(tmp_path / "dqt.db")
    try:
        persist_export_run(con, **_run_kwargs(run_id="r1"))
        persist_export_run(con, **_run_kwargs(run_id="r2"))
        assert con.execute("SELECT COUNT(*) FROM datasets WHERE dataset_id='d1'").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM columns WHERE dataset_id='d1'").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
    finally:
        con.close()


def test_persist_export_run_empty_issues_accepted(tmp_path: Path) -> None:
    con = _open_db(tmp_path / "dqt.db")
    try:
        persist_export_run(con, **_run_kwargs(run_id="r1"))
        assert con.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == 0
    finally:
        con.close()


def test_persist_export_run_source_path_stored(tmp_path: Path) -> None:
    con = _open_db(tmp_path / "dqt.db")
    try:
        persist_export_run(con, **_run_kwargs(source_path="/custom/path.csv"))
        row = con.execute("SELECT source_path FROM datasets WHERE dataset_id='d1'").fetchone()
        assert row["source_path"] == "/custom/path.csv"
    finally:
        con.close()


def test_persist_export_run_metric_detail_preserved(tmp_path: Path) -> None:
    con = _open_db(tmp_path / "dqt.db")
    try:
        persist_export_run(con, **_run_kwargs())
        rows = con.execute(
            "SELECT column_id, metric_name, value FROM quality_metrics WHERE run_id='r1'"
        ).fetchall()
        assert len(rows) == 6
        metric_names = {r["metric_name"] for r in rows}
        assert metric_names == {"null_pct", "distinct_count", "completeness"}
        column_ids = {r["column_id"] for r in rows}
        assert column_ids == {"col_id", "col_age"}
        completeness_by_col = {
            r["column_id"]: r["value"] for r in rows if r["metric_name"] == "completeness"
        }
        assert completeness_by_col["col_id"] == pytest.approx(1.0)
        assert completeness_by_col["col_age"] == pytest.approx(0.9)
    finally:
        con.close()


def test_persist_export_run_score_values_readable(tmp_path: Path) -> None:
    from data_quality_toolkit.adapters.storage.reader import read_run_history

    db = tmp_path / "dqt.db"
    con = _open_db(db)
    try:
        persist_export_run(con, **_run_kwargs())
    finally:
        con.close()
    records = read_run_history(db, "d1")
    assert len(records) == 1
    r = records[0]
    assert r["completeness_score"] == pytest.approx(0.95)
    assert r["quality_score"] == pytest.approx(0.92)


def test_persist_export_run_duplicate_run_raises_storage_error(tmp_path: Path) -> None:
    con = _open_db(tmp_path / "dqt.db")
    try:
        persist_export_run(con, **_run_kwargs(run_id="r1"))
        with pytest.raises(StorageError):
            persist_export_run(con, **_run_kwargs(run_id="r1"))
    finally:
        con.close()
