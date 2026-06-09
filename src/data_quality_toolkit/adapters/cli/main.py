# src/data_quality_toolkit/adapters/cli/main.py
"""CLI implementation."""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NoReturn, cast

from data_quality_toolkit.shared.config import load_dqt_config
from data_quality_toolkit.shared.constants import VERSION
from data_quality_toolkit.shared.exceptions import ConfigError
from data_quality_toolkit.shared.settings import load_settings
from data_quality_toolkit.utils.logging import setup_logging

# ----- Constants to de-duplicate literals (Sonar S1192) -----
CSV_PATH_HELP = "Path to CSV file"
DEFAULT_DIST = "./dist"
CROSS_FALLBACK = "[FAIL]"
FAIL_UNDER_HELP = "Exit 2 if quality score is below this threshold (0.0 to 1.0)"
SCORE_FIELD_CHOICES = ("score", "completeness_score", "quality_score")
SCORE_FIELD_DEFAULT = "score"
# ----- Phase 3 (KPI) constants -----
KPI_DEFAULT_CONFIG = "config/kpi_catalog.yaml"
KPI_CONFIG_HELP = "Path to KPI catalog YAML"

KPI_DEFAULT_DAX_OUT = "dist/powerbi_package/dax/quality_measures.dax"
KPI_DAX_OUT_HELP = "Output path for DAX measures"

KPI_DEFAULT_TMSL_OUT = "dist/powerbi_package/dax/model.tmsl.json"
KPI_TMSL_OUT_HELP = "Output path for TMSL"

KPI_DEFAULT_GRAPH_OUT = "dist/semantics/kpi_graph.mmd"
KPI_GRAPH_OUT_HELP = "Output path for graph file (.mmd or .dot)"

KPI_GRAPH_FORMAT_DEFAULT = "mermaid"
KPI_GRAPH_FORMAT_CHOICES = ["mermaid", "graphviz"]
KPI_GRAPH_FORMAT_HELP = "Graph format"


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


# ------------------------------------------------------------------------------


def cmd_settings_show(_: argparse.Namespace) -> int:
    """Show current settings."""
    s = load_settings()
    print(_json_dump(s))
    return 0


def cmd_version(_: argparse.Namespace) -> int:
    """Print version."""
    print(VERSION)
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
    manifest = manifest_create(args.run_id, args.sessions_root)
    tick = _safe_text("✓", "[OK]")
    print(f"{tick} Manifest created  [run_id={args.run_id}]", file=sys.stderr)
    if not getattr(args, "no_json", False):
        print(_json_dump(manifest))
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    """Profile a CSV file."""
    chunksize: int | None = getattr(args, "chunksize", None)
    if chunksize is not None:
        out = run_profile_chunked(args.csv, chunksize=chunksize, **_csv_kwargs_from_args(args))
    else:
        out = run_profile(
            args.csv, sample_size=_get_sample_size(args), **_csv_kwargs_from_args(args)
        )

    # Human-friendly summary -> stderr (stdout stays pure JSON)
    tick = _safe_text("✓", "[OK]")
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
        print(_json_dump(out))
    return 0


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
        return run_assessment_chunked(args.csv, chunksize=chunksize, **chunked_kw, **csv_kw)
    sample_size = _get_sample_size(args)
    db_path = Path(args.db) if getattr(args, "db", None) else None
    if nt is not None:
        return run_assessment(
            args.csv, null_threshold=nt, db_path=db_path, sample_size=sample_size, **csv_kw
        )
    return run_assessment(args.csv, db_path=db_path, sample_size=sample_size, **csv_kw)


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
    nt = _extract_null_threshold(args)
    fu = _extract_fail_under(args)
    chunksize: int | None = getattr(args, "chunksize", None)
    score_field = getattr(args, "score_field", SCORE_FIELD_DEFAULT) or SCORE_FIELD_DEFAULT
    csv_kw = _csv_kwargs_from_args(args)
    out = _dispatch_assessment(args, nt, chunksize, csv_kw)

    # Human-friendly summary -> stderr (stdout stays pure JSON)
    tick = _safe_text("✓", "[OK]")
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
        print(_json_dump(out))
    return _check_quality_gate(fu, out, score_field=score_field)


