"""UI-private managed trust authority.

This service owns the durable-free, in-process trust boundary for explicit
managed-version reopening:

* :class:`SessionCapability` — an identity-only session anchor. Two instances
  are never equal; a pickled or reconstructed copy is a *different* identity,
  so serialization can never carry authority. Only the activation path may
  ensure/create it; validation accessors never do.
* the managed generation counter and binding identity — the current generation
  alone defines validity, so stale bindings stay retired even when physical
  cleanup fails (reconciliation is marker-independent by construction);
* :class:`ManagedTrustRoot` — the authoritative managed binding. The session
  capability deliberately lives *outside* the root: a root copied, serialized,
  or rebuilt from durable state cannot revalidate without the live capability
  instance recorded at commit time;
* a privacy-safe :class:`ManagedSourceLocator` whose public identity is the
  display name and workspace-relative POSIX path only;
* fail-closed validation and reconciliation: a valid root is authoritative
  even over a stale ``DATASET_CONTEXT`` mirror, a managed-looking mirror
  without valid trust fails closed, and a manual path never overrides valid
  managed trust;
* managed cache-invalidation hooks, invoked on every generation change.

The module imports neither Streamlit nor pandas, performs no filesystem
access, and never exposes an absolute path through repr, str, labels, or
error text. There is exactly one trust-commit point
(:func:`commit_trust_root`); failures before it leave the previous authority
unchanged, and nothing after it ever rolls back to stale authority.
"""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from data_quality_toolkit.adapters.ui.state.context import DatasetContext, get_dataset_context

__all__ = [
    "MANAGED_TRUST_STATE_KEY",
    "ManagedSourceLocator",
    "ManagedTrustError",
    "ManagedTrustRoot",
    "SessionCapability",
    "TrustAuthority",
    "TrustDecision",
    "commit_trust_root",
    "current_generation",
    "ensure_session_capability",
    "get_valid_trust_root",
    "make_source_locator",
    "peek_session_capability",
    "reconcile_managed_trust",
    "register_cache_invalidation_hook",
    "resolve_trust_authority",
    "retire_managed_trust",
]

# Single private session-state slot owned by this service. The value is a
# plain in-process object; it is never written to disk and is meaningless if
# copied into durable state (validity requires the live capability instance).
MANAGED_TRUST_STATE_KEY = "_dqt_managed_trust_state"


class ManagedTrustError(Exception):
    """A managed-trust operation was refused; message text is privacy-safe."""


# --- Session capability (identity-only anchor) ------------------------------


@dataclass(eq=False, frozen=True, slots=True)
class SessionCapability:
    pass


# --- Privacy-safe source locator --------------------------------------------


@dataclass(frozen=True, slots=True)
class ManagedSourceLocator:
    """Locator whose *public identity* is privacy-safe.

    ``display_name`` and ``relative_posix`` are the only fields that may appear
    in labels, logs, reprs, or errors. ``absolute_path`` is machine-use only
    (opening the artifact); it is excluded from ``repr`` and must never become
    an identity, a cache key, or operator-facing output.
    """

    display_name: str
    relative_posix: str
    absolute_path: str = field(repr=False)


def make_source_locator(
    *, display_name: str, relative_posix: str, absolute_path: str
) -> ManagedSourceLocator:
    """Build a locator, refusing path-like or absolute public fields."""
    name = (display_name or "").strip()
    rel = (relative_posix or "").strip()
    if not name or "/" in name or "\\" in name or ":" in name:
        raise ManagedTrustError("locator display name must be a bare file name")
    if not rel or "\\" in rel or ":" in rel or PurePosixPath(rel).is_absolute():
        raise ManagedTrustError("locator relative path must be workspace-relative posix")
    if not (absolute_path or "").strip():
        raise ManagedTrustError("locator requires a machine-side artifact path")
    return ManagedSourceLocator(display_name=name, relative_posix=rel, absolute_path=absolute_path)


# --- Managed trust root ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ManagedTrustRoot:
    """The authoritative managed binding committed by trusted activation.

    Deliberately carries *no* :class:`SessionCapability` field: the capability
    recorded at commit time is held by the trust store, so a root copied out of
    session state (or rebuilt from durable data) can never revalidate on its
    own. ``generation`` ties the root to the store's current generation —
    validity is generation-driven, never marker-driven.
    """

    generation: int
    version_id: str
    family_id: str
    content_id: str
    root_content_id: str
    parent_version_id: str | None
    version_label: str
    locator: ManagedSourceLocator
    size_bytes: int
    modified_ns: int
    large_file_mode: bool


