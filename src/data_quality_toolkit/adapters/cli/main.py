# src/data_quality_toolkit/adapters/cli/main.py
"""CLI entrypoint.

This module is the thin, stable surface for the ``dqt`` CLI. It keeps:

* the process entry (:func:`main`) and the parser factory (:func:`build_parser`),
* the lazy-import API proxies (``run_profile``, ``run_drift``, ...), and
* the small shared helpers (``_json_dump``, ``_safe_text``, ``_get_sample_size``,
  ``_csv_kwargs_from_args``, ``_check_quality_gate``, ...).

Command registration and per-command handlers live under
``adapters/cli/commands``; shared parser pieces and the Streamlit launcher live
under ``adapters/cli/utils``. The command handlers resolve the proxies and
shared helpers *through this module* at call time, so tests that
``monkeypatch.setattr(cli.main, "<name>", ...)`` keep working after the split.
"""

from __future__ import annotations

import argparse
import codecs
import importlib
import json
import logging
import pkgutil
import subprocess  # noqa: F401  (retained: tests patch ``cli.subprocess.run``)
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from data_quality_toolkit.adapters.cli.utils.parser import (
    CROSS_FALLBACK,
    DEFAULT_DIST,
    DQTArgumentParser,
    add_csv_options,
    parse_bool_flag,
)
from data_quality_toolkit.shared.config import load_dqt_config
from data_quality_toolkit.shared.constants import (  # noqa: F401  (re-export for cmd_version/tests)
    VERSION,
)
from data_quality_toolkit.shared.error_contract import to_error_info
from data_quality_toolkit.shared.exceptions import ConfigError
from data_quality_toolkit.shared.models import ErrorInfo
from data_quality_toolkit.shared.result_types import (
    DriftHistoryXlsxExportResult,
    DriftNotificationSendResult,
    DriftPlotsExportResult,
    DriftRateThresholdResult,
    MonitoringDuckdbExportResult,
    PsiThresholdResult,
)
from data_quality_toolkit.shared.settings import (  # noqa: F401  (re-export for cmd_settings_show/tests)
    SettingsValidationError,
    describe_invalid_settings,
    load_settings,
)
from data_quality_toolkit.shared.text_redaction import redact_paths
from data_quality_toolkit.utils.logging import setup_logging

# Backward-compatible aliases for names that moved to utils.parser (kept so any
# external/import-path reference to ``cli.main._add_csv_options`` etc. still works).
_DQTArgumentParser = DQTArgumentParser
_add_csv_options = add_csv_options
_parse_bool_flag = parse_bool_flag

# Module logger (used for exception logging, satisfies Ruff S110)
LOGGER = logging.getLogger("dqt.cli")

# cspell:ignore TMSL tmsl kpis dmethod


def _json_dump(obj: Any) -> str:
    # Prefer Pydantic v2 native JSON
    try:
        mdj = obj.model_dump_json
    except AttributeError:
        mdj = None
    if mdj is not None:
        return str(mdj(indent=2))

    # Pydantic v1 fallback
    try:
        dmethod = obj.dict
    except AttributeError:
        dmethod = None
    if dmethod is not None:
        return json.dumps(dmethod(), indent=2, default=str)

    # Generic fallback (handles Path via default=str)
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


def _csv_kwargs_from_args(args: argparse.Namespace) -> dict[str, Any]:
    kw: dict[str, Any] = {}
    if args.sep is not None:
        kw["sep"] = args.sep
    if args.encoding is not None:
        kw["encoding"] = args.encoding
    if getattr(args, "no_header", False):
        kw["header"] = None
    if getattr(args, "na_values", None):
        kw["na_values"] = [x.strip() for x in args.na_values.split(",") if x.strip()]
    # IMPORTANT: do NOT include sample_size here; it is passed as an explicit named parameter
    return kw


def _get_sample_size(args: argparse.Namespace) -> int | None:
    """Extract --sample-size from parsed args; returns None when not provided."""
    val = getattr(args, "sample_size", None)
    return int(val) if val is not None else None


# --- Test-friendly, lazy-imported wrappers (so monkeypatch can replace them) ---


