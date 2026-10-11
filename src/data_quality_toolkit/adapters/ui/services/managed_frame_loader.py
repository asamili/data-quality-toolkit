"""Root-first managed frame/assessment dispatcher with session-isolated caches.

Trusted managed activation boundary. This UI-private service is the only place a managed
DataFrame or managed assessment may be materialized:

* dispatch is root-first: a valid :class:`ManagedTrustRoot` is required and a
  managed-looking mirror without valid trust fails closed upstream;
* cache identity is exactly :class:`CanonicalFrameKey` /
  :class:`AssessmentKey` — anchored on the identity-only
  :class:`SessionCapability`, never on paths, sizes, mtimes, inodes, stat
  tuples, source locators, or artifact metadata;
* the frame cache holds DataFrames only and the assessment cache holds
  assessment dicts only; both are in-process, bounded, and cleared by the
  managed-trust invalidation hooks (generation change, managed clear, managed
  version switch). Correctness never depends on that cleanup: every read
  revalidates trust first;
* managed FULL loading is permitted only at or below
  :data:`MANAGED_FULL_MAX_SOURCE_BYTES` (imported from the one shared owner,
  never redefined) and a FULL cache miss revalidates source confinement and
  content identity before parsing;
* managed LARGE mode refuses DataFrame materialization, refuses header-only
  reads, and never enters the frame cache. Header-only FULL is supported.

All refusals raise :class:`ManagedFrameLoadError` with a fixed reason code and
a fixed privacy-safe message: no absolute managed path, workspace path, or
trust-root serialization ever appears in error output.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.services.managed_trust import (
    ManagedTrustRoot,
    SessionCapability,
    peek_session_capability,
    register_cache_invalidation_hook,
    resolve_trust_authority,
)
from data_quality_toolkit.shared.managed_export_source import (
    MANAGED_FULL_MAX_SOURCE_BYTES,
    verify_managed_source,
)

__all__ = [
    "MODE_FULL",
    "MODE_LARGE",
    "AssessmentKey",
    "CanonicalFrameKey",
    "ManagedFrameLoadError",
    "clear_managed_caches",
    "compute_assessment_fingerprint",
    "compute_parser_fingerprint",
    "get_managed_assessment",
    "get_managed_frame",
    "get_managed_header",
]

MODE_FULL = "full"
MODE_LARGE = "large"

_PARSER_CONTRACT_VERSION = "dqt-managed-parser/1"
_ASSESSMENT_CONTRACT_VERSION = "dqt-managed-assessment/1"

# Bounded in-process cache ceilings (entries, FIFO eviction).
_FRAME_CACHE_MAX_ENTRIES = 4
_ASSESSMENT_CACHE_MAX_ENTRIES = 16


# --- Failure model (fixed, privacy-safe) -------------------------------------

_REFUSAL_MESSAGES: dict[str, str] = {
    "NO_VALID_TRUST": "managed loading requires a valid managed trust root",
    "NO_SESSION_CAPABILITY": "managed loading requires the live session capability",
    "LARGE_MODE_REFUSED": "managed LARGE mode never materializes a DataFrame",
    "LARGE_HEADER_REFUSED": "managed LARGE mode does not serve header-only reads",
    "FULL_SIZE_EXCEEDED": "managed FULL source exceeds the permitted size ceiling",
    "SOURCE_MISSING": "the managed source artifact is no longer available",
    "SOURCE_REPLACED": "the managed source artifact no longer matches its binding",
    "SOURCE_NOT_CONFINED": "the managed source artifact escaped its confinement",
    "CONTENT_MISMATCH": "the managed source content no longer matches its identity",
    "PARSE_FAILED": "the managed source could not be parsed",
    "ASSESSMENT_INVALID": "the managed assessment result was not an assessment mapping",
    "OPTION_NOT_CANONICAL": "fingerprint options must be canonical and path-free",
}


class ManagedFrameLoadError(Exception):
    """Managed load/assessment refusal with a fixed privacy-safe message."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(_REFUSAL_MESSAGES.get(reason_code, "managed load refused"))
        self.reason_code = reason_code


# --- Canonical cache identities ------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanonicalFrameKey:
    session_anchor: SessionCapability
    version_id: str
    content_id: str
    mode: str
    parser_fingerprint: str


@dataclass(frozen=True, slots=True)
class AssessmentKey:
    frame_key: CanonicalFrameKey
    assessment_fingerprint: str


# --- Fingerprints (deterministic, path-free) --------------------------------------

_ABSOLUTE_PATH_LIKE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/])")


