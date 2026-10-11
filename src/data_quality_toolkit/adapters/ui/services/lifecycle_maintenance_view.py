"""Safe projection of a lifecycle maintenance report into a renderable view (H4).

This is the trust boundary between the diagnostics service and the Start page.
The service returns a report that deliberately carries machine-only data — a
resolved location handle and per-artifact locators holding absolute paths — so a
page must never render it directly. :func:`project_maintenance` reads that report
and returns frozen value types built only from primitives that are already safe
to show: an opaque reference, a bounded application-controlled label, a fixed
reason code, and fixed guidance chosen at authoring time.

The projection also enforces the separation the surface depends on: findings that
can only be *explained* are kept apart from the abandoned temporary files that
may be *selected and deleted*, so no destructive control can ever appear beside a
managed record.

Pure: no I/O, no Streamlit, no session state, no mutation. It re-reads an
already-produced report and shapes safe views.
"""

from __future__ import annotations

from dataclasses import dataclass

from data_quality_toolkit.adapters.ui.services.confirmation_capability import capability_guidance
from data_quality_toolkit.adapters.ui.services.lifecycle_maintenance import (
    STATE_LOCATION_ABSENT,
    STATE_LOCATION_UNAVAILABLE,
    STATE_NOT_SCANNED,
    STATE_OK,
    STATE_ROOT_MISSING,
    STATE_SCAN_LIMIT_EXCEEDED,
    CleanupOutcome,
    CleanupResult,
    CleanupStatus,
    DiagnosticCategory,
    DiagnosticRecord,
    LifecycleDiagnosticsReport,
)

__all__ = [
    "CATEGORY_LABELS",
    "CLEANUP_SECTION_TITLE",
    "ISSUE_SECTION_TITLE",
    "MAINTENANCE_NOTICES",
    "MAX_CLEANUP_ROWS",
    "MAX_ISSUE_ROWS",
    "CleanupItemRow",
    "CleanupResultView",
    "MaintenanceCategoryCount",
    "MaintenanceCleanupRow",
    "MaintenanceIssueRow",
    "MaintenanceView",
    "blank_maintenance_view",
    "project_cleanup_result",
    "project_maintenance",
]

MAX_ISSUE_ROWS = 20
MAX_CLEANUP_ROWS = 20

ISSUE_SECTION_TITLE = "Needs attention (not repairable here)"
CLEANUP_SECTION_TITLE = "Abandoned temporary files (cleanup eligible)"

CATEGORY_LABELS: dict[DiagnosticCategory, str] = {
    DiagnosticCategory.ABANDONED_TEMP_ARTIFACT: "Abandoned temporary file",
    DiagnosticCategory.MISSING_CSV_REFERENCE: "Missing dataset reference",
    DiagnosticCategory.MISSING_RECIPE_REFERENCE: "Missing recipe reference",
    DiagnosticCategory.CORRUPT_SIDECAR: "Corrupt version record",
    DiagnosticCategory.FILESYSTEM_CAPABILITY_UNAVAILABLE: "Filesystem capability unavailable",
}

# Fixed operator guidance. Every one of these is a safe next step the operator
# can take themselves; none of them is a repair this surface performs, and none
# names a path, identifier, or value.
_GUIDANCE: dict[DiagnosticCategory, str] = {
    DiagnosticCategory.MISSING_CSV_REFERENCE: (
        "The processed dataset this record points to is not readable. Inspect or restore "
        "it, or re-run the originating workflow to produce a fresh version. Cleanup cannot "
        "recreate it, and nothing here deletes the record."
    ),
    DiagnosticCategory.MISSING_RECIPE_REFERENCE: (
        "The recipe artifact this record points to is not readable. Inspect or restore it, "
        "or re-run the originating workflow to produce a fresh version. Cleanup cannot "
        "recreate it, and nothing here deletes the record."
    ),
    DiagnosticCategory.CORRUPT_SIDECAR: (
        "This version record could not be read as a valid lifecycle record. Leave it "
        "quarantined: it is never activated, rewritten, or repaired. Re-run the originating "
        "workflow to produce a fresh version."
    ),
}

