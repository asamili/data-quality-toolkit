"""Pure, deterministic, bounded managed-version discovery.

This service scans the single approved lifecycle directory
``<workspace_root>/preprocessed`` for lifecycle sidecars, treats every sidecar
and every referenced artifact as untrusted durable input, and returns an
immutable, privacy-safe :class:`DiscoveryResult`.

It is intentionally a read-only trust boundary. It:

* uses ``Path.resolve(strict=True)`` as the sole canonical path API;
* confines the discovery directory and every artifact beneath the resolved
  workspace root, rejecting escaping links;
* protects against directory races with a pre- and post-enumeration identity
  recheck (``st_dev``/``st_ino``), failing closed on any change;
* bounds observed entries, retained sidecar candidates, and sidecar bytes;
* validates sidecar schema only through the accepted lifecycle parser
  (:func:`...dataset_versions.from_mapping`) — it defines no second parser;
* proves artifact readability with a bounded, non-mutating binary open plus a
  single byte read (never ``stat`` alone), with no retries;
* fully quarantines every duplicate ``version_id`` group (identical included),
  choosing no canonical member;
* separates trusted versions, untrusted issues, duplicate groups, internal
  locators, and operator-facing display data;
* emits opaque scan-local references (``issue-0001``/``duplicate-0001``) derived
  from no path, filename, UUID, hash, label, or record content.

CSV content parsing/hashing is deferred to trusted reopen; recipe JSON parsing and digest
verification to recipe reload. This module imports neither Streamlit, session state,
``DatasetContext``, the activation service, UI pages, nor pandas, reads no
session state, mutates nothing on disk, and never activates a version.
"""

from __future__ import annotations

import json
import os
import re
import stat
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath

from data_quality_toolkit.adapters.ui.services.dataset_versions import (
    _SUPPORTED_SCHEMA_VERSIONS,
    PREPROCESS_PARENT_REQUIRED,
    PREPROCESS_RECIPE_REQUIRED,
    CreationMechanism,
    DatasetVersionError,
    DatasetVersionRecord,
    from_mapping,
)

__all__ = [
    "ARTIFACT_KIND_CSV",
    "ARTIFACT_KIND_NONE",
    "ARTIFACT_KIND_RECIPE",
    "DiscoveryBounds",
    "DiscoveryConfigError",
    "DiscoveryFilters",
    "DiscoveryIssue",
    "DiscoveryResult",
    "DiscoveredVersion",
    "DuplicateGroup",
    "InternalLocator",
    "RecordStatus",
    "RootStatus",
    "VersionDisplay",
    "discover_managed_versions",
]

# --- Constants ------------------------------------------------------------

DISCOVERY_SUBFOLDER = "preprocessed"
SIDECAR_SUFFIX = ".dqtv.json"

# Which durable reference an ``UNAVAILABLE`` issue is about. The reason codes are
# deliberately shared between the two probes (a vanished CSV and a vanished recipe
# are the same filesystem fact), so this value-free token is the only thing that
# tells them apart. It names no path, filename, or identifier: a reader learns
# *which reference* failed, never where it pointed. Every other issue — every
# sidecar parse failure — carries ``ARTIFACT_KIND_NONE``.
ARTIFACT_KIND_NONE = ""
ARTIFACT_KIND_CSV = "csv"
ARTIFACT_KIND_RECIPE = "recipe"

_MAX_LABEL_LENGTH = 100
_LABEL_FALLBACK = "Managed dataset"
_STATUS_LABEL_MANAGED = "Managed version"

_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_WHITESPACE_RE = re.compile(r"\s+")

# Ceilings that mirror the accepted discovery safety caps. Callers may lower a
# bound (cheaper tests) but never raise it above its accepted maximum.
_BOUND_CEILINGS: dict[str, int] = {
    "max_entries": 10_000,
    "max_sidecar_candidates": 5_000,
    "max_sidecar_bytes": 1_048_576,
}


# --- Public enums ---------------------------------------------------------


class RootStatus(StrEnum):
    """Status of establishing a trustworthy, confined, fully-enumerable scan."""

    OK = "ok"
    MISSING = "missing"
    NOT_A_DIRECTORY = "not_a_directory"
    PERMISSION_DENIED = "permission_denied"
    UNRESOLVABLE = "unresolvable"
    UNSAFE_DISCOVERY_DIRECTORY = "unsafe_discovery_directory"
    LIMIT_EXCEEDED = "limit_exceeded"
    DIRECTORY_CHANGED = "directory_changed"


class RecordStatus(StrEnum):
    """Classification of a discovered lifecycle record."""

    VALID = "valid"
    UNAVAILABLE = "unavailable"
    CORRUPT = "corrupt"
    UNSUPPORTED = "unsupported"
    DUPLICATE = "duplicate"


# --- Configuration --------------------------------------------------------


class DiscoveryConfigError(ValueError):
    """Raised when discovery bounds are not positive, bounded integers."""


