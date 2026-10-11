"""Explicit, fail-closed managed-version reopen service.

This module is the reopen resolution boundary between the Start page's
privacy-safe history surface and the accepted lifecycle contracts. It accepts
only the operator-entered Workspace Root, the privacy-safe action reference
emitted by the renderer (the collision-safe projected short version id), and
narrowly injected callables for deterministic testing.

On an explicit operator click it:

* validates the action-reference shape before touching the filesystem;
* performs one fresh bounded discovery — render-time data is never trusted;
* resolves the reference against the fresh result only, requiring exactly one
  unique currently-valid match and rejecting every duplicate group completely;
* revalidates the CSV and recipe artifacts (strict resolution, confinement
  under the resolved Workspace Root, regular-file check, bounded single-byte
  readability probe, and size/mtime identity against the durable record)
  before any state mutation;
* activates only through the accepted activation contract
  (:func:`...dataset_activation.make_managed_context` plus
  :func:`...dataset_activation.activate_dataset_context`), which owns the one
  atomic snapshot/rollback session-state transition — no second transition
  algorithm exists here;
* returns only a fixed, generic, privacy-safe :class:`ReopenOutcome`.

Every failure is terminal and leaves the active dataset context and every
unrelated session-state key untouched. The module stores no lookup map,
discovery result, locator, record, path, or full identifier in session state;
parses and executes no recipe (recipe-reload scope); imports neither Streamlit nor
pandas nor ``json``; and never logs, prints, or returns a path, filename,
stem, full identifier, hash, or raw exception.
"""

from __future__ import annotations