def _safe_text(s: str, fallback: str) -> str:
    """Get console-safe text."""
    import sys

    enc = sys.stdout.encoding or "utf-8"
    try:
        s.encode(enc, "strict")
        return s
    except Exception:
        return fallback


def cmd_gen_dim_time(args: argparse.Namespace) -> int:
    """Generate dim_time.csv."""
    from pathlib import Path

    from data_quality_toolkit.adapters.exporters.time.dim_time_generator import write_dim_time

    try:
        path = write_dim_time(
            output_dir=Path(args.out),
            start_date=args.start,
            end_date=args.end,
            week_start=args.week_start,
            fiscal_year_start=args.fiscal,
        )
        if args.json:
            payload = {
                "status": "success",
                "dim_time_path": str(path),
                "start": args.start,
                "end": args.end,
                "week_start": args.week_start,
                "fiscal": args.fiscal,
            }
            print(_json_dump(payload))
        else:
            print(f"Generated: {path}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_build_pbi(args: argparse.Namespace) -> int:
    """Build Phase 2 Power BI package (zero-config orchestrator)."""
    from data_quality_toolkit.adapters.exporters.bi.powerbi_exporter import export_powerbi_package

    tick = _safe_text("✓", "[OK]")
    try:
        print("Building Power BI package...", file=sys.stderr)
        result = export_powerbi_package(
            star_dir=args.star,
            output_dir=args.out,
            time_start=args.time_start,
            time_end=args.time_end,
            base_folder=args.base_folder,
            fiscal_year_start=args.fiscal,
        )

        # Human-friendly summary → STDERR
        print(f"{tick} Package: {result['package_dir']}", file=sys.stderr)
        print(f"  - Files: {len(result.get('files', {}))}", file=sys.stderr)
        print(f"  - Time range: {result.get('time_range')}", file=sys.stderr)
        print(f"  - Base folder: {result.get('base_folder')}", file=sys.stderr)

        # Treat validation as generic mapping to avoid TypedDict optional-key warnings
        val: Mapping[str, Any] = cast(Mapping[str, Any], result["validation"])
        warnings: list[str] = cast(list[str], val.get("warnings", []))
        for w in warnings:
            print(f"  ⚠ {w}", file=sys.stderr)

        # Machine-friendly JSON → STDOUT
        print(_json_dump(result))
        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


# --- Phase 3: KPI CLI commands (argparse) -------------------------------------


def cmd_kpi_emit(args: argparse.Namespace) -> int:
    """Generate DAX measures and TMSL from KPI catalog."""
    tick = _safe_text("✓", "[OK]")
    try:
        print(f"Loading KPI catalog from {args.config}...", file=sys.stderr)
        result = kpi_emit_artifacts(args.config, args.dax_out, args.tmsl_out)

        print(f"{tick} Loaded {result.get('kpis', 0)} KPIs", file=sys.stderr)
        print(f"{tick} Generated DAX: {result.get('dax')}", file=sys.stderr)
        print(f"{tick} Generated TMSL: {result.get('tmsl')}", file=sys.stderr)

        print(_json_dump(result))
        return 0

    except Exception as e:
        LOGGER.exception("KPI emission failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_kpi_graph(args: argparse.Namespace) -> int:
    """Export KPI dependency graph (Mermaid or Graphviz)."""
    tick = _safe_text("✓", "[OK]")
    try:
        print(f"Loading KPI catalog from {args.config}...", file=sys.stderr)
        fmt = (args.format or KPI_GRAPH_FORMAT_DEFAULT).lower()
        result = kpi_export_graph(args.config, args.out, fmt)

        graph_path = result.get("graph", "")
        nodes = result.get("nodes", 0)
        print(f"{tick} Generated {fmt} graph: {graph_path}", file=sys.stderr)

        # Preview for small catalogs (first 20 lines)
        if nodes <= 10 and graph_path:
            print("\nGraph preview:", file=sys.stderr)
            text = Path(graph_path).read_text(encoding="utf-8")
            lines = text.splitlines()
            preview = lines[:20]
            for line in preview:
                print(line, file=sys.stderr)
            if len(lines) > 20:
                print("...", file=sys.stderr)

        print(_json_dump(result))
        return 0

    except Exception as e:
        LOGGER.exception("Graph generation failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_kpi_validate(args: argparse.Namespace) -> int:
    """Validate KPI catalog (schema, semantics, cycles)."""
    try:
        print(f"Validating KPI catalog: {args.config}", file=sys.stderr)
        result = kpi_validate_catalog(args.config)
        kpi_count = result.get("kpis", 0)
        print(f"✓ Loaded {kpi_count} KPIs", file=sys.stderr)

        if result.get("status") == "invalid":
            print("✗ Dependency cycles detected:", file=sys.stderr)
            for cycle_path in result.get("cycles", []):
                print(f"  - {' -> '.join(str(c) for c in cycle_path)}", file=sys.stderr)
            output = {k: v for k, v in result.items() if k != "by_grain"}
            print(_json_dump(output))
            return 1

        print("✓ Semantic validation passed", file=sys.stderr)
        print("\nCatalog Summary:", file=sys.stderr)
        for grain, count in (result.get("by_grain") or {}).items():
            print(f"  {grain}: {count} KPIs", file=sys.stderr)
        print(f"  Total dependencies: {result.get('dependencies', 0)}", file=sys.stderr)

        output = {k: v for k, v in result.items() if k != "by_grain"}
        print(_json_dump(output))
        return 0

    except Exception as e:
        LOGGER.exception("Validation failed")
        print(f"Error: {e}", file=sys.stderr)
        return 1


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
        cross = _safe_text("✗", CROSS_FALLBACK)
        print(
            f"{cross} Compare: not enough history for '{Path(args.csv).name}'",
            file=sys.stderr,
        )
        print(f"  {result['message']}", file=sys.stderr)
        if not getattr(args, "no_json", False):
            print(_json_dump(result))
        return 1

    # Human-friendly stderr summary
    tick = _safe_text("✓", "[OK]")
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
        print(_json_dump(result))
    return 0


def cmd_export_star(args: argparse.Namespace) -> int:
    """Export star schema."""
    nt = _extract_null_threshold(args)
    fu = _extract_fail_under(args)
    score_field = getattr(args, "score_field", SCORE_FIELD_DEFAULT) or SCORE_FIELD_DEFAULT
    sample_size = _get_sample_size(args)
    csv_kw = _csv_kwargs_from_args(args)
    if nt is not None:
        out = run_export_star(
            args.csv, output_dir=args.outdir, null_threshold=nt, sample_size=sample_size, **csv_kw
        )
    else:
        out = run_export_star(args.csv, output_dir=args.outdir, sample_size=sample_size, **csv_kw)

    # Friendly summary -> STDERR (so STDOUT stays pure JSON)
    tick = _safe_text("✓", "[OK]")
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
        print(_json_dump(out))
    return _check_quality_gate(fu, out, score_field=score_field)


def _add_csv_options(parser: argparse.ArgumentParser) -> None:
    """Add CSV-related options to parser."""
    parser.add_argument("--sep", help="CSV delimiter (e.g., ',' or '\\t')")
    parser.add_argument("--encoding", help="CSV encoding (e.g., 'utf-8', 'latin-1')")
    parser.add_argument("--no-header", action="store_true", help="Treat CSV as having no header")
    parser.add_argument("--na-values", help="Comma-separated NA values (e.g., 'NA,NaN,null')")
    parser.add_argument("--sample-size", type=int, help="Override SAMPLE_SIZE for this run")


class _DQTArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that adds actionable hints for common missing-input errors."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        if "required" in message and "csv" in message:
            print(
                "  Hint: provide the path to a CSV file as the first positional argument.",
                file=sys.stderr,
            )
            print("  Example: dqt profile data/my_file.csv", file=sys.stderr)
        sys.exit(2)


def cmd_plan(args: argparse.Namespace) -> int:
    """Generate per-column preprocessing recommendations for a CSV."""
    out = run_plan(args.csv, sample_size=_get_sample_size(args), **_csv_kwargs_from_args(args))

    tick = _safe_text("✓", "[OK]")
    columns = out.get("columns") or []
    cols_total = len(columns)
    cols_with_issues = sum(1 for c in columns if c.get("issues") != "none")
    print(f"{tick} Plan complete", file=sys.stderr)
    print(f"  - Columns: {cols_total}", file=sys.stderr)
    print(f"  - Columns with issues: {cols_with_issues}", file=sys.stderr)

    if not getattr(args, "no_json", False):
        print(_json_dump(out))
    return 0


def cmd_chart(args: argparse.Namespace) -> int:
    """Generate a terminal-based profiling chart for a column."""
    from data_quality_toolkit.adapters.cli.charts import render_univariate_chart
    from data_quality_toolkit.adapters.loaders.file.csv_loader import load_csv
    from data_quality_toolkit.domain.profiling.charts import compute_univariate_chart_data

    try:
        df, meta = load_csv(
            args.csv, sample_size=_get_sample_size(args), **_csv_kwargs_from_args(args)
        )
        chart_data = compute_univariate_chart_data(df, args.column)

        # We don't use tick/[OK] here because the chart is the main output
        render_univariate_chart(chart_data)

        if not getattr(args, "no_json", False):
            # Also emit JSON to stdout if requested
            print(_json_dump(chart_data))
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_dashboard(args: argparse.Namespace) -> int:
    try:
        import streamlit  # noqa: F401
    except ImportError:
        print(
            "Error: Streamlit is not installed.\n"
            "  Install it with: pip install data-quality-toolkit[ui]",
            file=sys.stderr,
        )
        return 1
    import data_quality_toolkit.adapters.ui.app as _app_mod

    app_file = inspect.getfile(_app_mod)
    try:
        result = subprocess.run([sys.executable, "-m", "streamlit", "run", app_file])  # noqa: S603
        return result.returncode
    except KeyboardInterrupt:
        return 130


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser."""
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
    sub = p.add_subparsers(dest="command", required=True)

    # settings
    sp = sub.add_parser("settings", help="Settings commands")
    ssp = sp.add_subparsers(dest="subcommand", required=True)
    ssp_show = ssp.add_parser("show", help="Show resolved settings")
    ssp_show.set_defaults(func=cmd_settings_show)

    # manifest
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

    # version
    sp_ver = sub.add_parser("version", help="Print package version")
    sp_ver.set_defaults(func=cmd_version)

    # log demo
    sp_log = sub.add_parser("log-demo", help="Emit sample log lines")
    sp_log.add_argument("--raise-error", action="store_true")
    sp_log.set_defaults(func=cmd_log_demo)

    # profile
    sp_prof = sub.add_parser("profile", help="Load CSV and emit profile JSON")
    sp_prof.add_argument("csv", help=CSV_PATH_HELP)
    _add_csv_options(sp_prof)
    sp_prof.add_argument(
        "--chunksize",
        type=int,
        default=None,
        metavar="N",
        help="Stream CSV in chunks of N rows (approximate profile; skips dtype/unique/memory_mb)",
    )
    sp_prof.set_defaults(func=cmd_profile)

    # assess
    sp_as = sub.add_parser("assess", help="Load CSV, profile, and assess JSON")
    sp_as.add_argument("csv", help=CSV_PATH_HELP)
    _add_csv_options(sp_as)
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

    # export-star
    sp_star = sub.add_parser("export-star", help="Export star schema CSVs to a folder")
    sp_star.add_argument("csv", help=CSV_PATH_HELP)
    sp_star.add_argument(
        "--outdir", default=None, help=f"Output directory (default: {DEFAULT_DIST})"
    )
    _add_csv_options(sp_star)
    sp_star.add_argument(
        "--null-threshold",
        dest="null_threshold",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Flag completeness issues above this missing-value fraction (0.0 to 1.0, default: 0.2)",
    )
    sp_star.add_argument(
        "--fail-under",
        dest="fail_under",
        type=float,
        default=None,
        metavar="FLOAT",
        help=FAIL_UNDER_HELP,
    )
    sp_star.add_argument(
        "--score-field",
        dest="score_field",
        choices=SCORE_FIELD_CHOICES,
        default=SCORE_FIELD_DEFAULT,
        metavar="FIELD",
        help="Score field used by --fail-under quality gate (default: score)",
    )
    sp_star.set_defaults(func=cmd_export_star)

    # alias: export
    sp_export = sub.add_parser("export", help="Alias for export-star")
    sp_export.add_argument("csv", help=CSV_PATH_HELP)
    sp_export.add_argument(
        "--outdir", default=None, help=f"Output directory (default: {DEFAULT_DIST})"
    )
    _add_csv_options(sp_export)
    sp_export.add_argument(
        "--null-threshold",
        dest="null_threshold",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Flag completeness issues above this missing-value fraction (0.0 to 1.0, default: 0.2)",
    )
    sp_export.add_argument(
        "--fail-under",
        dest="fail_under",
        type=float,
        default=None,
        metavar="FLOAT",
        help=FAIL_UNDER_HELP,
    )
    sp_export.add_argument(
        "--score-field",
        dest="score_field",
        choices=SCORE_FIELD_CHOICES,
        default=SCORE_FIELD_DEFAULT,
        metavar="FIELD",
        help="Score field used by --fail-under quality gate (default: score)",
    )
    sp_export.set_defaults(func=cmd_export_star)

    # build-pbi (Phase 2 orchestrator)
    sp_pbi = sub.add_parser("build-pbi", help="Build Power BI package (Phase 2)")
    sp_pbi.add_argument("--star", default=f"{DEFAULT_DIST}/star", help="Star schema directory")
    sp_pbi.add_argument("--out", default=f"{DEFAULT_DIST}/powerbi_package", help="Output directory")
    sp_pbi.add_argument(
        "--time-start", default="2018-01-01", help="Time dimension start (YYYY-MM-DD)"
    )
    sp_pbi.add_argument("--time-end", default="2030-12-31", help="Time dimension end (YYYY-MM-DD)")
    sp_pbi.add_argument(
        "--base-folder", default=DEFAULT_DIST, help="Base folder parameter for Power BI"
    )
    sp_pbi.add_argument("--fiscal", type=int, default=None, help="Fiscal year start month (1-12)")
    sp_pbi.set_defaults(func=cmd_build_pbi)

    # gen-dim-time
    sp_time = sub.add_parser("gen-dim-time", help="Generate dim_time.csv")
    sp_time.add_argument("--start", default="2018-01-01", help="Start date (YYYY-MM-DD)")
    sp_time.add_argument("--end", default="2030-12-31", help="End date (YYYY-MM-DD)")
    sp_time.add_argument(
        "--week-start",
        type=int,
        default=1,
        choices=[1, 2, 3, 4, 5, 6, 7],
        help="Custom week start (1=Mon .. 7=Sun)",
    )
    sp_time.add_argument("--fiscal", type=int, default=None, help="Fiscal year start month (1-12)")
    sp_time.add_argument("--out", default=f"{DEFAULT_DIST}/time", help="Output directory")
    sp_time.add_argument("--json", action="store_true", help="Emit JSON on stdout (path & args)")
    sp_time.set_defaults(func=cmd_gen_dim_time)

    # kpi-emit
    sp_kpi_emit = sub.add_parser("kpi-emit", help="Generate DAX and TMSL from KPI catalog")
    sp_kpi_emit.add_argument(
        "--config",
        default=KPI_DEFAULT_CONFIG,
        help=KPI_CONFIG_HELP,
    )
    sp_kpi_emit.add_argument(
        "--dax-out",
        dest="dax_out",
        default=KPI_DEFAULT_DAX_OUT,
        help=KPI_DAX_OUT_HELP,
    )
    sp_kpi_emit.add_argument(
        "--tmsl-out",
        dest="tmsl_out",
        default=KPI_DEFAULT_TMSL_OUT,
        help=KPI_TMSL_OUT_HELP,
    )
    sp_kpi_emit.set_defaults(func=cmd_kpi_emit)

    # kpi-graph
    sp_kpi_graph = sub.add_parser("kpi-graph", help="Export KPI dependency graph")
    sp_kpi_graph.add_argument("--config", default=KPI_DEFAULT_CONFIG, help=KPI_CONFIG_HELP)
    sp_kpi_graph.add_argument("--out", default=KPI_DEFAULT_GRAPH_OUT, help=KPI_GRAPH_OUT_HELP)
    sp_kpi_graph.add_argument(
        "--format",
        default=KPI_GRAPH_FORMAT_DEFAULT,
        choices=KPI_GRAPH_FORMAT_CHOICES,
        help=KPI_GRAPH_FORMAT_HELP,
    )
    sp_kpi_graph.set_defaults(func=cmd_kpi_graph)

    # compare
    sp_cmp = sub.add_parser("compare", help="Compare last two export runs for a dataset")
    sp_cmp.add_argument("csv", help=CSV_PATH_HELP)
    sp_cmp.add_argument(
        "--outdir",
        default=None,
        help=f"Output directory (default: {DEFAULT_DIST}); must match the --outdir used with export-star",
    )
    sp_cmp.set_defaults(func=cmd_compare)

    # kpi-validate
    sp_kpi_val = sub.add_parser("kpi-validate", help="Validate KPI catalog for errors")
    sp_kpi_val.add_argument("--config", default=KPI_DEFAULT_CONFIG, help=KPI_CONFIG_HELP)
    sp_kpi_val.set_defaults(func=cmd_kpi_validate)

    # plan
    sp_plan = sub.add_parser(
        "plan",
        help="Generate per-column preprocessing recommendations for a CSV",
    )
    sp_plan.add_argument("csv", help=CSV_PATH_HELP)
    _add_csv_options(sp_plan)
    sp_plan.set_defaults(func=cmd_plan)

    # chart
    sp_chart = sub.add_parser(
        "chart",
        help="Generate a terminal-based profiling chart for a column",
    )
    sp_chart.add_argument("csv", help=CSV_PATH_HELP)
    sp_chart.add_argument("--column", required=True, help="Column name to chart")
    _add_csv_options(sp_chart)
    sp_chart.set_defaults(func=cmd_chart)

    # dashboard (Phase 4)
    sp_dash = sub.add_parser(
        "dashboard",
        help="Launch the Streamlit dashboard (requires: pip install data-quality-toolkit[ui])",
    )
    sp_dash.set_defaults(func=cmd_dashboard)

    return p


_SUPPORTED_CSV_EXTENSIONS: frozenset[str] = frozenset({".csv"})


def _print_csv_hint(args: Any) -> None:
    """Print a CSV-specific hint to stderr when the failing command takes a csv arg."""
    if getattr(args, "csv", None) is not None:
        print("  Hint: check that the file is a valid, non-empty CSV.", file=sys.stderr)
        print("  Example: dqt profile data/my_file.csv", file=sys.stderr)


def _validate_csv_path(args: Any) -> str | None:
    """Return an error message if the csv positional arg is blank, else None."""
    csv_path = getattr(args, "csv", None)
    if csv_path is not None and not str(csv_path).strip():
        return "File path must not be blank or whitespace-only."
    return None


def _validate_csv_extension(args: Any) -> str | None:
    """Return an error message if the csv positional arg has an unsupported extension."""
    csv_path = getattr(args, "csv", None)
    if csv_path is None:
        return None
    stripped = str(csv_path).strip()
    if not stripped:
        return None  # already caught by _validate_csv_path
    suffix = Path(stripped).suffix.lower()
    if suffix not in _SUPPORTED_CSV_EXTENSIONS:
        supported = ", ".join(sorted(_SUPPORTED_CSV_EXTENSIONS))
        return (
            f"Unsupported file extension '{suffix or '(none)'}'. " f"Expected one of: {supported}"
        )
    return None


def _handle_value_error(e: ValueError, args: Any) -> int:
    """Handle ValueError from pipeline, with a specific branch for ParserError."""
    # pd.errors.ParserError is a ValueError subclass — give a targeted message
    if type(e).__name__ == "ParserError":
        print(f"Error: CSV could not be parsed: {e}", file=sys.stderr)
        print(
            "  Hint: check that all rows have the same number of columns"
            " and the correct delimiter (try --sep).",
            file=sys.stderr,
        )
        return 1
    print(f"Error: {e}", file=sys.stderr)
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


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging(level=_resolve_log_level(args), fmt=args.log_format)

    try:
        _apply_dqt_config(args)
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    path_error = _validate_csv_path(args) or _validate_csv_extension(args)
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
        missing = e.filename or str(e)
        print(f"Error: file not found: '{missing}'", file=sys.stderr)
        print("  Hint: check the path and make sure the file exists.", file=sys.stderr)
        print("  Example: dqt profile data/my_file.csv", file=sys.stderr)
        return 2
    except PermissionError as e:
        print(f"Error: permission denied: {e}", file=sys.stderr)
        return 13
    except UnicodeDecodeError as e:
        print(
            "Error: decoding failed (try --encoding utf-8 or the correct encoding).",
            file=sys.stderr,
        )
        print(str(e), file=sys.stderr)
        return 22
    except ValueError as e:
        code = _handle_value_error(e, args)
        return code


if __name__ == "__main__":
    sys.exit(main())
