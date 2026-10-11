"""Pure, dependency-free redaction of absolute filesystem paths.

This module is the single semantic authority for "how much of a filesystem path
may appear in user-facing text". Two shapes of the same policy live here:

* :func:`redact_paths` / :func:`redact_message_paths` scrub paths *embedded in a
  message*, preserving the surrounding wording. CLI, UI, and pipeline status text
  all route through these.
* :func:`redact_path_to_basename` reduces a *bare path value* to its leaf, for
  surfaces that display a location rather than a sentence.

Both share one leaf rule (:func:`_leaf`), so a bare drive/UNC root is never
displayed as a partial host path by one surface and suppressed by another.
Callers choose their own replacement wording; the shared error contract and path
guard keep raw paths for programmatic use.
"""

from __future__ import annotations

import re
from collections.abc import Callable

# A path component may legitimately contain spaces, but ordinary prose follows a
# path just as often, so a space is admitted only where the reading stays
# unambiguous. Two shapes are tried in order: a spaced form, whose trailing
# component must end in a file extension (that anchor is what forces
# ``...\drift.db (disk I/O error)`` to stop at the database file rather than run
# on to the slash in ``I/O``), and the historical whitespace-free form. A colon
# closes a trailing component (``x.db: no such file``) but stays legal inside a
# separator-closed directory component. The space run inside a directory
# component is possessive, which keeps the nested quantifiers linear.
_DIR_CHAR = r"[^\s\\/'\"<>|?*]"
_TAIL_CHAR = r"[^\s\\/:'\"<>|?*]"
_DIR_SEG = rf"{_DIR_CHAR}+(?:[ ]+{_DIR_CHAR}+)*+"
_TAIL_EXT = rf"{_TAIL_CHAR}+(?:[ ]+{_TAIL_CHAR}+)*?\.[A-Za-z0-9]{{1,8}}"

# Windows drive-absolute (``C:\...``) or UNC (``\\host\share``) paths. The
# single-letter drive is guarded by a lookbehind so URL schemes (e.g. the
# ``s:/`` inside ``https:/``) are never matched. Repeated separators keep the
# repr-escaped form (``C:\\Users\\...``) matching as a single path.
_WIN_PATH = re.compile(
    rf"(?<![A-Za-z0-9:])(?:[A-Za-z]:[\\/]+|\\\\+)"
    rf"(?:(?:{_DIR_SEG}[\\/]+)*{_TAIL_EXT}"
    rf"|(?:{_DIR_SEG}[\\/]+)+{_TAIL_CHAR}*"
    rf"|{_TAIL_CHAR}*)"
)
# POSIX absolute paths with at least two segments. The leading ``/`` must not be
# preceded by a word char, dot, colon, or slash, so URLs (``https://host/x``)
# and inline fractions like ``0/1`` or ``and/or`` are skipped.
_POSIX_PATH = re.compile(
    rf"(?<![\w.:/])(?:(?:/{_DIR_SEG})+/{_TAIL_EXT}|(?:/{_DIR_SEG})+/{_TAIL_CHAR}+)"
)


def _leaf(token: str) -> str | None:
    """Basename of a matched path token, or ``None`` for a bare root."""
    leaf = token.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if not leaf or leaf.endswith(":"):
        return None
    return leaf


def redact_paths(text: object, *, keep: Callable[[str], str], drop: str) -> str:
    """Redact absolute filesystem paths from *text*.

    Each Windows/UNC or POSIX absolute path found is replaced with
    ``keep(basename)``; a bare root (e.g. ``C:\\``) that has no useful leaf is
    replaced with *drop*. The surrounding message wording (and any quotes around
    the path) is preserved. Returns an empty string for falsy input. Never raises.
    """
    if not text:
        return ""

    def _sub(m: re.Match[str]) -> str:
        leaf = _leaf(m.group(0))
        return drop if leaf is None else keep(leaf)

    out = _WIN_PATH.sub(_sub, str(text))
    out = _POSIX_PATH.sub(_sub, out)
    return out


# Authoritative display marker for a path that has no safe leaf to show.
# Presentation modules import this rather than restating the literal.
PATH_REDACTED_DISPLAY = "[path redacted]"


def redact_message_paths(text: object) -> str:
    """Redact absolute paths using the UI format (basename / ``[path redacted]``).

    Reduces each absolute path to its bare basename and a bare root to
    ``[path redacted]``, preserving the surrounding error wording. This is the
    exact behavior the dashboard relies on.
    """
    return redact_paths(text, keep=lambda leaf: leaf, drop=PATH_REDACTED_DISPLAY)


def redact_path_to_basename(value: object) -> str:
    """Reduce a bare path *value* to a host-independent basename.

    Windows, UNC, and POSIX separators are stripped regardless of the host OS.
    Returns an empty string when no safe leaf exists -- a blank value, a bare
    root (``/``), or a bare drive (``C:\\``) -- so a caller's own fallback
    wording is used instead of a partial host path. Never raises.

    This is the value-shaped form of the same leaf policy
    :func:`redact_message_paths` applies inside a sentence; both delegate to
    :func:`_leaf`, so the two surfaces cannot drift apart.
    """
    if value is None:
        return ""
    try:
        text = str(value).strip()
    except Exception:  # pragma: no cover - defensive: __str__ must not leak
        return ""
    if not text:
        return ""
    return _leaf(text) or ""


__all__ = [
    "PATH_REDACTED_DISPLAY",
    "redact_paths",
    "redact_message_paths",
    "redact_path_to_basename",
]
