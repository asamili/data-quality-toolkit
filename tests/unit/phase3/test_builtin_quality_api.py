from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

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


def test_get_builtin_quality_catalog_returns_dict_summary() -> None:
    from data_quality_toolkit import get_builtin_quality_catalog
    from data_quality_toolkit.domain.semantics import build_builtin_quality_catalog

    catalog = build_builtin_quality_catalog()
    result = get_builtin_quality_catalog()

    assert type(result) is dict
    assert result["version"] == catalog.version
    assert result["measure_count"] == len(catalog.kpis)
    assert len(result["measures"]) == len(catalog.kpis)
    assert result["measures"][0]["source_columns"] == ["completeness"]


def test_builtin_quality_catalog_api_labels_proxy_and_holds_deferred_measures() -> None:
    from data_quality_toolkit import get_builtin_quality_catalog

    result = get_builtin_quality_catalog()
    by_id = {measure["id"]: measure for measure in result["measures"]}

    assert set(by_id).isdisjoint(HELD_MEASURE_IDS)
    proxy = by_id["quality_score_proxy"]
    assert proxy["title"] == "Quality Score (proxy)"
    assert proxy["support_status"] == "proxy-current-star"
    assert proxy["description"] is not None
    assert "not the true assessment quality_score" in proxy["description"]


def test_emit_builtin_quality_dax_returns_text_without_writing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import data_quality_toolkit.domain.semantics as semantics
    from data_quality_toolkit import emit_builtin_quality_dax

    def _write_must_not_run(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("write_dax should not run without output_path")

    monkeypatch.setattr(semantics, "write_dax", _write_must_not_run)

    result = emit_builtin_quality_dax()

    assert result["output_path"] is None
    assert result["measure_count"] == 11
    assert "MEASURE 'Quality'[Quality Score (proxy)]" in result["dax"]
    assert list(tmp_path.iterdir()) == []


def test_emit_builtin_quality_dax_writes_file_when_output_path_is_provided(tmp_path: Path) -> None:
    from data_quality_toolkit import emit_builtin_quality_dax

    output_path = tmp_path / "quality_measures.dax"
    result = emit_builtin_quality_dax(output_path)

    assert result["output_path"] == str(output_path)
    assert output_path.read_text(encoding="utf-8") == result["dax"]
    assert result["measure_count"] == 11


def test_validate_builtin_quality_semantic_contract_passes_valid_package(
    tmp_path: Path,
) -> None:
    from data_quality_toolkit import validate_builtin_quality_semantic_contract

    pkg = _write_valid_package(tmp_path)
    result = validate_builtin_quality_semantic_contract(pkg)

    assert result["valid"] is True
    assert result["errors"] == []
    assert result["input_mode"] == "package"
    assert "star/fact_issues.csv" in result["checked_files"]
    assert "quality_score_proxy" in result["checked_measures"]


def test_validate_builtin_quality_semantic_contract_passes_valid_star_dir(
    tmp_path: Path,
) -> None:
    from data_quality_toolkit import validate_builtin_quality_semantic_contract

    pkg = _write_valid_package(tmp_path)
    result = validate_builtin_quality_semantic_contract(pkg / "star", input_mode="star")

    assert result["valid"] is True
    assert result["errors"] == []
    assert result["input_mode"] == "star"
    assert "fact_issues.csv" in result["checked_files"]
    assert "parameters.json" not in result["checked_files"]


def test_validate_builtin_quality_semantic_contract_fails_when_fact_issues_missing(
    tmp_path: Path,
) -> None:
    from data_quality_toolkit import validate_builtin_quality_semantic_contract

    pkg = _write_valid_package(tmp_path)
    (pkg / "star" / "fact_issues.csv").unlink()
    result = validate_builtin_quality_semantic_contract(pkg)

    assert result["valid"] is False
    assert any("Missing required file: star/fact_issues.csv" in e for e in result["errors"])


def test_validate_builtin_quality_semantic_contract_fails_when_source_column_missing(
    tmp_path: Path,
) -> None:
    from data_quality_toolkit import validate_builtin_quality_semantic_contract

    pkg = _write_valid_package(tmp_path)
    (pkg / "star" / "fact_quality_metrics.csv").write_text(
        "run_id,column_id,distinct_count,completeness\nrun-1,col-1,10,1.0\n",
        encoding="utf-8",
    )
    result = validate_builtin_quality_semantic_contract(pkg)

    assert result["valid"] is False
    assert any("fact_quality_metrics.null_pct" in e for e in result["errors"])


def test_builtin_quality_api_exports_from_api_root_and_shared_result_types() -> None:
    import data_quality_toolkit as root
    import data_quality_toolkit.api as api
    import data_quality_toolkit.shared.result_types as result_types

    for name in (
        "get_builtin_quality_catalog",
        "emit_builtin_quality_dax",
        "validate_builtin_quality_semantic_contract",
    ):
        assert hasattr(api, name)
        assert name in api.__all__
        assert hasattr(root, name)
        assert name in root.__all__
        assert getattr(root, name) is getattr(api, name)

    for name in (
        "BuiltinQualityKpi",
        "BuiltinQualityCatalogResult",
        "BuiltinQualityDaxResult",
        "SemanticContractValidationResult",
    ):
        assert hasattr(result_types, name)
        assert name in result_types.__all__
        assert hasattr(api, name)
        assert name in api.__all__
        assert hasattr(root, name)
        assert name in root.__all__


def test_existing_generic_kpi_api_remains_unchanged(tmp_path: Path) -> None:
    from data_quality_toolkit import kpi_emit, kpi_graph, kpi_validate

    validation = kpi_validate("config/kpi_catalog.yaml")
    assert validation["status"] == "valid"
    assert validation["kpis"] > 0

    emitted = kpi_emit(
        "config/kpi_catalog.yaml",
        tmp_path / "generic_measures.dax",
        tmp_path / "generic_model.tmsl.json",
    )
    assert emitted["status"] == "success"
    assert Path(emitted["dax"]).exists()
    assert Path(emitted["tmsl"]).exists()

    graph = kpi_graph("config/kpi_catalog.yaml", tmp_path / "generic_graph.mmd")
    assert graph["status"] == "success"
    assert graph["format"] == "mermaid"
