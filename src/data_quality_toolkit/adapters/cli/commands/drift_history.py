# src/data_quality_toolkit/adapters/cli/commands/drift_history.py
"""``dqt drift-history`` subcommands + the static drift dashboard handler."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import data_quality_toolkit.adapters.cli.main as _m
from data_quality_toolkit.adapters.cli.utils.parser import parse_bool_flag


def cmd_drift_history(args: argparse.Namespace) -> int:
    """Read and print drift history records from a JSONL file."""
    records = _m.read_drift_history(args.history_path)
    tick = _m._safe_text("✓", "[OK]")
    print(f"{tick} Drift history read  [{Path(args.history_path).name}]", file=sys.stderr)
    print(f"  - Records: {len(records)}", file=sys.stderr)
    if not getattr(args, "no_json", False):
        print(_m._json_dump(records))
    return 0


def cmd_drift_history_import(args: argparse.Namespace) -> int:
    """Import drift history JSONL records into a SQLite monitoring DB."""
    _m.ensure_drift_db(args.db)
    imported_count = _m.import_drift_history_sqlite(args.db, args.history_path)
    tick = _m._safe_text("✓", "[OK]")
    print(
        f"{tick} Drift history imported  [{Path(args.history_path).name}]",
        file=sys.stderr,
    )
    print(f"  - Imported rows: {imported_count}", file=sys.stderr)
    if not getattr(args, "no_json", False):
        print(
            _m._json_dump(
                {
                    "imported_count": imported_count,
                    "history_path": str(args.history_path),
                    "db_path": str(args.db),
                }
            )
        )
    return 0


def cmd_drift_history_list(args: argparse.Namespace) -> int:
    """List imported drift runs from a SQLite monitoring DB."""
    runs = _m.read_drift_runs_sqlite(
        args.db,
        limit=getattr(args, "limit", None),
        current_dataset_id=getattr(args, "current_dataset_id", None),
        drift_detected=getattr(args, "drift_detected", None),
        status=getattr(args, "status", None),
    )
    tick = _m._safe_text("✓", "[OK]")
    print(f"{tick} Drift runs listed  [{Path(args.db).name}]", file=sys.stderr)
    print(f"  - Runs: {len(runs)}", file=sys.stderr)
    if not getattr(args, "no_json", False):
        print(_m._json_dump(runs))
    return 0


def cmd_drift_history_columns(args: argparse.Namespace) -> int:
    """List imported per-column drift metrics from a SQLite monitoring DB."""
    max_psi = _m._extract_drift_threshold(getattr(args, "fail_on_psi", None), "--fail-on-psi")
    rows = _m.read_drift_columns_sqlite(
        args.db,
        run_id=getattr(args, "run_id", None),
        column_name=getattr(args, "column_name", None),
        drift_detected=getattr(args, "drift_detected", None),
    )
    drifted = sum(1 for r in rows if r.get("drift_detected"))
    tick = _m._safe_text("✓", "[OK]")
    print(f"{tick} Drift columns listed  [{Path(args.db).name}]", file=sys.stderr)
    print(f"  - Columns: {len(rows)}", file=sys.stderr)
    print(f"  - Drifted columns: {drifted}", file=sys.stderr)
    if not getattr(args, "no_json", False):
        print(_m._json_dump(rows))
    if max_psi is not None:
        result = _m.evaluate_psi_threshold(rows, max_psi=max_psi)
        if result["breached"]:
            count = len(result["offenders"])
            print(
                f"PSI threshold breached: offenders={count} threshold={max_psi}",
                file=sys.stderr,
            )
            return 2
    return 0


def cmd_drift_history_trend(args: argparse.Namespace) -> int:
    """Summarize drift trends from a SQLite monitoring DB."""
    max_drift_rate = _m._extract_drift_threshold(
        getattr(args, "fail_on_drift_rate", None), "--fail-on-drift-rate"
    )
    summary = _m.summarize_drift_trends_sqlite(
        args.db,
        current_dataset_id=getattr(args, "current_dataset_id", None),
        limit=getattr(args, "limit", None),
    )
    tick = _m._safe_text("✓", "[OK]")
    print(f"{tick} Drift trend summarized  [{Path(args.db).name}]", file=sys.stderr)
    print(f"  - Total runs: {summary['total_runs']}", file=sys.stderr)
    print(f"  - Drifted runs: {summary['drifted_runs']}", file=sys.stderr)
    print(f"  - Drift rate: {summary['drift_rate']}", file=sys.stderr)
    if not getattr(args, "no_json", False):
        print(_m._json_dump(summary))
    if max_drift_rate is not None:
        result = _m.evaluate_drift_rate_threshold(summary, max_drift_rate=max_drift_rate)
        if result["breached"]:
            rate = result["drift_rate"]
            print(
                f"Drift rate threshold breached: drift_rate={rate} threshold={max_drift_rate}",
                file=sys.stderr,
            )
            return 2
    return 0


def cmd_drift_history_notify(args: argparse.Namespace) -> int:
    """Build (dry-run, default) or POST (--send) a one-shot drift webhook notification."""
    max_drift_rate = _m._extract_drift_threshold(
        getattr(args, "fail_on_drift_rate", None), "--fail-on-drift-rate"
    )
    max_psi = _m._extract_drift_threshold(getattr(args, "fail_on_psi", None), "--fail-on-psi")
    send = bool(getattr(args, "send", False))

    try:
        result = _m.send_drift_notification(
            args.db,
            args.webhook_url,
            max_drift_rate=max_drift_rate,
            max_psi=max_psi,
            dry_run=not send,
            send=send,
            timeout=getattr(args, "timeout", 10.0),
            allow_http=getattr(args, "allow_http", False),
            allow_insecure_host=getattr(args, "allow_insecure_host", False),
        )
    except Exception as exc:  # NotificationError/WebhookSecurityError/etc. -> controlled exit 1
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    payload = result["payload"]
    mode = "sent" if result["sent"] else "dry-run"
    tick = _m._safe_text("✓", "[OK]")
    # stderr summary is safe: only the redacted URL (no token/userinfo/query) is shown.
    print(f"{tick} Drift notification {mode}  [{result['redacted_url']}]", file=sys.stderr)
    print(f"  - Status: {payload['status']}", file=sys.stderr)
    if result["sent"]:
        print(f"  - HTTP: {result['status']}", file=sys.stderr)
    print(f"  - Drift rate: {payload['drift_summary']['drift_rate']}", file=sys.stderr)
    if not getattr(args, "no_json", False):
        print(_m._json_dump(payload))
    if result["breached"]:
        print("Drift threshold breached", file=sys.stderr)
        return 2
    return 0


def cmd_drift_history_report(args: argparse.Namespace) -> int:
    """Generate a drift-history monitoring report from a SQLite monitoring DB."""
    current_dataset_id = getattr(args, "current_dataset_id", None)
    limit = getattr(args, "limit", None)
    summary = _m.summarize_drift_trends_sqlite(
        args.db,
        current_dataset_id=current_dataset_id,
        limit=limit,
    )
    runs = _m.read_drift_runs_sqlite(
        args.db,
        limit=limit,
        current_dataset_id=current_dataset_id,
    )
    fmt = "html" if getattr(args, "format", None) == "html" else "md"

    columns: list[dict[str, Any]] | None = None
    if getattr(args, "include_columns", False):
        columns = _m.read_drift_columns_sqlite(args.db)

    distributions: list[dict[str, Any]] | None = None
    include_plots = getattr(args, "include_plots", False)
    if include_plots:
        distributions = _m.read_drift_distributions_sqlite(args.db)

    from data_quality_toolkit.adapters.reports.drift_history import (
        render_drift_history_report,
    )

    text = render_drift_history_report(
        summary=summary,
        runs=runs,
        db_path=args.db,
        current_dataset_id=current_dataset_id,
        limit=limit,
        fmt=fmt,
        columns=columns,
        distributions=distributions,
    )
    Path(args.output).write_text(text, encoding="utf-8")

    tick = _m._safe_text("✓", "[OK]")
    print(f"{tick} Drift report written  [{Path(args.output).name}]", file=sys.stderr)
    print(f"  - Output: {args.output}", file=sys.stderr)
    print(f"  - Total runs: {summary['total_runs']}", file=sys.stderr)
    if include_plots:
        print(f"  - Distribution rows: {len(distributions or [])}", file=sys.stderr)
    return 0


def cmd_drift_dashboard(args: argparse.Namespace) -> int:
    """Generate a static HTML drift analytics dashboard from a SQLite DB."""
    current_dataset_id = getattr(args, "current_dataset_id", None)
    limit = getattr(args, "limit", None)
    summary = _m.summarize_drift_trends_sqlite(
        args.db,
        current_dataset_id=current_dataset_id,
        limit=limit,
    )
    runs = _m.read_drift_runs_sqlite(
        args.db,
        limit=limit,
        current_dataset_id=current_dataset_id,
    )
    columns = _m.read_drift_columns_sqlite(args.db)

    distributions: list[dict[str, Any]] | None = None
    include_plots = getattr(args, "include_plots", False)
    if include_plots:
        distributions = _m.read_drift_distributions_sqlite(args.db)

    from data_quality_toolkit.adapters.reports.drift_dashboard import (
        render_drift_dashboard,
    )

    text = render_drift_dashboard(
        summary=summary,
        runs=runs,
        columns=columns,
        db_path=args.db,
        current_dataset_id=current_dataset_id,
        limit=limit,
        distributions=distributions,
    )
    Path(args.output).write_text(text, encoding="utf-8")

    tick = _m._safe_text("✓", "[OK]")
    print(f"{tick} Drift dashboard written  [{Path(args.output).name}]", file=sys.stderr)
    print(f"  - Output: {args.output}", file=sys.stderr)
    print(f"  - Total runs: {summary['total_runs']}", file=sys.stderr)
    print(f"  - Drifted runs: {summary['drifted_runs']}", file=sys.stderr)
    print(f"  - Column rows: {len(columns)}", file=sys.stderr)
    if include_plots:
        print(f"  - Distribution rows: {len(distributions or [])}", file=sys.stderr)
    return 0


def cmd_drift_history_export_xlsx(args: argparse.Namespace) -> int:
    """Export drift-history monitoring data to a multi-sheet .xlsx workbook."""
    try:
        result = _m.export_drift_history_xlsx(
            args.db,
            args.output,
            current_dataset_id=getattr(args, "current_dataset_id", None),
            limit=getattr(args, "limit", None),
            include_columns=getattr(args, "include_columns", True),
            include_distributions=getattr(args, "include_distributions", False),
            force=getattr(args, "force", False),
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    tick = _m._safe_text("✓", "[OK]")
    print(
        f"{tick} Drift workbook written  [{Path(result['output_path']).name}]",
        file=sys.stderr,
    )
    print(f"  - Output: {result['output_path']}", file=sys.stderr)
    print(f"  - Sheets: {', '.join(result['sheets'])}", file=sys.stderr)
    for name, count in result["row_counts"].items():
        print(f"  - {name} rows: {count}", file=sys.stderr)
    return 0


def cmd_drift_history_plot(args: argparse.Namespace) -> int:
    """Render drift-history monitoring data to local PNG chart files."""
    try:
        result = _m.export_drift_plots(
            args.db,
            args.output,
            chart=getattr(args, "chart", "all"),
            current_dataset_id=getattr(args, "current_dataset_id", None),
            limit=getattr(args, "limit", None),
            force=getattr(args, "force", False),
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    tick = _m._safe_text("✓", "[OK]")
    print(
        f"{tick} Drift plots written  [{Path(result['output_dir']).name}]",
        file=sys.stderr,
    )
    print(f"  - Output dir: {result['output_dir']}", file=sys.stderr)
    print(f"  - Charts: {', '.join(result['charts'])}", file=sys.stderr)
    for name, count in result["row_counts"].items():
        print(f"  - {name} points: {count}", file=sys.stderr)
    return 0


def cmd_drift_history_export_duckdb(args: argparse.Namespace) -> int:
    """Mirror drift-history monitoring tables from SQLite into a DuckDB file."""
    try:
        result = _m.export_monitoring_duckdb(
            args.db,
            args.output,
            overwrite=getattr(args, "overwrite", False),
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    tick = _m._safe_text("✓", "[OK]")
    print(
        f"{tick} DuckDB mirror written  [{Path(result['output_path']).name}]",
        file=sys.stderr,
    )
    print(f"  - Input DB: {result['input_db_path']}", file=sys.stderr)
    print(f"  - Output: {result['output_path']}", file=sys.stderr)
    print(f"  - Overwritten: {result['overwritten']}", file=sys.stderr)
    print(f"  - Tables: {', '.join(result['tables'])}", file=sys.stderr)
    for name, count in result["row_counts"].items():
        print(f"  - {name} rows: {count}", file=sys.stderr)
    if not getattr(args, "no_json", False):
        print(_m._json_dump(result))
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    sp_dh = sub.add_parser(
        "drift-history",
        help="Drift history commands (read JSONL, import to SQLite)",
    )
    ssp_dh = sp_dh.add_subparsers(dest="subcommand", required=True)

    ssp_dh_read = ssp_dh.add_parser(
        "read",
        help="Read drift history records from a JSONL file written by dqt drift --history",
    )
    ssp_dh_read.add_argument(
        "history_path",
        metavar="HISTORY_PATH",
        help="Path to a drift history JSONL file",
    )
    ssp_dh_read.set_defaults(func=cmd_drift_history)

    ssp_dh_import = ssp_dh.add_parser(
        "import",
        help="Import drift history JSONL records into a SQLite monitoring database",
    )
    ssp_dh_import.add_argument(
        "history_path",
        metavar="HISTORY_PATH",
        help="Path to a drift history JSONL file",
    )
    ssp_dh_import.add_argument(
        "--db",
        dest="db",
        required=True,
        metavar="PATH",
        help="Path to the SQLite monitoring database",
    )
    ssp_dh_import.set_defaults(func=cmd_drift_history_import)

    ssp_dh_list = ssp_dh.add_parser(
        "list",
        help="List imported drift runs from a SQLite monitoring database",
    )
    ssp_dh_list.add_argument(
        "--db",
        dest="db",
        required=True,
        metavar="PATH",
        help="Path to the SQLite monitoring database",
    )
    ssp_dh_list.add_argument(
        "--limit",
        dest="limit",
        type=int,
        metavar="N",
        help="Maximum number of runs to return",
    )
    ssp_dh_list.add_argument(
        "--current-dataset-id",
        dest="current_dataset_id",
        metavar="VALUE",
        help="Filter by current_dataset_id",
    )
    ssp_dh_list.add_argument(
        "--drift-detected",
        dest="drift_detected",
        type=parse_bool_flag,
        metavar="true|false",
        help="Filter by drift_detected (true|false)",
    )
    ssp_dh_list.add_argument(
        "--status",
        dest="status",
        metavar="VALUE",
        help="Filter by status",
    )
    ssp_dh_list.set_defaults(func=cmd_drift_history_list)

    ssp_dh_columns = ssp_dh.add_parser(
        "columns",
        help="List imported per-column drift metrics from a SQLite database",
    )
    ssp_dh_columns.add_argument(
        "--db",
        dest="db",
        required=True,
        metavar="PATH",
        help="Path to the SQLite monitoring database",
    )
    ssp_dh_columns.add_argument(
        "--run-id",
        dest="run_id",
        metavar="VALUE",
        help="Filter by run_id",
    )
    ssp_dh_columns.add_argument(
        "--column-name",
        dest="column_name",
        metavar="VALUE",
        help="Filter by column_name",
    )
    ssp_dh_columns.add_argument(
        "--drift-detected",
        dest="drift_detected",
        type=parse_bool_flag,
        metavar="true|false",
        help="Filter by drift_detected (true|false)",
    )
    ssp_dh_columns.add_argument(
        "--fail-on-psi",
        dest="fail_on_psi",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Exit 2 if any column PSI exceeds this threshold (0.0-1.0, strictly greater than)",
    )
    ssp_dh_columns.set_defaults(func=cmd_drift_history_columns)

    ssp_dh_trend = ssp_dh.add_parser(
        "trend",
        help="Summarize drift trends from a SQLite monitoring database",
    )
    ssp_dh_trend.add_argument(
        "--db",
        dest="db",
        required=True,
        metavar="PATH",
        help="Path to the SQLite monitoring database",
    )
    ssp_dh_trend.add_argument(
        "--current-dataset-id",
        dest="current_dataset_id",
        metavar="VALUE",
        help="Filter by current_dataset_id",
    )
    ssp_dh_trend.add_argument(
        "--limit",
        dest="limit",
        type=int,
        metavar="N",
        help="Maximum number of runs to aggregate",
    )
    ssp_dh_trend.add_argument(
        "--fail-on-drift-rate",
        dest="fail_on_drift_rate",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Exit 2 if drift_rate exceeds this threshold (0.0-1.0, strictly greater than)",
    )
    ssp_dh_trend.set_defaults(func=cmd_drift_history_trend)

    ssp_dh_notify = ssp_dh.add_parser(
        "notify",
        help="Build (dry-run) or POST (--send) a one-shot drift-threshold webhook "
        "notification (dry-run by default; real send needs --send and "
        "DQT_ALLOW_NETWORK=true)",
    )
    ssp_dh_notify.add_argument(
        "--db",
        dest="db",
        required=True,
        metavar="PATH",
        help="Path to the SQLite monitoring database",
    )
    ssp_dh_notify.add_argument(
        "--webhook-url",
        dest="webhook_url",
        required=True,
        metavar="URL",
        help="Webhook URL to POST to (https only by default; do NOT put secrets in "
        "the query string)",
    )
    ssp_dh_notify.add_argument(
        "--fail-on-drift-rate",
        dest="fail_on_drift_rate",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Mark breach (exit 2) if drift_rate exceeds this threshold (0.0-1.0)",
    )
    ssp_dh_notify.add_argument(
        "--fail-on-psi",
        dest="fail_on_psi",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Mark breach (exit 2) if any column PSI exceeds this threshold (0.0-1.0)",
    )
    notify_mode = ssp_dh_notify.add_mutually_exclusive_group()
    notify_mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Build and print the payload only; send nothing (default behavior)",
    )
    notify_mode.add_argument(
        "--send",
        dest="send",
        action="store_true",
        default=False,
        help="Actually POST the payload (also requires DQT_ALLOW_NETWORK=true)",
    )
    ssp_dh_notify.add_argument(
        "--timeout",
        dest="timeout",
        type=float,
        default=10.0,
        metavar="SECONDS",
        help="Connect/read timeout for a real send (default: 10.0)",
    )
    ssp_dh_notify.add_argument(
        "--allow-http",
        dest="allow_http",
        action="store_true",
        help="Permit a plain-http webhook URL (unsafe; https is the default)",
    )
    ssp_dh_notify.add_argument(
        "--allow-insecure-host",
        dest="allow_insecure_host",
        action="store_true",
        help="Skip the SSRF host check (unsafe; for trusted local testing only)",
    )
    ssp_dh_notify.set_defaults(func=cmd_drift_history_notify)

    ssp_dh_report = ssp_dh.add_parser(
        "report",
        help="Generate a drift-history monitoring report from a SQLite database",
    )
    ssp_dh_report.add_argument(
        "--db",
        dest="db",
        required=True,
        metavar="PATH",
        help="Path to the SQLite monitoring database",
    )
    ssp_dh_report.add_argument(
        "--output",
        dest="output",
        required=True,
        metavar="PATH",
        help="Path to write the report file",
    )
    ssp_dh_report.add_argument(
        "--current-dataset-id",
        dest="current_dataset_id",
        metavar="VALUE",
        help="Filter by current_dataset_id",
    )
    ssp_dh_report.add_argument(
        "--limit",
        dest="limit",
        type=int,
        metavar="N",
        help="Maximum number of runs to include",
    )
    ssp_dh_report.add_argument(
        "--format",
        dest="format",
        choices=["md", "html"],
        default="md",
        help="Report output format (md|html, default: md)",
    )
    ssp_dh_report.add_argument(
        "--include-columns",
        dest="include_columns",
        action="store_true",
        help="Include a per-column drift metrics section in the report",
    )
    ssp_dh_report.add_argument(
        "--include-plots",
        dest="include_plots",
        action="store_true",
        help="Include a dependency-free distribution-plots section in the report",
    )
    ssp_dh_report.set_defaults(func=cmd_drift_history_report)

    ssp_dh_dashboard = ssp_dh.add_parser(
        "dashboard",
        help="Generate a static HTML drift analytics dashboard from a SQLite database",
    )
    ssp_dh_dashboard.add_argument(
        "--db",
        dest="db",
        required=True,
        metavar="PATH",
        help="Path to the SQLite monitoring database",
    )
    ssp_dh_dashboard.add_argument(
        "--output",
        dest="output",
        required=True,
        metavar="PATH",
        help="Path to write the dashboard HTML file",
    )
    ssp_dh_dashboard.add_argument(
        "--current-dataset-id",
        dest="current_dataset_id",
        metavar="VALUE",
        help="Filter by current_dataset_id",
    )
    ssp_dh_dashboard.add_argument(
        "--limit",
        dest="limit",
        type=int,
        metavar="N",
        help="Maximum number of runs to include",
    )
    ssp_dh_dashboard.add_argument(
        "--include-plots",
        dest="include_plots",
        action="store_true",
        help="Include a dependency-free distribution-plots section in the dashboard",
    )
    ssp_dh_dashboard.set_defaults(func=cmd_drift_dashboard)

    ssp_dh_xlsx = ssp_dh.add_parser(
        "export-xlsx",
        help="Export drift-history monitoring data to a multi-sheet .xlsx workbook "
        "(requires: pip install data-quality-toolkit[powerbi])",
    )
    ssp_dh_xlsx.add_argument(
        "--db",
        dest="db",
        required=True,
        metavar="PATH",
        help="Path to the SQLite monitoring database",
    )
    ssp_dh_xlsx.add_argument(
        "--out",
        dest="output",
        required=True,
        metavar="PATH",
        help="Path to write the .xlsx workbook (must end with .xlsx)",
    )
    ssp_dh_xlsx.add_argument(
        "--current-dataset-id",
        dest="current_dataset_id",
        metavar="VALUE",
        help="Filter by current_dataset_id",
    )
    ssp_dh_xlsx.add_argument(
        "--limit",
        dest="limit",
        type=int,
        metavar="N",
        help="Maximum number of runs to include",
    )
    ssp_dh_xlsx.add_argument(
        "--include-columns",
        dest="include_columns",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include a per-column drift metrics sheet (default: on; use "
        "--no-include-columns to omit)",
    )
    ssp_dh_xlsx.add_argument(
        "--include-distributions",
        dest="include_distributions",
        action="store_true",
        help="Include a per-column distribution-bins sheet (default: off; can be large)",
    )
    ssp_dh_xlsx.add_argument(
        "--force",
        dest="force",
        action="store_true",
        help="Overwrite the output file if it already exists",
    )
    ssp_dh_xlsx.set_defaults(func=cmd_drift_history_export_xlsx)

    ssp_dh_plot = ssp_dh.add_parser(
        "plot",
        help="Render drift-history monitoring data to local PNG charts "
        "(requires: pip install data-quality-toolkit[viz])",
    )
    ssp_dh_plot.add_argument(
        "--db",
        dest="db",
        required=True,
        metavar="PATH",
        help="Path to the SQLite monitoring database",
    )
    ssp_dh_plot.add_argument(
        "--out",
        dest="output",
        required=True,
        metavar="DIR",
        help="Directory to write the PNG chart files into",
    )
    ssp_dh_plot.add_argument(
        "--chart",
        dest="chart",
        choices=["drift-rate", "psi-by-column", "top-drifted", "all"],
        default="all",
        help="Which chart(s) to render (default: all)",
    )
    ssp_dh_plot.add_argument(
        "--current-dataset-id",
        dest="current_dataset_id",
        metavar="VALUE",
        help="Filter by current_dataset_id",
    )
    ssp_dh_plot.add_argument(
        "--limit",
        dest="limit",
        type=int,
        metavar="N",
        help="Maximum number of runs to include",
    )
    ssp_dh_plot.add_argument(
        "--force",
        dest="force",
        action="store_true",
        help="Overwrite existing PNG files if they already exist",
    )
    ssp_dh_plot.set_defaults(func=cmd_drift_history_plot)

    ssp_dh_duckdb = ssp_dh.add_parser(
        "export-duckdb",
        help="Mirror drift-history monitoring tables from SQLite into a DuckDB file "
        "(requires: pip install data-quality-toolkit[duckdb])",
    )
    ssp_dh_duckdb.add_argument(
        "--db",
        dest="db",
        required=True,
        metavar="PATH",
        help="Path to the source SQLite monitoring database (read-only)",
    )
    ssp_dh_duckdb.add_argument(
        "--out",
        dest="output",
        required=True,
        metavar="PATH",
        help="Path to write the DuckDB mirror (must end with .duckdb)",
    )
    ssp_dh_duckdb.add_argument(
        "--overwrite",
        dest="overwrite",
        action="store_true",
        help="Overwrite the output file if it already exists",
    )
    ssp_dh_duckdb.set_defaults(func=cmd_drift_history_export_duckdb)
