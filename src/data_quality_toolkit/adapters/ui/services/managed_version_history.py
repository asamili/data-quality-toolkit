"""Pure safe-projection boundary for the Start-page managed-version history.

This module is the single trust boundary between the Phase-8 discovery service
(:mod:`...services.dataset_discovery`) and the Start page. Discovery returns rich,
machine-side objects (``DiscoveryResult`` carrying ``DatasetVersionRecord``,
``InternalLocator``, canonical paths, full UUIDs, and content hashes). The Start
page and its renderer must never receive or render those objects directly.

:func:`project_history` inspects a ``DiscoveryResult`` internally and returns new
frozen, slotted, UI-safe value types that contain *only* primitive, display-safe
fields — sanitized labels, collision-safe short ids, shortened family/parent
summaries, a UTC-normalized timestamp, fixed creation/availability labels, opaque
issue/duplicate references, and generic issue/duplicate/root states. No record,
locator, canonical/relative path, filename/stem, full UUID, content hash, family
UUID, raw exception, or arbitrary untrusted JSON crosses this boundary.

This module implements no reopen, activation, revalidation, CSV loading, recipe
execution, or lineage. It imports neither Streamlit, session state,
``DatasetContext``, nor the activation service, and it mutates nothing. It only
reads an already-produced ``DiscoveryResult`` and shapes safe views.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC

from data_quality_toolkit.adapters.ui.services.dataset_discovery import (
    DiscoveredVersion,
    DiscoveryIssue,
    DiscoveryResult,
    DuplicateGroup,
    RecordStatus,
    RootStatus,
)
from data_quality_toolkit.adapters.ui.services.dataset_versions import (
    CreationMechanism,
    DatasetVersionRecord,
    ParentRef,
)

__all__ = [
    "MAX_DUPLICATE_ROWS",
    "MAX_ISSUE_ROWS",
    "MAX_VALID_ROWS",
    "STATE_DIRECTORY_ABSENT",
    "STATE_DIRECTORY_CHANGED",
    "STATE_EMPTY",
    "STATE_LIMIT_EXCEEDED",
    "STATE_NON_DIRECTORY",
    "STATE_NO_WORKSPACE_ROOT",
    "STATE_OK",
    "STATE_PERMISSION_DENIED",
    "STATE_ROOT_MISSING",
    "STATE_UNRESOLVABLE",
    "STATE_UNSAFE_DIRECTORY",
    "ManagedVersionDuplicateRow",
    "ManagedVersionHistoryRow",
    "ManagedVersionHistoryView",
    "ManagedVersionIssueRow",
    "SET_ACTIVE_ACTION_LABEL",
    "blank_workspace_view",
    "project_history",
]

# --- Bounded display limits (independent of discovery bounds) --------------

MAX_VALID_ROWS = 20
MAX_ISSUE_ROWS = 20
MAX_DUPLICATE_ROWS = 10

# --- Fixed, generic root/discovery state tokens ----------------------------

STATE_NO_WORKSPACE_ROOT = "no_workspace_root"
STATE_OK = "ok"
STATE_EMPTY = "empty"
STATE_DIRECTORY_ABSENT = "directory_absent"
STATE_ROOT_MISSING = "root_missing"
STATE_NON_DIRECTORY = "non_directory"
STATE_PERMISSION_DENIED = "permission_denied"
STATE_UNRESOLVABLE = "unresolvable"
STATE_UNSAFE_DIRECTORY = "unsafe_directory"
STATE_DIRECTORY_CHANGED = "directory_changed"
STATE_LIMIT_EXCEEDED = "limit_exceeded"

# --- Fixed operator-facing labels ------------------------------------------

SET_ACTIVE_ACTION_LABEL = "Set Active"

_ROOT_SUMMARY = "Root version"
_CSV_AVAILABLE = "CSV available"
_CSV_UNAVAILABLE = "CSV unavailable"
_RECIPE_AVAILABLE = "Recipe available"
_RECIPE_NONE = "No recipe"
_RECIPE_UNAVAILABLE = "Recipe unavailable"
_DUPLICATE_QUARANTINED = "Quarantined"

_MECHANISM_LABELS: dict[CreationMechanism, str] = {
    CreationMechanism.ROOT_IMPORT: "Root import",
    CreationMechanism.PREPROCESS_RECIPE: "Preprocess recipe",
}

_ISSUE_STATUS_LABELS: dict[RecordStatus, str] = {
    RecordStatus.CORRUPT: "Corrupt record",
    RecordStatus.UNSUPPORTED: "Unsupported record",
    RecordStatus.UNAVAILABLE: "Unavailable artifact",
}

_DUPLICATE_KIND_LABELS: dict[str, str] = {
    "duplicate_identical": "Identical duplicate",
    "duplicate_conflict": "Conflicting duplicate",
}

_ROOT_STATE_TOKENS: dict[RootStatus, str] = {
    RootStatus.MISSING: STATE_ROOT_MISSING,
    RootStatus.NOT_A_DIRECTORY: STATE_NON_DIRECTORY,
    RootStatus.PERMISSION_DENIED: STATE_PERMISSION_DENIED,
    RootStatus.UNRESOLVABLE: STATE_UNRESOLVABLE,
    RootStatus.UNSAFE_DISCOVERY_DIRECTORY: STATE_UNSAFE_DIRECTORY,
    RootStatus.LIMIT_EXCEEDED: STATE_LIMIT_EXCEEDED,
    RootStatus.DIRECTORY_CHANGED: STATE_DIRECTORY_CHANGED,
}

# Generic messages. None contains a workspace path, filename, identifier, or raw
# exception text: every value is a fixed literal chosen at authoring time.
_MESSAGES: dict[str, str] = {
    STATE_NO_WORKSPACE_ROOT: "Enter a Workspace Root above to list managed versions.",
    STATE_OK: "Recent managed versions for this workspace.",
    STATE_EMPTY: "No managed versions found for this workspace yet.",
    STATE_DIRECTORY_ABSENT: "No managed-version location exists for this workspace yet.",
    STATE_ROOT_MISSING: "The Workspace Root could not be found.",
    STATE_NON_DIRECTORY: "The Workspace Root or its managed-version location is not a directory.",
    STATE_PERMISSION_DENIED: "Access to the managed-version location was denied.",
    STATE_UNRESOLVABLE: "The Workspace Root or managed-version location could not be resolved.",
    STATE_UNSAFE_DIRECTORY: (
        "The managed-version location resolved outside the Workspace Root and was refused."
    ),
    STATE_DIRECTORY_CHANGED: (
        "The managed-version location changed during scanning; nothing was loaded."
    ),
    STATE_LIMIT_EXCEEDED: "The managed-version location has too many entries to list safely.",
}


# --- Frozen, slotted, UI-safe projected value types ------------------------


@dataclass(frozen=True, slots=True)
class ManagedVersionHistoryRow:
    """One recent valid managed version, projected for display only.

    Every field is a primitive, display-safe string. There is no record, locator,
    path, filename, full UUID, content hash, or family UUID here by construction.
    """

    label: str
    short_version_id: str
    family_summary: str
    parent_summary: str
    confirmation_timestamp: str
    creation_mechanism: str
    csv_availability: str
    recipe_availability: str
    action_label: str


@dataclass(frozen=True, slots=True)
class ManagedVersionIssueRow:
    """A corrupt, unsupported, or unavailable record, projected generically."""

    reference: str
    status_label: str
    label: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class ManagedVersionDuplicateRow:
    """A quarantined duplicate group. Never selectable and carries no member locator."""

    kind_label: str
    short_version_id: str
    member_count: int
    member_references: tuple[str, ...]
    status_label: str


@dataclass(frozen=True, slots=True)
class ManagedVersionHistoryView:
    """The complete, bounded, privacy-safe Start-page history surface.

    This is the *only* type handed to the renderer. It holds fixed state tokens,
    generic messages, projected rows, and bounded totals/omitted counts.
    """

    state: str
    message: str
    scanned: bool
    valid_rows: tuple[ManagedVersionHistoryRow, ...]
    issue_rows: tuple[ManagedVersionIssueRow, ...]
    duplicate_rows: tuple[ManagedVersionDuplicateRow, ...]
    valid_total: int
    issue_total: int
    duplicate_total: int
    valid_omitted: int
    issue_omitted: int
    duplicate_omitted: int


# --- Short-identifier helpers (never emit a full UUID) ----------------------


def _short_hex(value: str) -> str:
    """Return the first eight hex chars of a UUID, or ``""`` when unparsable."""
    try:
        return uuid.UUID(value).hex[:8]
    except (AttributeError, TypeError, ValueError):
        return ""


def _family_summary(family_id: str) -> str:
    short = _short_hex(family_id)
    return f"Family f-{short}" if short else "Family (unavailable)"


def _parent_summary(parent: ParentRef | None) -> str:
    if parent is None or parent.version_id is None:
        return _ROOT_SUMMARY
    short = _short_hex(parent.version_id)
    return f"Parent v-{short}" if short else _ROOT_SUMMARY


# --- Fixed label helpers ----------------------------------------------------


def _confirmation_timestamp(record: DatasetVersionRecord) -> str:
    """Normalize the confirmation time consistently to UTC (no path, no locale)."""
    return record.created_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _csv_availability(status: str) -> str:
    return _CSV_AVAILABLE if status == "ARTIFACT_OK" else _CSV_UNAVAILABLE


def _recipe_availability(status: str) -> str:
    if status == "ARTIFACT_OK":
        return _RECIPE_AVAILABLE
    if status == "RECIPE_ABSENT":
        return _RECIPE_NONE
    return _RECIPE_UNAVAILABLE


# --- Per-item projection ----------------------------------------------------


def _project_row(version: DiscoveredVersion) -> ManagedVersionHistoryRow:
    record = version.record
    return ManagedVersionHistoryRow(
        label=version.display.label,
        short_version_id=version.display.short_version_id,
        family_summary=_family_summary(record.family_id),
        parent_summary=_parent_summary(record.parent),
        confirmation_timestamp=_confirmation_timestamp(record),
        creation_mechanism=_MECHANISM_LABELS.get(record.created_by, "Managed version"),
        csv_availability=_csv_availability(version.csv_status),
        recipe_availability=_recipe_availability(version.recipe_status),
        action_label=SET_ACTIVE_ACTION_LABEL,
    )


def _project_issue(issue: DiscoveryIssue) -> ManagedVersionIssueRow:
    return ManagedVersionIssueRow(
        reference=issue.reference,
        status_label=_ISSUE_STATUS_LABELS.get(issue.status, "Issue"),
        label=issue.label,
        reason_code=issue.reason_code,
    )


def _project_duplicate(group: DuplicateGroup) -> ManagedVersionDuplicateRow:
    return ManagedVersionDuplicateRow(
        kind_label=_DUPLICATE_KIND_LABELS.get(group.kind, "Duplicate"),
        short_version_id=group.short_version_id,
        member_count=group.member_count,
        member_references=group.member_references,
        status_label=_DUPLICATE_QUARANTINED,
    )


# --- Root/discovery state projection ---------------------------------------


def _project_state(result: DiscoveryResult) -> str:
    if result.root_status is RootStatus.OK:
        if result.root_reason == "DISCOVERY_DIR_ABSENT":
            return STATE_DIRECTORY_ABSENT
        if not result.versions and not result.issues and not result.duplicates:
            return STATE_EMPTY
        return STATE_OK
    return _ROOT_STATE_TOKENS.get(result.root_status, STATE_UNRESOLVABLE)


# --- Public entry points ----------------------------------------------------


def blank_workspace_view() -> ManagedVersionHistoryView:
    """Return the no-scan view used when the Workspace Root is blank.

    This performs no discovery and touches no filesystem: it is a fixed, safe
    prompt to enter a Workspace Root.
    """
    return ManagedVersionHistoryView(
        state=STATE_NO_WORKSPACE_ROOT,
        message=_MESSAGES[STATE_NO_WORKSPACE_ROOT],
        scanned=False,
        valid_rows=(),
        issue_rows=(),
        duplicate_rows=(),
        valid_total=0,
        issue_total=0,
        duplicate_total=0,
        valid_omitted=0,
        issue_omitted=0,
        duplicate_omitted=0,
    )


def project_history(
    result: DiscoveryResult,
    *,
    max_valid_rows: int = MAX_VALID_ROWS,
    max_issue_rows: int = MAX_ISSUE_ROWS,
    max_duplicate_rows: int = MAX_DUPLICATE_ROWS,
) -> ManagedVersionHistoryView:
    """Project a Phase-8 ``DiscoveryResult`` into a bounded, privacy-safe view.

    Ordering is preserved exactly as discovery produced it (newest-first for valid
    versions); nothing is re-sorted or rescanned. Rows are truncated to the display
    bounds and the number omitted by that truncation is reported. Only primitive,
    display-safe values are copied out — no record, locator, path, full UUID, hash,
    family UUID, or raw exception crosses this boundary.
    """
    state = _project_state(result)
    valid_rows = tuple(_project_row(version) for version in result.versions[:max_valid_rows])
    issue_rows = tuple(_project_issue(issue) for issue in result.issues[:max_issue_rows])
    duplicate_rows = tuple(
        _project_duplicate(group) for group in result.duplicates[:max_duplicate_rows]
    )
    valid_total = len(result.versions)
    issue_total = len(result.issues)
    duplicate_total = len(result.duplicates)
    return ManagedVersionHistoryView(
        state=state,
        message=_MESSAGES.get(state, ""),
        scanned=True,
        valid_rows=valid_rows,
        issue_rows=issue_rows,
        duplicate_rows=duplicate_rows,
        valid_total=valid_total,
        issue_total=issue_total,
        duplicate_total=duplicate_total,
        valid_omitted=valid_total - len(valid_rows),
        issue_omitted=issue_total - len(issue_rows),
        duplicate_omitted=duplicate_total - len(duplicate_rows),
    )
