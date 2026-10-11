"""UI-private bridge from validated managed trust to shared export provenance.

Trusted managed activation boundary. This module is the *only* place a
:class:`~data_quality_toolkit.shared.managed_export_source.VerifiedManagedExportSource`
may be minted. It sits exactly on the containment boundary:

* it reads UI-private trust types (``ManagedTrustRoot``, ``SessionCapability``)
  and never exports them;
* it emits one immutable shared provenance value that application-workflow and
  public-API code can consume without importing the UI layer at all.

Every managed export therefore carries provenance that was verified *here*,
under live session trust, and is passed downstream as a single undecomposed
object — never as loose version/content/path parameters.

Refusals are fail-closed and privacy-safe: no absolute managed path, no
workspace path, and no trust-root serialization ever reaches the message.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from data_quality_toolkit.adapters.ui.services.managed_trust import (
    ManagedTrustRoot,
    TrustAuthority,
    peek_session_capability,
    resolve_trust_authority,
)
from data_quality_toolkit.shared.managed_export_source import (
    MANAGED_FULL_MAX_SOURCE_BYTES,
    VerifiedManagedExportSource,
)

__all__ = [
    "ManagedExportRefusedError",
    "build_verified_managed_export_source",
    "managed_export_available",
]


# Fixed refusal vocabulary. Message text is chosen at authoring time and never
# interpolates a path, identifier, or exception.
_REFUSAL_MESSAGES: dict[str, str] = {
    "NO_VALID_TRUST": "managed export requires a valid managed trust root",
    "MANAGED_MIRROR_WITHOUT_TRUST": (
        "the managed dataset context is not backed by a valid managed trust root"
    ),
    "NO_SESSION_CAPABILITY": "managed export requires the live session capability",
    "LARGE_MODE_REFUSED": "managed LARGE versions cannot be exported",
    "FULL_SIZE_EXCEEDED": "the managed source exceeds the permitted export size ceiling",
    "PROVENANCE_INVALID": "the managed provenance failed validation",
}


class ManagedExportRefusedError(Exception):
    """A managed export was refused; carries a fixed privacy-safe message."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(_REFUSAL_MESSAGES.get(reason_code, "managed export refused"))
        self.reason_code = reason_code


def _require_export_authority(state: MutableMapping[str, Any]) -> ManagedTrustRoot:
    """Resolve managed export authority root-first, failing closed."""
    decision = resolve_trust_authority(state)
    if decision.authority is TrustAuthority.FAIL_CLOSED:
        raise ManagedExportRefusedError("MANAGED_MIRROR_WITHOUT_TRUST")
    if not decision.managed or decision.root is None:
        raise ManagedExportRefusedError("NO_VALID_TRUST")
    # Validation accessor only: this must never create a capability.
    if peek_session_capability(state) is None:
        raise ManagedExportRefusedError("NO_SESSION_CAPABILITY")
    return decision.root


def managed_export_available(state: MutableMapping[str, Any]) -> bool:
    """Report whether a managed export could be built, without building one.

    Never creates trust or capability state and never raises.
    """
    try:
        root = _require_export_authority(state)
    except ManagedExportRefusedError:
        return False
    return not root.large_file_mode and root.size_bytes <= MANAGED_FULL_MAX_SOURCE_BYTES


def build_verified_managed_export_source(
    state: MutableMapping[str, Any],
) -> VerifiedManagedExportSource:
    """Mint the one verified managed export provenance value for this session.

    Requires valid managed trust (root-first; a managed-looking mirror without
    trust fails closed), refuses managed LARGE outright, and enforces the single
    shared FULL size ceiling — exactly at
    :data:`MANAGED_FULL_MAX_SOURCE_BYTES` is permitted, above it is refused.

    The result carries the complete managed provenance as one immutable object.
    Callers must pass it downstream whole; the provenance is never decomposed
    into separate version, content, or path parameters.
    """
    root = _require_export_authority(state)
    if root.large_file_mode:
        raise ManagedExportRefusedError("LARGE_MODE_REFUSED")
    if root.size_bytes > MANAGED_FULL_MAX_SOURCE_BYTES:
        raise ManagedExportRefusedError("FULL_SIZE_EXCEEDED")
    try:
        return VerifiedManagedExportSource(
            version_id=root.version_id,
            family_id=root.family_id,
            content_id=root.content_id,
            root_content_id=root.root_content_id,
            parent_version_id=root.parent_version_id,
            version_label=root.version_label,
            display_name=root.locator.display_name,
            relative_posix=root.locator.relative_posix,
            size_bytes=root.size_bytes,
            modified_ns=root.modified_ns,
            large_file_mode=root.large_file_mode,
            source_path=root.locator.absolute_path,
        )
    except ValueError as exc:
        # Never let the underlying message escape: it could echo field content.
        raise ManagedExportRefusedError("PROVENANCE_INVALID") from exc
