# src/data_quality_toolkit/adapters/cli/commands/assess.py
"""``dqt assess`` — load a CSV, profile, and assess JSON."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

import data_quality_toolkit.adapters.cli.main as _m
from data_quality_toolkit.adapters.cli.utils.parser import (
    CSV_PATH_HELP,
    FAIL_UNDER_HELP,
    SCORE_FIELD_CHOICES,
    SCORE_FIELD_DEFAULT,
    add_csv_options,
)

LOGGER = logging.getLogger("dqt.cli")


def _print_assessment_score_lines(assessment: dict) -> None:
    """Print score breakdown lines to stderr for assess/export-star summaries."""
    try:
        print(f"  - Score: {float(assessment['score']):.2%}", file=sys.stderr)
    except Exception:
        LOGGER.debug("Failed to format Score from assessment: %r", assessment, exc_info=True)
    if "completeness_score" in assessment:
        try:
            print(
                f"  - Completeness Score: {float(assessment['completeness_score']):.2%}",
                file=sys.stderr,
            )
        except Exception:
            LOGGER.debug("Failed to format Completeness Score: %r", assessment, exc_info=True)
    if "quality_score" in assessment:
        try:
            print(
                f"  - Quality Score: {float(assessment['quality_score']):.2%}",
                file=sys.stderr,
            )
        except Exception:
            LOGGER.debug("Failed to format Quality Score: %r", assessment, exc_info=True)
    issues = assessment.get("issues") or []
    print(f"  - Issues flagged: {len(issues)}", file=sys.stderr)


def _dispatch_assessment(
    args: argparse.Namespace,
    nt: float | None,
    chunksize: int | None,
    csv_kw: dict[str, Any],
) -> Any:
    """Route to chunked or full-load assessment."""
    if chunksize is not None:
        chunked_kw: dict[str, Any] = {}
        if nt is not None:
            chunked_kw["null_threshold"] = nt
        return _m.run_assessment_chunked(args.csv, chunksize=chunksize, **chunked_kw, **csv_kw)
    sample_size = _m._get_sample_size(args)
    db_path = Path(args.db) if getattr(args, "db", None) else None
    if nt is not None:
        return _m.run_assessment(
            args.csv, null_threshold=nt, db_path=db_path, sample_size=sample_size, **csv_kw
        )
    return _m.run_assessment(args.csv, db_path=db_path, sample_size=sample_size, **csv_kw)


def _print_chunked_assessment_note(assessment: dict[str, Any]) -> None:
    """Print chunked-mode note and completeness score to stderr."""
    print(
        "  - Note: partial chunked assessment — distribution/cardinality/outlier rules skipped",
        file=sys.stderr,
    )
    if "completeness_score" in assessment:
        try:
            print(
                f"  - Completeness Score: {float(assessment['completeness_score']):.2%}",
                file=sys.stderr,
            )
        except Exception:
            LOGGER.debug("Failed to format Completeness Score: %r", assessment, exc_info=True)
    issues = assessment.get("issues") or []
    print(f"  - Issues flagged: {len(issues)}", file=sys.stderr)


def cmd_assess(args: argparse.Namespace) -> int:
    """Assess a CSV file."""
    nt = _m._extract_null_threshold(args)
    fu = _m._extract_fail_under(args)
    chunksize: int | None = getattr(args, "chunksize", None)
    score_field = getattr(args, "score_field", SCORE_FIELD_DEFAULT) or SCORE_FIELD_DEFAULT
    csv_kw = _m._csv_kwargs_from_args(args)
    out = _dispatch_assessment(args, nt, chunksize, csv_kw)

    # Human-friendly summary -> stderr (stdout stays pure JSON)
    tick = _m._safe_text("✓", "[OK]")
    mode = " [chunked, partial]" if chunksize is not None else ""
    print(f"{tick} Assessment complete{mode}", file=sys.stderr)
    prof = out.get("profile") or {}
    if isinstance(prof, dict):
        if "rows" in prof:
            print(f"  - Rows: {prof['rows']}", file=sys.stderr)
        if "cols" in prof:
            print(f"  - Columns: {prof['cols']}", file=sys.stderr)

    assessment = out.get("assessment")
    if chunksize is not None and isinstance(assessment, dict):
        _print_chunked_assessment_note(assessment)
    elif isinstance(assessment, dict) and "score" in assessment:
        _print_assessment_score_lines(assessment)

    if not getattr(args, "no_json", False):
        print(_m._json_dump(out))
    return _m._check_quality_gate(fu, out, score_field=score_field)


def register(sub: argparse._SubParsersAction) -> None:
    sp_as = sub.add_parser("assess", help="Load CSV, profile, and assess JSON")
    sp_as.add_argument("csv", help=CSV_PATH_HELP)
    add_csv_options(sp_as)
    sp_as.add_argument(
        "--null-threshold",
        dest="null_threshold",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Flag completeness issues above this missing-value fraction (0.0 to 1.0, default: 0.2)",
    )
    sp_as.add_argument(
        "--fail-under",
        dest="fail_under",
        type=float,
        default=None,
        metavar="FLOAT",
        help=FAIL_UNDER_HELP,
    )
    sp_as.add_argument(
        "--score-field",
        dest="score_field",
        choices=SCORE_FIELD_CHOICES,
        default=SCORE_FIELD_DEFAULT,
        metavar="FIELD",
        help="Score field used by --fail-under quality gate (default: score)",
    )
    sp_as.add_argument(
        "--db",
        dest="db",
        default=None,
        metavar="PATH",
        help="Persist assessment run to a dashboard-readable SQLite database",
    )
    sp_as.add_argument(
        "--chunksize",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Stream CSV in chunks of N rows (partial assessment; "
            "distribution/cardinality/outlier rules skipped)"
        ),
    )
    sp_as.set_defaults(func=cmd_assess)
