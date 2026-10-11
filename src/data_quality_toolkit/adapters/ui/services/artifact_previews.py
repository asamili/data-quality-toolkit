"""UI service: bounded, safe previews of local artifact files for the dashboard.

Reads are size-bounded and type-gated. Nothing here surfaces full paths; callers
pass a path for local read only and display basenames. No network, no eval, no
following of remote references — only local file reads with explicit limits.

Every string this module hands back is rendered directly by the dashboard (a
caption, a code block, a status line), so the exception text behind a failed
read is path-redacted here at that presentation boundary rather than at each
call site. Redaction is delegated to the shared scrubber so this surface cannot
drift from the CLI and error-banner ones. Exception types, control flow, and the
programmatic error contract in ``shared.error_contract`` are untouched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from data_quality_toolkit.shared.text_redaction import redact_message_paths

MAX_PREVIEW_BYTES = 64_000
MAX_PREVIEW_ROWS = 20
MAX_DOWNLOAD_BYTES = 25_000_000

_CSV_SUFFIXES = {".csv"}
_JSON_SUFFIXES = {".json"}
_TEXT_SUFFIXES = {".txt", ".md", ".dax", ".mmd", ".log", ".readme", ".jsonl"}


def human_size(size_bytes: int | None) -> str:
    """Format a byte count for compact display; ``None`` -> ``"unknown"``."""
    if size_bytes is None:
        return "unknown"
    size = max(0, int(size_bytes))
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.1f} KB"
    if size < 1024**3:
        return f"{size / 1024**2:.1f} MB"
    return f"{size / 1024**3:.1f} GB"


def file_size(path: str) -> int | None:
    """Return the file size in bytes, or ``None`` when unavailable."""
    try:
        return int(Path(path).stat().st_size)
    except OSError:
        return None


def read_bounded_bytes(
    path: str, max_bytes: int = MAX_DOWNLOAD_BYTES
) -> tuple[bytes | None, str | None]:
    """Read a local file's bytes if it exists and is within the size bound."""
    p = Path(path)
    if not p.is_file():
        return None, "file not available"
    size = p.stat().st_size
    if size > max_bytes:
        return None, f"file too large to download here ({human_size(size)})"
    try:
        return p.read_bytes(), None
    except OSError as exc:
        return None, redact_message_paths(str(exc))


def _read_text(p: Path, max_bytes: int) -> str:
    try:
        data = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"(could not read file: {redact_message_paths(str(exc))})"
    if len(data) > max_bytes:
        return data[:max_bytes] + "\n… (truncated)"
    return data


def preview_file(
    path: str, *, max_rows: int = MAX_PREVIEW_ROWS, max_bytes: int = MAX_PREVIEW_BYTES
) -> dict[str, Any]:
    """Return a bounded, type-aware preview of a local file.

    Result: ``{"kind": ..., "error": None|str, ...}`` where ``kind`` is one of
    ``csv`` (``data`` DataFrame), ``json`` (``data`` object), ``text`` (``text``
    string), ``binary`` (``size`` int), or ``missing``.
    """
    p = Path(path)
    if not p.is_file():
        return {"kind": "missing", "error": "file not available"}
    suffix = p.suffix.lower()
    if suffix in _CSV_SUFFIXES:
        try:
            frame = pd.read_csv(p, nrows=max_rows)
            return {"kind": "csv", "error": None, "data": frame, "rows": int(len(frame))}
        except Exception as exc:
            return {"kind": "csv", "error": redact_message_paths(str(exc))}
    if suffix in _JSON_SUFFIXES:
        raw = _read_text(p, max_bytes)
        try:
            return {"kind": "json", "error": None, "data": json.loads(raw)}
        except (ValueError, TypeError):
            # Truncated/invalid JSON: degrade to a bounded text preview.
            return {"kind": "text", "error": None, "text": raw, "note": "shown as text"}
    if suffix in _TEXT_SUFFIXES:
        return {"kind": "text", "error": None, "text": _read_text(p, max_bytes)}
    return {"kind": "binary", "error": None, "size": file_size(path)}
