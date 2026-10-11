# src/data_quality_toolkit/adapters/cli/commands/kpi_builtin.py
"""Built-in DQT quality semantics commands: kpi-builtin {catalog, emit-dax, validate-contract}.

Thin, additive CLI surface over the accepted public API
(``get_builtin_quality_catalog``, ``emit_builtin_quality_dax``,
``validate_builtin_quality_semantic_contract``). All business logic is resolved
through the monkeypatchable proxies on ``cli.main`` (``_m``), mirroring the other
command modules; this module imports no domain/business logic directly.
"""

from __future__ import annotations

import argparse
import logging
import sys

import data_quality_toolkit.adapters.cli.main as _m

LOGGER = logging.getLogger("dqt.cli")


def cmd_kpi_builtin_catalog(args: argparse.Namespace) -> int:
    """Print the built-in quality semantic catalog as JSON."""
    tick = _m._safe_text("✓", "[OK]")
    try:
        result = _m.get_builtin_quality_catalog()
        print(
            f"{tick} Built-in quality catalog  [{result.get('measure_count', 0)} measures]",
            file=sys.stderr,
        )
        if not getattr(args, "no_json", False):
            print(_m._json_dump(result))
        return 0
    except Exception as e:
        LOGGER.exception("Built-in quality catalog failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_kpi_builtin_emit_dax(args: argparse.Namespace) -> int:
    """Emit DAX for the built-in quality catalog (optionally writing to --out)."""
    tick = _m._safe_text("✓", "[OK]")
    try:
        result = _m.emit_builtin_quality_dax(output_path=args.out)
        written = result.get("output_path")
        if written:
            print(f"{tick} Wrote built-in quality DAX: {written}", file=sys.stderr)
        else:
            print(
                f"{tick} Emitted built-in quality DAX  [{result.get('measure_count', 0)} measures]",
                file=sys.stderr,
            )
        if not getattr(args, "no_json", False):
            print(_m._json_dump(result))
        return 0
    except Exception as e:
        LOGGER.exception("Built-in quality DAX emission failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_kpi_builtin_validate_contract(args: argparse.Namespace) -> int:
    """Validate the built-in quality contract against a package or star directory.

    Exit 0 when valid, 2 on contract validation failure, 1 on unexpected error.
    """
    cross = _m._safe_text("✗", "[FAIL]")
    tick = _m._safe_text("✓", "[OK]")
    try:
        if args.package is not None:
            path, input_mode = args.package, "package"
        elif args.star is not None:
            path, input_mode = args.star, "star"
        else:
            path, input_mode = args.path, "auto"

        result = _m.validate_builtin_quality_semantic_contract(path, input_mode=input_mode)
        valid = bool(result.get("valid", False))

        if valid:
            print(
                f"{tick} Built-in quality contract valid  [mode={result.get('input_mode')}]",
                file=sys.stderr,
            )
        else:
            print(
                f"{cross} Built-in quality contract INVALID  [mode={result.get('input_mode')}]",
                file=sys.stderr,
            )
            for err in result.get("errors", []):
                print(f"  - {err}", file=sys.stderr)

        if not getattr(args, "no_json", False):
            print(_m._json_dump(result))
        return 0 if valid else 2
    except Exception as e:
        LOGGER.exception("Built-in quality contract validation failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


def register_kpi_builtin(sub: argparse._SubParsersAction) -> None:
    sp = sub.add_parser(
        "kpi-builtin",
        help="Built-in DQT quality semantics (catalog, DAX, contract validation)",
    )
    ssp = sp.add_subparsers(dest="subcommand", required=True)

    sp_catalog = ssp.add_parser(
        "catalog",
        help="Print the built-in quality semantic catalog as JSON",
    )
    sp_catalog.set_defaults(func=cmd_kpi_builtin_catalog)

    sp_emit = ssp.add_parser(
        "emit-dax",
        help="Emit DAX for the built-in quality catalog (optionally write to --out)",
    )
    sp_emit.add_argument(
        "--out",
        dest="out",
        default=None,
        metavar="PATH",
        help="Write the DAX to PATH (omit to return DAX text in the JSON result)",
    )
    sp_emit.set_defaults(func=cmd_kpi_builtin_emit_dax)

    sp_validate = ssp.add_parser(
        "validate-contract",
        help="Validate the built-in quality contract against a package or star directory",
    )
    mode_group = sp_validate.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--package",
        dest="package",
        default=None,
        metavar="PATH",
        help="Validate a Power BI package directory (containing star/)",
    )
    mode_group.add_argument(
        "--star",
        dest="star",
        default=None,
        metavar="PATH",
        help="Validate a star schema directory directly",
    )
    mode_group.add_argument(
        "--path",
        dest="path",
        default=None,
        metavar="PATH",
        help="Validate a path with auto-detection of package vs star",
    )
    sp_validate.set_defaults(func=cmd_kpi_builtin_validate_contract)
