"""Tests for application/workflow/kpi.py orchestration functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from data_quality_toolkit.application.workflow.kpi import (
    emit_kpi_artifacts,
    export_kpi_graph,
    generate_dim_time_workflow,
    validate_kpi_catalog,
)

REAL_CATALOG = "config/kpi_catalog.yaml"


def _make_catalog_yaml(tmp_path: Path, kpis: list[dict]) -> str:
    """Write a minimal KPI catalog YAML and return its path."""
    import yaml  # noqa: PLC0415

    data = {"version": "1.0.0", "description": "test", "kpis": kpis}
    p = tmp_path / "catalog.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# validate_kpi_catalog
# ---------------------------------------------------------------------------


def test_validate_kpi_catalog_valid_real_catalog():
    result = validate_kpi_catalog(REAL_CATALOG)
    assert result["status"] == "valid"
    assert result["kpis"] > 0
    assert result["cycles"] == 0
    assert isinstance(result["grains"], list)
    assert isinstance(result["by_grain"], dict)
    assert "dependencies" in result


def test_validate_kpi_catalog_invalid_cycles(tmp_path: Path):
    kpis = [
        {
            "id": "a",
            "title": "A",
            "expression": "SUM([x])",
            "grain": "global",
            "unit": "count",
            "scale": 1,
            "depends_on": ["b"],
        },
        {
            "id": "b",
            "title": "B",
            "expression": "SUM([y])",
            "grain": "global",
            "unit": "count",
            "scale": 1,
            "depends_on": ["a"],
        },
    ]
    path = _make_catalog_yaml(tmp_path, kpis)
    result = validate_kpi_catalog(path)
    assert result["status"] == "invalid"
    assert result["reason"] == "cycles"
    assert isinstance(result["cycles"], list)
    assert len(result["cycles"]) > 0
    # Each cycle should have first node repeated at end
    for cycle in result["cycles"]:
        assert cycle[0] == cycle[-1]


def test_validate_kpi_catalog_missing_file():
    with pytest.raises(FileNotFoundError):
        validate_kpi_catalog("nonexistent/catalog.yaml")


# ---------------------------------------------------------------------------
# emit_kpi_artifacts
# ---------------------------------------------------------------------------


def test_emit_kpi_artifacts_creates_dax_and_tmsl(tmp_path: Path):
    dax_out = tmp_path / "out" / "measures.dax"
    tmsl_out = tmp_path / "out" / "model.tmsl.json"
    result = emit_kpi_artifacts(REAL_CATALOG, dax_out, tmsl_out)
    assert result["status"] == "success"
    assert result["kpis"] > 0
    assert Path(result["dax"]).exists()
    assert Path(result["tmsl"]).exists()


# ---------------------------------------------------------------------------
# export_kpi_graph
# ---------------------------------------------------------------------------


def test_export_kpi_graph_mermaid(tmp_path: Path):
    out = tmp_path / "graph.mmd"
    result = export_kpi_graph(REAL_CATALOG, out, graph_format="mermaid")
    assert result["status"] == "success"
    assert result["format"] == "mermaid"
    assert Path(result["graph"]).exists()
    assert result["graph"].endswith(".mmd")
    assert result["nodes"] > 0


def test_export_kpi_graph_graphviz(tmp_path: Path):
    out = tmp_path / "graph.dot"
    result = export_kpi_graph(REAL_CATALOG, out, graph_format="graphviz")
    assert result["status"] == "success"
    assert result["format"] == "graphviz"
    assert Path(result["graph"]).exists()
    assert result["graph"].endswith(".dot")


def test_export_kpi_graph_mermaid_adds_extension(tmp_path: Path):
    # no .mmd extension on out path — should be added
    out = tmp_path / "graph"
    result = export_kpi_graph(REAL_CATALOG, out, graph_format="mermaid")
    assert result["graph"].endswith(".mmd")


def test_export_kpi_graph_graphviz_replaces_mmd_extension(tmp_path: Path):
    out = tmp_path / "graph.mmd"
    result = export_kpi_graph(REAL_CATALOG, out, graph_format="graphviz")
    assert result["graph"].endswith(".dot")
    assert not result["graph"].endswith(".mmd")


# ---------------------------------------------------------------------------
# generate_dim_time_workflow
# ---------------------------------------------------------------------------


def test_generate_dim_time_workflow_no_output_dir():
    result = generate_dim_time_workflow(start_date="2024-01-01", end_date="2024-01-07")
    assert result["rows"] == 7
    assert result["start_date"] == "2024-01-01"
    assert result["end_date"] == "2024-01-07"
    assert "path" not in result


def test_generate_dim_time_workflow_with_output_dir(tmp_path: Path):
    result = generate_dim_time_workflow(
        start_date="2024-01-01", end_date="2024-01-07", output_dir=tmp_path
    )
    assert result["rows"] == 7
    assert "path" in result
    csv_path = Path(result["path"])
    assert csv_path.exists()
    assert csv_path.name == "dim_time.csv"


def test_generate_dim_time_workflow_fiscal_year_in_result():
    result = generate_dim_time_workflow(
        start_date="2024-01-01",
        end_date="2024-01-03",
        fiscal_year_start=7,
    )
    assert result.get("fiscal_year_start") == 7


def test_generate_dim_time_workflow_no_fiscal_year_key_when_none():
    result = generate_dim_time_workflow(start_date="2024-01-01", end_date="2024-01-03")
    assert "fiscal_year_start" not in result
