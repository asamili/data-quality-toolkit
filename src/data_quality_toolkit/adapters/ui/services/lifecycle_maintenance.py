"""Bounded lifecycle diagnostics and explicit abandoned-temp cleanup (H4).

Two operations live here and nothing else:

* :func:`collect_lifecycle_diagnostics` — a read-only, deterministic, bounded
  inspection of the single authoritative lifecycle location that reports what an
  operator may need to act on. It mutates nothing: no file, no directory, no
  sidecar, no session, no active pointer.
* :func:`execute_lifecycle_cleanup` — deletion of *individually selected*,
  independently revalidated, provably abandoned, application-owned temporary
  staging files, and of nothing else.

Everything the classifier can reuse, it reuses. Managed-record classification
comes verbatim from the accepted Phase-8 discovery service: this module defines
no second sidecar parser, no second schema check, and no second error taxonomy.
A record whose CSV reference is missing stays a *missing reference* and is never
re-presented as a corrupt sidecar, because discovery already distinguishes the
two. Staging-artifact labels are vetted by the confirmation-capability module's
own display guard rather than by a second one written here, and the wording for a
proven hard-link limitation is reused verbatim by the presentation layer.

What this module deliberately does **not** do:

* it never scans the repository, workspace root, home directory, drive, an
  arbitrary path, or any directory other than ``<workspace_root>/preprocessed``;
* it never recurses, globs, or walks — enumeration is one flat ``scandir``;
* it never deletes a directory, symlink, sidecar, CSV, recipe, export, managed
  version, unknown file, or anything it did not positively prove this
  application created and then abandoned;
* it never repairs, rewrites, registers, migrates, re-labels, or activates;
* it never runs on import, on startup, on a timer, on a thread, or on a retry
  loop — both entry points are called only from an explicit operator action.

Standard library only: no Streamlit, no session state, no pandas.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from data_quality_toolkit.adapters.ui.services.confirmation_capability import safe_temp_label
from data_quality_toolkit.adapters.ui.services.dataset_discovery import (
    ARTIFACT_KIND_RECIPE,
    DISCOVERY_SUBFOLDER,
    DiscoveryIssue,
    DiscoveryResult,
    RecordStatus,
    RootStatus,
    discover_managed_versions,
)

__all__ = [
    "ABANDONED_AFTER_SECONDS",
    "MAX_CLEANUP_BATCH",
    "MAX_ENTRIES_OBSERVED",
    "MAX_TEMP_ARTIFACTS",
    "STATE_LOCATION_ABSENT",
    "STATE_LOCATION_UNAVAILABLE",
    "STATE_NOT_SCANNED",
    "STATE_OK",
    "STATE_ROOT_MISSING",
    "STATE_SCAN_LIMIT_EXCEEDED",
    "CleanupItemResult",
    "CleanupOutcome",
    "CleanupResult",
    "CleanupStatus",
    "DiagnosticCategory",
    "DiagnosticRecord",
    "LifecycleDiagnosticsReport",
    "TempArtifactLocator",
    "collect_lifecycle_diagnostics",
    "execute_lifecycle_cleanup",
    "is_owned_temp_name",
]

# --- Declared bounds -------------------------------------------------------

#: Directory entries this scan will look at before it refuses to continue.
MAX_ENTRIES_OBSERVED = 2_000
#: Application-owned temporary artifacts retained as records in one report.
MAX_TEMP_ARTIFACTS = 50
#: Temporary artifacts one explicit cleanup call may delete.
MAX_CLEANUP_BATCH = 20

# How old an application-owned staging file must be before it can be called
# abandoned. Every lifecycle producer stages, publishes, and sweeps its temporary
# files inside one synchronous confirmation call within a single operator action;
# nothing holds a staging file across a rerun, a session, or a process. A full day
# therefore exceeds the longest possible in-flight staging window by orders of
# magnitude, so an active or newly created temporary file can never be classified
# as abandoned. A file whose modification time lies in the future is likewise
# never eligible.
ABANDONED_AFTER_SECONDS = 86_400
_ABANDONED_AFTER_NS = ABANDONED_AFTER_SECONDS * 1_000_000_000

_MAX_TEMP_NAME_CHARS = 160
_REFERENCE_HEX_CHARS = 12

# Exactly the staging name ``dataset_confirmation`` creates for the two final
# artifacts it publishes inside the lifecycle directory: a leading dot, the final
# name (``<stem>[-N].csv`` or that plus the sidecar suffix), the eight-character
# ``mkstemp`` token, and a ``.tmp`` suffix. The same shape the managed
# reprocessing rollback already admits as its own reserved temporary name. The
# character classes exclude every path separator, drive letter, UNC prefix, URI
# scheme, and ``~`` shorthand, and every part is length-bounded. A name that does
# not match is not proven to belong to this application and is therefore never
# eligible for deletion.
_OWNED_TEMP_NAME = re.compile(
    r"^\.(?:[A-Za-z0-9._-]{1,110}\.csv(?:\.dqtv\.json)?)\.[a-z0-9_]{8}\.tmp$"
)

_GENERIC_TEMP_LABEL = "Temporary staging file"
_CAPABILITY_LABEL = "Lifecycle location capability"
_CAPABILITY_REFERENCE = "capability-0001"
_HARDLINK_REASON = "HARDLINK_UNSUPPORTED"

# --- Report state tokens ---------------------------------------------------

STATE_NOT_SCANNED = "not_scanned"
STATE_OK = "ok"
STATE_ROOT_MISSING = "root_missing"
STATE_LOCATION_ABSENT = "location_absent"
STATE_LOCATION_UNAVAILABLE = "location_unavailable"
STATE_SCAN_LIMIT_EXCEEDED = "scan_limit_exceeded"


# --- Public value types ----------------------------------------------------


class DiagnosticCategory(StrEnum):
    """The five distinct things this surface can report.

    Only :attr:`ABANDONED_TEMP_ARTIFACT` is ever cleanup-eligible. Every other
    category is diagnostic-only: it is reported, explained, and left alone.
    """

    ABANDONED_TEMP_ARTIFACT = "abandoned_temp_artifact"
    MISSING_CSV_REFERENCE = "missing_csv_reference"
    MISSING_RECIPE_REFERENCE = "missing_recipe_reference"
    CORRUPT_SIDECAR = "corrupt_sidecar"
    FILESYSTEM_CAPABILITY_UNAVAILABLE = "filesystem_capability_unavailable"


# Fixed presentation order, so a report reads the same way every time.
_CATEGORY_ORDER: tuple[DiagnosticCategory, ...] = (
    DiagnosticCategory.ABANDONED_TEMP_ARTIFACT,
    DiagnosticCategory.MISSING_CSV_REFERENCE,
    DiagnosticCategory.MISSING_RECIPE_REFERENCE,
    DiagnosticCategory.CORRUPT_SIDECAR,
    DiagnosticCategory.FILESYSTEM_CAPABILITY_UNAVAILABLE,
)
_CATEGORY_RANK: dict[DiagnosticCategory, int] = {
    category: index for index, category in enumerate(_CATEGORY_ORDER)
}


class CleanupOutcome(StrEnum):
    """What happened to one individually selected artifact."""

    DELETED = "deleted"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class CleanupStatus(StrEnum):
    """Whether the cleanup call ran at all."""

    COMPLETED = "completed"
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class DiagnosticRecord:
    """One operator-facing finding.

    Every field is a bounded, application-controlled primitive: an opaque stable
    reference, a fixed or basename-only label, and a fixed reason code. No
    absolute path, parent directory, drive, UNC name, full version id, digest,
    recipe content, dataset value, raw sidecar content, or exception text can
    appear here by construction.
    """

    category: DiagnosticCategory
    reference: str
    label: str
    reason_code: str
    cleanup_eligible: bool = False


@dataclass(frozen=True, slots=True)
class TempArtifactLocator:
    """Machine-only identity of one proven-eligible temporary artifact.

    Never rendered: it deliberately holds the resolved path used for deletion.
    A cleanup call re-proves every property recorded here immediately before it
    unlinks anything, so a stale locator can only cause a skip, never a wrong
    deletion.
    """

    reference: str
    basename: str
    resolved_path: str
    parent_dev: int
    parent_ino: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class _Location:
    """Machine-only handle for the one directory this module may look at."""

    root: Path
    directory: Path
    dev: int
    ino: int


@dataclass(frozen=True, slots=True)
class LifecycleDiagnosticsReport:
    """Immutable outcome of one bounded, read-only diagnostics scan.

    ``records`` is the operator-facing surface. ``candidates`` and ``location``
    are machine-only, mirroring the Phase-8 separation between display data and
    internal locators; a renderer must never receive them.
    """

    state: str
    scanned: bool
    records: tuple[DiagnosticRecord, ...] = ()
    candidates: tuple[TempArtifactLocator, ...] = ()
    location: _Location | None = None
    entries_observed: int = 0
    temp_omitted: int = 0
    reason_code: str = ""

    def counts(self) -> dict[DiagnosticCategory, int]:
        """Return the per-category record count, every category always present."""
        tally = dict.fromkeys(_CATEGORY_ORDER, 0)
        for record in self.records:
            tally[record.category] += 1
        return tally

    @property
    def cleanup_eligible_total(self) -> int:
        return sum(1 for record in self.records if record.cleanup_eligible)


@dataclass(frozen=True, slots=True)
class CleanupItemResult:
    """Per-artifact outcome, privacy-safe by the same rules as a record."""

    reference: str
    label: str
    outcome: CleanupOutcome
    reason_code: str


@dataclass(frozen=True, slots=True)
class CleanupResult:
    """Outcome of one explicit, confirmed cleanup request."""

    status: CleanupStatus
    reason_code: str = ""
    items: tuple[CleanupItemResult, ...] = field(default_factory=tuple)

    def _count(self, outcome: CleanupOutcome) -> int:
        return sum(1 for item in self.items if item.outcome is outcome)

    @property
    def deleted_count(self) -> int:
        return self._count(CleanupOutcome.DELETED)

    @property
    def skipped_count(self) -> int:
        return self._count(CleanupOutcome.SKIPPED)

    @property
    def unavailable_count(self) -> int:
        return self._count(CleanupOutcome.UNAVAILABLE)

    @property
    def failed_count(self) -> int:
        return self._count(CleanupOutcome.FAILED)


# --- Small shared helpers --------------------------------------------------


def _normcase(path: Path | str) -> str:
    return os.path.normcase(str(path))


def _is_confined(target: Path, root: Path) -> bool:
    """True when ``target`` is equal to or beneath ``root`` (case-normalized)."""
    target_norm = _normcase(target)
    root_norm = _normcase(root)
    try:
        return os.path.commonpath([target_norm, root_norm]) == root_norm
    except ValueError:
        return False


def is_owned_temp_name(name: str) -> bool:
    """True only when ``name`` is provably a lifecycle staging file's basename.

    Ownership is a naming contract, not a guess: the name must be exactly what
    the confirmation service constructs. Anything else — an operator's own
    ``.tmp`` file, an editor swap file, a partially matching name — is not owned
    and can never become a cleanup candidate.
    """
    text = str(name or "")
    if len(text) > _MAX_TEMP_NAME_CHARS:
        return False
    return _OWNED_TEMP_NAME.fullmatch(text) is not None


def _temp_reference(basename: str) -> str:
    """Return a stable, opaque reference for one basename in one directory.

    Stability matters: an operator ticks a checkbox in one render and confirms in
    the next, and the reference must still mean the same artifact. Ordinal
    references would silently renumber if the directory changed between the two.
    The value discloses nothing — it is a truncated digest, not a name.
    """
    digest = hashlib.sha256(basename.encode("utf-8", "surrogatepass")).hexdigest()
    return f"temp-{digest[:_REFERENCE_HEX_CHARS]}"


def _temp_label(basename: str) -> str:
    """Return the display-safe basename, or a fixed generic label."""
    return safe_temp_label(basename) or _GENERIC_TEMP_LABEL


def _resolve_now_ns(now: datetime | None) -> int:
    """Return the reference instant in nanoseconds, always timezone-anchored."""
    moment = now if isinstance(now, datetime) and now.tzinfo is not None else datetime.now(UTC)
    return int(moment.timestamp() * 1_000_000_000)


# --- Location resolution ---------------------------------------------------

_ROOT_ERRORS: dict[type[BaseException], str] = {
    FileNotFoundError: "ROOT_MISSING",
    PermissionError: "ROOT_PERMISSION_DENIED",
}
_LOCATION_ERRORS: dict[type[BaseException], str] = {
    FileNotFoundError: "LOCATION_ABSENT",
    PermissionError: "LOCATION_PERMISSION_DENIED",
}


def _classify_os_error(
    exc: OSError, table: Mapping[type[BaseException], str], fallback: str
) -> str:
    for exc_type, code in table.items():
        if isinstance(exc, exc_type):
            return code
    return fallback


def _resolve_root(workspace_root: str) -> tuple[Path | None, str]:
    raw = str(workspace_root or "").strip()
    if not raw:
        return None, "ROOT_BLANK"
    try:
        return Path(raw).expanduser().resolve(strict=True), ""
    except OSError as exc:
        return None, _classify_os_error(exc, _ROOT_ERRORS, "ROOT_UNRESOLVABLE")
    except RuntimeError:
        return None, "ROOT_UNRESOLVABLE"


def _resolve_directory(root: Path) -> tuple[Path | None, str]:
    lexical = root / DISCOVERY_SUBFOLDER
    try:
        os.lstat(lexical)
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        return None, _classify_os_error(exc, _LOCATION_ERRORS, "LOCATION_UNRESOLVABLE")
    except RuntimeError:
        return None, "LOCATION_UNRESOLVABLE"
    if not _is_confined(resolved, root):
        return None, "LOCATION_OUTSIDE_ROOT"
    return resolved, ""


def _resolve_location(workspace_root: str) -> tuple[_Location | None, str]:
    """Resolve, confine, and identify the one directory that may be scanned.

    Fails closed on every ambiguity: a missing root, an unresolvable or dangling
    location, a location that resolves outside the root, a non-directory, or a
    filesystem that cannot supply a stable directory identity.
    """
    root, code = _resolve_root(workspace_root)
    if root is None:
        return None, code
    directory, code = _resolve_directory(root)
    if directory is None:
        return None, code
    try:
        st = directory.stat()
    except OSError as exc:
        return None, _classify_os_error(exc, _LOCATION_ERRORS, "LOCATION_UNREADABLE")
    if not stat.S_ISDIR(st.st_mode):
        return None, "LOCATION_NOT_A_DIRECTORY"
    if st.st_dev == 0 or st.st_ino == 0:
        return None, "LOCATION_IDENTITY_UNAVAILABLE"
    return _Location(root=root, directory=directory, dev=st.st_dev, ino=st.st_ino), ""


def _location_unchanged(location: _Location) -> bool:
    """True when the directory is still the exact one that was scanned."""
    fresh, code = _resolve_location(str(location.root))
    if fresh is None or code:
        return False
    return (
        _normcase(fresh.directory) == _normcase(location.directory)
        and fresh.dev == location.dev
        and fresh.ino == location.ino
    )


# --- Temporary-artifact scan ----------------------------------------------


def _enumerate_owned_temp_names(location: _Location) -> tuple[list[str], int, str]:
    """List owned staging basenames from one flat, bounded, non-recursive pass.

    ``scandir`` yields no defined order, so names are sorted before any bound is
    applied — truncation must be deterministic, not dependent on the filesystem.
    """
    observed = 0
    names: list[str] = []
    try:
        with os.scandir(location.directory) as iterator:
            for entry in iterator:
                observed += 1
                if observed > MAX_ENTRIES_OBSERVED:
                    return [], observed, "SCAN_LIMIT_EXCEEDED"
                if is_owned_temp_name(entry.name):
                    names.append(entry.name)
    except OSError as exc:
        return [], observed, _classify_os_error(exc, _LOCATION_ERRORS, "LOCATION_UNREADABLE")
    names.sort(key=_normcase)
    return names, observed, ""


def _is_reparse_point(st: os.stat_result) -> bool:
    """True for a Windows reparse point (symlink, junction, or mount point)."""
    attributes = getattr(st, "st_file_attributes", 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _lstat_regular(path: Path) -> os.stat_result | None:
    """Return the non-following stat of a plain regular file, else ``None``.

    ``lstat`` never follows, so a symlink, junction, directory, device, socket,
    or FIFO fails the regular-file test instead of being inspected through.
    """
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or _is_reparse_point(st):
        return None
    return st


def _contained_resolved_path(location: _Location, path: Path) -> str:
    """Return the resolved path when it stays put, else ``""``.

    Containment is checked twice over: the resolved target must sit beneath both
    the lifecycle directory and the workspace root, and its parent must be that
    exact directory — so nothing nested, linked, or relocated qualifies.
    """
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return ""
    if not _is_confined(resolved, location.directory) or not _is_confined(resolved, location.root):
        return ""
    if _normcase(resolved.parent) != _normcase(location.directory):
        return ""
    return str(resolved)


def _is_abandoned(st: os.stat_result, now_ns: int) -> bool:
    """True only when the file is older than the whole grace period."""
    age_ns = now_ns - st.st_mtime_ns
    return age_ns >= _ABANDONED_AFTER_NS


def _eligible_temp(
    location: _Location, name: str, now_ns: int, referenced: frozenset[str]
) -> TempArtifactLocator | None:
    """Prove every eligibility condition for one candidate, or return ``None``.

    Nothing is assumed from the previous step: ownership, regular-file status,
    containment, non-reference, and abandonment are each re-established here.
    A candidate that fails any one of them simply does not exist as far as
    cleanup is concerned.
    """
    if not is_owned_temp_name(name):
        return None
    path = location.directory / name
    st = _lstat_regular(path)
    if st is None:
        return None
    resolved = _contained_resolved_path(location, path)
    if not resolved or _normcase(resolved) in referenced:
        return None
    if not _is_abandoned(st, now_ns):
        return None
    return TempArtifactLocator(
        reference=_temp_reference(name),
        basename=name,
        resolved_path=resolved,
        parent_dev=location.dev,
        parent_ino=location.ino,
        mtime_ns=st.st_mtime_ns,
    )


def _referenced_paths(result: DiscoveryResult) -> frozenset[str]:
    """Every durable path a valid or quarantined record points at.

    A staging basename can never equal a final artifact name — finals never begin
    with a dot — so this set is a second, independent guarantee rather than the
    only one: a path any sidecar claims is never a cleanup candidate.
    """
    paths: set[str] = set()
    for version in result.versions:
        locator = version.locator
        for value in (
            locator.sidecar_resolved_path,
            locator.csv_resolved_path,
            locator.recipe_resolved_path,
        ):
            if value:
                paths.add(_normcase(value))
    for group in result.duplicates:
        for member in group.internal_members:
            paths.add(_normcase(member.sidecar_resolved_path))
    return frozenset(paths)


# --- Managed-record and capability projection ------------------------------


def _issue_category(issue: DiscoveryIssue) -> DiagnosticCategory:
    """Map one discovery issue onto its distinct diagnostic category.

    An unavailable artifact stays an unavailable artifact: discovery already
    separates "the record is unreadable" from "the thing it points at is gone",
    so a missing reference is never re-presented as a corrupt sidecar. The
    artifact kind carried by the issue keeps the CSV and recipe cases distinct.
    """
    if issue.status is RecordStatus.UNAVAILABLE:
        if issue.artifact_kind == ARTIFACT_KIND_RECIPE:
            return DiagnosticCategory.MISSING_RECIPE_REFERENCE
        return DiagnosticCategory.MISSING_CSV_REFERENCE
    return DiagnosticCategory.CORRUPT_SIDECAR


def _managed_records(result: DiscoveryResult) -> list[DiagnosticRecord]:
    """Project discovery issues, reusing their opaque references and codes."""
    return [
        DiagnosticRecord(
            category=_issue_category(issue),
            reference=issue.reference,
            label=issue.label,
            reason_code=issue.reason_code,
            cleanup_eligible=False,
        )
        for issue in result.issues
    ]


def _capability_record(reason_code: str) -> DiagnosticRecord:
    """Report a location capability the lifecycle services already recognized."""
    return DiagnosticRecord(
        category=DiagnosticCategory.FILESYSTEM_CAPABILITY_UNAVAILABLE,
        reference=_CAPABILITY_REFERENCE,
        label=_CAPABILITY_LABEL,
        reason_code=reason_code,
        cleanup_eligible=False,
    )


def _order_records(records: Iterable[DiagnosticRecord]) -> tuple[DiagnosticRecord, ...]:
    """Stable ordering: fixed category order, then reference."""
    return tuple(
        sorted(records, key=lambda record: (_CATEGORY_RANK[record.category], record.reference))
    )


# --- Diagnostics entry point ----------------------------------------------

# Root outcomes that are an *absence* rather than a capability limit. Everything
# else discovery refuses on — permission, unresolvable, non-directory, an escape,
# a directory that changed underneath the scan, or a location too large to read
# safely — is a capability this location does not currently provide.
_ABSENCE_ROOT_STATUSES = frozenset({RootStatus.MISSING})


def _blank_report(state: str, reason_code: str = "") -> LifecycleDiagnosticsReport:
    return LifecycleDiagnosticsReport(state=state, scanned=False, reason_code=reason_code)


def _capability_report(result: DiscoveryResult) -> LifecycleDiagnosticsReport:
    """Fail closed: report the capability, scan nothing, offer no cleanup."""
    return LifecycleDiagnosticsReport(
        state=STATE_LOCATION_UNAVAILABLE,
        scanned=False,
        records=(_capability_record(result.root_reason or "LOCATION_UNAVAILABLE"),),
        reason_code=result.root_reason,
    )


def _root_failure_report(result: DiscoveryResult) -> LifecycleDiagnosticsReport:
    if result.root_reason == "ROOT_BLANK":
        return _blank_report(STATE_NOT_SCANNED, "ROOT_BLANK")
    if result.root_status in _ABSENCE_ROOT_STATUSES:
        return _blank_report(STATE_ROOT_MISSING, result.root_reason)
    return _capability_report(result)


def _with_hardlink_signal(
    report: LifecycleDiagnosticsReport, capability_unavailable: bool
) -> LifecycleDiagnosticsReport:
    """Add the already-recognized hard-link limitation, without reclassifying.

    The signal is supplied by the caller because only a confirmation attempt can
    prove it; this module never attempts a link itself, since doing so would be a
    write. The existing capability wording is reused exactly as the confirmation
    service composes it — nothing here re-explains or re-categorizes it.
    """
    if not capability_unavailable:
        return report
    record = _capability_record(_HARDLINK_REASON)
    return LifecycleDiagnosticsReport(
        state=report.state,
        scanned=report.scanned,
        records=_order_records([*report.records, record]),
        candidates=report.candidates,
        location=report.location,
        entries_observed=report.entries_observed,
        temp_omitted=report.temp_omitted,
        reason_code=report.reason_code,
    )


def _temp_records(
    location: _Location, names: Sequence[str], now_ns: int, referenced: frozenset[str]
) -> tuple[list[DiagnosticRecord], list[TempArtifactLocator]]:
    records: list[DiagnosticRecord] = []
    locators: list[TempArtifactLocator] = []
    for name in names:
        locator = _eligible_temp(location, name, now_ns, referenced)
        if locator is None:
            continue
        locators.append(locator)
        records.append(
            DiagnosticRecord(
                category=DiagnosticCategory.ABANDONED_TEMP_ARTIFACT,
                reference=locator.reference,
                label=_temp_label(locator.basename),
                reason_code="TEMP_ABANDONED",
                cleanup_eligible=True,
            )
        )
    return records, locators


def _scanned_report(
    location: _Location, result: DiscoveryResult, now_ns: int
) -> LifecycleDiagnosticsReport:
    names, observed, code = _enumerate_owned_temp_names(location)
    if code:
        return LifecycleDiagnosticsReport(
            state=(
                STATE_SCAN_LIMIT_EXCEEDED
                if code == "SCAN_LIMIT_EXCEEDED"
                else STATE_LOCATION_UNAVAILABLE
            ),
            scanned=False,
            records=(_capability_record(code),),
            entries_observed=observed,
            reason_code=code,
        )
    retained = names[:MAX_TEMP_ARTIFACTS]
    temp_records, locators = _temp_records(location, retained, now_ns, _referenced_paths(result))
    return LifecycleDiagnosticsReport(
        state=STATE_OK,
        scanned=True,
        records=_order_records([*temp_records, *_managed_records(result)]),
        candidates=tuple(locators),
        location=location,
        entries_observed=observed,
        temp_omitted=len(names) - len(retained),
    )


def collect_lifecycle_diagnostics(
    workspace_root: str,
    *,
    now: datetime | None = None,
    capability_unavailable: bool = False,
) -> LifecycleDiagnosticsReport:
    """Inspect the one authoritative lifecycle location and report findings.

    Read-only and deterministic. Managed-record findings come from one Phase-8
    discovery pass and keep that service's own classification and reason codes.
    Temporary-artifact findings come from one flat, bounded, non-recursive pass
    over ``<workspace_root>/preprocessed`` and are reported only when this
    application's ownership *and* abandonment are both proven.

    Nothing is repaired, registered, activated, rewritten, or deleted, and no
    session state is read or written. When the location cannot be established at
    all, the result says so and offers no cleanup candidates.
    """
    result = discover_managed_versions(workspace_root)
    if result.root_status is not RootStatus.OK:
        return _with_hardlink_signal(_root_failure_report(result), capability_unavailable)
    if result.root_reason == "DISCOVERY_DIR_ABSENT":
        return _with_hardlink_signal(_blank_report(STATE_LOCATION_ABSENT), capability_unavailable)
    location, code = _resolve_location(workspace_root)
    if location is None:
        return _with_hardlink_signal(
            LifecycleDiagnosticsReport(
                state=STATE_LOCATION_UNAVAILABLE,
                scanned=False,
                records=(_capability_record(code),),
                reason_code=code,
            ),
            capability_unavailable,
        )
    report = _scanned_report(location, result, _resolve_now_ns(now))
    return _with_hardlink_signal(report, capability_unavailable)


# --- Explicit cleanup ------------------------------------------------------


def _refused(reason_code: str) -> CleanupResult:
    return CleanupResult(status=CleanupStatus.REFUSED, reason_code=reason_code)


def _selection(references: Iterable[str]) -> list[str]:
    """De-duplicate the operator's selection while preserving first appearance."""
    seen: list[str] = []
    for reference in references:
        text = str(reference or "")
        if text and text not in seen:
            seen.append(text)
    return seen