def _canonical_options(options: Mapping[str, Any] | None) -> dict[str, Any]:
    """Canonicalize fingerprint options; refuse path-like or unserializable values."""
    if options is None:
        return {}
    canonical: dict[str, Any] = {}
    for key in sorted(options):
        value = options[key]
        if isinstance(value, str) and _ABSOLUTE_PATH_LIKE.match(value):
            raise ManagedFrameLoadError("OPTION_NOT_CANONICAL")
        canonical[str(key)] = value
    try:
        json.dumps(canonical, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ManagedFrameLoadError("OPTION_NOT_CANONICAL") from exc
    return canonical


def _digest(contract: str, options: Mapping[str, Any] | None) -> str:
    payload = json.dumps(
        {"contract": contract, "options": _canonical_options(options)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_parser_fingerprint(options: Mapping[str, Any] | None = None) -> str:
    """Deterministic digest of the parser contract plus effective options."""
    return _digest(_PARSER_CONTRACT_VERSION, options)


def compute_assessment_fingerprint(options: Mapping[str, Any] | None = None) -> str:
    """Deterministic digest of the assessment ruleset plus effective config."""
    return _digest(_ASSESSMENT_CONTRACT_VERSION, options)


# --- Strictly separated, bounded, in-process caches ---------------------------------

_managed_frame_cache: dict[CanonicalFrameKey, pd.DataFrame] = {}
_managed_assessment_cache: dict[AssessmentKey, dict[str, Any]] = {}


def _bounded_store(cache: dict[Any, Any], key: Any, value: Any, max_entries: int) -> None:
    while len(cache) >= max_entries:
        cache.pop(next(iter(cache)))
    cache[key] = value


def clear_managed_caches() -> None:
    """Clear both managed caches (frame and assessment)."""
    _managed_frame_cache.clear()
    _managed_assessment_cache.clear()


def _invalidation_hook(_state: MutableMapping[str, Any]) -> None:
    clear_managed_caches()


register_cache_invalidation_hook(_invalidation_hook)


# --- Trust resolution and source revalidation ------------------------------------------


def _require_managed_authority(
    state: MutableMapping[str, Any],
) -> tuple[ManagedTrustRoot, SessionCapability]:
    decision = resolve_trust_authority(state)
    if not decision.managed or decision.root is None:
        raise ManagedFrameLoadError("NO_VALID_TRUST")
    capability = peek_session_capability(state)  # validation accessor: never creates
    if capability is None:
        raise ManagedFrameLoadError("NO_SESSION_CAPABILITY")
    return decision.root, capability


def _revalidate_source(root: ManagedTrustRoot) -> str | None:
    """Re-check confinement and content identity of the bound source artifact.

    The checks themselves are *not* owned here: they are the shared managed
    source policy in
    :func:`~data_quality_toolkit.shared.managed_export_source.verify_managed_source`,
    so this loader and the application export boundary can never drift apart.
    This module keeps only the mapping from the shared reason code onto
    :class:`ManagedFrameLoadError`.

    ``content_id`` is deliberately not passed: a managed frame load verifies
    path/stat identity only, exactly as before, and never pays a full-file hash.
    Exact content verification is required on the provenance-sensitive managed
    *export* path, which supplies it.

    Filesystem facts are used here strictly as non-authoritative validation:
    they can only *refuse* a load, never mint identity — cache identity stays
    purely capability/version/content/mode/fingerprint.
    """
    locator = root.locator
    return verify_managed_source(
        source_path=locator.absolute_path,
        relative_posix=locator.relative_posix,
        size_bytes=root.size_bytes,
        modified_ns=root.modified_ns,
    )


# Revalidation seam so tests can inject deterministic outcomes.
_revalidate = _revalidate_source


def _default_read_frame(path: str, options: Mapping[str, Any] | None) -> pd.DataFrame:
    return pd.read_csv(path, **dict(options or {}))


def _default_read_header(path: str, options: Mapping[str, Any] | None) -> list[str]:
    frame = pd.read_csv(path, nrows=0, **dict(options or {}))
    return [str(column) for column in frame.columns]


_FrameReader = Callable[[str, Mapping[str, Any] | None], pd.DataFrame]
_HeaderReader = Callable[[str, Mapping[str, Any] | None], "list[str]"]


# --- Root-first dispatch --------------------------------------------------------------


def _frame_key(
    capability: SessionCapability, root: ManagedTrustRoot, parser_fp: str
) -> CanonicalFrameKey:
    return CanonicalFrameKey(
        session_anchor=capability,
        version_id=root.version_id,
        content_id=root.content_id,
        mode=MODE_FULL,
        parser_fingerprint=parser_fp,
    )


def get_managed_frame(
    state: MutableMapping[str, Any],
    *,
    parser_options: Mapping[str, Any] | None = None,
    reader: _FrameReader | None = None,
) -> pd.DataFrame:
    """Return the managed FULL DataFrame under exact canonical cache identity.

    Fails closed without valid trust; refuses LARGE mode outright; refuses a
    FULL source above the shared byte ceiling; and on a cache miss revalidates
    confinement and content identity before parsing. Only DataFrames enter the
    frame cache, only under the complete :class:`CanonicalFrameKey`.
    """
    root, capability = _require_managed_authority(state)
    if root.large_file_mode:
        raise ManagedFrameLoadError("LARGE_MODE_REFUSED")
    if root.size_bytes > MANAGED_FULL_MAX_SOURCE_BYTES:
        raise ManagedFrameLoadError("FULL_SIZE_EXCEEDED")
    key = _frame_key(capability, root, compute_parser_fingerprint(parser_options))
    cached = _managed_frame_cache.get(key)
    if cached is not None:
        return cached
    reason = _revalidate(root)
    if reason is not None:
        raise ManagedFrameLoadError(reason)
    read = reader if reader is not None else _default_read_frame
    try:
        frame = read(root.locator.absolute_path, parser_options)
    except ManagedFrameLoadError:
        raise
    except Exception as exc:
        raise ManagedFrameLoadError("PARSE_FAILED") from exc
    if not isinstance(frame, pd.DataFrame):
        raise ManagedFrameLoadError("PARSE_FAILED")
    _bounded_store(_managed_frame_cache, key, frame, _FRAME_CACHE_MAX_ENTRIES)
    return frame


def get_managed_header(
    state: MutableMapping[str, Any],
    *,
    parser_options: Mapping[str, Any] | None = None,
    reader: _HeaderReader | None = None,
) -> list[str]:
    """Return column names for the managed FULL source (never cached as a frame).

    Header-only FULL is supported regardless of frame-cache state; header-only
    LARGE is refused. The source is revalidated before every read.
    """
    root, _capability = _require_managed_authority(state)
    if root.large_file_mode:
        raise ManagedFrameLoadError("LARGE_HEADER_REFUSED")
    if root.size_bytes > MANAGED_FULL_MAX_SOURCE_BYTES:
        raise ManagedFrameLoadError("FULL_SIZE_EXCEEDED")
    reason = _revalidate(root)
    if reason is not None:
        raise ManagedFrameLoadError(reason)
    read = reader if reader is not None else _default_read_header
    try:
        return list(read(root.locator.absolute_path, parser_options))
    except ManagedFrameLoadError:
        raise
    except Exception as exc:
        raise ManagedFrameLoadError("PARSE_FAILED") from exc


def get_managed_assessment(
    state: MutableMapping[str, Any],
    *,
    assessor: Callable[[pd.DataFrame], dict[str, Any]],
    parser_options: Mapping[str, Any] | None = None,
    assessment_options: Mapping[str, Any] | None = None,
    reader: _FrameReader | None = None,
) -> dict[str, Any]:
    """Return the managed assessment under exact :class:`AssessmentKey` identity.

    The assessment cache stores assessment mappings only — never DataFrames —
    and is keyed by the complete frame key plus the assessment fingerprint, so
    a changed assessment configuration can never reuse a stale assessment.
    """
    root, capability = _require_managed_authority(state)
    if root.large_file_mode:
        raise ManagedFrameLoadError("LARGE_MODE_REFUSED")
    frame_key = _frame_key(capability, root, compute_parser_fingerprint(parser_options))
    key = AssessmentKey(
        frame_key=frame_key,
        assessment_fingerprint=compute_assessment_fingerprint(assessment_options),
    )
    cached = _managed_assessment_cache.get(key)
    if cached is not None:
        return cached
    frame = get_managed_frame(state, parser_options=parser_options, reader=reader)
    result = assessor(frame)
    if not isinstance(result, dict) or isinstance(result, pd.DataFrame):
        raise ManagedFrameLoadError("ASSESSMENT_INVALID")
    if any(isinstance(value, pd.DataFrame) for value in result.values()):
        raise ManagedFrameLoadError("ASSESSMENT_INVALID")
    _bounded_store(_managed_assessment_cache, key, result, _ASSESSMENT_CACHE_MAX_ENTRIES)
    return result
