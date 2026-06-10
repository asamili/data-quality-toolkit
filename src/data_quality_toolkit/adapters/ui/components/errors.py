"""Error banner helpers shared across dashboard pages."""

from __future__ import annotations

from typing import Any


def show_error(st: Any, label: str, err: str) -> None:
    """Render the standard dashboard error banner: ``⚠️ <label>: <err>``."""
    st.error(f"⚠️ {label}: {err}")
