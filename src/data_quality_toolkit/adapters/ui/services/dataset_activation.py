"""Atomic, Streamlit-free dataset-context activation.

This service owns the one dataset-context transition algorithm for the UI:

* validated construction of legacy (unmanaged) and managed lifecycle contexts;
* version-aware change detection via ``DatasetContext.binding_identity``;
* one atomic activation that invalidates dataset-derived session state
  (``DATASET_DERIVED_STATE_KEYS``) only when the binding changes and rolls the
  full prior snapshot back on any mutation failure.

It performs no durable writes, no file/sidecar reading, and no directory
scanning, and imports neither Streamlit nor pandas. ``DATASET_CONTEXT`` remains
the single authoritative active pointer; no second active pointer is created.

``set_dataset_context`` / ``clear_dataset_context`` in ``state.context`` are thin
compatibility wrappers over the primitives here, so there is exactly one
transition algorithm.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import MutableMapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from data_quality_toolkit.adapters.ui.services.dataset_versions import DatasetVersionRecord
from data_quality_toolkit.adapters.ui.state.context import DatasetContext, get_dataset_context
from data_quality_toolkit.adapters.ui.state.keys import (
    DATASET_CONTEXT,
    DATASET_DERIVED_STATE_KEYS,
    EXPORT_CSV_PATH,
    SRC_DATASET_ID,
)

__all__ = [
    "ActivationStatus",
    "DatasetActivationError",
    "DatasetActivationResult",
    "InvalidLegacyContextError",
    "InvalidManagedContextError",
    "ManagedActivationDisabledError",
    "ManagedActivationOutcome",
    "ManagedActivationReport",
    "StateMutationError",
    "activate_dataset_context",
    "activate_managed_context",
    "clear_dataset_context",
    "make_legacy_context",
    "make_managed_context",
    "managed_activation_enabled",
    "require_managed_activation_enabled",
    "validate_dataset_context",
]


# --- Failure model --------------------------------------------------------


class DatasetActivationError(Exception):
    """Base class for dataset-context activation failures."""


class InvalidLegacyContextError(DatasetActivationError):
    """A legacy (unmanaged) context carries lifecycle identity or label data."""


class InvalidManagedContextError(DatasetActivationError):
    """A managed context is missing, blank, or malformed in a lifecycle field."""


class StateMutationError(DatasetActivationError):
    """Session-state mutation failed; the prior snapshot was restored exactly."""


class ManagedActivationDisabledError(DatasetActivationError):
    """Trusted managed activation was requested while the feature is disabled."""


# --- Managed activation guard ----------------------------------------------
#
# Production gate for the trusted managed-activation path. The literal below is
# the single enable point: every trusted managed activation must pass
# :func:`require_managed_activation_enabled` first, and enabling the feature is
# a flag-only change of this one literal — no other code participates.
_MANAGED_ACTIVATION_ENABLED = True


def managed_activation_enabled() -> bool:
    """Report whether the trusted managed-activation path is enabled."""
    return _MANAGED_ACTIVATION_ENABLED


def require_managed_activation_enabled() -> None:
    """Fail closed while the trusted managed-activation path is disabled.

    Raises :class:`ManagedActivationDisabledError` (never a bare exception) so
    callers surface a typed, privacy-safe refusal with no path or trust detail.
    """
    if not _MANAGED_ACTIVATION_ENABLED:
        raise ManagedActivationDisabledError("managed activation is disabled")


# --- Integrated trusted managed activation ---------------------------------
#
# The seam below is the complete integrated managed-activation transaction as
# the session-facing layer sees it. It is fully wired *now*, while
# ``_MANAGED_ACTIVATION_ENABLED`` is still False, so enabling the feature later
# is a flag-only change and never a code change.
#
# Ordering is the whole contract:
#
#   1. everything that can fail is validated *before* the trust commit, so a
#      pre-commit refusal leaves the previous valid authority untouched;
#   2. the trust commit is the single point at which the new generation,
#      verified binding, trust root, capability binding, and managed source
#      identity become authoritative — atomically from the caller's view;
#   3. after that point nothing rolls back to stale authority. A failure while
#      publishing the session-facing mirror is reconciled *forward* by retiring
#      the binding (a further generation advance that clears the managed caches
#      and leaves the session fail-closed), never by restoring the prior root.
#
# ``managed_trust`` is imported lazily inside the function: this module is
# imported by ``state.context`` and by the trust service's own consumers, so a
# module-level import would create a cycle.


class ManagedActivationOutcome(Enum):
    """Result of an integrated trusted managed activation attempt."""

    ACTIVATED = "activated"
    UNCHANGED = "unchanged"
    DISABLED = "disabled"
    REFUSED_PRE_COMMIT = "refused_pre_commit"
    INTERRUPTED_POST_COMMIT = "interrupted_post_commit"


@dataclass(frozen=True, slots=True)
class ManagedActivationReport:
    """Privacy-safe description of an integrated managed activation attempt.

    Carries no path, no locator, no trust-root serialization, and no exception
    text — only the outcome, whether the trust commit was reached, and the
    resulting generation.
    """

    outcome: ManagedActivationOutcome
    trust_committed: bool
    generation: int

    @property
    def activated(self) -> bool:
        """True when the managed version is the authoritative active dataset."""
        return self.outcome in (
            ManagedActivationOutcome.ACTIVATED,
            ManagedActivationOutcome.UNCHANGED,
        )


def activate_managed_context(
    state: MutableMapping[str, Any],
    target: DatasetContext,
    *,
    relative_posix: str,
    display_name: str | None = None,
) -> ManagedActivationReport:
    """Run the integrated trusted managed activation transaction.

    Refuses immediately while the feature flag is off, so production behavior
    is unchanged until the single flag literal is flipped. ``target`` must be a
    validated managed context; ``relative_posix`` is its workspace-relative
    locator, the only path form permitted in privacy-safe trust state.
    """
    from data_quality_toolkit.adapters.ui.services.managed_trust import (
        ManagedTrustError,
        commit_trust_root,
        current_generation,
        ensure_session_capability,
        make_source_locator,
        reconcile_managed_trust,
        retire_managed_trust,
    )

    if not _MANAGED_ACTIVATION_ENABLED:
        return ManagedActivationReport(
            outcome=ManagedActivationOutcome.DISABLED,
            trust_committed=False,
            generation=current_generation(state),
        )

    # Marker-independent forward reconciliation before anything else: an
    # invalid binding left by an interrupted attempt is retired by generation
    # and capability identity alone, never by inspecting a physical marker.
    reconcile_managed_trust(state)

    # ---- pre-commit: every failure leaves the previous authority intact ----
    try:
        validate_dataset_context(target)
        if not target.managed:
            raise InvalidManagedContextError("trusted activation requires a managed context")
        locator = make_source_locator(
            display_name=display_name or Path(target.source_path).name,
            relative_posix=relative_posix,
            absolute_path=target.source_path,
        )
    except (DatasetActivationError, ManagedTrustError):
        return ManagedActivationReport(
            outcome=ManagedActivationOutcome.REFUSED_PRE_COMMIT,
            trust_committed=False,
            generation=current_generation(state),
        )

    capability = ensure_session_capability(state)
    try:
        commit_trust_root(
            state,
            capability,
            version_id=str(target.version_id),
            family_id=str(target.family_id),
            content_id=str(target.content_id),
            root_content_id=str(target.root_content_id),
            parent_version_id=target.parent_version_id,
            version_label=str(target.version_label),
            locator=locator,
            size_bytes=target.size_bytes,
            modified_ns=target.modified_ns,
            large_file_mode=target.large_file_mode,
        )
    except ManagedTrustError:
        return ManagedActivationReport(
            outcome=ManagedActivationOutcome.REFUSED_PRE_COMMIT,
            trust_committed=False,
            generation=current_generation(state),
        )

    # ---- past the trust commit: forward-only, never a rollback ----
    try:
        activation = activate_dataset_context(state, target)
    except Exception:
        retire_managed_trust(state)
        return ManagedActivationReport(
            outcome=ManagedActivationOutcome.INTERRUPTED_POST_COMMIT,
            trust_committed=True,
            generation=current_generation(state),
        )
    return ManagedActivationReport(
        outcome=(
            ManagedActivationOutcome.ACTIVATED
            if activation.changed
            else ManagedActivationOutcome.UNCHANGED
        ),
        trust_committed=True,
        generation=current_generation(state),
    )


# --- Result contract ------------------------------------------------------


class ActivationStatus(Enum):
    """Outcome of an activation attempt."""

    ACTIVATED = "activated"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class DatasetActivationResult:
    """Typed description of an activation outcome.

    Carries only path-safe identity fields (managed flags and version IDs); it
    never exposes a source path.
    """

    status: ActivationStatus
    cleared_keys: tuple[str, ...]
    previous_managed: bool
    new_managed: bool
    previous_version_id: str | None
    new_version_id: str | None

    @property
    def changed(self) -> bool:
        """True when the dataset binding changed and derived state was cleared."""
        return self.status is ActivationStatus.ACTIVATED

    @property
    def activated(self) -> bool:
        """Alias of :attr:`changed`; True when a new binding became active."""
        return self.status is ActivationStatus.ACTIVATED


# --- Identity-format predicates (self-contained; stdlib only) --------------

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_LIFECYCLE_ID_FIELDS: tuple[str, ...] = (
    "version_id",
    "family_id",
    "content_id",
    "root_content_id",
)


def _is_uuid(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _is_sha256(value: str | None) -> bool:
    return isinstance(value, str) and _SHA256_RE.match(value) is not None


def _is_blank(value: str | None) -> bool:
    return not isinstance(value, str) or not value.strip()


# --- Context validation ---------------------------------------------------


def validate_dataset_context(context: DatasetContext) -> None:
    """Validate a context's lifecycle invariants before any state mutation.

    Raises :class:`InvalidLegacyContextError` for an unmanaged context that
    carries lifecycle data, or :class:`InvalidManagedContextError` for a managed
    context with missing/blank/malformed identities. Error text never echoes the
    source path.
    """
    if context.managed:
        _validate_managed_present(context)
        _validate_managed_formats(context)
    else:
        _validate_legacy(context)


def _validate_legacy(context: DatasetContext) -> None:
    carried = [
        name
        for name in (*_LIFECYCLE_ID_FIELDS, "parent_version_id", "version_label")
        if getattr(context, name) is not None
    ]
    if carried:
        raise InvalidLegacyContextError(
            "unmanaged context must not carry lifecycle fields: " + ", ".join(carried)
        )


def _validate_managed_present(context: DatasetContext) -> None:
    missing = [name for name in _LIFECYCLE_ID_FIELDS if _is_blank(getattr(context, name))]
    if missing:
        raise InvalidManagedContextError(
            "managed context requires non-empty: " + ", ".join(missing)
        )
    if _is_blank(context.version_label):
        raise InvalidManagedContextError("managed context requires a version label")


def _validate_managed_formats(context: DatasetContext) -> None:
    checks: tuple[tuple[bool, str], ...] = (
        (_is_uuid(context.version_id), "version_id is not a UUID"),
        (_is_uuid(context.family_id), "family_id is not a UUID"),
        (_is_sha256(context.content_id), "content_id is not sha256"),
        (_is_sha256(context.root_content_id), "root_content_id is not sha256"),
    )
    for ok, message in checks:
        if not ok:
            raise InvalidManagedContextError(message)
    if context.parent_version_id is not None and not _is_uuid(context.parent_version_id):
        raise InvalidManagedContextError("parent_version_id is not a UUID")


# --- Validated context factories (pure; no filesystem access) --------------


def make_legacy_context(
    *,
    source_path: str,
    display_name: str,
    size_bytes: int,
    modified_ns: int,
    large_file_mode: bool = False,
) -> DatasetContext:
    """Build and validate a legacy (unmanaged) context.

    Preserves the legacy field contract (``managed=False``, no lifecycle
    identities or label). Pure: performs no file or sidecar reading.
    """
    context = DatasetContext(
        source_path=source_path,
        display_name=display_name,
        size_bytes=size_bytes,
        modified_ns=modified_ns,
        large_file_mode=large_file_mode,
    )
    validate_dataset_context(context)
    return context


def make_managed_context(
    record: DatasetVersionRecord,
    *,
    source_path: str,
    display_name: str,
    size_bytes: int,
    modified_ns: int,
    large_file_mode: bool = False,
) -> DatasetContext:
    """Build and validate a managed context from a validated version record.

    Maps the record's lifecycle identities and operator-facing label, sets
    ``managed=True``, and maps ``parent_version_id`` to ``None`` when the
    immediate parent is unmanaged (or absent). Preserves the actual active
    ``source_path`` and current filesystem fingerprint supplied by the caller;
    the record's workspace-relative path is not the active pointer. Pure.
    """
    parent_version_id = record.parent.version_id if record.parent is not None else None
    context = DatasetContext(
        source_path=source_path,
        display_name=display_name,
        size_bytes=size_bytes,
        modified_ns=modified_ns,
        large_file_mode=large_file_mode,
        managed=True,
        version_id=record.version_id,
        family_id=record.family_id,
        content_id=record.content_id,
        root_content_id=record.root_content_id,
        parent_version_id=parent_version_id,
        version_label=record.label,
    )
    validate_dataset_context(context)
    return context


# --- Snapshot / rollback primitive ----------------------------------------

_TRACKED_KEYS: tuple[str, ...] = (DATASET_CONTEXT, *DATASET_DERIVED_STATE_KEYS)


def _snapshot(state: MutableMapping[str, Any]) -> dict[str, tuple[bool, Any]]:
    """Capture presence-and-value of every key this service may mutate."""
    return {key: (key in state, state.get(key)) for key in _TRACKED_KEYS}


def _restore(state: MutableMapping[str, Any], snapshot: dict[str, tuple[bool, Any]]) -> None:
    """Restore each tracked key exactly, including absent-versus-present state."""
    for key, (present, value) in snapshot.items():
        if present:
            state[key] = value
        elif key in state:
            del state[key]


# Keys an operator can legitimately have entered *before* any dataset is active,
# and which therefore survive a first activation. Both are values the operator
# typed themselves for manual or historical work; there is no previous dataset
# whose identity they could be stale against, so clearing them would simply
# discard the operator's own input. Every other derived key is dataset-derived by
# construction and is cleared as usual. This exemption is deliberately narrow and
# applies *only* to a first activation: once a prior context exists, a genuine
# switch clears both of these along with everything else.
_FIRST_ACTIVATION_PRESERVED_KEYS: frozenset[str] = frozenset({SRC_DATASET_ID, EXPORT_CSV_PATH})


def _keys_to_invalidate(*, had_prior_context: bool) -> tuple[str, ...]:
    """Return the derived keys cleared for an invalidating transition.

    A genuine replacement (a prior context existed) clears every derived key so
    a new dataset never inherits the previous dataset's identity. A first
    activation preserves the operator-entered compatibility keys listed in
    :data:`_FIRST_ACTIVATION_PRESERVED_KEYS` — an operator-typed ``SRC_DATASET_ID``
    used for manual/historical lookup, and a pre-entered ``EXPORT_CSV_PATH`` —
    because before any dataset is active neither can be stale.
    """
    if had_prior_context:
        return DATASET_DERIVED_STATE_KEYS
    return tuple(
        key for key in DATASET_DERIVED_STATE_KEYS if key not in _FIRST_ACTIVATION_PRESERVED_KEYS
    )


# --- Atomic transition operations -----------------------------------------


def activate_dataset_context(
    state: MutableMapping[str, Any],
    target: DatasetContext,
) -> DatasetActivationResult:
    """Atomically make ``target`` the one active dataset context.

    Validates ``target`` before touching state, compares the version-aware
    binding identities, clears ``DATASET_DERIVED_STATE_KEYS`` only on a binding
    change, and writes ``target`` as the sole authoritative ``DATASET_CONTEXT``.
    Unrelated session keys are never touched. If any mutation raises, the full
    prior snapshot is restored and :class:`StateMutationError` is raised so no
    partially active state remains.
    """
    validate_dataset_context(target)
    current = get_dataset_context(state)
    changed = current is None or current.binding_identity != target.binding_identity
    keys = _keys_to_invalidate(had_prior_context=current is not None) if changed else ()

    snapshot = _snapshot(state)
    try:
        for key in keys:
            if key in state:
                del state[key]
        state[DATASET_CONTEXT] = target
    except Exception as exc:
        _restore(state, snapshot)
        raise StateMutationError("failed to activate dataset context") from exc

    status = ActivationStatus.ACTIVATED if changed else ActivationStatus.UNCHANGED
    cleared = tuple(key for key in keys if snapshot[key][0])
    return DatasetActivationResult(
        status=status,
        cleared_keys=cleared,
        previous_managed=current.managed if current is not None else False,
        new_managed=target.managed,
        previous_version_id=current.version_id if current is not None else None,
        new_version_id=target.version_id,
    )


def clear_dataset_context(state: MutableMapping[str, Any]) -> bool:
    """Atomically clear the active context and all dataset-derived state.

    Removes ``DATASET_CONTEXT`` and every key in ``DATASET_DERIVED_STATE_KEYS``
    while preserving unrelated session keys. Returns ``True`` when an active
    typed context existed. A mutation failure restores the full prior snapshot
    and raises :class:`StateMutationError`, so clearing is never partial.
    """
    existed = get_dataset_context(state) is not None
    snapshot = _snapshot(state)
    try:
        for key in _TRACKED_KEYS:
            if key in state:
                del state[key]
    except Exception as exc:
        _restore(state, snapshot)
        raise StateMutationError("failed to clear dataset context") from exc
    return existed
