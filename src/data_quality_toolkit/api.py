"""Public Python API for data_quality_toolkit.

Thin wrappers over workflow.pipeline and workflow.compare.
CLI behavior is unchanged — these functions call the same internal implementations.
"""

# mypy: warn_unused_ignores = false

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

# Public re-exports (G8C1): make the stable view-model, exception family, and the
# storage error importable from the canonical ``data_quality_toolkit.api`` seam.
# Cycle-safe: view_model imports ``api`` only lazily inside its builder functions.
from data_quality_toolkit.adapters.storage.connection import StorageError
from data_quality_toolkit.application.monitoring.view_model import (
    ColumnDrift,
    DistributionBin,
    MonitoringOverview,
    RunDetail,
    RunRow,
    TrendSummary,
    build_column_drift,
    build_distribution_series,
    build_monitoring_overview,
    build_run_detail,
    list_run_rows,
)
from data_quality_toolkit.shared.exceptions import (
    AssessmentError,
    ConfigError,
    DQTError,
    LoaderError,
    NotificationError,
    ProfileError,
    ValidationError,
    WebhookSecurityError,
)
from data_quality_toolkit.shared.result_types import (
    AssessCsvResult,
    ColumnPlan,
    CsvAssessment,
    CsvAssessmentIssue,
    CsvExportPaths,
    CsvMeta,
    CsvProfile,
    CsvProfileColumn,
    CsvProfileCompact,
    CsvStarExport,
    DimTimeResult,
    DriftColumnRow,
    DriftDistributionRow,
    DriftHistoryXlsxExportResult,
    DriftNotificationSendResult,
    DriftPlotsExportResult,
    DriftRateThresholdResult,
    DriftRunRow,
    ExportCsvResult,
    KpiEmitResult,
    KpiGraphResult,
    MonitoringDuckdbExportResult,
    PlanCsvResult,
    PowerBIPackageResult,
    ProfileCsvResult,
    PsiOffender,
    PsiThresholdResult,
    SummarizeDriftTrendsResult,
)

if TYPE_CHECKING:
    from data_quality_toolkit.application.workflow.elt_pipeline import ELTPipeline

__all__ = [
    # CSV profiling / assessment / export
    "profile_csv",
    "assess_csv",
    "export_csv",
    "plan_csv",
    "compare_runs",
    "create_manifest",
    "create_elt_pipeline",
    # Drift detection + history readers
    "detect_drift",
    "read_drift_history",
    "import_drift_history_sqlite",
    "read_drift_runs_sqlite",
    "read_drift_columns_sqlite",
    "read_drift_distributions_sqlite",
    "summarize_drift_trends_sqlite",
    # Drift reporting / export
    "drift_history_report",
    "drift_dashboard",
    "export_drift_history_xlsx",
    "export_monitoring_duckdb",
    "export_drift_plots",
    "send_drift_notification",
    # Drift threshold evaluators
    "evaluate_drift_rate_threshold",
    "evaluate_psi_threshold",
    # KPI workflows
    "kpi_validate",
    "kpi_emit",
    "kpi_graph",
    "generate_dim_time",
    "build_powerbi_package",
    # Monitoring view-model (value objects + builders)
    "MonitoringOverview",
    "TrendSummary",
    "RunRow",
    "ColumnDrift",
    "DistributionBin",
    "RunDetail",
    "build_monitoring_overview",
    "list_run_rows",
    "build_column_drift",
    "build_distribution_series",
    "build_run_detail",
    # Exception family
    "DQTError",
    "LoaderError",
    "ValidationError",
    "ConfigError",
    "ProfileError",
    "AssessmentError",
    "NotificationError",
    "WebhookSecurityError",
    "StorageError",
    # Result TypedDicts (G8C2B)
    "DriftRateThresholdResult",
    "PsiOffender",
    "PsiThresholdResult",
    "ColumnPlan",
    "PlanCsvResult",
    "DimTimeResult",
    "KpiEmitResult",
    "KpiGraphResult",
    "SummarizeDriftTrendsResult",
    "DriftRunRow",
    "DriftColumnRow",
    "DriftDistributionRow",
    # Flat wrapper result TypedDicts (G8C2E)
    "DriftHistoryXlsxExportResult",
    "MonitoringDuckdbExportResult",
    "DriftPlotsExportResult",
    "DriftNotificationSendResult",
    # Power BI package contract (G8C3B)
    "PowerBIPackageResult",
    # Nested envelope contracts (G8C2G)
    "CsvMeta",
    "CsvProfileColumn",
    "CsvProfile",
    "CsvProfileCompact",
    "CsvAssessmentIssue",
    "CsvAssessment",
    "CsvStarExport",
    "CsvExportPaths",
    "ProfileCsvResult",
    "AssessCsvResult",
    "ExportCsvResult",
]


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
) -> ProfileCsvResult:
    """Profile a CSV file. Returns profile metadata — no disk writes.

    chunksize=None (default): full in-memory load, all metrics available.
    chunksize=N: streams in chunks; approximate=True, unsupported_metrics populated.
    """
    kw = _build_csv_kwargs(sep, encoding, na_values)
    if chunksize is not None:
        from data_quality_toolkit.application.workflow.pipeline import run_profile_chunked

        return cast(ProfileCsvResult, run_profile_chunked(str(path), chunksize=chunksize, **kw))
    from data_quality_toolkit.application.workflow.pipeline import run_profile

    return cast(ProfileCsvResult, run_profile(str(path), sample_size=sample_size, **kw))


