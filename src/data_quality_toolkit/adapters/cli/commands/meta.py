# src/data_quality_toolkit/adapters/cli/commands/meta.py
"""Small meta commands: settings, manifest, version, log-demo."""

from __future__ import annotations

import argparse
import sys

import data_quality_toolkit.adapters.cli.main as _m


def cmd_settings_show(_: argparse.Namespace) -> int:
    """Show current settings."""
    s = _m.load_settings()
    print(_m._json_dump(s))
    return 0


def cmd_version(_: argparse.Namespace) -> int:
    """Print version."""
    print(_m.VERSION)
    return 0


def cmd_log_demo(args: argparse.Namespace) -> int:
    """Demonstrate logging functionality."""
    # Lazy import to ensure logging is configured first in main()
    from data_quality_toolkit.utils.logging import get_logger

    logger = get_logger("dqt.cli")
    logger.debug("debug message")
    logger.info("info message")
    logger.warning("warning message")
    logger.error("error message")
    if args.raise_error:
        try:
            raise ZeroDivisionError("Test division error")
        except ZeroDivisionError:
            logger.exception("captured exception with stack")
    return 0


def cmd_manifest_create(args: argparse.Namespace) -> int:
    """Create a lineage manifest for a run."""
    manifest = _m.manifest_create(args.run_id, args.sessions_root)
    tick = _m._safe_text("✓", "[OK]")
    print(f"{tick} Manifest created  [run_id={args.run_id}]", file=sys.stderr)
    if not getattr(args, "no_json", False):
        print(_m._json_dump(manifest))
    return 0


def register_settings(sub: argparse._SubParsersAction) -> None:
    sp = sub.add_parser("settings", help="Settings commands")
    ssp = sp.add_subparsers(dest="subcommand", required=True)
    ssp_show = ssp.add_parser("show", help="Show resolved settings")
    ssp_show.set_defaults(func=cmd_settings_show)


def register_manifest(sub: argparse._SubParsersAction) -> None:
    sp_manifest = sub.add_parser("manifest", help="Manifest commands")
    ssp_manifest = sp_manifest.add_subparsers(dest="subcommand", required=True)
    ssp_manifest_create = ssp_manifest.add_parser("create", help="Build lineage manifest for a run")
    ssp_manifest_create.add_argument(
        "--run-id",
        dest="run_id",
        required=True,
        metavar="ID",
        help="Run identifier",
    )
    ssp_manifest_create.add_argument(
        "--sessions-root",
        dest="sessions_root",
        required=True,
        metavar="PATH",
        help="Root directory containing session folders",
    )
    ssp_manifest_create.set_defaults(func=cmd_manifest_create)


def register_version(sub: argparse._SubParsersAction) -> None:
    sp_ver = sub.add_parser("version", help="Print package version")
    sp_ver.set_defaults(func=cmd_version)


def register_log_demo(sub: argparse._SubParsersAction) -> None:
    sp_log = sub.add_parser("log-demo", help="Emit sample log lines")
    sp_log.add_argument("--raise-error", action="store_true")
    sp_log.set_defaults(func=cmd_log_demo)