_CAPABILITY_GUIDANCE = (
    "This workspace location does not provide a capability the lifecycle services "
    "require, so the managed-version location could not be inspected safely. Use a "
    "supported local filesystem location for the workspace, then run diagnostics again. "
    "Nothing was changed, repaired, or deleted."
)
_HARDLINK_REASON = "HARDLINK_UNSUPPORTED"

MAINTENANCE_NOTICES: tuple[str, ...] = (
    "Cleanup removes only verified abandoned temporary staging files. It cannot repair or "
    "restore corrupt version records, missing datasets, or missing recipes.",
    "No automatic, scheduled, startup, or background deletion happens. Nothing is deleted "
    "without an explicit selection and an explicit confirmation.",
    "Diagnostics are read-only and refresh only when you ask for them.",
)

_MESSAGES: dict[str, str] = {
    STATE_NOT_SCANNED: "Enter a Workspace Root above, then run lifecycle diagnostics.",
    STATE_OK: "Read-only diagnostics for the managed-version location of this workspace.",
    STATE_ROOT_MISSING: "The Workspace Root could not be found; nothing was inspected.",
    STATE_LOCATION_ABSENT: "No managed-version location exists for this workspace yet.",
    STATE_LOCATION_UNAVAILABLE: (
        "The managed-version location could not be inspected safely; nothing was changed."
    ),
    STATE_SCAN_LIMIT_EXCEEDED: (
        "The managed-version location has too many entries to inspect safely; nothing changed."
    ),
}

_CLEANUP_MESSAGES: dict[str, str] = {
    "NOT_CONFIRMED": "Confirm the cleanup checkbox before deleting anything. Nothing was deleted.",
    "NOT_SCANNED": "Run lifecycle diagnostics before requesting cleanup. Nothing was deleted.",
    "NOTHING_SELECTED": "Select at least one abandoned temporary file. Nothing was deleted.",
    "BATCH_TOO_LARGE": "Too many files selected for one cleanup. Nothing was deleted.",
    "LOCATION_CHANGED": (
        "The managed-version location changed since the scan. Nothing was deleted; run "
        "diagnostics again."
    ),
}
_CLEANUP_REFUSED_FALLBACK = "Cleanup was refused. Nothing was deleted."

_OUTCOME_LABELS: dict[CleanupOutcome, str] = {
    CleanupOutcome.DELETED: "Deleted",
    CleanupOutcome.SKIPPED: "Skipped",
    CleanupOutcome.UNAVAILABLE: "Already gone",
    CleanupOutcome.FAILED: "Failed",
}


# --- Frozen, display-safe view types ---------------------------------------


@dataclass(frozen=True, slots=True)
class MaintenanceCategoryCount:
    """One category and how many records it holds in this report."""

    label: str
    count: int


@dataclass(frozen=True, slots=True)
class MaintenanceIssueRow:
    """A diagnostic-only finding: explained, never selectable, never deleted."""

    reference: str
    category_label: str
    label: str
    reason_code: str
    guidance: str


@dataclass(frozen=True, slots=True)
class MaintenanceCleanupRow:
    """One abandoned temporary file the operator may explicitly select."""

    reference: str
    label: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class MaintenanceView:
    """The complete, bounded, privacy-safe maintenance surface."""

    state: str
    message: str
    scanned: bool
    counts: tuple[MaintenanceCategoryCount, ...]
    issue_rows: tuple[MaintenanceIssueRow, ...]
    cleanup_rows: tuple[MaintenanceCleanupRow, ...]
    issue_total: int
    cleanup_total: int
    issue_omitted: int
    cleanup_omitted: int
    notices: tuple[str, ...] = MAINTENANCE_NOTICES


@dataclass(frozen=True, slots=True)
class CleanupItemRow:
    """One per-artifact cleanup outcome, projected for display."""

    reference: str
    label: str
    outcome_label: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class CleanupResultView:
    """The bounded, privacy-safe summary of one cleanup attempt."""

    completed: bool
    message: str
    rows: tuple[CleanupItemRow, ...]
    deleted_count: int
    skipped_count: int
    unavailable_count: int
    failed_count: int


# --- Projection ------------------------------------------------------------


def _capability_text(record: DiagnosticRecord) -> str:
    """Reuse the confirmation service's own wording for a proven link limit."""
    if record.reason_code == _HARDLINK_REASON:
        return capability_guidance()
    return _CAPABILITY_GUIDANCE


