"""Public Python API for data_quality_toolkit.

Thin wrappers over workflow.pipeline and workflow.compare.
CLI behavior is unchanged — these functions call the same internal implementations.
"""

# mypy: warn_unused_ignores = false

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from data_quality_toolkit.application.workflow.elt_pipeline import ELTPipeline


def _build_csv_kwargs(
    sep: str | None,
    encoding: str | None,
    na_values: list[str] | None,
) -> dict[str, Any]:
    kw: dict[str, Any] = {}
    if sep is not None:
        kw["sep"] = sep
    if encoding is not None:
        kw["encoding"] = encoding
    if na_values is not None:
        kw["na_values"] = na_values
    return kw


def profile_csv(
    path: str | Path,
    *,
    sep: str | None = None,
    encoding: str | None = None,
    na_values: list[str] | None = None,
    sample_size: int | None = None,
    chunksize: int | None = None,
) -> dict[str, Any]:
    """Profile a CSV file. Returns profile metadata — no disk writes.

    chunksize=None (default): full in-memory load, all metrics available.
    chunksize=N: streams in chunks; approximate=True, unsupported_metrics populated.
    """
    kw = _build_csv_kwargs(sep, encoding, na_values)
    if chunksize is not None:
        from data_quality_toolkit.application.workflow.pipeline import run_profile_chunked

        return run_profile_chunked(str(path), chunksize=chunksize, **kw)
    from data_quality_toolkit.application.workflow.pipeline import run_profile

    return run_profile(str(path), sample_size=sample_size, **kw)


def assess_csv(
    path: str | Path,
    *,
    null_threshold: float | None = None,
    sep: str | None = None,
    encoding: str | None = None,
    na_values: list[str] | None = None,
    sample_size: int | None = None,
    chunksize: int | None = None,
) -> dict[str, Any]:
    """Profile and assess a CSV file. Returns profile + quality score + issues. No disk writes.

    chunksize=None (default): full in-memory load, all rules available.
    chunksize=N: streams in chunks; partial assessment, assessment_mode='chunked',
                 approximate=True, unsupported_rules populated; no quality_score.
    """
    kw = _build_csv_kwargs(sep, encoding, na_values)
    if chunksize is not None:
        from data_quality_toolkit.application.workflow.pipeline import run_assessment_chunked

        if null_threshold is not None:
            return run_assessment_chunked(
                str(path), chunksize=chunksize, null_threshold=null_threshold, **kw
            )
        return run_assessment_chunked(str(path), chunksize=chunksize, **kw)
    from data_quality_toolkit.application.workflow.pipeline import run_assessment

    if null_threshold is not None:
        return run_assessment(
            str(path), null_threshold=null_threshold, sample_size=sample_size, **kw
        )
    return run_assessment(str(path), sample_size=sample_size, **kw)


def export_csv(
    path: str | Path,
    *,
    output_dir: str | Path | None = None,
    null_threshold: float | None = None,
    sep: str | None = None,
    encoding: str | None = None,
    na_values: list[str] | None = None,
    sample_size: int | None = None,
    emit_manifest: bool = False,
) -> dict[str, Any]:
    """Full pipeline: profile → assess → star schema → write artifacts. Returns run metadata."""
    from data_quality_toolkit.application.workflow.pipeline import run_export_star

    kw = _build_csv_kwargs(sep, encoding, na_values)
    out_dir = str(output_dir) if output_dir is not None else None
    if null_threshold is not None:
        return run_export_star(
            str(path),
            output_dir=out_dir,
            null_threshold=null_threshold,
            sample_size=sample_size,
            emit_manifest=emit_manifest,
            **kw,
        )
    return run_export_star(
        str(path), output_dir=out_dir, sample_size=sample_size, emit_manifest=emit_manifest, **kw
    )


def create_manifest(run_id: str, sessions_root: str | Path) -> dict[str, Any]:
    """Build a lineage manifest for a specific run.

    Reuses existing lineage manifest builder. Returns a plain dictionary.
    """
    from data_quality_toolkit.lineage.manifest.builder import build_manifest

    manifest = build_manifest(run_id=run_id, sessions_root=Path(sessions_root))
    return manifest.model_dump(mode="json", by_alias=True)  # type: ignore