def _revalidate(
    location: _Location, locator: TempArtifactLocator, now_ns: int, referenced: frozenset[str]
) -> str:
    """Re-prove eligibility from scratch; return ``""`` when safe to delete.

    The report that produced ``locator`` is, by definition, a description of the
    past. Every property is therefore established again here — against the live
    filesystem, immediately before the unlink — and any disagreement refuses the
    deletion rather than resolving it.
    """
    fresh = _eligible_temp(location, locator.basename, now_ns, referenced)
    if fresh is None:
        return "NOT_ELIGIBLE"
    if fresh.reference != locator.reference:
        return "REFERENCE_MISMATCH"
    if _normcase(fresh.resolved_path) != _normcase(locator.resolved_path):
        return "PATH_CHANGED"
    return ""


def _delete_one(
    location: _Location, locator: TempArtifactLocator, now_ns: int, referenced: frozenset[str]
) -> CleanupItemResult:
    """Delete exactly one revalidated artifact by its own resolved path."""
    label = _temp_label(locator.basename)
    reason = _revalidate(location, locator, now_ns, referenced)
    if reason:
        return CleanupItemResult(locator.reference, label, CleanupOutcome.SKIPPED, reason)
    try:
        os.unlink(locator.resolved_path)
    except FileNotFoundError:
        return CleanupItemResult(
            locator.reference, label, CleanupOutcome.UNAVAILABLE, "ALREADY_ABSENT"
        )
    except PermissionError:
        return CleanupItemResult(
            locator.reference, label, CleanupOutcome.FAILED, "PERMISSION_DENIED"
        )
    except OSError:
        return CleanupItemResult(locator.reference, label, CleanupOutcome.FAILED, "DELETE_FAILED")
    return CleanupItemResult(locator.reference, label, CleanupOutcome.DELETED, "DELETED")


