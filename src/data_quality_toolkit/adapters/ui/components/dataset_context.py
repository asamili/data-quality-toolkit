"""Dataset-context presentation component."""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.ui.components.active_dataset_identity import (
    build_active_dataset_identity,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext


def format_file_size(size_bytes: int) -> str:
    """Format a non-negative byte count for compact UI display."""
    size = max(0, int(size_bytes))
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024**2:.1f} MB"


def render_dataset_context_panel(st: Any, context: DatasetContext) -> None:
    """Render safe active-context metadata without exposing an absolute path.

    Uses the shared identity model, so this panel and the downstream source callout
    name the active dataset with the same terminology. It describes the active
    dataset only — a confirmed-but-not-yet-active version is a separate surface.
    """
    identity = build_active_dataset_identity(context)
    details = [identity.descriptor]
    if identity.show_basename:
        details.append(f"`{identity.basename}`")
    details.append(format_file_size(context.size_bytes))
    details.append(identity.mode_label.capitalize())
    st.info(f"**Current dataset:** `{identity.label}`  \n" + " · ".join(details))
