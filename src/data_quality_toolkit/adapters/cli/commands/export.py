# src/data_quality_toolkit/adapters/cli/commands/export.py
"""``dqt export-star`` (and the ``export`` alias) — export star schema CSVs."""

from __future__ import annotations

import argparse
import sys

import data_quality_toolkit.adapters.cli.main as _m
from data_quality_toolkit.adapters.cli.commands.assess import _print_assessment_score_lines
from data_quality_toolkit.adapters.cli.utils.parser import (
    CSV_PATH_HELP,
    DEFAULT_DIST,
    FAIL_UNDER_HELP,
    SCORE_FIELD_CHOICES,
    SCORE_FIELD_DEFAULT,
    add_csv_options,
)


def cmd_export_star(args: argparse.Namespace) -> int:
    """Export star schema."""
    nt = _m._extract_null_threshold(args)
    fu = _m._extract_fail_under(args)
    score_field = getattr(args, "score_field", SCORE_FIELD_DEFAULT) or SCORE_FIELD_DEFAULT
    sample_size = _m._get_sample_size(args)
    csv_kw = _m._csv_kwargs_from_args(args)
    emit_manifest = getattr(args, "manifest", False)
    if nt is not None:
        out = _m.run_export_star(
            args.csv,
            output_dir=args.outdir,
            null_threshold=nt,
            sample_size=sample_size,
            emit_manifest=emit_manifest,
            **csv_kw,
        )
    else:
        out = _m.run_export_star(
            args.csv,
            output_dir=args.outdir,
            sample_size=sample_size,
            emit_manifest=emit_manifest,
            **csv_kw,
        )

    # Friendly summary -> STDERR (so STDOUT stays pure JSON)
    tick = _m._safe_text("✓", "[OK]")
    print(f"{tick} Profile complete", file=sys.stderr)

    prof = out.get("profile") or {}
    if isinstance(prof, dict):
        if "rows" in prof:
            print(f"  - Rows: {prof['rows']}", file=sys.stderr)
        if "cols" in prof:
            print(f"  - Columns: {prof['cols']}", file=sys.stderr)

    assessment = out.get("assessment")
    if isinstance(assessment, dict) and "score" in assessment:
        _print_assessment_score_lines(assessment)

    print(f"{tick} Star schema exported", file=sys.stderr)
    for name, path in (out.get("export_paths") or {}).items():
        if name != "relationships":
            print(f"  - {name}: {path}", file=sys.stderr)

    # Machine-friendly JSON last on STDOUT
    if not getattr(args, "no_json", False):
        print(_m._json_dump(out))
    return _m._check_quality_gate(fu, out, score_field=score_field)


def _add_export_arguments(parser: argparse.ArgumentParser) -> None:
    """Shared arguments for both ``export-star`` and its ``export`` alias."""
    parser.add_argument("csv", help=CSV_PATH_HELP)
    parser.add_argument(
        "--outdir", default=None, help=f"Output directory (default: {DEFAULT_DIST})"
    )
    add_csv_options(parser)
    parser.add_argument(
        "--null-threshold",
        dest="null_threshold",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Flag completeness issues above this missing-value fraction (0.0 to 1.0, default: 0.2)",
    )
    parser.add_argument(
        "--fail-under",
        dest="fail_under",
        type=float,
        default=None,
        metavar="FLOAT",
        help=FAIL_UNDER_HELP,
    )
    parser.add_argument(
        "--score-field",
        dest="score_field",
        choices=SCORE_FIELD_CHOICES,
        default=SCORE_FIELD_DEFAULT,
        metavar="FIELD",
        help="Score field used by --fail-under quality gate (default: score)",
    )
    parser.add_argument(
        "--manifest",
        action="store_true",
        default=False,
        help="Emit a lineage manifest (artifacts.json) alongside star outputs",
    )
    parser.set_defaults(func=cmd_export_star)


def register(sub: argparse._SubParsersAction) -> None:
    sp_star = sub.add_parser("export-star", help="Export star schema CSVs to a folder")
    _add_export_arguments(sp_star)


def register_alias(sub: argparse._SubParsersAction) -> None:
    sp_export = sub.add_parser("export", help="Alias for export-star")
    _add_export_arguments(sp_export)