_REQUIRED_ROOT_IDS: tuple[str, ...] = (
    "version_id",
    "family_id",
    "content_id",
    "root_content_id",
    "version_label",
)


# --- In-process trust store ---------------------------------------------------


class _TrustState:
    """Mutable, in-process-only trust store for one UI session."""

    __slots__ = ("capability", "generation", "root", "root_capability")

    def __init__(self) -> None:
        self.capability: SessionCapability | None = None
        self.generation: int = 0
        self.root: ManagedTrustRoot | None = None
        self.root_capability: SessionCapability | None = None


def _peek_state(state: MutableMapping[str, Any]) -> _TrustState | None:
    value = state.get(MANAGED_TRUST_STATE_KEY)
    return value if isinstance(value, _TrustState) else None


def _ensure_state(state: MutableMapping[str, Any]) -> _TrustState:
    existing = _peek_state(state)
    if existing is not None:
        return existing
    created = _TrustState()
    state[MANAGED_TRUST_STATE_KEY] = created
    return created


# --- Capability lifecycle -----------------------------------------------------


def ensure_session_capability(state: MutableMapping[str, Any]) -> SessionCapability:
    """Return the live session capability, creating it if absent.

    Activation is the *only* path allowed to call this. Everything else must
    use :func:`peek_session_capability`, which never creates.
    """
    trust = _ensure_state(state)
    if trust.capability is None:
        trust.capability = SessionCapability()
    return trust.capability


def peek_session_capability(state: MutableMapping[str, Any]) -> SessionCapability | None:
    """Validation accessor: report the live capability without creating one."""
    trust = _peek_state(state)
    return trust.capability if trust is not None else None


def current_generation(state: MutableMapping[str, Any]) -> int:
    """Return the current managed generation (0 before any commit)."""
    trust = _peek_state(state)
    return trust.generation if trust is not None else 0


# --- Cache invalidation hooks --------------------------------------------------

_InvalidationHook = Callable[[MutableMapping[str, Any]], None]
_INVALIDATION_HOOKS: list[_InvalidationHook] = []


def register_cache_invalidation_hook(hook: _InvalidationHook) -> None:
    """Register a hook invoked on every generation change (idempotent)."""
    if hook not in _INVALIDATION_HOOKS:
        _INVALIDATION_HOOKS.append(hook)


def _run_invalidation_hooks(state: MutableMapping[str, Any]) -> None:
    # Correctness never depends on a hook succeeding: cache reads revalidate
    # trust first, so a failed cleanup only delays memory reuse. A hook error
    # therefore must not roll anything back — reconcile forward and continue.
    for hook in list(_INVALIDATION_HOOKS):
        try:
            hook(state)
        except Exception:  # noqa: S112 - forward reconciliation, never rollback
            continue


# --- The single trust-commit point ---------------------------------------------


def commit_trust_root(
    state: MutableMapping[str, Any],
    capability: SessionCapability,
    *,
    version_id: str,
    family_id: str,
    content_id: str,
    root_content_id: str,
    parent_version_id: str | None,
    version_label: str,
    locator: ManagedSourceLocator,
    size_bytes: int,
    modified_ns: int,
    large_file_mode: bool,
) -> ManagedTrustRoot:
    """Commit a new managed trust root; this is the one trust-commit point.

    Every check happens *before* the commit, so a refusal leaves the previous
    valid authority unchanged. The commit itself establishes the new
    generation, verified binding, trust root, and capability binding in one
    caller-visible step, then runs the cache-invalidation hooks. Nothing after
    the commit rolls back to the previous authority.
    """
    trust = _peek_state(state)
    if trust is None or trust.capability is None:
        raise ManagedTrustError("no live session capability; activation must create it first")
    if capability is not trust.capability:
        raise ManagedTrustError("capability is not the live session capability")
    values = {
        "version_id": version_id,
        "family_id": family_id,
        "content_id": content_id,
        "root_content_id": root_content_id,
        "version_label": version_label,
    }
    blank = [name for name in _REQUIRED_ROOT_IDS if not (values[name] or "").strip()]
    if blank:
        raise ManagedTrustError("trust root requires non-empty: " + ", ".join(blank))
    if size_bytes < 0:
        raise ManagedTrustError("trust root size must be non-negative")

    root = ManagedTrustRoot(
        generation=trust.generation + 1,
        version_id=version_id,
        family_id=family_id,
        content_id=content_id,
        root_content_id=root_content_id,
        parent_version_id=parent_version_id,
        version_label=version_label,
        locator=locator,
        size_bytes=size_bytes,
        modified_ns=modified_ns,
        large_file_mode=large_file_mode,
    )
    # -- trust commit (atomic from the caller's perspective) --
    trust.generation = root.generation
    trust.root = root
    trust.root_capability = capability
    # -- post-commit: forward-only --
    _run_invalidation_hooks(state)
    return root