def _validate_bound(name: str, value: int, ceiling: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DiscoveryConfigError(f"{name} must be an integer")
    if value < 1 or value > ceiling:
        raise DiscoveryConfigError(f"{name} must be within 1..{ceiling}")


@dataclass(frozen=True, slots=True)
class DiscoveryBounds:
    """Positive, bounded processing limits. Every value is capped at its
    accepted safety ceiling, so a caller can only tighten, never loosen.

    Discovery is flat: there is no lineage traversal (parent-depth belongs to
    lineage presentation) and no separate issue-count knob (``max_sidecar_candidates`` already
    bounds the maximum number of issues), so neither is configurable here."""

    max_entries: int = 10_000
    max_sidecar_candidates: int = 5_000
    max_sidecar_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        for name, ceiling in _BOUND_CEILINGS.items():
            _validate_bound(name, getattr(self, name), ceiling)


@dataclass(frozen=True, slots=True)
class DiscoveryFilters:
    """Post-classification filters over the trusted, valid, non-duplicate set.

    Values are validated only when applied. An invalid UUID or enum value yields
    a deterministic empty valid-version set with a sanitized reason, never an
    unhandled exception.
    """

    family_id: str | None = None
    version_id: str | None = None
    created_by: str | None = None
    statuses: tuple[str, ...] | None = None
    roots_only: bool = False
    parent_version_id: str | None = None


# --- Public value types ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class VersionDisplay:
    """Operator-facing, privacy-safe presentation of a trusted version.

    Contains no absolute/relative path, filename, stem, full UUID, or hash by
    construction.
    """

    label: str
    short_version_id: str
    status_label: str
    kind_label: str


@dataclass(frozen=True, slots=True)
class InternalLocator:
    """Machine-only identity for later reopen re-resolution and revalidation.

    Never rendered: it deliberately holds canonical paths and full identifiers.
    """

    sidecar_relative_posix: str
    sidecar_resolved_path: str
    csv_resolved_path: str | None
    recipe_resolved_path: str | None
    version_id: str
    family_id: str
    content_id: str
    st_dev: int
    st_ino: int


@dataclass(frozen=True, slots=True)
class DiscoveredVersion:
    """A unique, valid, non-duplicate discovered version.

    ``record`` and ``locator`` are machine-side (needed by reopen); a UI must render
    only ``display``.
    """

    record: DatasetVersionRecord
    display: VersionDisplay
    csv_status: str
    recipe_status: str
    locator: InternalLocator


@dataclass(frozen=True, slots=True)
class DiscoveryIssue:
    """A corrupt, unsupported, or unavailable record.

    Every field is operator-safe: a fixed generic label, an opaque scan-local
    reference, a status, and a sanitized reason code. No path, filename, stem,
    UUID, hash, untrusted JSON value, or raw exception text appears here.

    ``artifact_kind`` distinguishes *which* durable reference an ``UNAVAILABLE``
    issue is about (``ARTIFACT_KIND_CSV`` / ``ARTIFACT_KIND_RECIPE``), because the
    two probes share their reason codes. It is ``ARTIFACT_KIND_NONE`` for every
    other status and carries no location information of any kind.
    """

    status: RecordStatus
    reference: str
    label: str
    reason_code: str
    artifact_kind: str = ARTIFACT_KIND_NONE


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """A quarantined group of two or more sidecars claiming one ``version_id``.

    No member is selectable or reopenable and no canonical member is chosen.
    ``internal_members`` is machine-only and separated from operator-facing data.
    """

    kind: str
    short_version_id: str
    member_count: int
    member_references: tuple[str, ...]
    internal_members: tuple[InternalLocator, ...]


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Immutable, privacy-safe outcome of one discovery scan."""

    root_status: RootStatus
    root_reason: str
    enumeration_complete: bool
    result_complete: bool
    reopen_safe: bool
    entries_observed: int
    candidates_retained: int
    sidecars_parsed: int
    records_returned: int
    duplicate_group_count: int
    duplicate_member_count: int
    versions: tuple[DiscoveredVersion, ...]
    issues: tuple[DiscoveryIssue, ...]
    duplicates: tuple[DuplicateGroup, ...]
    omitted_count: int | None
    reason_codes: tuple[str, ...]


# --- Operator label vocabulary --------------------------------------------

_KIND_LABELS: dict[CreationMechanism, str] = {
    CreationMechanism.ROOT_IMPORT: "Imported root",
    CreationMechanism.PREPROCESS_RECIPE: "Processed version",
}

_ISSUE_LABELS: dict[RecordStatus, str] = {
    RecordStatus.CORRUPT: "Unreadable version record",
    RecordStatus.UNSUPPORTED: "Unsupported version record",
    RecordStatus.UNAVAILABLE: "Version artifact unavailable",
}

_CREATED_BY_VALUES: frozenset[str] = frozenset(m.value for m in CreationMechanism)
_RECORD_STATUS_VALUES: frozenset[str] = frozenset(m.value for m in RecordStatus)


# --- Internal processing structures ---------------------------------------


@dataclass(frozen=True, slots=True)
class _DirIdentity:
    st_dev: int
    st_ino: int


@dataclass(frozen=True, slots=True)
class _DirPrep:
    resolved_root: Path
    resolved_pp: Path
    lexical: Path
    identity: _DirIdentity


@dataclass(frozen=True, slots=True)
class _ParsedSidecar:
    lexical_rel: str
    sidecar_resolved: str
    st_dev: int
    st_ino: int
    record: DatasetVersionRecord


@dataclass(frozen=True, slots=True)
class _RawIssue:
    lexical_rel: str
    resolved: str | None
    st_dev: int
    st_ino: int
    status: RecordStatus
    reason: str
    artifact_kind: str = ARTIFACT_KIND_NONE


@dataclass(frozen=True, slots=True)
class _RawDuplicate:
    kind: str
    short_version_id: str
    members: tuple[_ParsedSidecar, ...]


@dataclass(frozen=True, slots=True)
class _Eligible:
    member: _ParsedSidecar
    csv_status: str
    recipe_status: str
    csv_resolved: str | None
    recipe_resolved: str | None


class _DiscoveryStopError(Exception):
    """Internal control-flow signal carrying a terminal fail-closed result."""

    def __init__(self, result: DiscoveryResult) -> None:
        super().__init__("discovery stop")
        self.result = result


# --- Terminal-result builders ---------------------------------------------


def _base_result(
    status: RootStatus,
    reason: str,
    *,
    enumeration_complete: bool,
    result_complete: bool,
    reopen_safe: bool,
    entries_observed: int = 0,
    candidates_retained: int = 0,
    omitted_count: int | None = None,
) -> DiscoveryResult:
    codes: tuple[str, ...] = (reason,) if reason else ()
    return DiscoveryResult(
        root_status=status,
        root_reason=reason,
        enumeration_complete=enumeration_complete,
        result_complete=result_complete,
        reopen_safe=reopen_safe,
        entries_observed=entries_observed,
        candidates_retained=candidates_retained,
        sidecars_parsed=0,
        records_returned=0,
        duplicate_group_count=0,
        duplicate_member_count=0,
        versions=(),
        issues=(),
        duplicates=(),
        omitted_count=omitted_count,
        reason_codes=codes,
    )


def _error(status: RootStatus, reason: str) -> _DiscoveryStopError:
    return _DiscoveryStopError(
        _base_result(
            status, reason, enumeration_complete=False, result_complete=False, reopen_safe=False
        )
    )


def _dir_changed(reason: str) -> _DiscoveryStopError:
    return _error(RootStatus.DIRECTORY_CHANGED, reason)


def _absent() -> _DiscoveryStopError:
    return _DiscoveryStopError(
        _base_result(
            RootStatus.OK,
            "DISCOVERY_DIR_ABSENT",
            enumeration_complete=True,
            result_complete=True,
            reopen_safe=True,
        )
    )


def _limit(entries_observed: int, candidates: int) -> _DiscoveryStopError:
    return _DiscoveryStopError(
        _base_result(
            RootStatus.LIMIT_EXCEEDED,
            "LIMIT_EXCEEDED",
            enumeration_complete=False,
            result_complete=False,
            reopen_safe=False,
            entries_observed=entries_observed,
            candidates_retained=candidates,
            omitted_count=None,
        )
    )


# --- Canonical resolution + confinement -----------------------------------


def _resolve_strict(path: Path) -> tuple[Path | None, str | None]:
    """Resolve ``path`` strictly. Error codes: MISSING / PERMISSION_DENIED /
    UNRESOLVABLE."""
    try:
        return path.resolve(strict=True), None
    except FileNotFoundError:
        return None, "MISSING"
    except PermissionError:
        return None, "PERMISSION_DENIED"
    except (OSError, RuntimeError):
        return None, "UNRESOLVABLE"


def _stat_follow(path: Path) -> tuple[os.stat_result | None, str | None]:
    try:
        return path.stat(), None
    except FileNotFoundError:
        return None, "VANISHED"
    except PermissionError:
        return None, "PERMISSION_DENIED"
    except OSError:
        return None, "UNREADABLE"


def _normcase(path: Path) -> str:
    return os.path.normcase(str(path))


def _is_confined(target: Path, root: Path) -> bool:
    """True when ``target`` is equal to or beneath ``root`` (case-normalized)."""
    target_norm = _normcase(target)
    root_norm = _normcase(root)
    try:
        return os.path.commonpath([target_norm, root_norm]) == root_norm
    except ValueError:
        return False


def _capture_identity(path: Path) -> tuple[_DirIdentity | None, str | None]:
    """Capture directory identity. Error codes: NOT_A_DIRECTORY /
    IDENTITY_UNAVAILABLE / VANISHED / PERMISSION_DENIED / UNREADABLE."""
    st, err = _stat_follow(path)
    if err is not None or st is None:
        return None, err
    if not stat.S_ISDIR(st.st_mode):
        return None, "NOT_A_DIRECTORY"
    if st.st_dev == 0 or st.st_ino == 0:
        return None, "IDENTITY_UNAVAILABLE"
    return _DirIdentity(st.st_dev, st.st_ino), None


# --- Root + discovery-directory preparation -------------------------------


def _resolve_root(workspace_root: str) -> Path:
    raw = str(workspace_root or "").strip()
    if not raw:
        raise _error(RootStatus.MISSING, "ROOT_BLANK")
    resolved, err = _resolve_strict(Path(raw).expanduser())
    if err == "MISSING":
        raise _error(RootStatus.MISSING, "ROOT_MISSING")
    if err == "PERMISSION_DENIED":
        raise _error(RootStatus.PERMISSION_DENIED, "ROOT_PERMISSION_DENIED")
    if err is not None or resolved is None:
        raise _error(RootStatus.UNRESOLVABLE, "ROOT_UNRESOLVABLE")
    st, serr = _stat_follow(resolved)
    if serr is not None or st is None:
        raise _error(RootStatus.UNRESOLVABLE, "ROOT_STAT_FAILED")
    if not stat.S_ISDIR(st.st_mode):
        raise _error(RootStatus.NOT_A_DIRECTORY, "ROOT_NOT_A_DIRECTORY")
    return resolved


def _require_lexical_present(lexical: Path) -> None:
    """Non-following existence probe distinguishing true absence from dangling."""
    try:
        os.lstat(lexical)
    except FileNotFoundError as exc:
        raise _absent() from exc
    except PermissionError as exc:
        raise _error(RootStatus.PERMISSION_DENIED, "DISCOVERY_DIR_PERMISSION_DENIED") from exc
    except OSError as exc:
        raise _error(RootStatus.UNRESOLVABLE, "DISCOVERY_DIR_LSTAT_FAILED") from exc


def _resolve_discovery_dir(lexical: Path, root: Path) -> Path:
    resolved, err = _resolve_strict(lexical)
    if err == "MISSING":
        # The lexical entry exists (lstat passed) but its target cannot resolve.
        raise _error(RootStatus.UNRESOLVABLE, "DISCOVERY_DIR_DANGLING")
    if err == "PERMISSION_DENIED":
        raise _error(RootStatus.PERMISSION_DENIED, "DISCOVERY_DIR_PERMISSION_DENIED")
    if err is not None or resolved is None:
        raise _error(RootStatus.UNRESOLVABLE, "DISCOVERY_DIR_UNRESOLVABLE")
    if not _is_confined(resolved, root):
        raise _error(RootStatus.UNSAFE_DISCOVERY_DIRECTORY, "DISCOVERY_DIR_OUTSIDE_ROOT")
    return resolved


def _require_dir_identity(resolved: Path) -> _DirIdentity:
    identity, err = _capture_identity(resolved)
    if identity is not None:
        return identity
    if err == "NOT_A_DIRECTORY":
        raise _error(RootStatus.NOT_A_DIRECTORY, "DISCOVERY_DIR_NOT_A_DIRECTORY")
    if err == "IDENTITY_UNAVAILABLE":
        raise _dir_changed("DISCOVERY_DIR_IDENTITY_UNAVAILABLE")
    if err == "PERMISSION_DENIED":
        raise _error(RootStatus.PERMISSION_DENIED, "DISCOVERY_DIR_PERMISSION_DENIED")
    raise _error(RootStatus.UNRESOLVABLE, "DISCOVERY_DIR_STAT_FAILED")


def _prepare_discovery_dir(resolved_root: Path) -> _DirPrep:
    lexical = resolved_root / DISCOVERY_SUBFOLDER
    _require_lexical_present(lexical)
    resolved = _resolve_discovery_dir(lexical, resolved_root)
    identity = _require_dir_identity(resolved)
    return _DirPrep(resolved_root, resolved, lexical, identity)


def _recheck_dir(prep: _DirPrep, *, phase: str) -> None:
    """Re-resolve, re-confine, and re-stat the discovery directory; fail closed
    on any vanish, retarget, replacement, or unavailable identity."""
    resolved, err = _resolve_strict(prep.lexical)
    if err == "PERMISSION_DENIED":
        raise _error(RootStatus.PERMISSION_DENIED, f"DISCOVERY_DIR_{phase}_PERMISSION_DENIED")
    if err == "MISSING":
        raise _dir_changed(f"DISCOVERY_DIR_{phase}_VANISHED")
    if err is not None or resolved is None:
        raise _dir_changed(f"DISCOVERY_DIR_{phase}_RETARGETED")
    if not _is_confined(resolved, prep.resolved_root) or _normcase(resolved) != _normcase(
        prep.resolved_pp
    ):
        raise _dir_changed(f"DISCOVERY_DIR_{phase}_RETARGETED")
    identity, ierr = _capture_identity(resolved)
    if ierr == "IDENTITY_UNAVAILABLE":
        raise _dir_changed(f"DISCOVERY_DIR_{phase}_IDENTITY_UNAVAILABLE")
    if identity is None or identity != prep.identity:
        raise _dir_changed(f"DISCOVERY_DIR_{phase}_REPLACED")


# --- Enumeration ----------------------------------------------------------


def _is_sidecar_name(name: str) -> bool:
    return name.lower().endswith(SIDECAR_SUFFIX)


def _enumerate(prep: _DirPrep, bounds: DiscoveryBounds) -> tuple[int, list[str]]:
    """Flat, non-recursive enumeration of the resolved directory target."""
    _recheck_dir(prep, phase="PRECHECK")
    observed = 0
    candidates: list[str] = []
    try:
        with os.scandir(prep.resolved_pp) as iterator:
            for entry in iterator:
                if observed >= bounds.max_entries:
                    raise _limit(observed, len(candidates))
                observed += 1
                if not _is_sidecar_name(entry.name):
                    continue
                if len(candidates) >= bounds.max_sidecar_candidates:
                    raise _limit(observed, len(candidates))
                candidates.append(entry.name)
    except _DiscoveryStopError:
        raise
    except FileNotFoundError as exc:
        raise _dir_changed("DISCOVERY_DIR_SCAN_VANISHED") from exc
    except PermissionError as exc:
        raise _error(RootStatus.PERMISSION_DENIED, "DISCOVERY_DIR_SCAN_PERMISSION_DENIED") from exc
    except OSError as exc:
        raise _error(RootStatus.UNRESOLVABLE, "DISCOVERY_DIR_SCAN_FAILED") from exc
    return observed, candidates


# --- Sidecar parsing ------------------------------------------------------

_SIDECAR_RESOLVE_CODES: dict[str, str] = {
    "MISSING": "CORRUPT_SIDECAR_VANISHED",
    "PERMISSION_DENIED": "CORRUPT_SIDECAR_PERMISSION_DENIED",
    "UNRESOLVABLE": "CORRUPT_SIDECAR_UNRESOLVABLE",
}
_SIDECAR_STAT_CODES: dict[str, str] = {
    "VANISHED": "CORRUPT_SIDECAR_VANISHED",
    "PERMISSION_DENIED": "CORRUPT_SIDECAR_PERMISSION_DENIED",
    "UNREADABLE": "CORRUPT_SIDECAR_UNREADABLE",
}


def _lock_or_perm(exc: OSError, *, prefix: str) -> str:
    """Map an open failure to a LOCKED (Windows sharing violation) or
    PERMISSION_DENIED reason code."""
    if getattr(exc, "winerror", None) in (32, 33):
        return f"{prefix}_LOCKED"
    if isinstance(exc, PermissionError):
        return f"{prefix}_PERMISSION_DENIED"
    return f"{prefix}_UNREADABLE"


def _read_bounded(resolved: Path, max_bytes: int) -> tuple[bytes | None, str | None]:
    try:
        with open(resolved, "rb") as handle:
            data = handle.read(max_bytes + 1)
    except FileNotFoundError:
        return None, "CORRUPT_SIDECAR_VANISHED"
    except OSError as exc:
        return None, _lock_or_perm(exc, prefix="CORRUPT_SIDECAR")
    if len(data) > max_bytes:
        return None, "CORRUPT_OVERSIZE"
    return data, None


def _load_mapping(data: bytes) -> tuple[dict[str, object] | None, str | None]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, "CORRUPT_ENCODING"
    try:
        obj = json.loads(text)
    except RecursionError:
        # Pathologically deep nesting within the byte limit: fail closed as a
        # corrupt sidecar instead of letting RecursionError escape. Caught only
        # here, at the JSON-loading boundary, so it can never mask a genuine
        # recursion defect elsewhere. No raw exception text is exposed.
        return None, "CORRUPT_JSON_DEPTH"
    except (json.JSONDecodeError, ValueError):
        return None, "CORRUPT_JSON"
    if not isinstance(obj, dict):
        return None, "CORRUPT_STRUCTURE"
    return obj, None


def _issue(
    lexical_rel: str,
    resolved: str | None,
    status: RecordStatus,
    reason: str,
    *,
    st_dev: int = -1,
    st_ino: int = -1,
    artifact_kind: str = ARTIFACT_KIND_NONE,
) -> _RawIssue:
    return _RawIssue(lexical_rel, resolved, st_dev, st_ino, status, reason, artifact_kind)


# Creator-reference invariant failures surface as distinct corrupt reason codes;
# every other lifecycle validation error collapses to the generic CORRUPT_SCHEMA.
_CREATOR_REF_CODES: dict[str, str] = {
    PREPROCESS_PARENT_REQUIRED: "CORRUPT_PREPROCESS_PARENT_REQUIRED",
    PREPROCESS_RECIPE_REQUIRED: "CORRUPT_PREPROCESS_RECIPE_REQUIRED",
}


def _creator_ref_code(exc: DatasetVersionError) -> str:
    """Classify a lifecycle validation failure into an operator-safe reason code.

    Exposes no message text, path, identifier, recipe data, or record value: only
    a fixed token drawn from a closed set.
    """
    return _CREATOR_REF_CODES.get(exc.code or "", "CORRUPT_SCHEMA")


def _classify_payload(
    lexical_rel: str, resolved: Path, st: os.stat_result, data: bytes
) -> _ParsedSidecar | _RawIssue:
    resolved_str = str(resolved)
    obj, code = _load_mapping(data)
    if code is not None or obj is None:
        return _issue(lexical_rel, resolved_str, RecordStatus.CORRUPT, code or "CORRUPT_JSON")
    schema_version = obj.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        return _issue(lexical_rel, resolved_str, RecordStatus.CORRUPT, "CORRUPT_SCHEMA_MISSING")
    if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        return _issue(lexical_rel, resolved_str, RecordStatus.UNSUPPORTED, "UNSUPPORTED_SCHEMA")
    try:
        record = from_mapping(obj)
    except DatasetVersionError as exc:
        return _issue(lexical_rel, resolved_str, RecordStatus.CORRUPT, _creator_ref_code(exc))
    return _ParsedSidecar(lexical_rel, resolved_str, st.st_dev, st.st_ino, record)


def _process_sidecar(
    prep: _DirPrep, name: str, bounds: DiscoveryBounds
) -> _ParsedSidecar | _RawIssue:
    lexical_rel = f"{DISCOVERY_SUBFOLDER}/{name}"
    resolved, err = _resolve_strict(prep.resolved_pp / name)
    if err is not None or resolved is None:
        return _issue(lexical_rel, None, RecordStatus.CORRUPT, _SIDECAR_RESOLVE_CODES[err or ""])
    if not _is_confined(resolved, prep.resolved_root):
        return _issue(
            lexical_rel, str(resolved), RecordStatus.CORRUPT, "CORRUPT_SIDECAR_UNSAFE_PATH"
        )
    st, serr = _stat_follow(resolved)
    if serr is not None or st is None:
        return _issue(
            lexical_rel, str(resolved), RecordStatus.CORRUPT, _SIDECAR_STAT_CODES[serr or ""]
        )
    if not stat.S_ISREG(st.st_mode):
        return _issue(
            lexical_rel, str(resolved), RecordStatus.CORRUPT, "CORRUPT_SIDECAR_NOT_REGULAR"
        )
    if st.st_size > bounds.max_sidecar_bytes:
        return _issue(lexical_rel, str(resolved), RecordStatus.CORRUPT, "CORRUPT_OVERSIZE")
    data, rerr = _read_bounded(resolved, bounds.max_sidecar_bytes)
    if rerr is not None or data is None:
        return _issue(
            lexical_rel, str(resolved), RecordStatus.CORRUPT, rerr or "CORRUPT_SIDECAR_UNREADABLE"
        )
    return _classify_payload(lexical_rel, resolved, st, data)


def _parse_candidates(
    prep: _DirPrep, candidates: list[str], bounds: DiscoveryBounds
) -> tuple[list[_ParsedSidecar], list[_RawIssue]]:
    parsed: list[_ParsedSidecar] = []
    issues: list[_RawIssue] = []
    for name in candidates:
        outcome = _process_sidecar(prep, name, bounds)
        if isinstance(outcome, _ParsedSidecar):
            parsed.append(outcome)
        else:
            issues.append(outcome)
    return parsed, issues


# --- Artifact readability -------------------------------------------------

_ARTIFACT_RESOLVE_CODES: dict[str, str] = {
    "MISSING": "ARTIFACT_VANISHED",
    "PERMISSION_DENIED": "ARTIFACT_PERMISSION_DENIED",
    "UNRESOLVABLE": "ARTIFACT_UNREADABLE",
}
_ARTIFACT_STAT_CODES: dict[str, str] = {
    "VANISHED": "ARTIFACT_VANISHED",
    "PERMISSION_DENIED": "ARTIFACT_PERMISSION_DENIED",
    "UNREADABLE": "ARTIFACT_UNREADABLE",
}


def _resolve_confined_regular(root: Path, relative_posix: str) -> tuple[Path | None, str | None]:
    lexical = root.joinpath(*PurePosixPath(relative_posix).parts)
    resolved, err = _resolve_strict(lexical)
    if err is not None or resolved is None:
        return None, _ARTIFACT_RESOLVE_CODES[err or ""]
    if not _is_confined(resolved, root):
        return None, "ARTIFACT_UNSAFE_PATH"
    st, serr = _stat_follow(resolved)
    if serr is not None or st is None:
        return None, _ARTIFACT_STAT_CODES[serr or ""]
    if not stat.S_ISREG(st.st_mode):
        return None, "ARTIFACT_NOT_REGULAR_FILE"
    return resolved, None


def _bounded_readable(resolved: Path) -> str:
    try:
        with open(resolved, "rb") as handle:
            data = handle.read(1)
    except FileNotFoundError:
        return "ARTIFACT_VANISHED"
    except OSError as exc:
        return _lock_or_perm(exc, prefix="ARTIFACT")
    if not data:
        return "ARTIFACT_EMPTY"
    return "ARTIFACT_OK"


def _probe_artifact(root: Path, relative_posix: str) -> tuple[str, str | None]:
    resolved, err = _resolve_confined_regular(root, relative_posix)
    if err is not None or resolved is None:
        return err or "ARTIFACT_UNREADABLE", None
    code = _bounded_readable(resolved)
    if code != "ARTIFACT_OK":
        return code, None
    return "ARTIFACT_OK", str(resolved)


def _probe_recipe(root: Path, record: DatasetVersionRecord) -> tuple[str, str | None]:
    if record.recipe is None:
        # Schema-legal: a ROOT_IMPORT (or compatibility) record without a recipe.
        # Not invented and not treated as unavailable.
        return "RECIPE_ABSENT", None
    return _probe_artifact(root, record.recipe.relative_path)


# --- Classification (duplicates, availability) ----------------------------


def _finalize_singleton(member: _ParsedSidecar, root: Path) -> _Eligible | _RawIssue:
    csv_status, csv_resolved = _probe_artifact(root, member.record.file_relative_path)
    if csv_status != "ARTIFACT_OK":
        return _issue(
            member.lexical_rel,
            member.sidecar_resolved,
            RecordStatus.UNAVAILABLE,
            csv_status,
            st_dev=member.st_dev,
            st_ino=member.st_ino,
            artifact_kind=ARTIFACT_KIND_CSV,
        )
    recipe_status, recipe_resolved = _probe_recipe(root, member.record)
    if recipe_status not in ("ARTIFACT_OK", "RECIPE_ABSENT"):
        return _issue(
            member.lexical_rel,
            member.sidecar_resolved,
            RecordStatus.UNAVAILABLE,
            recipe_status,
            st_dev=member.st_dev,
            st_ino=member.st_ino,
            artifact_kind=ARTIFACT_KIND_RECIPE,
        )
    return _Eligible(member, csv_status, recipe_status, csv_resolved, recipe_resolved)


def _build_duplicate(members: list[_ParsedSidecar]) -> _RawDuplicate:
    first = members[0].record
    identical = all(member.record == first for member in members)
    kind = "duplicate_identical" if identical else "duplicate_conflict"
    return _RawDuplicate(kind, _short_version_id(first.version_id), tuple(members))


def _classify(
    parsed: list[_ParsedSidecar], root: Path
) -> tuple[list[_Eligible], list[_RawDuplicate], list[_RawIssue]]:
    groups: dict[str, list[_ParsedSidecar]] = {}
    for member in parsed:
        groups.setdefault(member.record.version_id, []).append(member)

    eligibles: list[_Eligible] = []
    duplicates: list[_RawDuplicate] = []
    issues: list[_RawIssue] = []
    for members in groups.values():
        if len(members) >= 2:
            duplicates.append(_build_duplicate(members))
            continue
        outcome = _finalize_singleton(members[0], root)
        if isinstance(outcome, _Eligible):
            eligibles.append(outcome)
        else:
            issues.append(outcome)
    return eligibles, duplicates, issues


# --- Deterministic ordering + opaque references ---------------------------


def _private_key(
    lexical_rel: str, status_value: str, resolved: str | None, st_dev: int, st_ino: int
) -> tuple[str, str, str, int, int]:
    return (
        os.path.normcase(lexical_rel),
        status_value,
        os.path.normcase(resolved or ""),
        st_dev,
        st_ino,
    )


def _issue_key(issue: _RawIssue) -> tuple[str, str, str, int, int]:
    return _private_key(
        issue.lexical_rel, issue.status.value, issue.resolved, issue.st_dev, issue.st_ino
    )


def _member_key(member: _ParsedSidecar) -> tuple[str, str, str, int, int]:
    return _private_key(
        member.lexical_rel,
        RecordStatus.DUPLICATE.value,
        member.sidecar_resolved,
        member.st_dev,
        member.st_ino,
    )


def _member_locator(member: _ParsedSidecar) -> InternalLocator:
    record = member.record
    return InternalLocator(
        sidecar_relative_posix=member.lexical_rel,
        sidecar_resolved_path=member.sidecar_resolved,
        csv_resolved_path=None,
        recipe_resolved_path=None,
        version_id=record.version_id,
        family_id=record.family_id,
        content_id=record.content_id,
        st_dev=member.st_dev,
        st_ino=member.st_ino,
    )


def _build_issue_refs(issues: list[_RawIssue]) -> tuple[DiscoveryIssue, ...]:
    ordered = sorted(issues, key=_issue_key)
    return tuple(
        DiscoveryIssue(
            status=issue.status,
            reference=f"issue-{index:04d}",
            label=_ISSUE_LABELS[issue.status],
            reason_code=issue.reason,
            artifact_kind=issue.artifact_kind,
        )
        for index, issue in enumerate(ordered, start=1)
    )


def _build_duplicate_refs(duplicates: list[_RawDuplicate]) -> tuple[DuplicateGroup, ...]:
    groups_sorted = sorted(
        duplicates, key=lambda group: min(_member_key(member) for member in group.members)
    )
    final: list[DuplicateGroup] = []
    counter = 1
    for group in groups_sorted:
        members_sorted = sorted(group.members, key=_member_key)
        references: list[str] = []
        locators: list[InternalLocator] = []
        for member in members_sorted:
            references.append(f"duplicate-{counter:04d}")
            locators.append(_member_locator(member))
            counter += 1
        final.append(
            DuplicateGroup(
                kind=group.kind,
                short_version_id=group.short_version_id,
                member_count=len(group.members),
                member_references=tuple(references),
                internal_members=tuple(locators),
            )
        )
    return tuple(final)


def _sort_eligibles(eligibles: list[_Eligible]) -> list[_Eligible]:
    ordered = sorted(eligibles, key=lambda item: item.member.record.version_id)
    # Stable secondary pass -> newest first, version_id ascending within a tie.
    ordered.sort(key=lambda item: item.member.record.created_at.astimezone(UTC), reverse=True)
    return ordered


# --- Privacy-safe display -------------------------------------------------


def _reduce_pathlike(text: str) -> str:
    if "/" in text or "\\" in text or _DRIVE_RE.match(text):
        return PureWindowsPath(text).name or PurePosixPath(text).name
    return text


def _sanitize_label(raw: str) -> str:
    text = "".join(ch for ch in str(raw or "") if ord(ch) >= 32 and ord(ch) != 127)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if not text:
        return _LABEL_FALLBACK
    text = _reduce_pathlike(text).strip()
    if not text:
        return _LABEL_FALLBACK
    if len(text) > _MAX_LABEL_LENGTH:
        text = text[: _MAX_LABEL_LENGTH - 1] + "…"
    return text


def _short_version_id(version_id: str) -> str:
    try:
        return "v-" + uuid.UUID(version_id).hex[:8]
    except (AttributeError, TypeError, ValueError):
        return ""


def _resolve_short_ids(version_ids: list[str]) -> list[str]:
    """Short ids (``v-`` + 8 hex) with bounded prefix-expansion (to 12) then an
    ordinal fallback on collision. Never yields a full UUID."""
    hexes = [uuid.UUID(value).hex for value in version_ids]
    result = ["v-" + digest[:8] for digest in hexes]
    counts8 = Counter(result)
    for index, short in enumerate(result):
        if counts8[short] > 1:
            result[index] = "v-" + hexes[index][:12]
    counts12 = Counter(result)
    for index, short in enumerate(result):
        if counts12[short] > 1:
            result[index] = f"{short}-{index + 1}"
    return result


def _make_version(eligible: _Eligible, short_id: str) -> DiscoveredVersion:
    record = eligible.member.record
    display = VersionDisplay(
        label=_sanitize_label(record.label),
        short_version_id=short_id,
        status_label=_STATUS_LABEL_MANAGED,
        kind_label=_KIND_LABELS[record.created_by],
    )
    locator = InternalLocator(
        sidecar_relative_posix=eligible.member.lexical_rel,
        sidecar_resolved_path=eligible.member.sidecar_resolved,
        csv_resolved_path=eligible.csv_resolved,
        recipe_resolved_path=eligible.recipe_resolved,
        version_id=record.version_id,
        family_id=record.family_id,
        content_id=record.content_id,
        st_dev=eligible.member.st_dev,
        st_ino=eligible.member.st_ino,
    )
    return DiscoveredVersion(
        record=record,
        display=display,
        csv_status=eligible.csv_status,
        recipe_status=eligible.recipe_status,
        locator=locator,
    )


def _build_versions(eligibles: list[_Eligible]) -> tuple[DiscoveredVersion, ...]:
    ordered = _sort_eligibles(eligibles)
    short_ids = _resolve_short_ids([item.member.record.version_id for item in ordered])
    return tuple(_make_version(item, short_id) for item, short_id in zip(ordered, short_ids))


# --- Filtering ------------------------------------------------------------


def _norm_uuid(raw: str) -> str | None:
    try:
        return str(uuid.UUID(raw))
    except (AttributeError, TypeError, ValueError):
        return None


def _family_id_of(record: DatasetVersionRecord) -> str | None:
    return record.family_id


def _version_id_of(record: DatasetVersionRecord) -> str | None:
    return record.version_id


def _parent_version_id(record: DatasetVersionRecord) -> str | None:
    return record.parent.version_id if record.parent is not None else None


def _add_uuid_filter(
    checks: list[Callable[[DiscoveredVersion], bool]],
    errors: list[str],
    raw: str | None,
    code: str,
    extractor: Callable[[DatasetVersionRecord], str | None],
) -> None:
    if raw is None:
        return
    value = _norm_uuid(raw)
    if value is None:
        errors.append(code)
        return

    def check(version: DiscoveredVersion) -> bool:
        return extractor(version.record) == value

    checks.append(check)


def _add_created_by_filter(
    checks: list[Callable[[DiscoveredVersion], bool]],
    errors: list[str],
    filters: DiscoveryFilters,
) -> None:
    if filters.created_by is None:
        return
    if filters.created_by not in _CREATED_BY_VALUES:
        errors.append("FILTER_INVALID_CREATED_BY")
        return
    wanted = filters.created_by

    def check(version: DiscoveredVersion) -> bool:
        return version.record.created_by.value == wanted

    checks.append(check)


def _add_status_filter(
    checks: list[Callable[[DiscoveredVersion], bool]],
    errors: list[str],
    filters: DiscoveryFilters,
) -> None:
    if filters.statuses is None:
        return
    if any(value not in _RECORD_STATUS_VALUES for value in filters.statuses):
        errors.append("FILTER_INVALID_STATUSES")
        return
    allowed = RecordStatus.VALID.value in filters.statuses

    def check(_version: DiscoveredVersion) -> bool:
        return allowed

    checks.append(check)


def _build_predicate(
    filters: DiscoveryFilters,
) -> tuple[Callable[[DiscoveredVersion], bool], list[str]]:
    checks: list[Callable[[DiscoveredVersion], bool]] = []
    errors: list[str] = []
    _add_uuid_filter(checks, errors, filters.family_id, "FILTER_INVALID_FAMILY_ID", _family_id_of)
    _add_uuid_filter(
        checks, errors, filters.version_id, "FILTER_INVALID_VERSION_ID", _version_id_of
    )
    _add_uuid_filter(
        checks,
        errors,
        filters.parent_version_id,
        "FILTER_INVALID_PARENT_VERSION_ID",
        _parent_version_id,
    )
    _add_created_by_filter(checks, errors, filters)
    _add_status_filter(checks, errors, filters)
    if filters.roots_only:
        checks.append(lambda version: version.record.created_by == CreationMechanism.ROOT_IMPORT)
    return (lambda version: all(check(version) for check in checks)), errors


def _apply_filters(
    versions: tuple[DiscoveredVersion, ...], filters: DiscoveryFilters | None
) -> tuple[tuple[DiscoveredVersion, ...], tuple[str, ...]]:
    if filters is None:
        return versions, ()
    predicate, errors = _build_predicate(filters)
    if errors:
        return (), tuple(errors)
    return tuple(version for version in versions if predicate(version)), ()


# --- Assembly + public entry point ----------------------------------------


def _finalize(
    bounds: DiscoveryBounds,
    observed: int,
    candidates_retained: int,
    parsed_count: int,
    eligibles: list[_Eligible],
    issues: list[_RawIssue],
    raw_duplicates: list[_RawDuplicate],
    filters: DiscoveryFilters | None,
) -> DiscoveryResult:
    versions_all = _build_versions(eligibles)
    final_issues = _build_issue_refs(issues)
    final_duplicates = _build_duplicate_refs(raw_duplicates)
    versions_final, filter_reasons = _apply_filters(versions_all, filters)
    return DiscoveryResult(
        root_status=RootStatus.OK,
        root_reason="",
        enumeration_complete=True,
        result_complete=True,
        reopen_safe=True,
        entries_observed=observed,
        candidates_retained=candidates_retained,
        sidecars_parsed=parsed_count,
        records_returned=len(versions_final),
        duplicate_group_count=len(final_duplicates),
        duplicate_member_count=sum(group.member_count for group in final_duplicates),
        versions=versions_final,
        issues=final_issues,
        duplicates=final_duplicates,
        omitted_count=len(versions_all) - len(versions_final),
        reason_codes=filter_reasons,
    )


def _run(
    workspace_root: str, filters: DiscoveryFilters | None, bounds: DiscoveryBounds
) -> DiscoveryResult:
    resolved_root = _resolve_root(workspace_root)
    prep = _prepare_discovery_dir(resolved_root)
    observed, candidates = _enumerate(prep, bounds)
    _recheck_dir(prep, phase="POSTCHECK")
    parsed, parse_issues = _parse_candidates(prep, candidates, bounds)
    eligibles, raw_duplicates, availability_issues = _classify(parsed, resolved_root)
    return _finalize(
        bounds,
        observed,
        len(candidates),
        len(parsed),
        eligibles,
        parse_issues + availability_issues,
        raw_duplicates,
        filters,
    )


def discover_managed_versions(
    workspace_root: str,
    *,
    filters: DiscoveryFilters | None = None,
    bounds: DiscoveryBounds | None = None,
) -> DiscoveryResult:
    """Discover managed lifecycle versions under ``<workspace_root>/preprocessed``.

    Pure and read-only: scans only the approved directory, treats every sidecar
    and artifact as untrusted, fully quarantines duplicate ``version_id`` groups,
    proves artifact readability with a bounded open, fails closed on directory
    races or bound exhaustion, and returns an immutable, privacy-safe result. It
    never mutates disk, session state, or the active dataset context.
    """
    active_bounds = bounds if bounds is not None else DiscoveryBounds()
    try:
        return _run(workspace_root, filters, active_bounds)
    except _DiscoveryStopError as stop:
        return stop.result
