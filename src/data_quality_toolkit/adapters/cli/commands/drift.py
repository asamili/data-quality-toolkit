# src/data_quality_toolkit/adapters/cli/commands/drift.py
"""``dqt drift`` — detect statistical drift between two CSV files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import data_quality_toolkit.adapters.cli.main as _m
from data_quality_toolkit.adapters.cli.utils.parser import CROSS_FALLBACK


def _drift_kwargs_from_args(args: argparse.Namespace) -> dict[str, Any]:
    """Collect detect_drift kwargs from parsed args; omit unset so API defaults win."""
    kw: dict[str, Any] = {}
    if args.alpha is not None:
        kw["alpha"] = float(args.alpha)
    if args.min_samples is not None:
        kw["min_samples"] = int(args.min_samples)
    if args.max_categories is not None:
        kw["max_categories"] = int(args.max_categories)
    if args.sep is not None:
        kw["sep"] = args.sep
    if args.encoding is not None:
        kw["encoding"] = args.encoding
    if getattr(args, "na_values", None):
        kw["na_values"] = [x.strip() for x in args.na_values.split(",") if x.strip()]
    sample_size = _m._get_sample_size(args)
    if sample_size is not None:
        kw["sample_size"] = sample_size
    if getattr(args, "output", None):
        kw["output_path"] = args.output
    if getattr(args, "history", None):
        kw["history_path"] = args.history
    return kw


def _print_drift_report_line(result: dict[str, Any]) -> None:
    """Print the evidence-report stderr line when a report file was written."""
    if out_path := result.get("output_path"):
        print(f"  - Report written: {out_path}", file=sys.stderr)
    if hist_path := result.get("history_path"):
        print(f"  - History appended: {hist_path}", file=sys.stderr)


def cmd_drift(args: argparse.Namespace) -> int:
    """Detect statistical drift between a baseline CSV and a current CSV."""
    result = _m.run_drift(args.baseline, args.current, **_drift_kwargs_from_args(args))

    if result.get("status") == "unavailable":
        cross = _m._safe_text("✗", CROSS_FALLBACK)
        print(f"{cross} Drift detection unavailable: scipy is not installed", file=sys.stderr)
        if reason := result.get("reason"):
            print(f"  {reason}", file=sys.stderr)
        _print_drift_report_line(result)
        if not getattr(args, "no_json", False):
            print(_m._json_dump(result))
        return 1

    tick = _m._safe_text("✓", "[OK]")
    baseline_name = Path(args.baseline).name
    current_name = Path(args.current).name
    print(f"{tick} Drift check complete  [{baseline_name} vs {current_name}]", file=sys.stderr)
    print(
        f"  - Rows: {result.get('reference_rows')} (baseline)"
        f" vs {result.get('current_rows')} (current)",
        file=sys.stderr,
    )
    summary = result.get("summary") or {}
    print(
        f"  - Columns tested: {summary.get('columns_tested', 0)},"
        f" skipped: {summary.get('columns_skipped', 0)}",
        file=sys.stderr,
    )
    print(f"  - Columns drifted: {summary.get('columns_drifted', 0)}", file=sys.stderr)
    for col in result.get("columns") or []:
        if col.get("drift_detected"):
            print(
                f"  - {col['column']}: {col.get('test')} {col.get('interpretation')}",
                file=sys.stderr,
            )
    if note := summary.get("note"):
        print(f"  - Note: {note}", file=sys.stderr)
    _print_drift_report_line(result)

    if not getattr(args, "no_json", False):
        print(_m._json_dump(result))

    if args.fail_on_drift and summary.get("columns_drifted", 0) > 0:
        return 2

    return 0


def register(sub: argparse._SubParsersAction) -> None:
    sp_drift = sub.add_parser(
        "drift",
        help="Detect statistical drift between two CSV files (KS / chi-square)",
    )
    sp_drift.add_argument("baseline", help="Path to baseline CSV file")
    sp_drift.add_argument("current", help="Path to current CSV file")
    sp_drift.add_argument(
        "--alpha",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Significance level for drift tests, in (0, 1) (default: 0.05)",
    )
    sp_drift.add_argument(
        "--min-samples",
        dest="min_samples",
        type=int,
        default=None,
        metavar="N",
        help="Minimum non-null samples per column required to test (default: 30)",
    )
    sp_drift.add_argument(
        "--max-categories",
        dest="max_categories",
        type=int,
        default=None,
        metavar="N",
        help="Max categories kept before bucketing rare values (default: 20)",
    )
    sp_drift.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="Exit 2 if statistical drift is detected",
    )
    sp_drift.add_argument(
        "--output",
        default=None,
        help="Write the drift result to this path as a JSON evidence report",
    )
    sp_drift.add_argument(
        "--history",
        default=None,
        metavar="PATH",
        help="Append a compact drift history record (JSONL) to this path",
    )
    sp_drift.add_argument("--sep", help="CSV delimiter (e.g., ',' or '\\t')")
    sp_drift.add_argument("--encoding", help="CSV encoding (e.g., 'utf-8', 'latin-1')")
    sp_drift.add_argument("--na-values", help="Comma-separated NA values (e.g., 'NA,NaN,null')")
    sp_drift.add_argument("--sample-size", type=int, help="Override SAMPLE_SIZE for this run")
    sp_drift.set_defaults(func=cmd_drift)
