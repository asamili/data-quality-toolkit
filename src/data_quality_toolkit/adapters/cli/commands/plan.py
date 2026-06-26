# src/data_quality_toolkit/adapters/cli/commands/plan.py
"""``dqt plan`` — per-column preprocessing recommendations for a CSV."""

from __future__ import annotations

import argparse
import sys

import data_quality_toolkit.adapters.cli.main as _m
from data_quality_toolkit.adapters.cli.utils.parser import CSV_PATH_HELP, add_csv_options


def cmd_plan(args: argparse.Namespace) -> int:
    """Generate per-column preprocessing recommendations for a CSV."""
    out = _m.run_plan(
        args.csv, sample_size=_m._get_sample_size(args), **_m._csv_kwargs_from_args(args)
    )

    tick = _m._safe_text("✓", "[OK]")
    columns = out.get("columns") or []
    cols_total = len(columns)
    cols_with_issues = sum(1 for c in columns if c.get("issues") != "none")
    print(f"{tick} Plan complete", file=sys.stderr)
    print(f"  - Columns: {cols_total}", file=sys.stderr)
    print(f"  - Columns with issues: {cols_with_issues}", file=sys.stderr)

    if not getattr(args, "no_json", False):
        print(_m._json_dump(out))
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    sp_plan = sub.add_parser(
        "plan",
        help="Generate per-column preprocessing recommendations for a CSV",
    )
    sp_plan.add_argument("csv", help=CSV_PATH_HELP)
    add_csv_options(sp_plan)
    sp_plan.set_defaults(func=cmd_plan)
