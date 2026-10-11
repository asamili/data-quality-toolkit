from __future__ import annotations

import json
import zipfile
from pathlib import Path

from data_quality_toolkit.adapters.exporters.bi.powerbi_zero_config import generator as gen
from data_quality_toolkit.adapters.exporters.bi.powerbi_zero_config.packager import (
    validate_package,
    validate_relationships,
)

# ---------- helpers ----------


def _setup_package(tmp: Path, with_model: bool = True) -> Path:
    pkg = tmp / "pkg"
    (pkg / "star").mkdir(parents=True)
    (pkg / "time").mkdir(parents=True)

    # Required CSVs with minimal headers
    (pkg / "star" / "dim_dataset.csv").write_text("dataset_id,name\n1,foo\n", encoding="utf-8")
    (pkg / "star" / "dim_column.csv").write_text(
        "column_id,dataset_id,name\n1,1,col\n", encoding="utf-8"
    )
    (pkg / "star" / "fact_profile_runs.csv").write_text(
        "id,dataset_id,ts\n1,1,2024-01-01\n", encoding="utf-8"
    )
    (pkg / "star" / "fact_quality_metrics.csv").write_text(
        "id,column_id,metric,value\n1,1,acc,1.0\n", encoding="utf-8"
    )
    (pkg / "star" / "fact_issues.csv").write_text(
        "run_id,dataset_id,column_id,issue_type,severity,category,message\n"
        "run-1,1,1,nulls,warning,completeness,too many nulls\n",
        encoding="utf-8",
    )

    # Time CSV
    (pkg / "time" / "dim_time.csv").write_text(
        "time_id,date\n20240101,2024-01-01\n", encoding="utf-8"
    )

    # parameters.json with BaseFolder
    (pkg / "parameters.json").write_text(
        json.dumps(
            {"parameters": [{"name": "BaseFolder", "type": "Text", "currentValue": "./dist"}]}
        ),
        encoding="utf-8",
    )

    # relationships.json: dim_column and fact_issues package relationships
    (pkg / "relationships.json").write_text(
        json.dumps(
            {
                "relationships": [
                    {
                        "from": ["dim_column", "dataset_id"],
                        "to": ["dim_dataset", "dataset_id"],
                        "type": "many-to-one",
                    },
                    {
                        "from": ["fact_issues", "dataset_id"],
                        "to": ["dim_dataset", "dataset_id"],
                        "type": "many-to-one",
                    },
                    {
                        "from": ["fact_issues", "column_id"],
                        "to": ["dim_column", "column_id"],
                        "type": "many-to-one",
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # model.pbit (warning-only if missing)
    if with_model:
        # Write a minimal, valid OPC-style zip so validator passes the "is zip" check.
        pbit = pkg / "model.pbit"
        with zipfile.ZipFile(pbit, "w") as zf:
            # Either of these is fine for the current validator:
            # 1) Just a dummy entry (ensures a valid zip archive)
            zf.writestr("dummy", "x")
            # 2) (Optional, more future-proof) add the typical OPC root part:
            # zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?>')

    return pkg


# ---------- tests ----------


def test_validate_relationships_success(tmp_path: Path):
    pkg = _setup_package(tmp_path)
    rel = validate_relationships(pkg)
    assert rel.get("valid", False) is True
    assert rel.get("relationships_count", 0) == 3
    assert rel.get("errors", []) == []


def test_validate_package_success(tmp_path: Path):
    pkg = _setup_package(tmp_path, with_model=True)
    out = validate_package(pkg)
    assert out.get("valid", False) is True
    assert out.get("csv_count", 0) >= 6  # 5 star + 1 time
    assert out.get("relationships_count", 0) == 3
    assert out.get("warnings", []) == []  # model exists


def test_validate_package_warns_without_model(tmp_path: Path):
    pkg = _setup_package(tmp_path, with_model=False)
    out = validate_package(pkg)
    assert out.get("valid", False) is True  # only a warning, not an error
    assert any("model.pbit not found" in w for w in out.get("warnings", []))


def test_validate_package_missing_file(tmp_path: Path):
    pkg = _setup_package(tmp_path)
    (pkg / "star" / "fact_quality_metrics.csv").unlink()
    out = validate_package(pkg)
    assert out.get("valid", True) is False
    assert any(
        "Missing required file: star/fact_quality_metrics.csv" in e for e in out.get("errors", [])
    )


def test_validate_package_requires_fact_issues_csv(tmp_path: Path):
    pkg = _setup_package(tmp_path)
    (pkg / "star" / "fact_issues.csv").unlink()

    out = validate_package(pkg)

    assert out.get("valid", True) is False
    assert any("Missing required file: star/fact_issues.csv" in e for e in out.get("errors", []))


def test_validate_package_validates_fact_issues_required_columns(tmp_path: Path):
    pkg = _setup_package(tmp_path)
    (pkg / "star" / "fact_issues.csv").write_text(
        "run_id,dataset_id,column_id,issue_type,category,message\n"
        "run-1,1,1,nulls,completeness,too many nulls\n",
        encoding="utf-8",
    )

    out = validate_package(pkg)

    assert out.get("valid", True) is False
    assert any(
        "star/fact_issues.csv missing required columns" in e and "severity" in e
        for e in out.get("errors", [])
    )


def test_validate_package_params_missing_basefolder(tmp_path: Path):
    pkg = _setup_package(tmp_path)
    (pkg / "parameters.json").write_text(
        json.dumps({"parameters": [{"name": "OtherParam", "type": "Text", "currentValue": "/x"}]}),
        encoding="utf-8",
    )
    out = validate_package(pkg)
    assert out.get("valid", True) is False
    assert any("BaseFolder parameter not found" in e for e in out.get("errors", []))


def test_validate_package_unreadable_csv(tmp_path: Path):
    pkg = _setup_package(tmp_path)
    (pkg / "star" / "bad.csv").write_text("", encoding="utf-8")
    out = validate_package(pkg)
    assert out.get("valid", True) is False
    assert any(e.startswith("Cannot read bad.csv:") for e in out.get("errors", []))


def test_generator_includes_fact_issues_relationships(monkeypatch, tmp_path: Path):
    star = tmp_path / "star_src"
    star.mkdir()
    (star / "dim_dataset.csv").write_text("dataset_id,name\n1,foo\n", encoding="utf-8")
    (star / "dim_column.csv").write_text("column_id,dataset_id,name\n1,1,col\n", encoding="utf-8")
    (star / "fact_profile_runs.csv").write_text(
        "run_id,dataset_id,ts\nrun-1,1,2024-01-01\n", encoding="utf-8"
    )
    (star / "fact_quality_metrics.csv").write_text(
        "run_id,column_id,null_pct,distinct_count,completeness\nrun-1,1,0,1,1\n",
        encoding="utf-8",
    )
    (star / "fact_issues.csv").write_text(
        "run_id,dataset_id,column_id,issue_type,severity,category,message\n"
        "run-1,1,1,nulls,warning,completeness,too many nulls\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gen, "_get_template_dir", lambda: tmp_path / "no_templates")

    out_dir = tmp_path / "pkg"
    gen.generate_powerbi_package(star, out_dir)

    rel = json.loads((out_dir / "relationships.json").read_text(encoding="utf-8"))
    relationships = rel["relationships"]
    assert any(
        r.get("from") == ["fact_issues", "dataset_id"]
        and r.get("to") == ["dim_dataset", "dataset_id"]
        for r in relationships
    )
    assert any(
        r.get("from") == ["fact_issues", "column_id"] and r.get("to") == ["dim_column", "column_id"]
        for r in relationships
    )