def _guidance_for(record: DiagnosticRecord) -> str:
    if record.category is DiagnosticCategory.FILESYSTEM_CAPABILITY_UNAVAILABLE:
        return _capability_text(record)
    return _GUIDANCE.get(record.category, "")


def _issue_row(record: DiagnosticRecord) -> MaintenanceIssueRow:
    return MaintenanceIssueRow(
        reference=record.reference,
        category_label=CATEGORY_LABELS[record.category],
        label=record.label,
        reason_code=record.reason_code,
        guidance=_guidance_for(record),
    )


def _cleanup_row(record: DiagnosticRecord) -> MaintenanceCleanupRow:
    return MaintenanceCleanupRow(
        reference=record.reference,
        label=record.label,
        reason_code=record.reason_code,
    )


def _counts(report: LifecycleDiagnosticsReport) -> tuple[MaintenanceCategoryCount, ...]:
    tally = report.counts()
    return tuple(
        MaintenanceCategoryCount(label=CATEGORY_LABELS[category], count=count)
        for category, count in tally.items()
    )


def blank_maintenance_view() -> MaintenanceView:
    """The no-scan surface shown before the operator asks for diagnostics."""
    return MaintenanceView(
        state=STATE_NOT_SCANNED,
        message=_MESSAGES[STATE_NOT_SCANNED],
        scanned=False,
        counts=(),
        issue_rows=(),
        cleanup_rows=(),
        issue_total=0,
        cleanup_total=0,
        issue_omitted=0,
        cleanup_omitted=0,
    )


def project_maintenance(
    report: LifecycleDiagnosticsReport,
    *,
    max_issue_rows: int = MAX_ISSUE_ROWS,
    max_cleanup_rows: int = MAX_CLEANUP_ROWS,
) -> MaintenanceView:
    """Project a diagnostics report into the bounded, privacy-safe view.

    Ordering is preserved exactly as the service produced it; nothing is
    re-sorted or rescanned. Cleanup-eligible abandoned temporary files are
    separated from diagnostic-only findings, rows are truncated to the display
    bounds, and the number omitted by that truncation is reported. No locator,
    resolved path, absolute path, identifier, digest, or exception crosses this
    boundary.
    """
    cleanup_records = [record for record in report.records if record.cleanup_eligible]
    issue_records = [record for record in report.records if not record.cleanup_eligible]
    issue_rows = tuple(_issue_row(record) for record in issue_records[:max_issue_rows])
    cleanup_rows = tuple(_cleanup_row(record) for record in cleanup_records[:max_cleanup_rows])
    return MaintenanceView(
        state=report.state,
        message=_MESSAGES.get(report.state, _MESSAGES[STATE_LOCATION_UNAVAILABLE]),
        scanned=report.scanned,
        counts=_counts(report),
        issue_rows=issue_rows,
        cleanup_rows=cleanup_rows,
        issue_total=len(issue_records),
        cleanup_total=len(cleanup_records),
        issue_omitted=len(issue_records) - len(issue_rows),
        cleanup_omitted=len(cleanup_records) - len(cleanup_rows),
    )


def project_cleanup_result(result: CleanupResult) -> CleanupResultView:
    """Project a cleanup outcome into fixed labels and fixed reason codes."""
    if result.status is CleanupStatus.REFUSED:
        return CleanupResultView(
            completed=False,
            message=_CLEANUP_MESSAGES.get(result.reason_code, _CLEANUP_REFUSED_FALLBACK),
            rows=(),
            deleted_count=0,
            skipped_count=0,
            unavailable_count=0,
            failed_count=0,
        )
    rows = tuple(
        CleanupItemRow(
            reference=item.reference,
            label=item.label,
            outcome_label=_OUTCOME_LABELS[item.outcome],
            reason_code=item.reason_code,
        )
        for item in result.items
    )
    return CleanupResultView(
        completed=True,
        message=(
            f"Cleanup finished. Deleted {result.deleted_count}, skipped {result.skipped_count}, "
            f"already gone {result.unavailable_count}, failed {result.failed_count}."
        ),
        rows=rows,
        deleted_count=result.deleted_count,
        skipped_count=result.skipped_count,
        unavailable_count=result.unavailable_count,
        failed_count=result.failed_count,
    )
