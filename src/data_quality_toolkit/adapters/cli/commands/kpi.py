# src/data_quality_toolkit/adapters/cli/commands/kpi.py
"""KPI commands: kpi-emit, kpi-graph, kpi-validate."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import data_quality_toolkit.adapters.cli.main as _m
from data_quality_toolkit.adapters.cli.utils.parser import (
    KPI_CONFIG_HELP,
    KPI_DAX_OUT_HELP,
    KPI_DEFAULT_CONFIG,
    KPI_DEFAULT_DAX_OUT,
    KPI_DEFAULT_GRAPH_OUT,
    KPI_DEFAULT_TMSL_OUT,
    KPI_GRAPH_FORMAT_CHOICES,
    KPI_GRAPH_FORMAT_DEFAULT,
    KPI_GRAPH_FORMAT_HELP,
    KPI_GRAPH_OUT_HELP,
    KPI_TMSL_OUT_HELP,
)

LOGGER = logging.getLogger("dqt.cli")


def cmd_kpi_emit(args: argparse.Namespace) -> int:
    """Generate DAX measures and TMSL from KPI catalog."""
    tick = _m._safe_text("✓", "[OK]")
    try:
        print(f"Loading KPI catalog from {args.config}...", file=sys.stderr)
        result = _m.kpi_emit_artifacts(args.config, args.dax_out, args.tmsl_out)

        print(f"{tick} Loaded {result.get('kpis', 0)} KPIs", file=sys.stderr)
        print(f"{tick} Generated DAX: {result.get('dax')}", file=sys.stderr)
        print(f"{tick} Generated TMSL: {result.get('tmsl')}", file=sys.stderr)

        print(_m._json_dump(result))
        return 0

    except Exception as e:
        LOGGER.exception("KPI emission failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_kpi_graph(args: argparse.Namespace) -> int:
    """Export KPI dependency graph (Mermaid or Graphviz)."""
    tick = _m._safe_text("✓", "[OK]")
    try:
        print(f"Loading KPI catalog from {args.config}...", file=sys.stderr)
        fmt = (args.format or KPI_GRAPH_FORMAT_DEFAULT).lower()
        result = _m.kpi_export_graph(args.config, args.out, fmt)

        graph_path = result.get("graph", "")
        nodes = result.get("nodes", 0)
        print(f"{tick} Generated {fmt} graph: {graph_path}", file=sys.stderr)

        # Preview for small catalogs (first 20 lines)
        if nodes <= 10 and graph_path:
            print("\nGraph preview:", file=sys.stderr)
            text = Path(graph_path).read_text(encoding="utf-8")
            lines = text.splitlines()
            preview = lines[:20]
            for line in preview:
                print(line, file=sys.stderr)
            if len(lines) > 20:
                print("...", file=sys.stderr)

        print(_m._json_dump(result))
        return 0

    except Exception as e:
        LOGGER.exception("Graph generation failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_kpi_validate(args: argparse.Namespace) -> int:
    """Validate KPI catalog (schema, semantics, cycles)."""
    try:
        print(f"Validating KPI catalog: {args.config}", file=sys.stderr)
        result = _m.kpi_validate_catalog(args.config)
        kpi_count = result.get("kpis", 0)
        print(f"✓ Loaded {kpi_count} KPIs", file=sys.stderr)

        if result.get("status") == "invalid":
            print("✗ Dependency cycles detected:", file=sys.stderr)
            for cycle_path in result.get("cycles", []):
                print(f"  - {' -> '.join(str(c) for c in cycle_path)}", file=sys.stderr)
            output = {k: v for k, v in result.items() if k != "by_grain"}
            print(_m._json_dump(output))
            return 1

        print("✓ Semantic validation passed", file=sys.stderr)
        print("\nCatalog Summary:", file=sys.stderr)
        for grain, count in (result.get("by_grain") or {}).items():
            print(f"  {grain}: {count} KPIs", file=sys.stderr)
        print(f"  Total dependencies: {result.get('dependencies', 0)}", file=sys.stderr)

        output = {k: v for k, v in result.items() if k != "by_grain"}
        print(_m._json_dump(output))
        return 0

    except Exception as e:
        LOGGER.exception("Validation failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


def register_kpi_emit(sub: argparse._SubParsersAction) -> None:
    sp_kpi_emit = sub.add_parser("kpi-emit", help="Generate DAX and TMSL from KPI catalog")
    sp_kpi_emit.add_argument("--config", default=KPI_DEFAULT_CONFIG, help=KPI_CONFIG_HELP)
    sp_kpi_emit.add_argument(
        "--dax-out", dest="dax_out", default=KPI_DEFAULT_DAX_OUT, help=KPI_DAX_OUT_HELP
    )
    sp_kpi_emit.add_argument(
        "--tmsl-out", dest="tmsl_out", default=KPI_DEFAULT_TMSL_OUT, help=KPI_TMSL_OUT_HELP
    )
    sp_kpi_emit.set_defaults(func=cmd_kpi_emit)


def register_kpi_graph(sub: argparse._SubParsersAction) -> None:
    sp_kpi_graph = sub.add_parser("kpi-graph", help="Export KPI dependency graph")
    sp_kpi_graph.add_argument("--config", default=KPI_DEFAULT_CONFIG, help=KPI_CONFIG_HELP)
    sp_kpi_graph.add_argument("--out", default=KPI_DEFAULT_GRAPH_OUT, help=KPI_GRAPH_OUT_HELP)
    sp_kpi_graph.add_argument(
        "--format",
        default=KPI_GRAPH_FORMAT_DEFAULT,
        choices=KPI_GRAPH_FORMAT_CHOICES,
        help=KPI_GRAPH_FORMAT_HELP,
    )
    sp_kpi_graph.set_defaults(func=cmd_kpi_graph)


def register_kpi_validate(sub: argparse._SubParsersAction) -> None:
    sp_kpi_val = sub.add_parser("kpi-validate", help="Validate KPI catalog for errors")
    sp_kpi_val.add_argument("--config", default=KPI_DEFAULT_CONFIG, help=KPI_CONFIG_HELP)
    sp_kpi_val.set_defaults(func=cmd_kpi_validate)
