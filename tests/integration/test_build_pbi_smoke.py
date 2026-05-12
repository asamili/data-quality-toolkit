# tests/integration/test_build_pbi_smoke.py
# cspell:ignore pbit
"""Phase 2: Integration test for Power BI build (robust)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from data_quality_toolkit.exporters.bi.powerbi_exporter import export_powerbi_package


def _write_star(tmp: Path) -> Path:
    """Write a minimal star schema (with time_id) directly to CSVs."""
    star = tmp / "star"
    star.mkdir(parents=True, exist_ok=True)

    # dim_dataset
    pd.DataFrame([{"dataset_id": "ds1", "source_path": str(tmp / "test.csv")}]).to_csv(
        star / "dim_dataset.csv", index=False
    )

    # dim_column
    pd.DataFrame(
        [{"column_id": "ds1:id", "dataset_id": "ds1", "column_name": "id", "dtype": "int64"}]
    ).to_csv(star / "dim_column.csv", index=False)

    # fact_profile_runs (include time_id to enable time relationship)
    pd.DataFrame(
        [
            {
                "run_id": "r1",
                "dataset_id": "ds1",
                "ts": "2024-06-15T12:00:00Z",
                "time_id": 20240615,
                "rows": 3,
                "cols": 2,
                "memory_mb": 1.23,
            }
        ]
    ).to_csv(star / "fact_profile_runs.csv", index=False)

    # fact_quality_metrics
    pd.DataFrame(
        [
            {
                "run_id": "r1",
                "column_id": "ds1:id",
                "null_pct": 0.0,
                "distinct_count": 3,
                "completeness": 1.0,
            }
        ]
    ).to_csv(star / "fact_quality_metrics.csv", index=False)

    return star


@pytest.mark.integration
def test_build_pbi_end_to_end(tmp_path: Path):
    """Build a complete Power BI package and verify structure & validation."""
    # Phase 1: star schema
    star_dir = _write_star(tmp_path)

    # Phase 2: package
    pbi_result = export_powerbi_package(
        star_dir=star_dir,
        output_dir=tmp_path / "powerbi_package",
        time_start="2024-01-01",
        time_end="2024-12-31",
        base_folder=str(tmp_path / "powerbi_package"),
    )

    # Validation summary
    val = pbi_result["validation"]
    assert bool(val.get("valid", False)) is True

    package_dir = Path(pbi_result["package_dir"])

    # Must-exist files (independent of template)
    assert (package_dir / "parameters.json").exists()
    assert (package_dir / "relationships.json").exists()
    assert (package_dir / "star" / "dim_dataset.csv").exists()
    assert (package_dir / "star" / "dim_column.csv").exists()
    assert (package_dir / "star" / "fact_profile_runs.csv").exists()
    assert (package_dir / "star" / "fact_quality_metrics.csv").exists()
    assert (package_dir / "time" / "dim_time.csv").exists()
    assert (package_dir / "README.txt").exists()

    # Template handling:
    # - If a real model.pbit is present, it must be a valid zip (real PBIT)
    # - Else, we expect the guidance file to be present.
    pbit = package_dir / "model.pbit"
    pbit_readme = package_dir / "model.pbit.README"

    if pbit.exists():
        assert zipfile.is_zipfile(
            pbit
        ), "model.pbit exists but is not a valid Power BI template archive"
    else:
        assert (
            pbit_readme.exists()
        ), "Expected either model.pbit or model.pbit.README in the package"

    # Parameters sanity
    params = json.loads((package_dir / "parameters.json").read_text(encoding="utf-8"))
    assert params["parameters"][0]["name"] == "BaseFolder"

    # Optional: relationships_count is int-like if present
    rel_count = val.get("relationships_count", 0)
    assert isinstance(rel_count, int)
