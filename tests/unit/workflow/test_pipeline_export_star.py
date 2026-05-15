from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from data_quality_toolkit.workflow.pipeline import run_export_star


def test_run_export_star_creates_csvs_and_relationships(tmp_path):
    f = tmp_path / "tiny.csv"
    f.write_text("id,age\n1,30\n2,40\n", encoding="utf-8")

    out = run_export_star(str(f), output_dir=str(tmp_path))

    # basic structure
    assert set(out.keys()) >= {
        "run_id",
        "dataset_id",
        "ts",
        "meta",
        "profile",
        "star",
        "export_paths",
    }

    # files exist
    paths = out["export_paths"]
    expected = {
        "dim_dataset",
        "dim_column",
        "fact_profile_runs",
        "fact_quality_metrics",
        "fact_issues",
        "quality_history",
        "relationships",
    }
    assert expected.issubset(set(paths.keys()))

    for p in paths.values():
        assert Path(p).exists(), f"missing file: {p}"

    # history file must be a valid JSONL with at least one record
    import json

    history_lines = Path(paths["quality_history"]).read_text(encoding="utf-8").splitlines()
    assert len(history_lines) >= 1
    record = json.loads(history_lines[-1])
    assert "issues_by_severity" in record
    assert "issues_by_category" in record

    # star info consistency
    star = out["star"]
    assert set(star["tables"]) >= {
        "dim_dataset",
        "dim_column",
        "fact_profile_runs",
        "fact_quality_metrics",
    }
    assert isinstance(star["rows"], dict)


def test_run_export_star_creates_sqlite_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DQT_DB_PATH", str(tmp_path / "dqt.db"))

    f = tmp_path / "tiny.csv"
    f.write_text("id,age\n1,30\n2,40\n", encoding="utf-8")

    out = run_export_star(str(f), output_dir=str(tmp_path))

    db_path = tmp_path / "dqt.db"
    assert db_path.exists()

    con = sqlite3.connect(str(db_path))
    try:
        run_id = out["run_id"]

        # runs table has exactly one row for this run
        assert con.execute("SELECT COUNT(*) FROM runs WHERE run_id=?", (run_id,)).fetchone()[0] == 1

        # quality_metrics: 2 columns × 3 metrics (null_pct, distinct_count, completeness) = 6
        assert (
            con.execute(
                "SELECT COUNT(*) FROM quality_metrics WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            == 6
        )

        # quality_history.jsonl still exists and has at least one record
        qh = Path(out["export_paths"]["quality_history"])
        assert qh.exists()
        record = json.loads(qh.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert "run_id" in record

        # star CSVs still exist
        for key in ("dim_dataset", "dim_column", "fact_profile_runs", "fact_quality_metrics"):
            assert Path(out["export_paths"][key]).exists()
    finally:
        con.close()
