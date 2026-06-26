"""Public result TypedDicts for the DQT public API.

These types describe the return shapes of stable public API functions.
They are dicts at runtime — no runtime cost, fully backward-compatible.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


class DriftRateThresholdResult(TypedDict):
    """Return type of evaluate_drift_rate_threshold."""

    breached: bool
    drift_rate: float
    threshold: float


class PsiOffender(TypedDict):
    """One per-column entry in PsiThresholdResult.offenders."""

    column_name: str
    psi: float


class PsiThresholdResult(TypedDict):
    """Return type of evaluate_psi_threshold."""

    breached: bool
    threshold: float
    offenders: list[PsiOffender]


class ColumnPlan(TypedDict):
    """One per-column entry in PlanCsvResult.columns."""

    column: str
    dtype: str
    issues: str
    recommendations: str


class PlanCsvResult(TypedDict):
    """Return type of plan_csv."""

    dataset_id: str
    columns: list[ColumnPlan]


class DimTimeResult(TypedDict):
    """Return type of generate_dim_time."""

    rows: int
    start_date: str
    end_date: str
    week_start: int
    fiscal_year_start: NotRequired[int]
    path: NotRequired[str]


class KpiEmitResult(TypedDict):
    """Return type of kpi_emit."""

    status: Literal["success"]
    kpis: int
    dax: str
    tmsl: str


class KpiGraphResult(TypedDict):
    """Return type of kpi_graph."""

    status: Literal["success"]
    graph: str
    format: str
    nodes: int


class SummarizeDriftTrendsResult(TypedDict):
    """Return type of summarize_drift_trends_sqlite."""

    total_runs: int
    drifted_runs: int
    non_drifted_runs: int
    drift_rate: float
    latest_run_id: str | None
    latest_created_at: str | None
    latest_drift_detected: bool | None
    columns_tested_total: int
    columns_tested_average: float
    columns_drifted_total: int
    columns_drifted_average: float


class DriftRunRow(TypedDict):
    """One row returned by read_drift_runs_sqlite (a drift_runs table row).

    Keys are the fixed SELECT columns and are always present. drift_detected is
    the stored 0/1 integer (or None), not a bool — consumers normalize as needed.
    """

    run_id: str
    created_at: str | None
    baseline_path: str | None
    current_path: str | None
    baseline_dataset_id: str | None
    current_dataset_id: str | None
    status: str | None
    alpha: float | None
    columns_tested: int | None
    columns_skipped: int | None
    columns_drifted: int | None
    drift_detected: int | None
    report_path: str | None
    schema_version: str | None


class DriftColumnRow(TypedDict):
    """One row returned by read_drift_columns_sqlite (a drift_columns table row).

    Keys are the fixed SELECT columns and are always present. drift_detected is
    the stored 0/1 integer (or None), not a bool.
    """

    run_id: str
    column_name: str
    kind: str | None
    test: str | None
    statistic: float | None
    p_value: float | None
    drift_detected: int | None
    reference_n: int | None
    current_n: int | None
    status: str | None
    skip_reason: str | None
    psi: float | None
    js_distance: float | None
    wasserstein: float | None


class DriftDistributionRow(TypedDict):
    """One row from read_drift_distributions_sqlite (a distribution-bin row).

    Keys are the fixed SELECT columns and are always present.
    """

    run_id: str
    column_name: str
    kind: str | None
    bin_index: int
    bin_label: str | None
    reference_prob: float | None
    current_prob: float | None


class DriftHistoryXlsxExportResult(TypedDict):
    """Return type of export_drift_history_xlsx."""

    output_path: str
    sheets: list[str]
    row_counts: dict[str, int]


class MonitoringDuckdbExportResult(TypedDict):
    """Return type of export_monitoring_duckdb."""

    input_db_path: str
    output_path: str
    tables: list[str]
    row_counts: dict[str, int]
    overwritten: bool


class DriftPlotsExportResult(TypedDict):
    """Return type of export_drift_plots."""

    output_dir: str
    charts: list[str]
    row_counts: dict[str, int]


class DriftNotificationSendResult(TypedDict):
    """Return type of send_drift_notification."""

    payload: dict[str, Any]
    sent: bool
    status: int | None
    breached: bool
    redacted_url: str


class CsvMeta(TypedDict):
    """Loader/chunked metadata envelope shared by profile/assess/export results.

    Full-load adds rows/cols; chunked adds chunksize instead — both NotRequired.
    """

    dataset_id: str
    source_path: str
    file_size_bytes: int
    modified_ts: str
    sample_applied: bool
    sample_size: int | None
    rows: NotRequired[int]
    cols: NotRequired[int]
    chunksize: NotRequired[int]


class CsvProfileColumn(TypedDict):
    """One per-column entry in CsvProfile.columns.

    unique is full-load only; min/max appear only for numeric columns.
    """

    name: str
    dtype: str
    nulls: int
    unique: NotRequired[int]
    min: NotRequired[float | None]
    max: NotRequired[float | None]


class CsvProfile(TypedDict):
    """Profile body of profile_csv / assess_csv (memory_mb is None in chunked mode)."""

    rows: int
    cols: int
    memory_mb: float | None
    columns: list[CsvProfileColumn]


class CsvProfileCompact(TypedDict):
    """Compact profile body of export_csv — omits the per-column list."""

    rows: int
    cols: int
    memory_mb: float | None


class CsvAssessmentIssue(TypedDict, total=False):
    """One per-issue entry in CsvAssessment.issues (all keys optional)."""

    type: str
    column: str | None
    pct: float | None
    severity: str
    category: str
    message: str


class CsvAssessment(TypedDict):
    """Assessment body of assess_csv / export_csv.

    quality_score is full-load only; assessment_mode / approximate /
    unsupported_rules appear only in chunked mode — all NotRequired.
    """

    run_id: str
    dataset_id: str
    ts: str
    score: float
    completeness_score: float
    issues: list[CsvAssessmentIssue]
    quality_score: NotRequired[float]
    assessment_mode: NotRequired[Literal["chunked"]]
    approximate: NotRequired[bool]
    unsupported_rules: NotRequired[list[str]]


class CsvStarExport(TypedDict):
    """The star block of export_csv."""

    tables: list[str]
    rows: dict[str, int]


class CsvExportPaths(TypedDict):
    """The export_paths map of export_csv (manifest is conditional)."""

    dim_dataset: str
    dim_column: str
    fact_profile_runs: str
    fact_quality_metrics: str
    fact_issues: str
    relationships: str
    quality_report: str
    quality_history: str
    manifest: NotRequired[str]


class ProfileCsvResult(TypedDict):
    """Return envelope of profile_csv (chunked adds approximate/unsupported_metrics)."""

    run_id: str
    dataset_id: str
    ts: str
    meta: CsvMeta
    profile: CsvProfile
    approximate: NotRequired[bool]
    unsupported_metrics: NotRequired[list[str]]


class AssessCsvResult(TypedDict):
    """Return envelope of assess_csv (chunked adds top-level approximate)."""

    run_id: str
    dataset_id: str
    ts: str
    duration_secs: float
    meta: CsvMeta
    profile: CsvProfile
    assessment: CsvAssessment
    approximate: NotRequired[bool]


class ExportCsvResult(TypedDict):
    """Return envelope of export_csv (full-load only)."""

    run_id: str
    dataset_id: str
    ts: str
    duration_secs: float
    meta: CsvMeta
    profile: CsvProfileCompact
    assessment: CsvAssessment
    star: CsvStarExport
    export_paths: CsvExportPaths


class PowerBIPackageResult(TypedDict):
    """Return type of build_powerbi_package.

    Mirrors the internal exporter result (export_powerbi_package). files is a
    name->path mapping; time_range is the "<start> to <end>" string; validation
    is the normalized validator output (valid/errors/warnings[/csv_count]).
    """

    package_dir: str
    files: dict[str, str]
    validation: dict[str, Any]
    time_range: str
    base_folder: str
    dim_time_path: str


__all__ = [
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
    "DriftHistoryXlsxExportResult",
    "MonitoringDuckdbExportResult",
    "DriftPlotsExportResult",
    "DriftNotificationSendResult",
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
    # Power BI package contract (G8C3B)
    "PowerBIPackageResult",
]
