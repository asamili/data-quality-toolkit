"""Shared error contract: map any exception to a typed ErrorInfo dict."""

from __future__ import annotations

from data_quality_toolkit.shared.exceptions import DQTError
from data_quality_toolkit.shared.models import ErrorInfo

__all__ = ["to_error_info"]


def to_error_info(exc: Exception) -> ErrorInfo:
    """Return a structured ErrorInfo for *exc*.

    Handles DQTError subclasses, common OS/IO errors, and an unknown fallback.
    Never raises.
    """
    if isinstance(exc, DQTError):
        info: ErrorInfo = {
            "code": type(exc).__name__.upper(),
            "message": str(exc),
            "exc_type": type(exc).__name__,
        }
        if exc.hint is not None:
            info["hint"] = exc.hint
        if exc.metadata is not None:
            info["metadata"] = exc.metadata
        return info

    if isinstance(exc, FileNotFoundError):
        filename = exc.filename or str(exc)
        return {
            "code": "FILE_NOT_FOUND",
            "message": f"file not found: '{filename}'",
            "exc_type": "FileNotFoundError",
            "hint": (
                "check the path and make sure the file exists.\n"
                "Example: dqt profile data/my_file.csv"
            ),
        }

    if isinstance(exc, PermissionError):
        return {
            "code": "PERMISSION_DENIED",
            "message": f"permission denied: {exc}",
            "exc_type": "PermissionError",
        }

    if isinstance(exc, UnicodeDecodeError):
        return {
            "code": "DECODE_ERROR",
            "message": "decoding failed (try --encoding utf-8 or the correct encoding).",
            "exc_type": "UnicodeDecodeError",
            "metadata": {"detail": str(exc)},
        }

    if isinstance(exc, ValueError):
        return {
            "code": "VALUE_ERROR",
            "message": str(exc),
            "exc_type": type(exc).__name__,
        }

    return {
        "code": "INTERNAL_ERROR",
        "message": str(exc) or repr(exc),
        "exc_type": type(exc).__name__,
    }
