# tests/unit/test_pipeline_shim.py
from __future__ import annotations

from pathlib import Path

from data_quality_toolkit.workflow.pipeline import run_pipeline_csv_to_star


def test_pipeline_shim(tmp_path: Path):
    csv = tmp_path / "t.csv"
    csv.write_text("id,name\n1,A\n", encoding="utf-8")
    res = run_pipeline_csv_to_star(str(csv), output_dir=str(tmp_path / "dist"))
    arts = res["artifacts"]
    assert arts["dim_dataset"]
    assert arts["dim_column"]
    assert arts["fact_profile_runs"]
    assert arts["fact_quality_metrics"]
    assert arts["fact_profile_runs"]
    assert arts["fact_quality_metrics"]