def assess_csv(
    path: str | Path,
    *,
    null_threshold: float | None = None,
    sep: str | None = None,
    encoding: str | None = None,
    na_values: list[str] | None = None,
    sample_size: int | None = None,
    chunksize: int | None = None,
) -> AssessCsvResult:
    """Profile and assess a CSV file. Returns profile + quality score + issues. No disk writes.

    chunksize=None (default): full in-memory load, all rules available.
    chunksize=N: streams in chunks; partial assessment, assessment_mode='chunked',
                 approximate=True, unsupported_rules populated; no quality_score.
    """
    kw = _build_csv_kwargs(sep, encoding, na_values)
    if chunksize is not None:
        from data_quality_toolkit.application.workflow.pipeline import run_assessment_chunked

        if null_threshold is not None:
            return cast(
                AssessCsvResult,
                run_assessment_chunked(
                    str(path), chunksize=chunksize, null_threshold=null_threshold, **kw
                ),
            )
        return cast(AssessCsvResult, run_assessment_chunked(str(path), chunksize=chunksize, **kw))
    from data_quality_toolkit.application.workflow.pipeline import run_assessment

    if null_threshold is not None:
        return cast(
            AssessCsvResult,
            run_assessment(str(path), null_threshold=null_threshold, sample_size=sample_size, **kw),
        )
    return cast(AssessCsvResult, run_assessment(str(path), sample_size=sample_size, **kw))


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
) -> ExportCsvResult:
    """Full pipeline: profile → assess → star schema → write artifacts. Returns run metadata."""
    from data_quality_toolkit.application.workflow.pipeline import run_export_star

    kw = _build_csv_kwargs(sep, encoding, na_values)
    out_dir = str(output_dir) if output_dir is not None else None
    if null_threshold is not None:
        return cast(
            ExportCsvResult,
            run_export_star(
                str(path),
                output_dir=out_dir,
                null_threshold=null_threshold,
                sample_size=sample_size,
                emit_manifest=emit_manifest,
                **kw,
            ),
        )
    return cast(
        ExportCsvResult,
        run_export_star(
            str(path),
            output_dir=out_dir,
            sample_size=sample_size,
            emit_manifest=emit_manifest,
            **kw,
        ),
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


def compare_runs_history(
    dataset_id: str,
    history_path: str | Path,
) -> dict[str, Any]:
    """Compare last two runs by dataset_id and an explicit JSONL history file path.

    Thin seam for callers that already have dataset_id and history_path
    (e.g. the UI service, which infers history_path from a DB directory).
    """
    from data_quality_toolkit.application.workflow.compare import compare_last_two_runs

    return compare_last_two_runs(dataset_id, Path(history_path))


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
) -> PlanCsvResult:
    """Return per-column preprocessing recommendations for a CSV. No disk writes."""
    from data_quality_toolkit.adapters.loaders.file.csv_loader import load_csv
    from data_quality_toolkit.application.workflow.preprocessing import plan_preprocessing

    kw = _build_csv_kwargs(sep, encoding, na_values)
    df, meta = load_csv(str(path), sample_size=sample_size, **kw)
    return {
        "dataset_id": meta["dataset_id"],
        "columns": cast(list[ColumnPlan], plan_preprocessing(df)),
    }