def run_profile(csv: str, sample_size: int | None = None, **kw: Any) -> Any:
    """Proxy to pipeline.run_profile (lazy import to avoid early heavy imports)."""
    from data_quality_toolkit.application.workflow.pipeline import run_profile as _impl

    return _impl(csv, sample_size=sample_size, **kw)


def run_profile_chunked(csv: str, chunksize: int = 100_000, **kw: Any) -> Any:
    """Proxy to pipeline.run_profile_chunked (lazy import for monkeypatching)."""
    from data_quality_toolkit.application.workflow.pipeline import run_profile_chunked as _impl

    return _impl(csv, chunksize=chunksize, **kw)


def run_assessment(csv: str, sample_size: int | None = None, **kw: Any) -> Any:
    """Proxy to pipeline.run_assessment."""
    from data_quality_toolkit.application.workflow.pipeline import run_assessment as _impl

    return _impl(csv, sample_size=sample_size, **kw)


def run_assessment_chunked(csv: str, chunksize: int = 100_000, **kw: Any) -> Any:
    """Proxy to pipeline.run_assessment_chunked (lazy import for monkeypatching)."""
    from data_quality_toolkit.application.workflow.pipeline import run_assessment_chunked as _impl

    return _impl(csv, chunksize=chunksize, **kw)


def run_export_star(
    csv: str, *, output_dir: str | None = None, sample_size: int | None = None, **kw: Any
) -> Any:
    """Proxy to pipeline.run_export_star."""
    from data_quality_toolkit.application.workflow.pipeline import run_export_star as _impl

    return _impl(csv, output_dir=output_dir, sample_size=sample_size, **kw)


def run_plan(csv: str, sample_size: int | None = None, **kw: Any) -> dict[str, Any]:
    """Load CSV and return per-column preprocessing plan (lazy import for monkeypatching)."""
    from data_quality_toolkit.adapters.loaders.file.csv_loader import load_csv
    from data_quality_toolkit.application.workflow.preprocessing import plan_preprocessing

    df, meta = load_csv(csv, sample_size=sample_size, **kw)
    return {
        "dataset_id": meta["dataset_id"],
        "columns": plan_preprocessing(df),
    }


