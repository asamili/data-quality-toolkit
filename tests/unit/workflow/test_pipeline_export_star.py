from __future__ import annotations

from pathlib import Path

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
