"""Shared immutable managed-export provenance contract.

This module is the one crossing point between the UI trust boundary and the
application-workflow / public-API layers for managed exports. It deliberately
lives in the shared kernel: it imports only the standard library (no pandas,
no Streamlit, and no UI trust types), so workflow and API code can depend on
it without ever importing the UI layer.

:data:`MANAGED_FULL_MAX_SOURCE_BYTES` is the single authoritative managed FULL
source-size ceiling; every consumer imports it from here rather than redefining
it.

:class:`VerifiedManagedExportSource` carries verified managed provenance as one
immutable value. Managed export siblings accept exactly this object — the
provenance is never decomposed into separate version/content/path parameters.
The public identity is privacy-safe (display name, workspace-relative POSIX
path, lifecycle identifiers); the machine-side ``source_path`` exists only so
downstream code can open the artifact and is excluded from ``repr``.

:func:`verify_managed_source` is the one authoritative managed-source
verification policy. It lives here — below ``adapters.ui`` and below
``application`` — so the UI frame loader and the application export boundary
enforce the *same* checks instead of each owning a private copy. Path/stat
identity is always evaluated; exact content identity is evaluated only when a
trusted ``content_id`` is supplied, which is mandatory on the managed export
path (provenance correctness) and deliberately skipped on ordinary managed
frame loads (unchanged performance semantics).
"""

from __future__ import annotations

import hashlib
import os
import stat as stat_module
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

__all__ = [
    "MANAGED_FULL_MAX_SOURCE_BYTES",
    "MANAGED_SOURCE_READ_CHUNK_BYTES",
    "ManagedSourceVerificationError",
    "VerifiedManagedExportSource",
    "managed_content_id_from_file",
    "verify_managed_export_source",
    "verify_managed_source",
]

# Managed FULL loading/export permits sources up to and including this many
# bytes (128 MiB). Exactly at the boundary is permitted; above it is refused.
MANAGED_FULL_MAX_SOURCE_BYTES = 134_217_728


def _require_non_blank(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"managed export source requires non-empty {name}")


@dataclass(frozen=True, slots=True)
class VerifiedManagedExportSource:
    """Immutable, verified managed provenance for one export-capable source.

    Instances are produced only by the UI-side managed export gateway after
    trust validation; downstream workflow/API/export code treats the object as
    the complete provenance authority and never re-derives or decomposes it.

    ``source_path`` is machine-use only: excluded from ``repr`` and never part
    of the public identity, labels, or error text.
    """

    version_id: str
    family_id: str
    content_id: str
    root_content_id: str
    parent_version_id: str | None
    version_label: str
    display_name: str
    relative_posix: str
    size_bytes: int
    modified_ns: int
    large_file_mode: bool
    source_path: str = field(repr=False)

    def __post_init__(self) -> None:
        for name in (
            "version_id",
            "family_id",
            "content_id",
            "root_content_id",
            "version_label",
        ):
            _require_non_blank(name, getattr(self, name))
        _require_non_blank("display_name", self.display_name)
        _require_non_blank("relative_posix", self.relative_posix)
        _require_non_blank("source_path", self.source_path)
        if "/" in self.display_name or "\\" in self.display_name or ":" in self.display_name:
            raise ValueError("display_name must be a bare file name")
        if (
            "\\" in self.relative_posix
            or ":" in self.relative_posix
            or PurePosixPath(self.relative_posix).is_absolute()
        ):
            raise ValueError("relative_posix must be a workspace-relative posix path")
        if not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ValueError("size_bytes must be a non-negative integer")
        if not self.large_file_mode and self.size_bytes > MANAGED_FULL_MAX_SOURCE_BYTES:
            raise ValueError(
                "managed FULL source exceeds the maximum permitted size "
                f"({MANAGED_FULL_MAX_SOURCE_BYTES} bytes)"
            )


# --- Authoritative managed-source verification policy -------------------------
#
# One policy, two callers. The UI managed frame loader delegates its generic
# path/stat identity checks here; the application managed export boundary calls
# the same function and additionally supplies the trusted ``content_id`` so the
# actual bytes are proven immediately before they are consumed.
#
# The stage order below is the established managed-source order and is part of
# the contract: an earlier refusal always wins, so callers observe exactly the
# reason codes they observed before unification.

# Managed sources are hashed in bounded chunks; a bounded-but-large source is
# never materialized in memory merely to establish its identity. This mirrors
# the canonical lifecycle content-identity algorithm (streamed full-file
# SHA-256, rendered ``sha256:<64 hex>``) byte for byte.
MANAGED_SOURCE_READ_CHUNK_BYTES = 1024 * 1024

_SHA256_PREFIX = "sha256:"

