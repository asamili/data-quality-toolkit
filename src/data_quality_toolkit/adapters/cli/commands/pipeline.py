# src/data_quality_toolkit/adapters/cli/commands/pipeline.py
"""``dqt pipeline run`` — run an ELT pipeline via the create_elt_pipeline() API."""

from __future__ import annotations

import argparse
import sys

import data_quality_toolkit.adapters.cli.main as _m
from data_quality_toolkit.shared.config import load_pipeline_config
from data_quality_toolkit.shared.exceptions import ConfigError


def _apply_pipeline_config(args: argparse.Namespace) -> None:
    """Fill unset pipeline run args from --config YAML. CLI flags always win."""
    config_path = getattr(args, "config", None)
    if config_path is None:
        return
    config = load_pipeline_config(config_path)
    for key in ("run_id", "sessions_root", "extract", "transform", "load"):
        if getattr(args, key, None) is None and key in config:
            setattr(args, key, config[key])
    for key in ("assess", "manifest"):
        if not getattr(args, key, False) and config.get(key):
            setattr(args, key, True)


def cmd_pipeline_run(args: argparse.Namespace) -> int:
    """Run an ELT pipeline via the create_elt_pipeline() API."""
    import dataclasses

    from data_quality_toolkit.api import create_elt_pipeline

    try:
        _apply_pipeline_config(args)
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if not getattr(args, "run_id", None):
        print("Error: --run-id is required (provide via CLI or --config)", file=sys.stderr)
        return 2
    if not getattr(args, "sessions_root", None):
        print("Error: --sessions-root is required (provide via CLI or --config)", file=sys.stderr)
        return 2

    pipeline = create_elt_pipeline(args.run_id, args.sessions_root)
    if args.extract:
        pipeline.extract(args.extract)
    if args.transform:
        pipeline.transform(name=args.transform)
    if args.load:
        pipeline.load(args.load)
    if args.assess:
        pipeline.assess()
    if args.manifest:
        pipeline.manifest()

    result = pipeline.run()

    if not getattr(args, "no_json", False):
        print(_m._json_dump(dataclasses.asdict(result)))
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    sp_pipeline = sub.add_parser("pipeline", help="Pipeline commands")
    ssp_pipeline = sp_pipeline.add_subparsers(dest="subcommand", required=True)
    ssp_pipeline_run = ssp_pipeline.add_parser(
        "run", help="Run an ELT pipeline (extract → transform → load → assess → manifest)"
    )
    ssp_pipeline_run.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to pipeline YAML config file (CLI flags override config values)",
    )
    ssp_pipeline_run.add_argument(
        "--run-id",
        dest="run_id",
        required=False,
        default=None,
        metavar="ID",
        help="Unique run identifier",
    )
    ssp_pipeline_run.add_argument(
        "--sessions-root",
        dest="sessions_root",
        required=False,
        default=None,
        metavar="PATH",
        help="Root directory for session data",
    )
    ssp_pipeline_run.add_argument(
        "--extract", default=None, metavar="PATH", help="Source path for the extract step"
    )
    ssp_pipeline_run.add_argument(
        "--transform", default=None, metavar="NAME", help="Name for the transform step"
    )
    ssp_pipeline_run.add_argument(
        "--load", default=None, metavar="PATH", help="Output path for the load step"
    )
    ssp_pipeline_run.add_argument(
        "--assess", action="store_true", default=False, help="Add an assess step"
    )
    ssp_pipeline_run.add_argument(
        "--manifest", action="store_true", default=False, help="Add a manifest step"
    )
    ssp_pipeline_run.set_defaults(func=cmd_pipeline_run)
