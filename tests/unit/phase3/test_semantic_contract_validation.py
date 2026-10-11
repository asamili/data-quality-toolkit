from __future__ import annotations

import json
import zipfile
from pathlib import Path

from data_quality_toolkit.adapters.exporters.bi.powerbi_zero_config import packager
from data_quality_toolkit.domain.semantics import build_builtin_quality_catalog


def _write_valid_package(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    (pkg / "star").mkdir(parents=True)
    (pkg / "time").mkdir()

    (pkg / "star" / "dim_dataset.csv").write_text(
        "dataset_id,source_path\nds-1,input.csv\n", encoding="utf-8"
    )
    (pkg / "star" / "dim_column.csv").write_text(
        "column_id,dataset_id,column_name,dtype\ncol-1,ds-1,name,string\n", encoding="utf-8"
    )
    (pkg / "star" / "fact_profile_runs.csv").write_text(
        "run_id,dataset_id,ts,time_id,rows,cols,memory_mb\n"
        "run-1,ds-1,2024-01-01,20240101,10,1,0.1\n",
        encoding="utf-8",
    )
    (pkg / "star" / "fact_quality_metrics.csv").write_text(
        "run_id,column_id,null_pct,distinct_count,completeness\n" "run-1,col-1,0.0,10,1.0\n",
        encoding="utf-8",
    )
    (pkg / "star" / "fact_issues.csv").write_text(
        "run_id,dataset_id,column_id,issue_type,severity,category,message\n"
        "run-1,ds-1,col-1,nulls,warning,completeness,too many nulls\n",
        encoding="utf-8",
    )
    (pkg / "time" / "dim_time.csv").write_text(
        "time_id,date\n20240101,2024-01-01\n", encoding="utf-8"
    )
    (pkg / "parameters.json").write_text(
        json.dumps(
            {"parameters": [{"name": "BaseFolder", "type": "Text", "currentValue": "./dist"}]}
        ),
        encoding="utf-8",
    )
    (pkg / "relationships.json").write_text(
        json.dumps(
            {
                "relationships": [
                    {
                        "from": ["fact_issues", "dataset_id"],
                        "to": ["dim_dataset", "dataset_id"],
                    },
                    {
                        "from": ["fact_issues", "column_id"],
                        "to": ["dim_column", "column_id"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    with zipfile.ZipFile(pkg / "model.pbit", "w") as zf:
        zf.writestr("dummy", "x")

    return pkg


def test_builtin_quality_catalog_semantic_contract_passes_valid_package(tmp_path: Path) -> None:
    pkg = _write_valid_package(tmp_path)
    catalog = build_builtin_quality_catalog()

    summary = packager._validate_semantic_contract(catalog, pkg)

    assert summary["valid"] is True
    assert summary["errors"] == []
    assert summary["checked_kpis"] == len(catalog.kpis)
    assert "fact_issues" in summary["checked_tables"]


def test_builtin_quality_catalog_semantic_contract_fails_when_fact_issues_missing(
    tmp_path: Path,
) -> None:
    pkg = _write_valid_package(tmp_path)
    (pkg / "star" / "fact_issues.csv").unlink()

    summary = packager._validate_semantic_contract(build_builtin_quality_catalog(), pkg)

    assert summary["valid"] is False
    assert any("Missing required file: star/fact_issues.csv" in e for e in summary["errors"])
    assert any("star/fact_issues.csv" in e for e in summary["errors"])


def test_builtin_quality_catalog_semantic_contract_fails_when_source_column_missing(
    tmp_path: Path,
) -> None:
    pkg = _write_valid_package(tmp_path)
    (pkg / "star" / "fact_quality_metrics.csv").write_text(
        "run_id,column_id,distinct_count,completeness\nrun-1,col-1,10,1.0\n",
        encoding="utf-8",
    )

    summary = packager._validate_semantic_contract(build_builtin_quality_catalog(), pkg)

    assert summary["valid"] is False
    assert any("fact_quality_metrics.null_pct" in e for e in summary["errors"])


def test_semantic_contract_validation_checks_package_basefolder_shape(tmp_path: Path) -> None:
    pkg = _write_valid_package(tmp_path)
    (pkg / "parameters.json").write_text(
        json.dumps({"parameters": [{"name": "OtherParam", "currentValue": "./dist"}]}),
        encoding="utf-8",
    )

    summary = packager._validate_semantic_contract(build_builtin_quality_catalog(), pkg)

    assert summary["valid"] is False
    assert any("BaseFolder parameter not found" in e for e in summary["errors"])