import os
import re
import stat as stat_module
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from data_quality_toolkit.adapters.ui.services.dataset_activation import (
    ActivationStatus,
    DatasetActivationResult,
    activate_dataset_context,
    make_managed_context,
    managed_activation_enabled,
)
from data_quality_toolkit.adapters.ui.services.dataset_discovery import (
    DiscoveredVersion,
    DiscoveryBounds,
    DiscoveryResult,
    RootStatus,
    discover_managed_versions,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    ManagedTrustError,
    commit_trust_root,
    ensure_session_capability,
    make_source_locator,
    reconcile_managed_trust,
    retire_managed_trust,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext

__all__ = [
    "STATUS_ALREADY_ACTIVE",
    "STATUS_FAILED",
    "STATUS_REOPENED",
    "STATUS_REQUIRES_REPAIR",
    "STATUS_STALE",
    "STATUS_UNAVAILABLE",
    "ReopenOutcome",
    "reopen_managed_version",
]

# --- Fixed outcome statuses and generic operator messages -------------------

STATUS_REOPENED = "reopened"
STATUS_ALREADY_ACTIVE = "already_active"
STATUS_STALE = "stale_selection"
STATUS_UNAVAILABLE = "unavailable"
STATUS_REQUIRES_REPAIR = "requires_repair"
STATUS_FAILED = "failed"

_SUCCESS_STATUSES = frozenset({STATUS_REOPENED, STATUS_ALREADY_ACTIVE})

# Fixed literals chosen at authoring time. No message ever interpolates a path,
# filename, identifier, hash, locator value, or exception text.
_MESSAGES: dict[str, str] = {
    STATUS_REOPENED: "Managed version reopened.",
    STATUS_ALREADY_ACTIVE: "This managed version is already active.",
    STATUS_STALE: "The selection is stale. Refresh the history and try again.",
    STATUS_UNAVAILABLE: "The managed version is no longer available.",
    STATUS_REQUIRES_REPAIR: "The managed version requires repair and cannot be reopened.",
    STATUS_FAILED: "The managed version could not be reopened.",
}

# Accepted collision-safe short-id shapes produced by discovery:
# ``v-`` + 8 hex, prefix-expanded to 12 hex, with an optional ordinal suffix.
# Anything else — including anything path-like — fails closed before any scan.
_REFERENCE_RE = re.compile(r"^v-[0-9a-f]{8}(?:[0-9a-f]{4})?(?:-[0-9]{1,6})?$")

_CSV_OK = "ARTIFACT_OK"
_RECIPE_OK_STATUSES = frozenset({"ARTIFACT_OK", "RECIPE_ABSENT"})

_DiscoverFn = Callable[..., DiscoveryResult]
_ActivateFn = Callable[[MutableMapping[str, Any], DatasetContext], DatasetActivationResult]


# --- Public outcome type ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReopenOutcome:
    """Fixed, generic reopen outcome — safe through repr/asdict/JSON.

    ``status`` and ``reason_code`` come from small authoring-time vocabularies
    and ``message`` from :data:`_MESSAGES`; no field ever carries a path,
    filename, full identifier, hash, or exception text.
    """

    status: str
    message: str
    reason_code: str

    @property
    def reopened(self) -> bool:
        """True when the managed version is the active dataset after the call."""
        return self.status in _SUCCESS_STATUSES


def _outcome(status: str, reason_code: str) -> ReopenOutcome:
    return ReopenOutcome(status=status, message=_MESSAGES[status], reason_code=reason_code)


# --- Fresh discovery + unique-valid resolution ------------------------------


def _fresh_discovery(
    root_raw: str, discover: _DiscoverFn | None, bounds: DiscoveryBounds | None
) -> tuple[DiscoveryResult | None, ReopenOutcome | None]:
    """Run one fresh bounded discovery for this reopen attempt; fail closed."""
    discover_fn = discover if discover is not None else discover_managed_versions
    try:
        result = discover_fn(root_raw) if bounds is None else discover_fn(root_raw, bounds=bounds)
    except Exception:
        return None, _outcome(STATUS_FAILED, "DISCOVERY_FAILED")
    if (
        result.root_status is not RootStatus.OK
        or not result.result_complete
        or not result.reopen_safe
    ):
        return None, _outcome(STATUS_FAILED, "DISCOVERY_NOT_SAFE")
    return result, None


def _resolve_reference(
    result: DiscoveryResult, action_reference: str
) -> tuple[DiscoveredVersion | None, ReopenOutcome | None]:
    """Resolve the reference to exactly one currently-valid version, else fail."""
    if any(group.short_version_id == action_reference for group in result.duplicates):
        return None, _outcome(STATUS_REQUIRES_REPAIR, "DUPLICATE_GROUP")
    matches = [
        version
        for version in result.versions
        if version.display.short_version_id == action_reference
    ]
    if not matches:
        return None, _outcome(STATUS_UNAVAILABLE, "REFERENCE_NOT_FOUND")
    if len(matches) > 1:
        return None, _outcome(STATUS_STALE, "REFERENCE_AMBIGUOUS")
    version = matches[0]
    if version.csv_status != _CSV_OK or version.recipe_status not in _RECIPE_OK_STATUSES:
        return None, _outcome(STATUS_UNAVAILABLE, "RECORD_NOT_VALID")
    return version, None


# --- Artifact revalidation (bounded, confined, identity-checked) ------------


@dataclass(frozen=True, slots=True)
class _PreparedSource:
    """Machine-side activation input captured during revalidation.

    ``relative_posix`` is the durable workspace-relative reference and is the
    only path form that may reach a privacy-safe locator; ``source_path`` is
    machine-use only.
    """

    source_path: str
    size_bytes: int
    modified_ns: int
    relative_posix: str = ""


def _resolve_strict(path: Path) -> Path | None:
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None


# Artifact-resolution seam, separate from workspace-root resolution so tests can
# inject deterministic resolution outcomes without touching root handling.
_resolve_artifact = _resolve_strict


def _is_confined(target: Path, root: Path) -> bool:
    target_norm = os.path.normcase(str(target))
    root_norm = os.path.normcase(str(root))
    try:
        return os.path.commonpath([target_norm, root_norm]) == root_norm
    except ValueError:
        return False


def _resolve_workspace_root(root_raw: str) -> Path | None:
    resolved = _resolve_strict(Path(root_raw).expanduser())
    if resolved is None:
        return None
    try:
        st = resolved.stat()
    except OSError:
        return None
    if not stat_module.S_ISDIR(st.st_mode):
        return None
    return resolved


def _bounded_probe(resolved: Path) -> str | None:
    """Prove readability with one bounded single-byte read; never stat alone."""
    try:
        with open(resolved, "rb") as handle:
            first = handle.read(1)
    except OSError:
        return "UNREADABLE"
    if not first:
        return "EMPTY"
    return None


def _check_artifact(
    resolved_root: Path, relative_posix: str, expected_resolved: str | None
) -> tuple[os.stat_result | None, Path | None, str | None]:
    """Revalidate one durable artifact at click time. Returns (stat, path, reason).

    The artifact must strictly resolve, stay confined under the resolved
    Workspace Root, still be the same canonical target discovery just probed
    (``expected_resolved``), be a regular file, and pass a bounded readability
    probe. Any deviation is a race/replacement and fails closed.
    """
    lexical = resolved_root.joinpath(*PurePosixPath(relative_posix).parts)
    resolved = _resolve_artifact(lexical)
    if resolved is None:
        return None, None, "MISSING"
    if not _is_confined(resolved, resolved_root):
        return None, None, "ESCAPES_ROOT"
    if expected_resolved is None or os.path.normcase(str(resolved)) != os.path.normcase(
        expected_resolved
    ):
        return None, None, "REPLACED"
    try:
        st = resolved.stat()
    except OSError:
        return None, None, "UNREADABLE"
    if not stat_module.S_ISREG(st.st_mode):
        return None, None, "NOT_REGULAR"
    probe = _bounded_probe(resolved)
    if probe is not None:
        return None, None, probe
    return st, resolved, None


def _revalidate_csv(
    resolved_root: Path, version: DiscoveredVersion
) -> tuple[_PreparedSource | None, str | None]:
    """Revalidate the CSV artifact and capture the activation fingerprint.

    Size (always) and ``mtime_ns`` (when the durable record carries one) must
    still match the record — a mismatch means the artifact changed between
    render/discovery and activation and fails closed.
    """
    record = version.record
    st, resolved, reason = _check_artifact(
        resolved_root, record.file_relative_path, version.locator.csv_resolved_path
    )
    if reason is not None or st is None or resolved is None:
        return None, f"CSV_{reason or 'UNREADABLE'}"
    if int(st.st_size) != record.size_bytes:
        return None, "CSV_CHANGED"
    if record.mtime_ns is not None and int(st.st_mtime_ns) != record.mtime_ns:
        return None, "CSV_CHANGED"
    return (
        _PreparedSource(
            str(resolved),
            int(st.st_size),
            int(st.st_mtime_ns),
            record.file_relative_path,
        ),
        None,
    )


def _revalidate_recipe(resolved_root: Path, version: DiscoveredVersion) -> str | None:
    """Revalidate the recipe artifact's existence/confinement/readability only.

    The recipe is never opened beyond the bounded probe, never parsed, and
    never executed here — recipe reload/reprocessing is a separate scope. A record
    without a recipe reference is schema-legal and passes.
    """
    record = version.record
    if record.recipe is None:
        return None
    _, _, reason = _check_artifact(
        resolved_root, record.recipe.relative_path, version.locator.recipe_resolved_path
    )
    if reason is not None:
        return f"RECIPE_{reason}"
    return None


def _revalidate_for_activation(
    root_raw: str, version: DiscoveredVersion
) -> tuple[_PreparedSource | None, ReopenOutcome | None]:
    """Complete every artifact check before any session-state mutation."""
    resolved_root = _resolve_workspace_root(root_raw)
    if resolved_root is None:
        return None, _outcome(STATUS_FAILED, "WORKSPACE_ROOT_UNAVAILABLE")
    prepared, csv_reason = _revalidate_csv(resolved_root, version)
    if csv_reason is not None or prepared is None:
        return None, _outcome(STATUS_UNAVAILABLE, csv_reason or "CSV_UNREADABLE")
    recipe_reason = _revalidate_recipe(resolved_root, version)
    if recipe_reason is not None:
        return None, _outcome(STATUS_UNAVAILABLE, recipe_reason)
    return prepared, None


# --- Activation through the accepted contract -------------------------------


def _activation_outcome(activation: DatasetActivationResult) -> ReopenOutcome:
    if activation.status is ActivationStatus.UNCHANGED:
        return _outcome(STATUS_ALREADY_ACTIVE, "ALREADY_ACTIVE")
    return _outcome(STATUS_REOPENED, "REOPENED")


def _trusted_activate(
    session_state: MutableMapping[str, Any],
    version: DiscoveredVersion,
    prepared: _PreparedSource,
    context: DatasetContext,
    activate_fn: _ActivateFn,
) -> ReopenOutcome:
    """Run the trusted managed activation transaction (one trust-commit point).

    Everything that can fail is done *before* the commit, so a pre-commit
    refusal leaves the previous valid authority exactly as it was. The commit
    itself establishes the new generation, verified binding, trust root,
    capability binding, and managed source identity in one caller-visible step.

    After the commit nothing rolls back to stale authority: if publishing the
    session-facing mirror fails, the binding is *retired forward* (a further
    generation advance that clears both managed caches and leaves the session
    fail-closed) rather than the previous trust root being restored.
    """
    record = version.record
    try:
        locator = make_source_locator(
            display_name=Path(prepared.source_path).name,
            relative_posix=prepared.relative_posix,
            absolute_path=prepared.source_path,
        )
    except ManagedTrustError:
        return _outcome(STATUS_FAILED, "ACTIVATION_REJECTED")

    # Activation is the only path permitted to ensure/create the capability.
    capability = ensure_session_capability(session_state)
    try:
        commit_trust_root(
            session_state,
            capability,
            version_id=record.version_id,
            family_id=record.family_id,
            content_id=record.content_id,
            root_content_id=record.root_content_id,
            parent_version_id=context.parent_version_id,
            version_label=record.label,
            locator=locator,
            size_bytes=prepared.size_bytes,
            modified_ns=prepared.modified_ns,
            large_file_mode=context.large_file_mode,
        )
    except ManagedTrustError:
        # Pre-commit failure: the previous authority is untouched.
        return _outcome(STATUS_FAILED, "ACTIVATION_REJECTED")

    # ---- past the trust commit: forward-only, never a rollback ----
    try:
        activation = activate_fn(session_state, context)
    except Exception:
        retire_managed_trust(session_state)
        return _outcome(STATUS_FAILED, "ACTIVATION_INTERRUPTED")
    return _activation_outcome(activation)


def _activate(
    session_state: MutableMapping[str, Any],
    version: DiscoveredVersion,
    prepared: _PreparedSource,
    activate: _ActivateFn | None,
) -> ReopenOutcome:
    """Activate through the accepted contracts; expose only generic outcomes.

    ``make_managed_context`` validates before any mutation. While trusted
    managed activation is disabled the legacy behavior is used verbatim, so the
    accepted reopen contract is unchanged; when it is enabled the trusted
    transaction in :func:`_trusted_activate` owns the transition. No internal
    error detail crosses to the caller in either case.
    """
    activate_fn = activate if activate is not None else activate_dataset_context
    try:
        context = make_managed_context(
            version.record,
            source_path=prepared.source_path,
            display_name=Path(prepared.source_path).name,
            size_bytes=prepared.size_bytes,
            modified_ns=prepared.modified_ns,
        )
    except Exception:
        return _outcome(STATUS_FAILED, "ACTIVATION_REJECTED")

    if not managed_activation_enabled():
        try:
            activation = activate_fn(session_state, context)
        except Exception:
            return _outcome(STATUS_FAILED, "ACTIVATION_REJECTED")
        return _activation_outcome(activation)

    return _trusted_activate(session_state, version, prepared, context, activate_fn)


# --- Public entry point -----------------------------------------------------


def reopen_managed_version(
    session_state: MutableMapping[str, Any],
    workspace_root: str,
    action_reference: str,
    *,
    discover: _DiscoverFn | None = None,
    activate: _ActivateFn | None = None,
    bounds: DiscoveryBounds | None = None,
) -> ReopenOutcome:
    """Explicitly reopen one currently-valid managed version, failing closed.

    Accepts only the operator-entered Workspace Root and the privacy-safe
    action reference from the clicked row (plus injectable ``discover`` /
    ``activate`` / ``bounds`` for deterministic tests). A blank root performs
    no scan; a malformed reference fails before any filesystem access. All
    resolution uses one fresh bounded discovery, all artifact revalidation
    completes before state mutation, and activation goes only through the
    accepted atomic contract, so every failure leaves the current active
    dataset and all unrelated session-state keys unchanged.
    """
    # Marker-independent forward reconciliation: an invalid binding left by an
    # interrupted attempt is retired by generation/capability alone, without
    # consulting or requiring cleanup of any physical marker or mirror.
    if managed_activation_enabled():
        reconcile_managed_trust(session_state)

    root_raw = str(workspace_root or "").strip()
    if not root_raw:
        return _outcome(STATUS_FAILED, "WORKSPACE_ROOT_BLANK")
    if _REFERENCE_RE.match(str(action_reference or "")) is None:
        return _outcome(STATUS_STALE, "REFERENCE_MALFORMED")
    result, discovery_failure = _fresh_discovery(root_raw, discover, bounds)
    if discovery_failure is not None or result is None:
        return discovery_failure or _outcome(STATUS_FAILED, "DISCOVERY_FAILED")
    version, resolve_failure = _resolve_reference(result, action_reference)
    if resolve_failure is not None or version is None:
        return resolve_failure or _outcome(STATUS_FAILED, "DISCOVERY_FAILED")
    prepared, revalidate_failure = _revalidate_for_activation(root_raw, version)
    if revalidate_failure is not None or prepared is None:
        return revalidate_failure or _outcome(STATUS_FAILED, "WORKSPACE_ROOT_UNAVAILABLE")
    return _activate(session_state, version, prepared, activate)