# Fixed refusal vocabulary, reusing the established managed reason codes. Every
# message is authored text: no path, identifier, stat value, or exception is
# ever interpolated, so a refusal is safe to surface to an operator verbatim.
_VERIFICATION_MESSAGES: dict[str, str] = {
    "SOURCE_MISSING": "the managed source artifact is no longer available",
    "SOURCE_REPLACED": "the managed source artifact no longer matches its binding",
    "SOURCE_NOT_CONFINED": "the managed source artifact escaped its confinement",
    "CONTENT_MISMATCH": "the managed source content no longer matches its identity",
}


class ManagedSourceVerificationError(Exception):
    """A managed source failed verification; carries a privacy-safe message.

    ``reason_code`` is one of the fixed codes in :data:`_VERIFICATION_MESSAGES`.
    Neither the code nor the message ever carries an absolute path, a workspace
    path, or the trusted content identity.
    """

    def __init__(self, reason_code: str) -> None:
        super().__init__(
            _VERIFICATION_MESSAGES.get(reason_code, "managed source verification refused")
        )
        self.reason_code = reason_code


def managed_content_id_from_file(path: Path) -> str:
    """Return the streamed full-file content identity as ``sha256:<64 hex>``.

    Reads the complete byte sequence in bounded chunks, so any change — at any
    offset, and regardless of file size — changes the result. File size never
    determines identity.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(MANAGED_SOURCE_READ_CHUNK_BYTES), b""):
            digest.update(chunk)
    return f"{_SHA256_PREFIX}{digest.hexdigest()}"


def verify_managed_source(
    *,
    source_path: str,
    relative_posix: str,
    size_bytes: int,
    modified_ns: int,
    content_id: str | None = None,
) -> str | None:
    """Verify a managed source against its trusted identity; never raise.

    Returns ``None`` when the source still matches, otherwise the fixed reason
    code of the first failed stage:

    1. the path still resolves strictly (``SOURCE_MISSING``);
    2. the strict resolution is still the originally trusted target — no
       symlink, junction, reparse, or path indirection was introduced
       (``SOURCE_REPLACED``);
    3. the resolved path still ends in the trusted workspace-relative tail, so
       the artifact remains confined (``SOURCE_NOT_CONFINED``);
    4. the target is still a readable regular file (``SOURCE_MISSING``);
    5. its size still matches ``size_bytes`` (``CONTENT_MISMATCH``);
    6. its stat identity still matches ``modified_ns`` (``CONTENT_MISMATCH``);
    7. when ``content_id`` is supplied, the actual streamed content identity
       still equals it (``CONTENT_MISMATCH``).

    Stage 7 is skipped when ``content_id`` is ``None``: that is the ordinary
    managed frame-load posture, which must not pay a full-file hash. Managed
    export always supplies it, because provenance asserts that exact identity.

    The filesystem is only ever read: nothing is created, repaired, or
    rewritten, and no trust or session state is touched.
    """
    try:
        resolved = Path(source_path).resolve(strict=True)
    except (OSError, RuntimeError):
        return "SOURCE_MISSING"
    if os.path.normcase(str(resolved)) != os.path.normcase(source_path):
        return "SOURCE_REPLACED"
    rel_parts = PurePosixPath(relative_posix).parts
    tail = resolved.parts[-len(rel_parts) :] if rel_parts else ()
    if [os.path.normcase(part) for part in tail] != [os.path.normcase(part) for part in rel_parts]:
        return "SOURCE_NOT_CONFINED"
    try:
        st = resolved.stat()
    except OSError:
        return "SOURCE_MISSING"
    if not stat_module.S_ISREG(st.st_mode):
        return "SOURCE_MISSING"
    if int(st.st_size) != size_bytes:
        return "CONTENT_MISMATCH"
    if int(st.st_mtime_ns) != modified_ns:
        return "CONTENT_MISMATCH"
    if content_id is None:
        return None
    try:
        actual = managed_content_id_from_file(resolved)
    except (OSError, RuntimeError):
        return "SOURCE_MISSING"
    return None if actual == content_id else "CONTENT_MISMATCH"


def verify_managed_export_source(source: VerifiedManagedExportSource) -> None:
    """Re-verify a managed export source immediately before its bytes are read.

    Managed export asserts ``source.content_id`` in its provenance manifest, so
    exact content verification is always required here — trust established at
    activation, gateway minting, or page render may be arbitrarily stale by the
    time an export actually runs.

    Returns ``None`` on success and raises
    :class:`ManagedSourceVerificationError` otherwise, so a caller can never
    proceed to export by ignoring a return value.
    """
    reason = verify_managed_source(
        source_path=source.source_path,
        relative_posix=source.relative_posix,
        size_bytes=source.size_bytes,
        modified_ns=source.modified_ns,
        content_id=source.content_id,
    )
    if reason is not None:
        raise ManagedSourceVerificationError(reason)
