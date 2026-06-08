"""Shared path guard utilities for validating server-side output paths."""

from __future__ import annotations

from pathlib import Path

from data_quality_toolkit.shared.exceptions import DQTError


class PathGuardError(DQTError):
    """Raised when a user-provided path fails safety validation."""


def validate_output_dir(path: str | Path, *, must_be_absolute: bool = True) -> Path:
    """Validate *path* is safe for server-side directory writes.

    Rules enforced:
    - Path must not be empty.
    - Path must be absolute when *must_be_absolute* is True (default).
    - Path must not contain '..' traversal components.
    - If the path already exists, it must be a directory (not a file).
    - If the path contains symlinks, the resolved target must remain under
      the resolved parent directory (no symlink escape).

    Returns the resolved Path.  Does **not** create the directory.
    Raises PathGuardError on any violation.
    """
    raw = str(path).strip()
    if not raw:
        raise PathGuardError("Output directory path must not be empty.")

    p = Path(raw)

    if ".." in p.parts:
        raise PathGuardError(f"Path traversal ('..') is not allowed in output directory: {p!s}")

    if must_be_absolute and not p.is_absolute():
        raise PathGuardError(f"Output directory must be an absolute path. Got: {p!s}")

    resolved = p.resolve()

    if resolved.exists() and not resolved.is_dir():
        raise PathGuardError(f"Output path exists but is a file, not a directory: {resolved!s}")

    if p.exists():
        parent_resolved = p.parent.resolve()
        try:
            resolved.relative_to(parent_resolved)
        except ValueError:
            raise PathGuardError(
                f"Symlink escape detected: '{p!s}' resolves to '{resolved!s}', "
                f"which is outside the expected parent '{parent_resolved!s}'."
            ) from None

    return resolved


def ensure_safe_output_dir(path: str | Path, *, create: bool = False) -> Path:
    """Validate *path* and optionally create the directory.

    If *create* is True and the directory does not exist, it is created
    (including parents) only after validation passes.

    Returns the resolved Path.
    Raises PathGuardError on any violation.
    """
    resolved = validate_output_dir(path)
    if create and not resolved.exists():
        resolved.mkdir(parents=True, exist_ok=True)
    return resolved


__all__ = ["PathGuardError", "validate_output_dir", "ensure_safe_output_dir"]