def _guard_request(
    report: LifecycleDiagnosticsReport, selected: Sequence[str], confirmed: bool
) -> str:
    if not confirmed:
        return "NOT_CONFIRMED"
    if not report.scanned or report.location is None:
        return "NOT_SCANNED"
    if not selected:
        return "NOTHING_SELECTED"
    if len(selected) > MAX_CLEANUP_BATCH:
        return "BATCH_TOO_LARGE"
    return ""


def execute_lifecycle_cleanup(
    report: LifecycleDiagnosticsReport,
    references: Iterable[str],
    *,
    confirmed: bool,
    now: datetime | None = None,
) -> CleanupResult:
    """Delete only the individually selected, still-eligible abandoned artifacts.

    Runs only on an explicit, confirmed operator request. Refuses outright — with
    nothing touched — when confirmation is absent, no scan backs the request, the
    selection is empty, the batch exceeds its declared bound, or the lifecycle
    location is no longer the exact directory that was scanned.

    Otherwise it walks the scan's own order, revalidates each selected artifact
    against the live filesystem immediately before unlinking it, and reports
    deleted, skipped, unavailable, and failed items separately. A per-item
    failure never widens, retries, or aborts the rest of the batch; a selection
    that matches no candidate is reported, never guessed at.
    """
    selected = _selection(references)
    refusal = _guard_request(report, selected, confirmed)
    if refusal:
        return _refused(refusal)
    location = report.location
    if location is None or not _location_unchanged(location):  # pragma: no branch - guarded above
        return _refused("LOCATION_CHANGED")

    now_ns = _resolve_now_ns(now)
    referenced = _referenced_paths(discover_managed_versions(str(location.root)))
    chosen = set(selected)
    known: set[str] = set()
    items: list[CleanupItemResult] = []
    for locator in report.candidates:
        if locator.reference not in chosen:
            continue
        known.add(locator.reference)
        items.append(_delete_one(location, locator, now_ns, referenced))
    for reference in selected:
        if reference not in known:
            items.append(
                CleanupItemResult(
                    reference, _GENERIC_TEMP_LABEL, CleanupOutcome.SKIPPED, "UNKNOWN_SELECTION"
                )
            )
    return CleanupResult(status=CleanupStatus.COMPLETED, items=tuple(items))
