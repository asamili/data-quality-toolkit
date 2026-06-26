# src/data_quality_toolkit/adapters/cli/commands/compare.py
"""``dqt compare`` — compare the last two export runs for a dataset."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import data_quality_toolkit.adapters.cli.main as _m
from data_quality_toolkit.adapters.cli.utils.parser import (
    CROSS_FALLBACK,
    CSV_PATH_HELP,
    DEFAULT_DIST,
)


def _print_compare_score_lines(result: dict) -> None:
    """Print quality_score and completeness_score compare lines to stderr if present."""
    if "current_quality_score" in result or "previous_quality_score" in result:
        prev_qs = result.get("previous_quality_score")
        curr_qs = result.get("current_quality_score")
        prev_str = f"{prev_qs:.3f}" if prev_qs is not None else "N/A"
        curr_str = f"{curr_qs:.3f}" if curr_qs is not None else "N/A"
        print(f"  - Quality Score: {prev_str} -> {curr_str}", file=sys.stderr)
    if "current_completeness_score" in result or "previous_completeness_score" in result:
        prev_cs = result.get("previous_completeness_score")
        curr_cs = result.get("current_completeness_score")
        prev_str = f"{prev_cs:.3f}" if prev_cs is not None else "N/A"
        curr_str = f"{curr_cs:.3f}" if curr_cs is not None else "N/A"
        print(f"  - Completeness Score: {prev_str} -> {curr_str}", file=sys.stderr)


def cmd_compare(args: argparse.Namespace) -> int:
    """Compare the last two export runs for a dataset."""
    from data_quality_toolkit.adapters.loaders.file.csv_loader import dataset_id_from_file
    from data_quality_toolkit.application.workflow.compare import compare_last_two_runs

    try:
        dataset_id = dataset_id_from_file(Path(args.csv))
    except Exception as e:
        print(f"Error: could not compute dataset_id from '{args.csv}': {e}", file=sys.stderr)
        return 1

    history_path = Path(args.outdir) / "star" / "quality_history.jsonl"
    result = compare_last_two_runs(dataset_id, history_path)

    if "error" in result:
        cross = _m._safe_text("✗", CROSS_FALLBACK)
        print(
            f"{cross} Compare: not enough history for '{Path(args.csv).name}'",
            file=sys.stderr,
        )
        print(f"  {result['message']}", file=sys.stderr)
        if not getattr(args, "no_json", False):
            print(_m._json_dump(result))
        return 1

    # Human-friendly stderr summary
    tick = _m._safe_text("✓", "[OK]")
    csv_name = Path(args.csv).name
    print(f"{tick} Compare complete  [{csv_name}]", file=sys.stderr)

    prev_score = result.get("previous_score")
    curr_score = result.get("current_score")
    score_delta = result.get("score_delta")
    if prev_score is not None and curr_score is not None and score_delta is not None:
        direction = "up" if score_delta > 0 else ("down" if score_delta < 0 else "flat")
        delta_sign = "+" if score_delta > 0 else ""
        print(
            f"  - Score: {prev_score:.3f} -> {curr_score:.3f}"
            f"  ({direction}, {delta_sign}{score_delta:.3f})",
            file=sys.stderr,
        )

    _print_compare_score_lines(result)

    prev_issues = result.get("previous_issues_total")
    curr_issues = result.get("current_issues_total")
    if prev_issues is not None and curr_issues is not None:
        print(f"  - Issues: {prev_issues} -> {curr_issues}", file=sys.stderr)

    sev_delta = result.get("issues_by_severity_delta")
    if isinstance(sev_delta, dict) and sev_delta:
        parts = [f"{k} {'+' if v > 0 else ''}{v}" for k, v in sev_delta.items()]
        print(f"  - Severity delta: {', '.join(parts)}", file=sys.stderr)

    cat_delta = result.get("issues_by_category_delta")
    if isinstance(cat_delta, dict) and cat_delta:
        parts = [f"{k} {'+' if v > 0 else ''}{v}" for k, v in cat_delta.items()]
        print(f"  - Category delta: {', '.join(parts)}", file=sys.stderr)

    if not getattr(args, "no_json", False):
        print(_m._json_dump(result))
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    sp_cmp = sub.add_parser("compare", help="Compare last two export runs for a dataset")
    sp_cmp.add_argument("csv", help=CSV_PATH_HELP)
    sp_cmp.add_argument(
        "--outdir",
        default=None,
        help=f"Output directory (default: {DEFAULT_DIST}); must match the --outdir used with export-star",
    )
    sp_cmp.set_defaults(func=cmd_compare)