def kpi_validate(config_path: str | Path) -> dict[str, Any]:
    """Validate a KPI catalog YAML (schema, semantics, dependency cycles). No disk writes."""
    from data_quality_toolkit.application.workflow.kpi import validate_kpi_catalog

    return validate_kpi_catalog(config_path)


def kpi_emit(
    config_path: str | Path,
    dax_out: str | Path,
    tmsl_out: str | Path,
) -> KpiEmitResult:
    """Load KPI catalog, validate, and emit DAX + TMSL files. Writes two output files."""
    from data_quality_toolkit.application.workflow.kpi import emit_kpi_artifacts

    return cast(KpiEmitResult, emit_kpi_artifacts(config_path, dax_out, tmsl_out))


def kpi_graph(
    config_path: str | Path,
    out: str | Path,
    graph_format: Literal["mermaid", "graphviz"] = "mermaid",
) -> KpiGraphResult:
    """Export KPI dependency graph as Mermaid (.mmd) or Graphviz (.dot). Writes one file."""
    from data_quality_toolkit.application.workflow.kpi import export_kpi_graph

    return cast(KpiGraphResult, export_kpi_graph(config_path, out, graph_format=graph_format))


def generate_dim_time(
    start_date: str = "2018-01-01",
    end_date: str = "2030-12-31",
    *,
    week_start: int = 1,
    fiscal_year_start: int | None = None,
    output_dir: str | Path | None = None,
) -> DimTimeResult:
    """
    Generate a time dimension table.

    If output_dir is provided, writes dim_time.csv and includes "path" in the result.
    Without output_dir, returns metadata only (rows, start_date, end_date, week_start).
    """
    from data_quality_toolkit.application.workflow.kpi import generate_dim_time_workflow

    return cast(
        DimTimeResult,
        generate_dim_time_workflow(
            start_date=start_date,
            end_date=end_date,
            week_start=week_start,
            fiscal_year_start=fiscal_year_start,
            output_dir=output_dir,
        ),
    )


