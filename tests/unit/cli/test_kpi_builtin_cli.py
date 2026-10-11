"""CLI tests for the additive ``dqt kpi-builtin`` command family.

Covers parser/help registration, the three sub-commands (catalog, emit-dax,
validate-contract), exit-code behavior (0 / 2 / argparse-2), proxy labeling, and
that held/unsupported measures are not exposed. Existing kpi-* commands are
asserted to still register (no regression).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from data_quality_toolkit.adapters.cli import main as cli

# Measures intentionally NOT exposed by the built-in quality catalog (mirrors
# tests/unit/phase3/test_builtin_quality_api.py).
HELD_MEASURE_IDS = {
    "quality_score",
    "average_quality_score",
    "latest_quality_score",
    "quality_score_trend",
    "failed_quality_gate_count",
    "duplicate_rate",
    "drift_rate",
    "drifted_column_count",
    "max_psi",
    "average_psi",
    "last_run_date",
}


def _write_valid_package(tmp_path: Path) -> Path:
    """Build a minimal valid Power BI package directory (star/ + time/ + manifests)."""
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
        "run_id,column_id,null_pct,distinct_count,completeness\nrun-1,col-1,0.0,10,1.0\n",
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
                    {"from": ["fact_issues", "dataset_id"], "to": ["dim_dataset", "dataset_id"]},
                    {"from": ["fact_issues", "column_id"], "to": ["dim_column", "column_id"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    with zipfile.ZipFile(pkg / "model.pbit", "w") as zf:
        zf.writestr("dummy", "x")

    return pkg


# --------------------------------------------------------------------------- #
# Parser / help registration
# --------------------------------------------------------------------------- #
def test_parser_registers_kpi_builtin_family(capsys: pytest.CaptureFixture) -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["kpi-builtin", "--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "catalog" in out
    assert "emit-dax" in out
    assert "validate-contract" in out


def test_existing_kpi_commands_still_register() -> None:
    """Existing kpi-emit/kpi-graph/kpi-validate must remain unchanged siblings."""
    parser = cli.build_parser()
    assert parser.parse_args(["kpi-emit"]).func is cli.cmd_kpi_emit
    assert parser.parse_args(["kpi-graph"]).func is cli.cmd_kpi_graph
    assert parser.parse_args(["kpi-validate"]).func is cli.cmd_kpi_validate


# --------------------------------------------------------------------------- #
# catalog
# --------------------------------------------------------------------------- #
def test_catalog_returns_zero_and_json_with_measure_count(capsys: pytest.CaptureFixture) -> None:
    rc = cli.main(["kpi-builtin", "catalog"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["measure_count"] == 11
    assert len(payload["measures"]) == payload["measure_count"]
    assert payload["measures"][0]["source_columns"] == ["completeness"]


def test_catalog_holds_unsupported_measures_and_labels_proxy(
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["kpi-builtin", "catalog"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    by_id = {m["id"]: m for m in payload["measures"]}

    # Held/unsupported measures (true Quality Score, Drift Rate, PSI, Duplicate
    # Rate, Failed Gate Count, Last Run Date) must not appear.
    assert set(by_id).isdisjoint(HELD_MEASURE_IDS)
    assert "quality_score" not in by_id

    # Quality Score must remain clearly labeled as a proxy.
    proxy = by_id["quality_score_proxy"]
    assert proxy["title"] == "Quality Score (proxy)"
    assert proxy["support_status"] == "proxy-current-star"


# --------------------------------------------------------------------------- #
# emit-dax
# --------------------------------------------------------------------------- #
def test_emit_dax_without_out_returns_dax_in_json(capsys: pytest.CaptureFixture) -> None:
    rc = cli.main(["kpi-builtin", "emit-dax"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["output_path"] is None
    assert payload["measure_count"] == 11
    assert "MEASURE 'Quality'[Quality Score (proxy)]" in payload["dax"]


def test_emit_dax_with_out_writes_file(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    out_path = tmp_path / "builtin_quality.dax"
    rc = cli.main(["kpi-builtin", "emit-dax", "--out", str(out_path)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["output_path"] == str(out_path)
    assert out_path.exists()
    assert out_path.read_text(encoding="utf-8") == payload["dax"]


# --------------------------------------------------------------------------- #
# validate-contract
# --------------------------------------------------------------------------- #
def test_validate_contract_package_valid_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    pkg = _write_valid_package(tmp_path)
    rc = cli.main(["kpi-builtin", "validate-contract", "--package", str(pkg)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["input_mode"] == "package"
    assert "star/fact_issues.csv" in payload["checked_files"]


def test_validate_contract_star_valid_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    pkg = _write_valid_package(tmp_path)
    rc = cli.main(["kpi-builtin", "validate-contract", "--star", str(pkg / "star")])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["input_mode"] == "star"


def test_validate_contract_missing_fact_issues_returns_two(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    pkg = _write_valid_package(tmp_path)
    (pkg / "star" / "fact_issues.csv").unlink()
    rc = cli.main(["kpi-builtin", "validate-contract", "--package", str(pkg)])
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    assert any("Missing required file: star/fact_issues.csv" in e for e in payload["errors"])


def test_validate_contract_path_auto_valid_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    pkg = _write_valid_package(tmp_path)
    rc = cli.main(["kpi-builtin", "validate-contract", "--path", str(pkg)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["input_mode"] == "package"


def test_validate_contract_rejects_multiple_path_flags() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["kpi-builtin", "validate-contract", "--package", "a", "--star", "b"])
    assert exc_info.value.code == 2