def compare_runs(
    path: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Compare the last two export_csv runs for this CSV. output_dir must match export_csv call."""
    from data_quality_toolkit.adapters.loaders.file.csv_loader import dataset_id_from_file
    from data_quality_toolkit.application.workflow.compare import compare_last_two_runs

    dataset_id = dataset_id_from_file(Path(path))
    history_path = Path(output_dir) / "star" / "quality_history.jsonl"
    return compare_last_two_runs(dataset_id, history_path)


DRIFT_REPORT_SCHEMA_VERSION = "3"
DRIFT_HISTORY_SCHEMA_VERSION = "1"


def _drift_run_identity() -> dict[str, str]:
    """Generate the run identity shared by the evidence report and history record."""
    import uuid
    from datetime import UTC, datetime

    return {
        "run_id": uuid.uuid4().hex,
        "created_at": datetime.now(UTC).isoformat(),
    }


def _write_drift_report(
    output_path: Path,
    baseline_path: str,
    current_path: str,
    result: dict[str, Any],
    identity: dict[str, str],
) -> None:
    """Atomically write a drift evidence report (versioned envelope around *result*)."""
    import json
    import os
    import tempfile

    envelope = {
        "schema_version": DRIFT_REPORT_SCHEMA_VERSION,
        "kind": "drift_report",
        "run_id": identity["run_id"],
        "created_at": identity["created_at"],
        "baseline_path": baseline_path,
        "current_path": current_path,
        "result": result,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=str(output_path.parent), suffix=".tmp"
    ) as tmp:
        json.dump(envelope, tmp, indent=2, sort_keys=True, default=str)
        tmp.flush()
        os.fsync(tmp.fileno())
    os.replace(tmp.name, output_path)


def _append_drift_history(
    history_path: Path,
    baseline_path: str,
    current_path: str,
    result: dict[str, Any],
    identity: dict[str, str],
    report_path: str | None,
) -> None:
    """Append one compact drift history record (a single JSON line) to *history_path*."""
    from data_quality_toolkit.adapters.storage.jsonl import append_jsonl_record

    summary = result.get("summary") or {}
    record = {
        "schema_version": DRIFT_HISTORY_SCHEMA_VERSION,
        "kind": "drift_history_record",
        "run_id": identity["run_id"],
        "created_at": identity["created_at"],
        "baseline_path": baseline_path,
        "current_path": current_path,
        "baseline_dataset_id": result.get("baseline_dataset_id"),
        "current_dataset_id": result.get("current_dataset_id"),
        "status": result.get("status"),
        "alpha": result.get("alpha"),
        "columns_tested": summary.get("columns_tested"),
        "columns_skipped": summary.get("columns_skipped"),
        "columns_drifted": summary.get("columns_drifted"),
        "drift_detected": summary.get("drift_detected"),
        "report_path": report_path,
    }
    append_jsonl_record(history_path, record)


def detect_drift(
    baseline_path: str | Path,
    current_path: str | Path,
    *,
    alpha: float = 0.05,
    min_samples: int = 30,
    max_categories: int = 20,
    sep: str | None = None,
    encoding: str | None = None,
    na_values: list[str] | None = None,
    sample_size: int | None = None,
    output_path: str | Path | None = None,
    history_path: str | Path | None = None,
) -> dict[str, Any]:
    """Detect statistical drift between two CSV files. No disk writes unless paths are set.

    Numeric columns: two-sample KS test. Categorical columns: chi-square test.
    Requires the optional stats extra (scipy); without it the result has
    status="unavailable" instead of raising.

    When *output_path* is set, the result is written there as a JSON evidence
    report wrapped in a versioned envelope (schema_version, run_id, created_at,
    baseline/current paths). The report is written even when scipy is
    unavailable, and the returned dict gains an "output_path" key.

    When *history_path* is set, one compact history record (JSON line) is
    appended there, sharing the report's run_id when both paths are given.
    The record is appended even when scipy is unavailable, and the returned
    dict gains a "history_path" key.
    """
    from data_quality_toolkit.adapters.loaders.file.csv_loader import load_csv
    from data_quality_toolkit.domain.statistics.drift import detect_drift_frames

    kw = _build_csv_kwargs(sep, encoding, na_values)
    ref_df, ref_meta = load_csv(str(baseline_path), sample_size=sample_size, **kw)
    cur_df, cur_meta = load_csv(str(current_path), sample_size=sample_size, **kw)
    result = detect_drift_frames(
        ref_df,
        cur_df,
        alpha=alpha,
        min_samples=min_samples,
        max_categories=max_categories,
    )
    result["baseline_dataset_id"] = ref_meta["dataset_id"]
    result["current_dataset_id"] = cur_meta["dataset_id"]
    if output_path is not None or history_path is not None:
        identity = _drift_run_identity()
        out: Path | None = None
        if output_path is not None:
            out = Path(output_path)
            _write_drift_report(out, str(baseline_path), str(current_path), result, identity)
            result["output_path"] = str(out)
        if history_path is not None:
            hist = Path(history_path)
            _append_drift_history(
                hist,
                str(baseline_path),
                str(current_path),
                result,
                identity,
                report_path=str(out) if out is not None else None,
            )
            result["history_path"] = str(hist)
    return result


def plan_csv(
    path: str | Path,
    *,
    sep: str | None = None,
    encoding: str | None = None,
    na_values: list[str] | None = None,
    sample_size: int | None = None,
) -> dict[str, Any]:
    """Return per-column preprocessing recommendations for a CSV. No disk writes."""
    from data_quality_toolkit.adapters.loaders.file.csv_loader import load_csv
    from data_quality_toolkit.application.workflow.preprocessing import plan_preprocessing

    kw = _build_csv_kwargs(sep, encoding, na_values)
    df, meta = load_csv(str(path), sample_size=sample_size, **kw)
    return {
        "dataset_id": meta["dataset_id"],
        "columns": plan_preprocessing(df),
    }


def kpi_validate(config_path: str | Path) -> dict[str, Any]:
    """Validate a KPI catalog YAML (schema, semantics, dependency cycles). No disk writes."""
    from data_quality_toolkit.application.workflow.kpi import validate_kpi_catalog

    return validate_kpi_catalog(config_path)


def kpi_emit(
    config_path: str | Path,
    dax_out: str | Path,
    tmsl_out: str | Path,
) -> dict[str, Any]:
    """Load KPI catalog, validate, and emit DAX + TMSL files. Writes two output files."""
    from data_quality_toolkit.application.workflow.kpi import emit_kpi_artifacts

    return emit_kpi_artifacts(config_path, dax_out, tmsl_out)


def kpi_graph(
    config_path: str | Path,
    out: str | Path,
    graph_format: Literal["mermaid", "graphviz"] = "mermaid",
) -> dict[str, Any]:
    """Export KPI dependency graph as Mermaid (.mmd) or Graphviz (.dot). Writes one file."""
    from data_quality_toolkit.application.workflow.kpi import export_kpi_graph

    return export_kpi_graph(config_path, out, graph_format=graph_format)


def generate_dim_time(
    start_date: str = "2018-01-01",
    end_date: str = "2030-12-31",
    *,
    week_start: int = 1,
    fiscal_year_start: int | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Generate a time dimension table.

    If output_dir is provided, writes dim_time.csv and includes "path" in the result.
    Without output_dir, returns metadata only (rows, start_date, end_date, week_start).
    """
    from data_quality_toolkit.application.workflow.kpi import generate_dim_time_workflow

    return generate_dim_time_workflow(
        start_date=start_date,
        end_date=end_date,
        week_start=week_start,
        fiscal_year_start=fiscal_year_start,
        output_dir=output_dir,
    )


def create_elt_pipeline(run_id: str, sessions_root: str | Path) -> ELTPipeline:
    """Create a new ELT pipeline for orchestration."""
    from data_quality_toolkit.application.workflow.elt_pipeline import (
        create_elt_pipeline as _create,
    )

    return _create(run_id, sessions_root)


def read_drift_history(history_path: str | Path) -> list[dict[str, Any]]:
    """Return all drift history records from a JSONL file written by detect_drift.

    Missing file returns []. Blank and malformed lines are skipped. Preserves append order.
    Records are filtered to kind == "drift_history_record".
    """
    from data_quality_toolkit.adapters.storage.jsonl import read_drift_history as _read

    return _read(Path(history_path))


def import_drift_history_sqlite(
    db_path: str | Path,
    history_path: str | Path,
) -> int:
    """Import drift history JSONL records into SQLite.

    Returns the number of records imported.
    """
    from data_quality_toolkit.adapters.storage.connection import connect
    from data_quality_toolkit.adapters.storage.importer import import_drift_history as _import

    with connect(Path(db_path)) as con:
        return _import(con, Path(history_path))


def read_drift_runs_sqlite(
    db_path: str | Path,
    *,
    limit: int | None = None,
    current_dataset_id: str | None = None,
    drift_detected: bool | int | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Return imported drift runs from a SQLite monitoring database.

    Reads rows from the drift_runs table written by import_drift_history_sqlite.
    Newest first (created_at descending, run_id tie-break). Optional filters:
    limit, current_dataset_id, drift_detected, status. Missing DB or no matching
    rows returns []. Raises StorageError on DB read failure.
    """
    from data_quality_toolkit.adapters.storage.queries import read_drift_runs as _read

    return _read(
        Path(db_path),
        limit=limit,
        current_dataset_id=current_dataset_id,
        drift_detected=drift_detected,
        status=status,
    )


def read_drift_columns_sqlite(
    db_path: str | Path,
    *,
    run_id: str | None = None,
    column_name: str | None = None,
    drift_detected: bool | int | None = None,
) -> list[dict[str, Any]]:
    """Return imported per-column drift results from a SQLite monitoring database.

    Reads rows from the drift_columns table populated by
    import_drift_history_sqlite from each drift run's evidence-report columns.
    Ordered by run_id then column_name. Optional filters: run_id, column_name,
    drift_detected. Missing DB or no matching rows returns []. Raises
    StorageError on DB read failure.
    """
    from data_quality_toolkit.adapters.storage.queries import read_drift_columns as _read

    return _read(
        Path(db_path),
        run_id=run_id,
        column_name=column_name,
        drift_detected=drift_detected,
    )


def read_drift_distributions_sqlite(
    db_path: str | Path,
    *,
    run_id: str | None = None,
    column_name: str | None = None,
) -> list[dict[str, Any]]:
    """Return imported per-column distribution bins from a SQLite monitoring database.

    Reads rows from the drift_column_distributions table populated by
    import_drift_history_sqlite from each drift run's evidence-report
    ``result.columns[].distribution`` bins. Ordered by run_id, column_name, then
    bin_index. Optional filters: run_id, column_name. Missing DB or no matching
    rows returns []. Raises StorageError on DB read failure.
    """
    from data_quality_toolkit.adapters.storage.queries import read_drift_distributions as _read

    return _read(
        Path(db_path),
        run_id=run_id,
        column_name=column_name,
    )


def summarize_drift_trends_sqlite(
    db_path: str | Path,
    *,
    current_dataset_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Summarize drift history from a SQLite monitoring database as a JSON-ready dict.

    Aggregates rows from the drift_runs table (written by import_drift_history_sqlite)
    using the read_drift_runs query behavior. Returns total_runs, drifted_runs,
    non_drifted_runs, drift_rate, the latest run's run_id/created_at/drift_detected,
    and columns_tested/columns_drifted totals and averages. Optional
    current_dataset_id and limit filters narrow the runs aggregated. A missing DB,
    an empty table, or no matching rows returns a stable zero-summary. Raises
    StorageError on DB read failure.
    """
    from data_quality_toolkit.adapters.storage.trends import summarize_drift_trends as _summarize

    return _summarize(
        Path(db_path),
        current_dataset_id=current_dataset_id,
        limit=limit,
    )


def drift_history_report(
    db_path: str | Path,
    *,
    current_dataset_id: str | None = None,
    limit: int | None = None,
    fmt: str = "md",
    include_plots: bool = False,
) -> str:
    """Render a drift-history monitoring report from a SQLite database.

    Reuses read_drift_runs_sqlite and summarize_drift_trends_sqlite to build a
    readable report string. fmt is "md" (default Markdown) or "html"
    (dependency-free). Optional current_dataset_id and limit filters narrow the
    runs included. When include_plots is True, persisted distribution bins are
    read via read_drift_distributions_sqlite and rendered as a dependency-free
    "Distribution plots" section. A missing DB or empty table yields a valid zero
    report rather than raising. Raises StorageError on DB read failure.
    """
    from data_quality_toolkit.adapters.reports.drift_history import (
        build_drift_history_report as _build,
    )

    return _build(
        db_path,
        current_dataset_id=current_dataset_id,
        limit=limit,
        fmt=fmt,
        include_plots=include_plots,
    )


def drift_dashboard(
    db_path: str | Path,
    *,
    current_dataset_id: str | None = None,
    limit: int | None = None,
    include_plots: bool = False,
) -> str:
    """Render a static, self-contained drift analytics dashboard from SQLite.

    Reuses read_drift_runs_sqlite, summarize_drift_trends_sqlite, and
    read_drift_columns_sqlite to build a dependency-free HTML string (inline CSS,
    no JavaScript, no external assets). Optional current_dataset_id and limit
    filters narrow the runs included. When include_plots is True, persisted
    distribution bins are read via read_drift_distributions_sqlite and rendered as
    a dependency-free "Distribution plots" section. A missing DB or empty table
    yields a valid zero dashboard rather than raising. Raises StorageError on DB
    read failure.
    """
    from data_quality_toolkit.adapters.reports.drift_dashboard import (
        build_drift_dashboard as _build,
    )

    return _build(
        db_path,
        current_dataset_id=current_dataset_id,
        limit=limit,
        include_plots=include_plots,
    )
