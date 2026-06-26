# src/data_quality_toolkit/adapters/cli/commands/chart.py
"""``dqt chart`` — terminal-based profiling chart for a column."""

from __future__ import annotations

import argparse
import sys

import data_quality_toolkit.adapters.cli.main as _m
from data_quality_toolkit.adapters.cli.utils.parser import CSV_PATH_HELP, add_csv_options


def cmd_chart(args: argparse.Namespace) -> int:
    """Generate a terminal-based profiling chart for a column."""
    from data_quality_toolkit.adapters.cli.charts import render_univariate_chart
    from data_quality_toolkit.adapters.loaders.file.csv_loader import load_csv
    from data_quality_toolkit.domain.profiling.charts import compute_univariate_chart_data

    try:
        df, meta = load_csv(
            args.csv, sample_size=_m._get_sample_size(args), **_m._csv_kwargs_from_args(args)
        )
        chart_data = compute_univariate_chart_data(df, args.column)

        # We don't use tick/[OK] here because the chart is the main output
        render_univariate_chart(chart_data)

        if not getattr(args, "no_json", False):
            # Also emit JSON to stdout if requested
            print(_m._json_dump(chart_data))
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def register(sub: argparse._SubParsersAction) -> None:
    sp_chart = sub.add_parser(
        "chart",
        help="Generate a terminal-based profiling chart for a column",
    )
    sp_chart.add_argument("csv", help=CSV_PATH_HELP)
    sp_chart.add_argument("--column", required=True, help="Column name to chart")
    add_csv_options(sp_chart)
    sp_chart.set_defaults(func=cmd_chart)
