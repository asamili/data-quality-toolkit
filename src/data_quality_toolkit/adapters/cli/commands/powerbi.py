# src/data_quality_toolkit/adapters/cli/commands/powerbi.py
"""Power BI / time-dimension commands: build-pbi, gen-dim-time."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from typing import Any, cast

import data_quality_toolkit.adapters.cli.main as _m
from data_quality_toolkit.adapters.cli.utils.parser import DEFAULT_DIST


def cmd_gen_dim_time(args: argparse.Namespace) -> int:
    """Generate dim_time.csv."""
    from data_quality_toolkit.api import generate_dim_time

    try:
        result = generate_dim_time(
            args.start,
            args.end,
            week_start=args.week_start,
            fiscal_year_start=args.fiscal,
            output_dir=args.out,
        )
        path = result["path"]
        if args.json:
            payload = {
                "status": "success",
                "dim_time_path": str(path),
                "start": args.start,
                "end": args.end,
                "week_start": args.week_start,
                "fiscal": args.fiscal,
            }
            print(_m._json_dump(payload))
        else:
            print(f"Generated: {path}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_build_pbi(args: argparse.Namespace) -> int:
    """Build Phase 2 Power BI package (zero-config orchestrator)."""
    from data_quality_toolkit.adapters.exporters.bi.powerbi_exporter import export_powerbi_package

    tick = _m._safe_text("✓", "[OK]")
    try:
        print("Building Power BI package...", file=sys.stderr)
        result = export_powerbi_package(
            star_dir=args.star,
            output_dir=args.out,
            time_start=args.time_start,
            time_end=args.time_end,
            base_folder=args.base_folder,
            fiscal_year_start=args.fiscal,
        )

        # Human-friendly summary → STDERR
        print(f"{tick} Package: {result['package_dir']}", file=sys.stderr)
        print(f"  - Files: {len(result.get('files', {}))}", file=sys.stderr)
        print(f"  - Time range: {result.get('time_range')}", file=sys.stderr)
        print(f"  - Base folder: {result.get('base_folder')}", file=sys.stderr)

        # Treat validation as generic mapping to avoid TypedDict optional-key warnings
        val: Mapping[str, Any] = cast(Mapping[str, Any], result["validation"])
        warnings: list[str] = cast(list[str], val.get("warnings", []))
        for w in warnings:
            print(f"  ⚠ {w}", file=sys.stderr)

        # Machine-friendly JSON → STDOUT
        print(_m._json_dump(result))
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def register_build_pbi(sub: argparse._SubParsersAction) -> None:
    sp_pbi = sub.add_parser("build-pbi", help="Build Power BI package (Phase 2)")
    sp_pbi.add_argument("--star", default=f"{DEFAULT_DIST}/star", help="Star schema directory")
    sp_pbi.add_argument("--out", default=f"{DEFAULT_DIST}/powerbi_package", help="Output directory")
    sp_pbi.add_argument(
        "--time-start", default="2018-01-01", help="Time dimension start (YYYY-MM-DD)"
    )
    sp_pbi.add_argument("--time-end", default="2030-12-31", help="Time dimension end (YYYY-MM-DD)")
    sp_pbi.add_argument(
        "--base-folder", default=DEFAULT_DIST, help="Base folder parameter for Power BI"
    )
    sp_pbi.add_argument("--fiscal", type=int, default=None, help="Fiscal year start month (1-12)")
    sp_pbi.set_defaults(func=cmd_build_pbi)


def register_gen_dim_time(sub: argparse._SubParsersAction) -> None:
    sp_time = sub.add_parser("gen-dim-time", help="Generate dim_time.csv")
    sp_time.add_argument("--start", default="2018-01-01", help="Start date (YYYY-MM-DD)")
    sp_time.add_argument("--end", default="2030-12-31", help="End date (YYYY-MM-DD)")
    sp_time.add_argument(
        "--week-start",
        type=int,
        default=1,
        choices=[1, 2, 3, 4, 5, 6, 7],
        help="Custom week start (1=Mon .. 7=Sun)",
    )
    sp_time.add_argument("--fiscal", type=int, default=None, help="Fiscal year start month (1-12)")
    sp_time.add_argument("--out", default=f"{DEFAULT_DIST}/time", help="Output directory")
    sp_time.add_argument("--json", action="store_true", help="Emit JSON on stdout (path & args)")
    sp_time.set_defaults(func=cmd_gen_dim_time)
