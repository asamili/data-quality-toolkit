"""Small common empty, information, and warning state renderers."""

from __future__ import annotations

from typing import Any


def render_empty_state(st: Any, title: str, message: str) -> None:
    """Render an actionable empty state."""
    st.info(f"**{title}**\n\n{message}")


def render_info_state(st: Any, message: str) -> None:
    """Render a shared informational callout."""
    st.info(message)


def render_warning_state(st: Any, message: str) -> None:
    """Render a shared warning callout."""
    st.warning(message)


def render_error_state(st: Any, message: str) -> None:
    """Render a shared error callout."""
    st.error(message)


def render_success_state(st: Any, message: str) -> None:
    """Render a shared success callout."""
    st.success(message)
