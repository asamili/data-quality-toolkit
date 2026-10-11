"""Save-to-Workspace foundation: safe, opt-in local file writes under Workspace Root.

This module is a self-contained helper layer. It writes text/bytes to a normalized,
containment-checked path under a user-provided Workspace Root and reports basenames
and workspace-relative paths only — never an absolute local path as primary display.

It is intentionally *not* wired into any page here: no UI buttons, no captions, no
browser-download changes. It does not run export, Power BI, or pipeline logic, and it
does not read/write databases or manifests. All disk access is confined under the
normalized Workspace Root and guarded against path traversal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

SaveStatus = Literal["saved", "failed", "invalid"]

DEFAULT_FILENAME = "artifact"
MAX_FILENAME_LENGTH = 100
MAX_COLLISION_SUFFIX = 1000

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_WHITESPACE = re.compile(r"\s+")
_REPEAT_UNDERSCORE = re.compile(r"_{2,}")
_UNDERSCORE_AROUND_DOT = re.compile(r"_*\._*")
_REPEAT_DOT = re.compile(r"\.{2,}")


@dataclass(frozen=True, slots=True)
class WorkspaceSaveResult:
    """Outcome of a Save-to-Workspace call, using display-safe fields only.

    ``filename`` and ``relative_path`` are basename / workspace-relative only; no
    absolute local path is ever placed in these fields or in ``message``.
    """

    status: SaveStatus
    filename: str = ""
    relative_path: str = ""
    message: str = ""
    bytes_written: int | None = None


def sanitize_filename(name: str, *, default: str = DEFAULT_FILENAME) -> str:
    """Return a safe single-segment filename with no separators, traversal, or drive.

    Any path components are reduced to a basename first, so traversal such as
    ``../../etc/passwd`` collapses to ``passwd``. Unsafe characters become ``_``,
    whitespace collapses to ``_``, leading/trailing dots and underscores are
    stripped (which also neutralizes ``.``/``..``), and the result is length-capped
    while preserving a safe extension. Never returns blank.
    """
    text = str(name).strip()
    # Reduce to a basename first so embedded separators cannot survive.
    text = text.replace("\\", "/").rsplit("/", 1)[-1]
    text = _WHITESPACE.sub("_", text)
    text = _UNSAFE_CHARS.sub("_", text)
    text = _REPEAT_UNDERSCORE.sub("_", text)
    # Tidy underscores adjacent to dots and collapse repeated dots (traversal-safe).
    text = _UNDERSCORE_AROUND_DOT.sub(".", text)
    text = _REPEAT_DOT.sub(".", text)
    text = text.strip("._")
    if not text or text in {".", ".."}:
        return default
    return _cap_length(text, MAX_FILENAME_LENGTH)


def build_workspace_filename(
    *,
    artifact: str,
    extension: str,
    dataset: str | None = None,
    run_id: str | None = None,
    timestamp: str | None = None,
    default: str = DEFAULT_FILENAME,
) -> str:
    """Build a sanitized ``dataset__artifact__run__timestamp.ext`` style filename.

    The dataset component is reduced to a basename and its own extension is dropped
    so a display name like ``customers.csv`` contributes only ``customers``. Every
    part is sanitized; missing parts are omitted. Output is deterministic: no clock
    is read here — pass ``timestamp`` explicitly when a time component is wanted.
    """
    parts: list[str] = []
    if dataset:
        dataset_stem = _drop_extension(sanitize_filename(dataset, default=""))
        if dataset_stem:
            parts.append(dataset_stem)

    artifact_part = _drop_extension(sanitize_filename(artifact, default=""))
    if artifact_part:
        parts.append(artifact_part)

    if run_id:
        run_part = _drop_extension(sanitize_filename(run_id, default=""))
        if run_part:
            parts.append(run_part)

    if timestamp:
        ts_part = _drop_extension(sanitize_filename(timestamp, default=""))
        if ts_part:
            parts.append(ts_part)

    # Parts are individually sanitized above; join with "__" without re-collapsing
    # the separators, then cap length preserving the extension.
    stem = "__".join(parts) if parts else default
    return _cap_length(f"{stem}{_normalize_extension(extension)}", MAX_FILENAME_LENGTH)


def save_to_workspace(
    workspace_root: str,
    subfolder: str,
    filename: str,
    data: str | bytes,
    *,
    overwrite: bool = False,
) -> WorkspaceSaveResult:
    """Save ``data`` under ``workspace_root/subfolder`` with a safe, non-clobbering name.

    Safety:
    - a blank workspace root is a no-op (``invalid``);
    - the subfolder must be relative and free of ``..``/drive/absolute segments;
    - the filename is sanitized to a single safe segment (traversal-proof);
    - the resolved target must stay under the normalized Workspace Root;
    - by default an existing file is never overwritten — a ``-1``/``-2`` suffix is
      added instead; ``overwrite=True`` overwrites only the exact safe target;
    - only the target subfolder is created, and only when a save actually happens.

    Returns a :class:`WorkspaceSaveResult` whose displayed fields are basename /
    workspace-relative only.
    """
    root = str(workspace_root).strip()
    if not root:
        return WorkspaceSaveResult(
            status="invalid",
            message="Enter a Workspace Root before saving.",
        )

    root_abs = Path(root).expanduser().resolve(strict=False)

    sub_parts, sub_error = _safe_subfolder_parts(subfolder)
    if sub_error is not None:
        return WorkspaceSaveResult(status="invalid", message=sub_error)

    safe_name = sanitize_filename(filename)
    target_dir = root_abs.joinpath(*sub_parts) if sub_parts else root_abs
    target = target_dir / safe_name

    if not _is_within(target, root_abs):
        return WorkspaceSaveResult(
            status="invalid",
            filename=safe_name,
            message="Resolved target is outside the Workspace Root.",
        )

    final: Path = target
    if not overwrite:
        candidate = _next_available(target_dir, safe_name)
        if candidate is None:
            return WorkspaceSaveResult(
                status="failed",
                filename=safe_name,
                message="Too many existing files with this name to save safely.",
            )
        final = candidate

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            bytes_written = len(data)
            final.write_bytes(data)
        else:
            payload = str(data).encode("utf-8")
            bytes_written = len(payload)
            final.write_bytes(payload)
    except (OSError, RuntimeError, ValueError):
        return WorkspaceSaveResult(
            status="failed",
            filename=final.name,
            message=f"Could not save {final.name}.",
        )

    return WorkspaceSaveResult(
        status="saved",
        filename=final.name,
        relative_path=_relative_display(final, root_abs),
        message=f"Saved {final.name}.",
        bytes_written=bytes_written,
    )


def _safe_subfolder_parts(subfolder: str) -> tuple[list[str], str | None]:
    """Validate/sanitize a relative subfolder into safe path segments.

    Returns ``(parts, None)`` on success or ``([], error)`` when the subfolder is
    absolute, drive-qualified, or contains ``..`` traversal.
    """
    raw = str(subfolder or "").strip()
    if not raw:
        return [], None

    normalized = raw.replace("\\", "/")
    if normalized.startswith("/") or PureWindowsPath(raw).drive:
        return [], "Subfolder must be a relative path inside the Workspace Root."

    parts: list[str] = []
    for segment in normalized.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            return [], "Subfolder must not contain path traversal ('..')."
        parts.append(sanitize_filename(segment, default="folder"))
    return parts, None


def _next_available(target_dir: Path, filename: str) -> Path | None:
    """Return a non-colliding path, adding ``-1``/``-2`` suffixes before the extension."""
    candidate = target_dir / filename
    if not candidate.exists():
        return candidate
    stem, suffix = _split_stem_suffix(filename)
    for index in range(1, MAX_COLLISION_SUFFIX + 1):
        candidate = target_dir / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    return None


def _is_within(target: Path, root_abs: Path) -> bool:
    try:
        target.resolve(strict=False).relative_to(root_abs)
        return True
    except ValueError:
        return False


def _relative_display(path: Path, root_abs: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root_abs).as_posix()
    except ValueError:
        return path.name


def _cap_length(name: str, limit: int) -> str:
    if len(name) <= limit:
        return name
    stem, suffix = _split_stem_suffix(name)
    if len(suffix) >= limit:
        return name[:limit]
    keep = max(1, limit - len(suffix))
    return f"{stem[:keep]}{suffix}"


def _split_stem_suffix(name: str) -> tuple[str, str]:
    pure = PurePosixPath(name)
    suffix = pure.suffix
    stem = name[: -len(suffix)] if suffix else name
    return stem, suffix


def _drop_extension(name: str) -> str:
    return _split_stem_suffix(name)[0]


def _normalize_extension(extension: str) -> str:
    ext = str(extension or "").strip().lstrip(".")
    ext = _UNSAFE_CHARS.sub("", ext)
    return f".{ext}" if ext else ""


__all__ = [
    "WorkspaceSaveResult",
    "sanitize_filename",
    "build_workspace_filename",
    "save_to_workspace",
]