# --- Validation accessors (never create capability or trust) --------------------


def get_valid_trust_root(state: MutableMapping[str, Any]) -> ManagedTrustRoot | None:
    """Return the trust root only when it is currently valid; else ``None``.

    Fail-closed conditions: no trust store, no root, missing live capability,
    a replaced capability (the commit-time instance is no longer the live
    one), or a generation mismatch (the binding was retired). This accessor
    never creates capability or trust state.
    """
    trust = _peek_state(state)
    if trust is None or trust.root is None:
        return None
    if trust.capability is None or trust.root_capability is not trust.capability:
        return None
    if trust.root.generation != trust.generation:
        return None
    return trust.root


def retire_managed_trust(state: MutableMapping[str, Any]) -> None:
    """Retire any managed binding by advancing the generation (managed clear).

    Generation-driven: even if some caller kept a reference to the old root,
    the generation mismatch alone invalidates it. Runs the cache-invalidation
    hooks so both managed caches are cleared.
    """
    trust = _peek_state(state)
    if trust is None:
        return
    trust.generation += 1
    trust.root = None
    trust.root_capability = None
    _run_invalidation_hooks(state)


# --- Root-first authority resolution ---------------------------------------------


class TrustAuthority(Enum):
    """Which authority governs the active dataset for managed dispatch."""

    MANAGED_AUTHORITY = "managed_authority"
    UNMANAGED = "unmanaged"
    FAIL_CLOSED = "fail_closed"


@dataclass(frozen=True, slots=True)
class TrustDecision:
    """Outcome of root-first authority resolution (privacy-safe fields only)."""

    authority: TrustAuthority
    root: ManagedTrustRoot | None
    reason_code: str
    mirror_stale: bool = False

    @property
    def managed(self) -> bool:
        """True when a valid managed trust root is the governing authority."""
        return self.authority is TrustAuthority.MANAGED_AUTHORITY


def _mirror_matches(context: DatasetContext, root: ManagedTrustRoot) -> bool:
    return (
        context.managed
        and context.version_id == root.version_id
        and context.content_id == root.content_id
    )


def resolve_trust_authority(state: MutableMapping[str, Any]) -> TrustDecision:
    """Resolve the governing authority, root-first and fail-closed.

    * A valid trust root is authoritative even when ``DATASET_CONTEXT`` is
      stale, missing, or manually overridden — a manual path never outranks
      valid managed trust.
    * A managed-looking ``DATASET_CONTEXT`` without valid trust fails closed.
    * With no valid trust and no managed-looking mirror, unmanaged behavior is
      untouched.
    """
    root = get_valid_trust_root(state)
    context = get_dataset_context(state)
    if root is not None:
        stale = context is None or not _mirror_matches(context, root)
        return TrustDecision(
            authority=TrustAuthority.MANAGED_AUTHORITY,
            root=root,
            reason_code="ROOT_VALID",
            mirror_stale=stale,
        )
    if context is not None and context.managed:
        return TrustDecision(
            authority=TrustAuthority.FAIL_CLOSED,
            root=None,
            reason_code="MANAGED_MIRROR_WITHOUT_TRUST",
        )
    return TrustDecision(authority=TrustAuthority.UNMANAGED, root=None, reason_code="UNMANAGED")


def reconcile_managed_trust(state: MutableMapping[str, Any]) -> TrustDecision:
    """Marker-independent forward reconciliation of the trust store.

    Drops an internally-recorded binding that is no longer valid (retired
    generation, missing or replaced capability) without touching the previous
    generation's authority — there is nothing to roll back to. The governing
    decision is then re-resolved root-first. Physical cleanup of any mirror or
    marker is *not* required for correctness; validity is generation-driven.
    """
    trust = _peek_state(state)
    if trust is not None and trust.root is not None and get_valid_trust_root(state) is None:
        trust.root = None
        trust.root_capability = None
    return resolve_trust_authority(state)
