"""Recognition and privacy-safe presentation of a missing hard-link capability.

Confirmation publishes every final artifact with ``os.link`` — the one primitive
that creates a name atomically and *cannot* overwrite, truncate, or replace an
existing file. Some filesystems (FAT32, exFAT, and several network mounts) do
not implement hard links at all. That is a capability limit of the location, not
a transient error and not a permission problem, and it deserves guidance an
operator can act on rather than the generic "could not write" wording.

This module owns exactly two decisions and nothing else:

* whether an :class:`OSError` raised by ``os.link`` *proves* the filesystem
  lacks the capability, as opposed to any other failure;
* how a temporary staging artifact left behind by that failure may be named on
  screen.

Recognition is narrow on purpose. An unrecognized error keeps the existing
generic fail-closed message, because presenting a permission, disk-space, or
read-only failure as "unsupported filesystem" would send an operator to fix the
wrong thing. Nothing here recovers, retries, or publishes: the fail-closed
contract stays in the confirmation service, and this module only explains it.

The module is deliberately pure — standard library only, no IO, no session
state, no Streamlit, no pandas, and no knowledge of lifecycle identities.
"""

from __future__ import annotations

import errno
import re
from collections.abc import Iterable

__all__ = [
    "capability_guidance",
    "is_hardlink_unsupported",
    "safe_temp_label",
]


def _errno_set(*names: str) -> frozenset[int]:
    """Collect the named errno values that exist on this platform."""
    found = (getattr(errno, name, None) for name in names)
    return frozenset(value for value in found if isinstance(value, int))


# POSIX ``link(2)`` reports a filesystem that cannot create hard links at all.
# ``EPERM`` is that documented signal for FAT/exFAT mounts under Linux, which is
# why it is here; ``EACCES`` — the permission-denied code — is deliberately
# absent, so a denied write is never presented as a missing capability. So are
# ``EXDEV`` (cross-device, impossible here: staging happens in the destination
# directory), ``ENOSPC``, ``EROFS``, ``EIO``, and ``ENOENT``.
_UNSUPPORTED_ERRNOS = _errno_set("ENOSYS", "ENOTSUP", "EOPNOTSUPP", "EPERM")

# Windows ``CreateHardLinkW``: ERROR_INVALID_FUNCTION on a volume with no
# hard-link support (FAT/exFAT), ERROR_NOT_SUPPORTED on mounts that refuse the
# operation. ERROR_ACCESS_DENIED (5) and ERROR_NOT_SAME_DEVICE (17) are excluded
# for the same reason their POSIX counterparts are.
_UNSUPPORTED_WINERRORS = frozenset({1, 50})

# One filename segment produced by this application's own staging: a leading
# dot, the reserved artifact name, the ``mkstemp`` token, and a ``.tmp`` suffix.
# The character class alone excludes path separators, drive letters, UNC
# prefixes, URI schemes, and ``~`` home shorthands, and the bound keeps any
# unexpected name from reaching a page.
_MAX_TEMP_LABEL_CHARS = 160
_TEMP_LABEL = re.compile(r"\.[A-Za-z0-9._-]{1,150}\.tmp")

_GUIDANCE = (
    "Confirmation failed safely. This workspace location does not support the "
    "atomic hard-link publication that confirmation requires, so no version was "
    "published. The processed output remains unmanaged, the active managed "
    "version did not change, and no copy, overwrite, or replace fallback was "
    "attempted."
)
_ANONYMOUS_TEMP = "A temporary staging file may remain in the workspace."
_NO_CLEANUP = "Nothing was deleted automatically; review before removing anything."


def is_hardlink_unsupported(exc: OSError) -> bool:
    """True only when ``exc`` proves the filesystem cannot create hard links.

    A Windows ``winerror`` is authoritative whenever it is present: its errno
    translation is lossy (ERROR_INVALID_FUNCTION arrives as ``EINVAL``, which is
    far too broad to classify on). Everything else falls back to the narrow
    POSIX errno set. Any unrecognized failure returns ``False`` so the caller
    keeps its existing generic behavior.
    """
    winerror = getattr(exc, "winerror", None)
    if isinstance(winerror, int):
        return winerror in _UNSUPPORTED_WINERRORS
    return exc.errno in _UNSUPPORTED_ERRNOS


def safe_temp_label(name: str) -> str:
    """Return ``name`` when it is a displayable staging basename, else ``""``.

    The caller must already have proven ownership — that this exact name was
    created by the attempt being reported. This function adds the display
    guarantee on top: a single bounded filename segment with no directory, no
    separator, and no location information of any kind. Anything that does not
    match degrades to ``""`` so the caller can fall back to a generic statement
    rather than echoing an unexpected value.
    """
    text = str(name or "")
    if len(text) > _MAX_TEMP_LABEL_CHARS:
        return ""
    return text if _TEMP_LABEL.fullmatch(text) else ""


def capability_guidance(temp_labels: Iterable[str] = ()) -> str:
    """Compose the operator guidance for a proven missing hard-link capability.

    States, in order: that confirmation failed safely, why, that the output is
    unmanaged, that the active version is unchanged, that no fallback was
    attempted, what may remain, and that nothing was removed for you. Only
    already-vetted labels are interpolated; an empty set degrades to a generic
    statement instead of naming anything.
    """
    names = [label for label in temp_labels if label]
    if names:
        noun = "file" if len(names) == 1 else "files"
        remaining = f"Temporary staging {noun} left for your review: {', '.join(names)}."
    else:
        remaining = _ANONYMOUS_TEMP
    return f"{_GUIDANCE} {remaining} {_NO_CLEANUP}"
