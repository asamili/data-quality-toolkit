"""Tests: KPI and dim_time functions exposed through the public API."""

from __future__ import annotations

from pathlib import Path

import pytest

REAL_CATALOG = "config/kpi_catalog.yaml"


def test_api_imports_available():
    from data_quality_toolkit import (  # noqa: F401
        generate_dim_time,
        kpi_emit,
        kpi_graph,
        kpi_validate,
    )


def test_kpi_validate_valid():
    from data_quality_toolkit import kpi_validate

    result = kpi_validate(REAL_CATALOG)
    assert result["status"] == "valid"
    assert result["kpis"] > 0


def test_kpi_validate_missing_file():
    from data_quality_toolkit import kpi_validate

    with pytest.raises(FileNotFoundError):
        kpi_validate("nonexistent/catalog.yaml")


def test_kpi_emit_writes_files(tmp_path: Path):
    from data_quality_toolkit import kpi_emit

    dax_out = tmp_path / "measures.dax"
    tmsl_out = tmp_path / "model.tmsl.json"
    result = kpi_emit(REAL_CATALOG, dax_out, tmsl_out)
    assert result["status"] == "success"
    assert Path(result["dax"]).exists()
    assert Path(result["tmsl"]).exists()


def test_kpi_graph_mermaid(tmp_path: Path):
    from data_quality_toolkit import kpi_graph

    out = tmp_path / "graph.mmd"
    result = kpi_graph(REAL_CATALOG, out)
    assert result["status"] == "success"
    assert result["format"] == "mermaid"
    assert Path(result["graph"]).exists()


def test_kpi_graph_graphviz(tmp_path: Path):
    from data_quality_toolkit import kpi_graph

    out = tmp_path / "graph.dot"
    result = kpi_graph(REAL_CATALOG, out, graph_format="graphviz")
    assert result["status"] == "success"
    assert result["format"] == "graphviz"
    assert Path(result["graph"]).exists()


def test_generate_dim_time_no_output():
    from data_quality_toolkit import generate_dim_time

    result = generate_dim_time(start_date="2024-01-01", end_date="2024-01-05")
    assert result["rows"] == 5
    assert "path" not in result


def test_generate_dim_time_with_output(tmp_path: Path):
    from data_quality_toolkit import generate_dim_time

    result = generate_dim_time(start_date="2024-01-01", end_date="2024-01-05", output_dir=tmp_path)
    assert result["rows"] == 5
    assert Path(result["path"]).exists()
    assert Path(result["path"]).name == "dim_time.csv"