def run_drift(baseline: str, current: str, **kw: Any) -> dict[str, Any]:
    """Proxy to api.detect_drift (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import detect_drift

    return detect_drift(baseline, current, **kw)


def read_drift_history(history_path: str) -> list[dict[str, Any]]:
    """Proxy to api.read_drift_history (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import read_drift_history as _impl

    return _impl(history_path)


def import_drift_history_sqlite(db_path: str, history_path: str) -> int:
    """Proxy to api.import_drift_history_sqlite (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import import_drift_history_sqlite as _impl

    return _impl(db_path, history_path)


def ensure_drift_db(db_path: str) -> None:
    """Proxy to storage.schema.ensure_db (lazy import for monkeypatching)."""
    from data_quality_toolkit.adapters.storage.schema import ensure_db as _impl

    _impl(Path(db_path))


def summarize_drift_trends_sqlite(
    db_path: str,
    *,
    current_dataset_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Proxy to api.summarize_drift_trends_sqlite (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import summarize_drift_trends_sqlite as _impl

    return _impl(db_path, current_dataset_id=current_dataset_id, limit=limit)


def read_drift_runs_sqlite(
    db_path: str,
    *,
    limit: int | None = None,
    current_dataset_id: str | None = None,
    drift_detected: bool | int | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Proxy to api.read_drift_runs_sqlite (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import read_drift_runs_sqlite as _impl

    return _impl(
        db_path,
        limit=limit,
        current_dataset_id=current_dataset_id,
        drift_detected=drift_detected,
        status=status,
    )


def read_drift_columns_sqlite(
    db_path: str,
    *,
    run_id: str | None = None,
    column_name: str | None = None,
    drift_detected: bool | int | None = None,
    run_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Proxy to api.read_drift_columns_sqlite (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import read_drift_columns_sqlite as _impl

    return _impl(
        db_path,
        run_id=run_id,
        column_name=column_name,
        drift_detected=drift_detected,
        run_ids=run_ids,
    )


def read_drift_distributions_sqlite(
    db_path: str,
    *,
    run_id: str | None = None,
    column_name: str | None = None,
    run_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Proxy to api.read_drift_distributions_sqlite (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import read_drift_distributions_sqlite as _impl

    return _impl(
        db_path,
        run_id=run_id,
        column_name=column_name,
        run_ids=run_ids,
    )


def export_drift_history_xlsx(
    db_path: str,
    output_path: str,
    *,
    current_dataset_id: str | None = None,
    limit: int | None = None,
    include_columns: bool = True,
    include_distributions: bool = False,
    force: bool = False,
) -> DriftHistoryXlsxExportResult:
    """Proxy to api.export_drift_history_xlsx (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import export_drift_history_xlsx as _impl

    return _impl(
        db_path,
        output_path,
        current_dataset_id=current_dataset_id,
        limit=limit,
        include_columns=include_columns,
        include_distributions=include_distributions,
        force=force,
    )


def export_monitoring_duckdb(
    db_path: str,
    out_path: str,
    *,
    overwrite: bool = False,
) -> MonitoringDuckdbExportResult:
    """Proxy to api.export_monitoring_duckdb (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import export_monitoring_duckdb as _impl

    return _impl(db_path, out_path, overwrite=overwrite)


def export_drift_plots(
    db_path: str,
    out: str,
    *,
    chart: str = "all",
    current_dataset_id: str | None = None,
    limit: int | None = None,
    force: bool = False,
) -> DriftPlotsExportResult:
    """Proxy to api.export_drift_plots (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import export_drift_plots as _impl

    return _impl(
        db_path,
        out,
        chart=chart,
        current_dataset_id=current_dataset_id,
        limit=limit,
        force=force,
    )


def send_drift_notification(
    db_path: str,
    webhook_url: str,
    *,
    max_drift_rate: float | None = None,
    max_psi: float | None = None,
    dry_run: bool = True,
    send: bool = False,
    timeout: float = 10.0,
    allow_http: bool = False,
    allow_insecure_host: bool = False,
) -> DriftNotificationSendResult:
    """Proxy to api.send_drift_notification (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import send_drift_notification as _impl

    return _impl(
        db_path,
        webhook_url,
        max_drift_rate=max_drift_rate,
        max_psi=max_psi,
        dry_run=dry_run,
        send=send,
        timeout=timeout,
        allow_http=allow_http,
        allow_insecure_host=allow_insecure_host,
    )


def evaluate_drift_rate_threshold(
    summary: dict[str, Any],
    *,
    max_drift_rate: float,
) -> DriftRateThresholdResult:
    """Proxy to api.evaluate_drift_rate_threshold (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import evaluate_drift_rate_threshold as _impl

    return _impl(summary, max_drift_rate=max_drift_rate)


def evaluate_psi_threshold(
    columns: list[dict[str, Any]],
    *,
    max_psi: float,
) -> PsiThresholdResult:
    """Proxy to api.evaluate_psi_threshold (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import evaluate_psi_threshold as _impl

    return _impl(columns, max_psi=max_psi)


def stats_profile_csv(path: str, **kw: Any) -> dict[str, Any]:
    """Proxy to api.stats_profile_csv (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import stats_profile_csv as _impl

    return dict(_impl(path, **kw))


def select_statistical_test(
    variable_type: str,
    group_structure: str,
    **kw: Any,
) -> dict[str, Any]:
    """Proxy to api.select_statistical_test (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import select_statistical_test as _impl

    return dict(_impl(variable_type, group_structure, **kw))


def run_statistical_test(test_key: str, **kw: Any) -> dict[str, Any]:
    """Proxy to api.run_statistical_test (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import run_statistical_test as _impl

    return dict(_impl(test_key, **kw))


def compare_ab(*args: Any, **kw: Any) -> dict[str, Any]:
    """Proxy to api.compare_ab (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import compare_ab as _impl

    return dict(_impl(*args, **kw))


def kpi_validate_catalog(config_path: str) -> dict[str, Any]:
    """Proxy to application.workflow.kpi.validate_kpi_catalog (lazy import for monkeypatching)."""
    from data_quality_toolkit.application.workflow.kpi import validate_kpi_catalog

    return validate_kpi_catalog(config_path)


def kpi_emit_artifacts(config_path: str, dax_out: str, tmsl_out: str) -> dict[str, Any]:
    """Proxy to application.workflow.kpi.emit_kpi_artifacts (lazy import for monkeypatching)."""
    from data_quality_toolkit.application.workflow.kpi import emit_kpi_artifacts

    return emit_kpi_artifacts(config_path, dax_out, tmsl_out)


def kpi_export_graph(config_path: str, out: str, graph_format: str = "mermaid") -> dict[str, Any]:
    """Proxy to application.workflow.kpi.export_kpi_graph (lazy import for monkeypatching)."""
    from data_quality_toolkit.application.workflow.kpi import export_kpi_graph

    return export_kpi_graph(config_path, out, graph_format=graph_format)  # type: ignore[arg-type]


def get_builtin_quality_catalog() -> dict[str, Any]:
    """Proxy to api.get_builtin_quality_catalog (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import get_builtin_quality_catalog as _impl

    return dict(_impl())


def emit_builtin_quality_dax(output_path: str | None = None) -> dict[str, Any]:
    """Proxy to api.emit_builtin_quality_dax (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import emit_builtin_quality_dax as _impl

    return dict(_impl(output_path=output_path))


def validate_builtin_quality_semantic_contract(
    path: str, *, input_mode: str = "auto"
) -> dict[str, Any]:
    """Proxy to api.validate_builtin_quality_semantic_contract (lazy import for monkeypatching)."""
    from data_quality_toolkit.api import validate_builtin_quality_semantic_contract as _impl

    return dict(_impl(path, input_mode=input_mode))  # type: ignore[arg-type]


def manifest_create(run_id: str, sessions_root: str) -> Any:
    """Proxy to lineage manifest builder (lazy import for monkeypatching)."""
    from data_quality_toolkit.lineage.manifest.builder import build_manifest

    return build_manifest(run_id=run_id, sessions_root=sessions_root)


def _extract_null_threshold(args: argparse.Namespace) -> float | None:
    """Validate and return --null-threshold if provided; None otherwise."""
    nt = getattr(args, "null_threshold", None)
    if nt is None:
        return None
    if not (0.0 <= nt <= 1.0):
        raise ValueError(f"--null-threshold must be between 0.0 and 1.0, got {nt}")
    return float(nt)


def _extract_fail_under(args: argparse.Namespace) -> float | None:
    """Validate and return --fail-under if provided; None otherwise."""
    fu = getattr(args, "fail_under", None)
    if fu is None:
        return None
    if not (0.0 <= fu <= 1.0):
        raise ValueError(f"--fail-under must be between 0.0 and 1.0, got {fu}")
    return float(fu)


def _extract_drift_threshold(value: float | None, flag_name: str) -> float | None:
    """Validate and return a drift threshold float if provided; None otherwise."""
    if value is None:
        return None
    if not (0.0 <= value <= 1.0):
        raise ValueError(f"{flag_name} must be between 0.0 and 1.0, got {value}")
    return float(value)


def _apply_dqt_config(args: argparse.Namespace) -> None:
    """Fill unset CLI options from ./dqt.yaml. Explicit CLI args always win."""
    config = load_dqt_config()
    for key in ("null_threshold", "fail_under"):
        if hasattr(args, key) and getattr(args, key) is None and key in config:
            setattr(args, key, config[key])
    if hasattr(args, "outdir"):
        if args.outdir is None and "outdir" in config:
            args.outdir = config["outdir"]
        if args.outdir is None:
            args.outdir = DEFAULT_DIST


def _check_quality_gate(fu: float | None, out: dict, score_field: str = "score") -> int:
    """Return 2 with a stderr message if selected score < fu; 0 otherwise."""
    if fu is None:
        return 0
    assessment = out.get("assessment") or {}
    score = float(assessment.get(score_field, assessment.get("score", 1.0)))
    if score < fu:
        cross = _safe_text("✗", CROSS_FALLBACK)
        print(
            f"{cross} Quality gate FAILED: {score_field} {score:.2%} is below --fail-under {fu:.2%}",
            file=sys.stderr,
        )
        return 2
    return 0


def _safe_text(s: str, fallback: str) -> str:
    """Get console-safe text."""
    import sys

    enc = sys.stdout.encoding or "utf-8"
    try:
        s.encode(enc, "strict")
        return s
    except Exception:
        return fallback


# Command modules live under ``adapters/cli/commands`` and reach back into this
# module (``import ...cli.main as _m``) to resolve the monkeypatchable proxies and
# shared helpers above. When this module is launched via
# ``python -m data_quality_toolkit.adapters.cli.main`` it runs as ``__main__`` and
# is NOT registered under its real dotted name, so register an alias first to
# avoid a re-import cycle when the command modules import this module.
if __name__ == "__main__":  # pragma: no cover
    sys.modules.setdefault("data_quality_toolkit.adapters.cli.main", sys.modules[__name__])

# Imported via importlib (not ``import`` statements) so they can sit below the
# proxy/helper definitions without tripping E402 / import-sorting.
_meta = importlib.import_module("data_quality_toolkit.adapters.cli.commands.meta")
_pipeline = importlib.import_module("data_quality_toolkit.adapters.cli.commands.pipeline")
_profile = importlib.import_module("data_quality_toolkit.adapters.cli.commands.profile")
_assess = importlib.import_module("data_quality_toolkit.adapters.cli.commands.assess")
_export = importlib.import_module("data_quality_toolkit.adapters.cli.commands.export")
_powerbi = importlib.import_module("data_quality_toolkit.adapters.cli.commands.powerbi")
_kpi = importlib.import_module("data_quality_toolkit.adapters.cli.commands.kpi")
_kpi_builtin = importlib.import_module("data_quality_toolkit.adapters.cli.commands.kpi_builtin")
_compare = importlib.import_module("data_quality_toolkit.adapters.cli.commands.compare")
_drift = importlib.import_module("data_quality_toolkit.adapters.cli.commands.drift")
_drift_history = importlib.import_module("data_quality_toolkit.adapters.cli.commands.drift_history")
_plan = importlib.import_module("data_quality_toolkit.adapters.cli.commands.plan")
_chart = importlib.import_module("data_quality_toolkit.adapters.cli.commands.chart")
_dashboard = importlib.import_module("data_quality_toolkit.adapters.cli.commands.dashboard")
_ui = importlib.import_module("data_quality_toolkit.adapters.cli.commands.ui")
_stats = importlib.import_module("data_quality_toolkit.adapters.cli.commands.stats")
_CORE_COMMAND_MODULES = frozenset(
    module.__name__
    for module in (
        _meta,
        _pipeline,
        _profile,
        _assess,
        _export,
        _powerbi,
        _kpi,
        _kpi_builtin,
        _compare,
        _drift,
        _drift_history,
        _plan,
        _chart,
        _dashboard,
        _ui,
        _stats,
    )
)


def _discover_command_extensions() -> tuple[ModuleType, ...]:
    """Import the optional command extensions shipped in the ``commands`` package.

    Any module there beyond the core set above that exposes
    ``register(subparsers)`` is an extension; a distribution may ship none. They
    are found by listing the package, so an extension that is present is imported
    normally and a failure inside it propagates instead of reading as absence.
    """
    package = importlib.import_module("data_quality_toolkit.adapters.cli.commands")
    extensions = []
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda found: found.name):
        name = f"{package.__name__}.{info.name}"
        if info.ispkg or name in _CORE_COMMAND_MODULES:
            continue
        module = importlib.import_module(name)
        if callable(getattr(module, "register", None)):
            extensions.append(module)
    return tuple(extensions)


_extensions = _discover_command_extensions()

# Re-export handlers so ``cli.main.cmd_*`` identity is preserved (tests assert
# ``ns.func is cli.cmd_X`` and call ``cli.cmd_X(...)`` directly).
cmd_settings_show = _meta.cmd_settings_show
cmd_version = _meta.cmd_version
cmd_log_demo = _meta.cmd_log_demo
cmd_manifest_create = _meta.cmd_manifest_create
cmd_pipeline_run = _pipeline.cmd_pipeline_run
cmd_profile = _profile.cmd_profile
cmd_assess = _assess.cmd_assess
cmd_export_star = _export.cmd_export_star
cmd_build_pbi = _powerbi.cmd_build_pbi
cmd_gen_dim_time = _powerbi.cmd_gen_dim_time
cmd_kpi_emit = _kpi.cmd_kpi_emit
cmd_kpi_graph = _kpi.cmd_kpi_graph
cmd_kpi_validate = _kpi.cmd_kpi_validate
cmd_kpi_builtin_catalog = _kpi_builtin.cmd_kpi_builtin_catalog
cmd_kpi_builtin_emit_dax = _kpi_builtin.cmd_kpi_builtin_emit_dax
cmd_kpi_builtin_validate_contract = _kpi_builtin.cmd_kpi_builtin_validate_contract
cmd_compare = _compare.cmd_compare
cmd_drift = _drift.cmd_drift
cmd_drift_history = _drift_history.cmd_drift_history
cmd_drift_history_import = _drift_history.cmd_drift_history_import
cmd_drift_history_list = _drift_history.cmd_drift_history_list
cmd_drift_history_columns = _drift_history.cmd_drift_history_columns
cmd_drift_history_trend = _drift_history.cmd_drift_history_trend
cmd_drift_history_report = _drift_history.cmd_drift_history_report
cmd_drift_history_notify = _drift_history.cmd_drift_history_notify
cmd_drift_dashboard = _drift_history.cmd_drift_dashboard
cmd_plan = _plan.cmd_plan
cmd_chart = _chart.cmd_chart
cmd_dashboard = _dashboard.cmd_dashboard
cmd_ui = _ui.cmd_ui
cmd_stats_profile = _stats.cmd_stats_profile
cmd_stats_select_test = _stats.cmd_stats_select_test
cmd_stats_test = _stats.cmd_stats_test
cmd_stats_ab = _stats.cmd_stats_ab
# Extension handlers are re-exported the same way, never shadowing a core name.
for _extension in _extensions:
    for _handler_name in dir(_extension):
        if _handler_name.startswith("cmd_"):
            globals().setdefault(_handler_name, getattr(_extension, _handler_name))


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser.

    Subcommands are registered by each command module's ``register*`` function,
    in the original order so ``dqt --help`` listing is unchanged.
    """
    p = _DQTArgumentParser(prog="dqt", description="Data Quality Toolkit CLI")
    p.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    p.add_argument("--log-format", choices=["json", "text"])
    p.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress INFO/DEBUG log lines (sets log level to WARNING unless --log-level is provided)",
    )
    p.add_argument(
        "--no-json",
        dest="no_json",
        action="store_true",
        default=False,
        help="Suppress machine JSON on stdout (human summaries on stderr are unaffected)",
    )
    p.add_argument(
        "--json-errors",
        dest="json_errors",
        action="store_true",
        default=False,
        help="Emit error information as JSON to stderr instead of human-readable text",
    )
    sub = p.add_subparsers(dest="command", required=True)

    _meta.register_settings(sub)
    _meta.register_manifest(sub)
    _pipeline.register(sub)
    _meta.register_version(sub)
    _meta.register_log_demo(sub)
    _profile.register(sub)
    _assess.register(sub)
    _export.register(sub)
    _export.register_alias(sub)
    _powerbi.register_build_pbi(sub)
    _powerbi.register_gen_dim_time(sub)
    _kpi.register_kpi_emit(sub)
    _kpi.register_kpi_graph(sub)
    _compare.register(sub)
    _drift.register(sub)
    _drift_history.register(sub)
    _kpi.register_kpi_validate(sub)
    _plan.register(sub)
    _chart.register(sub)
    _dashboard.register(sub)
    _stats.register(sub)
    _ui.register(sub)
    _kpi_builtin.register_kpi_builtin(sub)
    for extension in _extensions:
        extension.register(sub)

    return p


_SUPPORTED_CSV_EXTENSIONS: frozenset[str] = frozenset({".csv"})


def _redact_cli_paths(text: object) -> str:
    """Redact absolute paths in human-facing CLI error text.

    Basename-preserving: an absolute path becomes ``<path:basename>``; a bare
    root or otherwise unparseable path becomes ``<path>``. Applied only to the
    human (text) error surface — the ``--json-errors`` programmatic output and
    the shared error contract keep raw paths.
    """
    return redact_paths(text, keep=lambda leaf: f"<path:{leaf}>", drop="<path>")


def _print_error_info(info: ErrorInfo, *, json_errors: bool = False) -> None:
    """Print structured ErrorInfo to stderr."""
    if json_errors:
        sys.stderr.write(_json_dump({"error": info}) + "\n")
        return
    print(f"Error: {_redact_cli_paths(info['message'])}", file=sys.stderr)
    if hint := info.get("hint"):
        lines = hint.splitlines()
        print(f"  Hint: {lines[0]}", file=sys.stderr)
        for line in lines[1:]:
            print(f"  {line}", file=sys.stderr)
    if detail := (info.get("metadata") or {}).get("detail"):
        print(_redact_cli_paths(detail), file=sys.stderr)


def _invalid_dir_target_error_info(exc: OSError) -> ErrorInfo:
    """Describe an expected "this path cannot be a directory" operator error.

    ``FileExistsError`` (the given path is itself an existing file) and
    ``NotADirectoryError`` (a component of it is) are ordinary operator-input
    conditions for a directory option such as ``--outdir`` or ``--sessions-root``,
    not internal failures. The raw path stays in the ErrorInfo, as the shared
    error contract does; :func:`_print_error_info` redacts the human surface.
    """
    target = exc.filename or exc.filename2 or ""
    located = f" '{target}'" if target else ""
    if isinstance(exc, NotADirectoryError):
        message = f"cannot create directory{located}: a component of the path is an existing file."
    else:
        message = f"cannot use{located} as a directory: a file already exists at that path."
    info: ErrorInfo = {
        "code": "INVALID_DIR_TARGET",
        "message": message,
        "exc_type": type(exc).__name__,
        "hint": "pass a directory path, or remove or rename the conflicting file.",
    }
    return info


def _print_csv_hint(args: Any) -> None:
    """Print a CSV-specific hint to stderr when the failing command takes a csv arg."""
    if getattr(args, "csv", None) is not None:
        print("  Hint: check that the file is a valid, non-empty CSV.", file=sys.stderr)
        print("  Example: dqt profile data/my_file.csv", file=sys.stderr)


# Positional path attributes subject to CSV path/extension validation
_CSV_PATH_ATTRS: tuple[str, ...] = ("csv", "baseline", "current")


def _validate_csv_path(args: Any) -> str | None:
    """Return an error message if any CSV positional arg is blank, else None."""
    for attr in _CSV_PATH_ATTRS:
        csv_path = getattr(args, attr, None)
        if csv_path is not None and not str(csv_path).strip():
            return "File path must not be blank or whitespace-only."
    return None


def _validate_csv_extension(args: Any) -> str | None:
    """Return an error message if any CSV positional arg has an unsupported extension."""
    for attr in _CSV_PATH_ATTRS:
        csv_path = getattr(args, attr, None)
        if csv_path is None:
            continue
        stripped = str(csv_path).strip()
        if not stripped:
            continue  # already caught by _validate_csv_path
        suffix = Path(stripped).suffix.lower()
        if suffix not in _SUPPORTED_CSV_EXTENSIONS:
            supported = ", ".join(sorted(_SUPPORTED_CSV_EXTENSIONS))
            return (
                f"Unsupported file extension '{suffix or '(none)'}'. Expected one of: {supported}"
            )
    return None


def _validate_csv_encoding(args: Any) -> str | None:
    """Return an error message if ``--encoding`` is not a text encoding name, else None.

    The CSV readers resolve the name through Python's codec registry, which raises a
    raw ``LookupError`` for an unknown name or a non-text codec such as ``base64``.
    Resolving it here first reports that as operator input before any file is read,
    and never substitutes another encoding. Only the lookup failure is handled; the
    supplied value is not shown.
    """
    encoding = getattr(args, "encoding", None)
    if encoding is None:
        return None
    try:
        is_text = codecs.lookup(encoding)._is_text_encoding
    except LookupError:
        is_text = False
    if is_text:
        return None
    return (
        "Unsupported --encoding: not a known text encoding (the supplied value is not shown)."
        " Use a standard encoding name such as 'utf-8' or 'latin-1'."
    )


def _handle_value_error(e: ValueError, args: Any, *, json_errors: bool = False) -> int:
    """Handle ValueError from pipeline, with a specific branch for ParserError."""
    if json_errors:
        if type(e).__name__ == "ParserError":
            info: ErrorInfo = {
                "code": "VALUE_ERROR",
                "message": f"CSV could not be parsed: {e}",
                "exc_type": type(e).__name__,
                "hint": (
                    "check that all rows have the same number of columns"
                    " and the correct delimiter (try --sep)."
                ),
            }
        else:
            info = to_error_info(e)
        sys.stderr.write(_json_dump({"error": info}) + "\n")
        return 1
    # pd.errors.ParserError is a ValueError subclass — give a targeted message
    if type(e).__name__ == "ParserError":
        print(f"Error: CSV could not be parsed: {_redact_cli_paths(str(e))}", file=sys.stderr)
        print(
            "  Hint: check that all rows have the same number of columns"
            " and the correct delimiter (try --sep).",
            file=sys.stderr,
        )
        return 1
    info = to_error_info(e)
    print(f"Error: {_redact_cli_paths(info['message'])}", file=sys.stderr)
    _print_csv_hint(args)
    return 1


def _resolve_log_level(args: argparse.Namespace) -> str | None:
    if getattr(args, "quiet", False) and args.log_level is None:
        return "WARNING"
    log_level: str | None = args.log_level
    return log_level


def _apply_log_level_override(args: argparse.Namespace) -> None:
    if args.log_level in ("ERROR", "CRITICAL"):
        for name, logger_obj in logging.root.manager.loggerDict.items():
            if isinstance(logger_obj, logging.PlaceHolder):
                continue
            if not name.startswith("data_quality_toolkit"):
                logging.getLogger(name).setLevel(logging.ERROR)


def _invalid_settings_exit() -> int | None:
    """Return 2 after reporting invalid environment-backed settings, else ``None``.

    Settings come from the process environment (and an opted-in ``.env``), which
    the operator controls, so a rejected value is operator input: it is reported
    like an invalid ``dqt.yaml`` -- a bounded ``Error:`` line and exit 2 -- rather
    than escaping as a traceback. Only the settings validation failure is handled;
    the supplied value is never printed.
    """
    try:
        load_settings()
    except SettingsValidationError as e:
        print(f"Error: invalid DQT configuration: {describe_invalid_settings(e)}.", file=sys.stderr)
        print(
            "  Hint: correct the environment variable (or the .env entry when"
            " DQT_LOAD_ENV is enabled); the supplied value is not shown.",
            file=sys.stderr,
        )
        return 2
    return None


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    settings_exit = _invalid_settings_exit()
    if settings_exit is not None:
        return settings_exit

    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging(level=_resolve_log_level(args), fmt=args.log_format)

    try:
        _apply_dqt_config(args)
    except ConfigError as e:
        print(f"Error: {_redact_cli_paths(str(e))}", file=sys.stderr)
        return 2

    path_error = (
        _validate_csv_path(args) or _validate_csv_extension(args) or _validate_csv_encoding(args)
    )
    if path_error is not None:
        print(f"Error: {path_error}", file=sys.stderr)
        return 2

    _apply_log_level_override(args)

    try:
        handler: Callable[[argparse.Namespace], int] = cast(
            Callable[[argparse.Namespace], int], args.func
        )
        return handler(args)
    except FileNotFoundError as e:
        _print_error_info(to_error_info(e), json_errors=getattr(args, "json_errors", False))
        return 2
    except PermissionError as e:
        _print_error_info(to_error_info(e), json_errors=getattr(args, "json_errors", False))
        return 13
    except (FileExistsError, NotADirectoryError) as e:
        _print_error_info(
            _invalid_dir_target_error_info(e), json_errors=getattr(args, "json_errors", False)
        )
        return 2
    except UnicodeDecodeError as e:
        _print_error_info(to_error_info(e), json_errors=getattr(args, "json_errors", False))
        return 22
    except ValueError as e:
        code = _handle_value_error(e, args, json_errors=getattr(args, "json_errors", False))
        return code


if __name__ == "__main__":
    sys.exit(main())
