"""Error banner helpers shared across dashboard pages.

Path redaction is delegated to :mod:`data_quality_toolkit.shared.text_redaction`
so the CLI and UI surfaces share one authoritative set of path-detection rules.
``redact_message_paths`` is re-exported here for backward compatibility.
"""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.shared.text_redaction import redact_message_paths

__all__ = ["redact_message_paths", "show_error"]


def show_error(st: Any, label: str, err: str) -> None:
    """Render the standard dashboard error banner: ``⚠️ <label>: <err>``.

    The error detail is path-redacted so absolute local paths embedded in
    exception strings never reach the UI.
    """
    st.error(f"⚠️ {label}: {redact_message_paths(err)}")
