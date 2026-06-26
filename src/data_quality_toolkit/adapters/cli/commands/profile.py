# src/data_quality_toolkit/adapters/cli/commands/profile.py
"""``dqt profile`` — load a CSV and emit profile JSON."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import data_quality_toolkit.adapters.cli.main as _m
from data_quality_toolkit.adapters.cli.utils.parser import CSV_PATH_HELP, add_csv_options


def cmd_profile(args: argparse.Namespace) -> int:
    """Profile a CSV file."""
    chunksize: int | None = getattr(args, "chunksize", None)
    if chunksize is not None:
        out = _m.run_profile_chunked(
            args.csv, chunksize=chunksize, **_m._csv_kwargs_from_args(args)
        )
    else:
        out = _m.run_profile(
            args.csv, sample_size=_m._get_sample_size(args), **_m._csv_kwargs_from_args(args)
        )

    # Human-friendly summary -> stderr (stdout stays pure JSON)
    tick = _m._safe_text("✓", "[OK]")
    csv_name = Path(args.csv).name
    mode = " [chunked]" if chunksize is not None else ""
    print(f"{tick} Profile complete  [{csv_name}]{mode}", file=sys.stderr)
    prof = out.get("profile") or {}
    if isinstance(prof, dict):
        if "rows" in prof:
            print(f"  - Rows: {prof['rows']}", file=sys.stderr)
        if "cols" in prof:
            print(f"  - Columns: {prof['cols']}", file=sys.stderr)
        memory_mb = prof.get("memory_mb")
        if memory_mb is not None:
            print(f"  - Memory: {memory_mb:.2f} MB", file=sys.stderr)
    if out.get("approximate"):
        print("  - Note: approximate profile (chunked mode)", file=sys.stderr)

    if not getattr(args, "no_json", False):
        print(_m._json_dump(out))
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    sp_prof = sub.add_parser("profile", help="Load CSV and emit profile JSON")
    sp_prof.add_argument("csv", help=CSV_PATH_HELP)
    add_csv_options(sp_prof)
    sp_prof.add_argument(
        "--chunksize",
        type=int,
        default=None,
        metavar="N",
        help="Stream CSV in chunks of N rows (approximate profile; skips dtype/unique/memory_mb)",
    )
    sp_prof.set_defaults(func=cmd_profile)