def build_powerbi_package(
    star_dir: str | Path,
    output_dir: str | Path,
    time_start: str = "2018-01-01",
    time_end: str = "2030-12-31",
    base_folder: str = "./dist",
    fiscal_year_start: int | None = None,
) -> PowerBIPackageResult:
    """Build a Power BI package from a star-schema directory. Writes package files.

    Thin pass-through over the internal exporter — behavior is unchanged. Generates
    a time dimension, scaffolds the zero-config Power BI package, validates it, and
    returns the package metadata. Raises ValueError when validation fails and
    FileNotFoundError when star_dir is missing.
    """
    from data_quality_toolkit.adapters.exporters.bi.powerbi_exporter import export_powerbi_package

    return cast(
        PowerBIPackageResult,
        export_powerbi_package(
            star_dir,
            output_dir,
            time_start=time_start,
            time_end=time_end,
            base_folder=base_folder,
            fiscal_year_start=fiscal_year_start,
        ),
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
    See DriftRunRow for the stable key contract.
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
    See DriftColumnRow for the stable key contract.
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
    See DriftDistributionRow for the stable key contract.
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
    See SummarizeDriftTrendsResult for the stable key contract.
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


def export_drift_history_xlsx(
    db_path: str | Path,
    output_path: str | Path,
    *,
    current_dataset_id: str | None = None,
    limit: int | None = None,
    include_columns: bool = True,
    include_distributions: bool = False,
    force: bool = False,
) -> DriftHistoryXlsxExportResult:
    """Export drift-history monitoring data to a multi-sheet .xlsx workbook.

    Reuses read_drift_runs_sqlite, summarize_drift_trends_sqlite,
    read_drift_columns_sqlite, and read_drift_distributions_sqlite to build a
    local Excel workbook (sheets: runs, trend_summary, columns when
    include_columns, distributions when include_distributions, metadata). Refuses
    to overwrite an existing file unless force is True. A missing or empty DB
    yields a valid zero-state workbook. All string cells are escaped against
    spreadsheet formula injection.

    Requires the optional [powerbi] extra (openpyxl); raises XlsxExportError with
    a "pip install data-quality-toolkit[powerbi]" hint when it is absent. Returns
    {"output_path", "sheets", "row_counts"}.
    """
    from data_quality_toolkit.adapters.exporters.bi.xlsx_drift_exporter import (
        export_drift_history_xlsx as _impl,
    )

    return cast(
        DriftHistoryXlsxExportResult,
        _impl(
            db_path,
            output_path,
            current_dataset_id=current_dataset_id,
            limit=limit,
            include_columns=include_columns,
            include_distributions=include_distributions,
            force=force,
        ),
    )


def export_monitoring_duckdb(
    db_path: str | Path,
    out_path: str | Path,
    *,
    overwrite: bool = False,
) -> MonitoringDuckdbExportResult:
    """Mirror drift-history monitoring tables from SQLite into a DuckDB file.

    Opens an existing monitoring SQLite database read-only (never mutating it) and
    writes a standalone DuckDB database mirroring the drift-history tables
    drift_runs, drift_columns, and drift_column_distributions with a stable schema.
    DuckDB is export/mirror only — it is never a live monitoring backend, and the
    SQLite store is unchanged. Tables absent from the source are mirrored empty.

    Refuses to overwrite an existing output unless overwrite is True, in which case
    the output is recreated deterministically. Requires the optional [duckdb] extra
    (duckdb); raises DuckdbExportError with a "pip install data-quality-toolkit[duckdb]"
    hint when it is absent. Returns
    {"input_db_path", "output_path", "tables", "row_counts", "overwritten"}.
    """
    from data_quality_toolkit.adapters.exporters.bi.duckdb_exporter import (
        export_monitoring_duckdb as _impl,
    )

    return cast(MonitoringDuckdbExportResult, _impl(db_path, out_path, overwrite=overwrite))


def export_drift_plots(
    db_path: str | Path,
    out: str | Path,
    *,
    chart: str = "all",
    current_dataset_id: str | None = None,
    limit: int | None = None,
    force: bool = False,
) -> DriftPlotsExportResult:
    """Export drift-history monitoring data to local PNG chart files.

    Reuses read_drift_runs_sqlite, summarize_drift_trends_sqlite, and
    read_drift_columns_sqlite to render static PNG charts into the *out*
    directory. Supported charts: "drift-rate", "psi-by-column", "top-drifted"
    (or "all", the default). Refuses to overwrite an existing PNG unless force is
    True. A missing or empty DB yields valid zero-state PNGs. Only local file
    writes — no network, no GUI backend.

    Requires the optional [viz] extra (matplotlib); raises PlotExportError with a
    "pip install data-quality-toolkit[viz]" hint when it is absent. Returns
    {"output_dir", "charts", "row_counts"}.
    """
    from data_quality_toolkit.adapters.exporters.viz.drift_plots import export_drift_plots as _impl

    return cast(
        DriftPlotsExportResult,
        _impl(
            db_path,
            out,
            chart=chart,
            current_dataset_id=current_dataset_id,
            limit=limit,
            force=force,
        ),
    )


def send_drift_notification(
    db_path: str | Path,
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
    """Build (and optionally POST) a one-shot drift-threshold webhook notification.

    Reads a drift trend summary (and per-column PSI when *max_psi* is set) from the
    SQLite monitoring database via the existing summarize/read/evaluate seams, then
    builds a minimal JSON payload. Dry-run (the default, and whenever *send* is False)
    performs no network call. A real POST happens only when ``send=True`` and
    ``dry_run=False`` AND ``DQT_ALLOW_NETWORK=true``; the URL is SSRF-validated
    (https-only unless *allow_http*), redirects are refused, and the request uses a
    single attempt with a mandatory *timeout*. Returns
    ``{"payload", "sent", "status", "breached", "redacted_url"}``. Raises
    NotificationError / WebhookSecurityError on a send or security failure.
    """
    from data_quality_toolkit.adapters.notifications.webhook import (
        post_json,
        redact_url,
        validate_webhook_url,
    )
    from data_quality_toolkit.application.monitoring.notifications import (
        build_drift_notification_payload,
    )
    from data_quality_toolkit.shared.constants import VERSION
    from data_quality_toolkit.shared.exceptions import NotificationError
    from data_quality_toolkit.shared.settings import load_settings

    summary = summarize_drift_trends_sqlite(db_path)

    rate_result = None
    if max_drift_rate is not None:
        rate_result = evaluate_drift_rate_threshold(summary, max_drift_rate=max_drift_rate)

    psi_result = None
    if max_psi is not None:
        columns = read_drift_columns_sqlite(db_path)
        psi_result = evaluate_psi_threshold(columns, max_psi=max_psi)

    payload = build_drift_notification_payload(
        summary,
        version=VERSION,
        max_drift_rate=max_drift_rate,
        max_psi=max_psi,
        rate_result=rate_result,  # type: ignore[arg-type]
        psi_result=psi_result,  # type: ignore[arg-type]
    )
    breached = bool(payload["breached"])
    redacted = redact_url(webhook_url)

    # Fail safe: only a real send when explicitly requested and not in dry-run.
    if not (send and not dry_run):
        return cast(
            DriftNotificationSendResult,
            {
                "payload": payload,
                "sent": False,
                "status": None,
                "breached": breached,
                "redacted_url": redacted,
            },
        )

    if not load_settings().dqt_allow_network:
        raise NotificationError(
            "real webhook send refused: network is disabled",
            hint="set DQT_ALLOW_NETWORK=true to allow real sends, or use --dry-run",
        )

    redacted = validate_webhook_url(
        webhook_url,
        allow_http=allow_http,
        allow_insecure_host=allow_insecure_host,
    )
    status = post_json(webhook_url, payload, version=VERSION, timeout=timeout)
    return cast(
        DriftNotificationSendResult,
        {
            "payload": payload,
            "sent": True,
            "status": status,
            "breached": breached,
            "redacted_url": redacted,
        },
    )


def evaluate_drift_rate_threshold(
    summary: dict[str, Any],
    *,
    max_drift_rate: float,
) -> DriftRateThresholdResult:
    """Evaluate a drift-rate trend summary against a threshold.

    Returns a JSON-ready dict with breached (bool), drift_rate (float), and
    threshold (float). Missing or None drift_rate is treated as 0.0. Breach
    is strictly greater than (equality is not a breach). No I/O, no network,
    no new dependencies.
    """
    from data_quality_toolkit.application.monitoring.thresholds import (
        evaluate_drift_rate_threshold as _impl,
    )

    return cast(DriftRateThresholdResult, _impl(summary, max_drift_rate=max_drift_rate))


def evaluate_psi_threshold(
    columns: list[dict[str, Any]],
    *,
    max_psi: float,
) -> PsiThresholdResult:
    """Evaluate per-column PSI values against a threshold.

    Returns a JSON-ready dict with breached (bool), threshold (float), and
    offenders (list of {column_name, psi} dicts). Skips None PSI values safely.
    Breach is strictly greater than (equality is not a breach). Offender ordering
    matches input order. No I/O, no network, no new dependencies.
    """
    from data_quality_toolkit.application.monitoring.thresholds import (
        evaluate_psi_threshold as _impl,
    )

    return cast(PsiThresholdResult, _impl(columns, max_psi=max_psi))
