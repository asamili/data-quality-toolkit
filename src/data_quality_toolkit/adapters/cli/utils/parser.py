# src/data_quality_toolkit/adapters/cli/utils/parser.py
"""Shared argparse building blocks and CLI text constants.

This module is import-time safe: it pulls in only argparse/sys and defines no
heavy dependencies, so importing the CLI never drags in pandas/streamlit.
"""

from __future__ import annotations

import argparse
import sys
from typing import NoReturn

# ----- Constants to de-duplicate literals (Sonar S1192) -----
CSV_PATH_HELP = "Path to CSV file"
DEFAULT_DIST = "./dist"
CROSS_FALLBACK = "[FAIL]"
FAIL_UNDER_HELP = "Exit 2 if quality score is below this threshold (0.0 to 1.0)"
SCORE_FIELD_CHOICES = ("score", "completeness_score", "quality_score")
SCORE_FIELD_DEFAULT = "score"

# ----- Phase 3 (KPI) constants -----
KPI_DEFAULT_CONFIG = "config/kpi_catalog.yaml"
KPI_CONFIG_HELP = "Path to KPI catalog YAML"

KPI_DEFAULT_DAX_OUT = "dist/powerbi_package/dax/quality_measures.dax"
KPI_DAX_OUT_HELP = "Output path for DAX measures"

KPI_DEFAULT_TMSL_OUT = "dist/powerbi_package/dax/model.tmsl.json"
KPI_TMSL_OUT_HELP = "Output path for TMSL"

KPI_DEFAULT_GRAPH_OUT = "dist/semantics/kpi_graph.mmd"
KPI_GRAPH_OUT_HELP = "Output path for graph file (.mmd or .dot)"

KPI_GRAPH_FORMAT_DEFAULT = "mermaid"
KPI_GRAPH_FORMAT_CHOICES = ["mermaid", "graphviz"]
KPI_GRAPH_FORMAT_HELP = "Graph format"


def parse_bool_flag(value: str) -> bool:
    """Parse a true|false CLI string into a bool (argparse type callback).

    argparse ``type=bool`` is unusable here because ``bool("false")`` is ``True``.
    """
    v = value.strip().lower()
    if v in {"true", "1", "yes"}:
        return True
    if v in {"false", "0", "no"}:
        return False
    raise argparse.ArgumentTypeError(f"expected true|false, got {value!r}")


def add_csv_options(parser: argparse.ArgumentParser) -> None:
    """Add CSV-related options to parser."""
    parser.add_argument("--sep", help="CSV delimiter (e.g., ',' or '\\t')")
    parser.add_argument("--encoding", help="CSV encoding (e.g., 'utf-8', 'latin-1')")
    parser.add_argument("--no-header", action="store_true", help="Treat CSV as having no header")
    parser.add_argument("--na-values", help="Comma-separated NA values (e.g., 'NA,NaN,null')")
    parser.add_argument("--sample-size", type=int, help="Override SAMPLE_SIZE for this run")


class DQTArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that adds actionable hints for common missing-input errors."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        if "required" in message and "csv" in message:
            print(
                "  Hint: provide the path to a CSV file as the first positional argument.",
                file=sys.stderr,
            )
            print("  Example: dqt profile data/my_file.csv", file=sys.stderr)
        sys.exit(2)
