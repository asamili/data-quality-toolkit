"""Coupling test: CLI must not import domain.semantics directly."""

from __future__ import annotations

import ast
from pathlib import Path


def _all_imports(source: str) -> list[str]:
    """Return module strings for all import/from-import nodes in source (including function-local)."""
    tree = ast.parse(source)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    return modules


def test_cli_main_has_no_direct_domain_semantics_imports():
    """adapters/cli/main.py must route KPI through application.workflow.kpi, not domain.semantics."""
    cli_path = Path("src/data_quality_toolkit/adapters/cli/main.py")
    source = cli_path.read_text(encoding="utf-8")
    modules = _all_imports(source)
    domain_semantics = [m for m in modules if "domain.semantics" in m]
    assert domain_semantics == [], (
        f"Direct domain.semantics imports found in cli/main.py: {domain_semantics}. "
        "Route through application.workflow.kpi instead."
    )


def test_cli_kpi_proxy_functions_route_through_application():
    """kpi_validate_catalog, kpi_emit_artifacts, kpi_export_graph must import from application layer."""
    cli_path = Path("src/data_quality_toolkit/adapters/cli/main.py")
    source = cli_path.read_text(encoding="utf-8")
    assert (
        "application.workflow.kpi" in source
    ), "CLI kpi proxy functions should import from application.workflow.kpi"
