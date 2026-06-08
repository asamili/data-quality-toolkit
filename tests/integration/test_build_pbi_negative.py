# tests/integration/test_build_pbi_negative.py
"""Phase 2: Negative integration test — relationship/header mismatch."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit.adapters.exporters.bi.powerbi_exporter import export_powerbi_package


def _write_minimal_star(star_dir: Path) -> Path:
    """Write a minimal valid star schema directly (fallback when pipeline helpers are absent)."""
    star_dir.mkdir(parents=True, exist_ok=True)
    (star_dir / "dim_dataset.csv").write_text("dataset_id,source_path\n1,\n", encoding="utf-8")
    (star_dir / "dim_column.csv").write_text(
        "column_id,dataset_id,column_name,dtype\n1__id,1,id,int64\n", encoding="utf-8"
    )
    (star_dir / "fact_profile_runs.csv").write_text(
        "run_id,dataset_id,ts,rows,cols,memory_mb\n" "r1,1,2024-01-02T00:00:00Z,3,2,10\n",
        encoding="utf-8",
    )
    (star_dir / "fact_quality_metrics.csv").write_text(
        "run_id,column_id,null_pct,distinct_count,completeness\n" "r1,1__id,0.0,3,1.0\n",
        encoding="utf-8",
    )
    return star_dir


def _extract_artifacts(obj: Any) -> dict[str, Any]:
    """Safely pull artifact paths from a pipeline result."""
    if isinstance(obj, dict):
        maybe = obj.get("artifacts") or obj.get("export_paths")
        if isinstance(maybe, dict):
            return maybe  # already a dict[str, Any]
    return {}


def _make_star(tmp_path: Path) -> Path:
    """Create a small CSV and build Phase-1 star via pipeline if available; otherwise fallback."""
    test_csv = tmp_path / "test.csv"
    test_csv.write_text("id,name,score\n1,Alice,95\n", encoding="utf-8")

    try:
        pl = importlib.import_module("data_quality_toolkit.application.workflow.pipeline")
    except Exception:
        pl = None

    if pl is not None:
        run1 = getattr(pl, "run_pipeline_csv_to_star", None)
        if callable(run1):
            star_result = run1(str(test_csv))
            artifacts = _extract_artifacts(star_result)
            dd = artifacts.get("dim_dataset")
            if isinstance(dd, str):
                return Path(dd).parent

        run2 = getattr(pl, "run_export_star", None)
        if callable(run2):
            outdir = tmp_path / "dist"
            result = run2(str(test_csv), output_dir=str(outdir))
            artifacts = _extract_artifacts(result)
            dd = artifacts.get("dim_dataset")
            if isinstance(dd, str):
                return Path(dd).parent
            return outdir / "star"

    # Fallback: synthesize a minimal star
    return _write_minimal_star(tmp_path / "star")


@pytest.mark.integration
def test_build_pbi_fails_on_relationship_header_mismatch(tmp_path: Path):
    # 1) Build a valid star first
    star_dir = _make_star(tmp_path)

    # 2) Deliberately break relationship: remove `column_id` from dim_column.csv
    dim_column = star_dir / "dim_column.csv"
    assert dim_column.exists(), "dim_column.csv must exist in the star"
    dim_column.write_text("dataset_id,name\n1,foo\n", encoding="utf-8")  # no 'column_id'

    # 3) Build the PBI package → should fail validation and raise
    with pytest.raises(ValueError) as ei:
        export_powerbi_package(
            star_dir=star_dir,
            output_dir=tmp_path / "powerbi_package_bad",
            time_start="2024-01-01",
            time_end="2024-12-31",
            base_folder="./dist",
        )

    msg = str(ei.value)
    assert "Invalid Power BI package" in msg
    assert "dim_column.column_id not found in CSV" in msg
