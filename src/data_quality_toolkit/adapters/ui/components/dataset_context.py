"""Dataset-context presentation component."""

from __future__ import annotations

from typing import Any

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
    """Render safe active-context metadata without exposing an absolute path."""
    mode = "Large-file profile mode" if context.large_file_mode else "Full analysis mode"
    st.info(
        f"**Current dataset:** `{context.display_name}`  \n"
        f"{format_file_size(context.size_bytes)} · {mode}"
    )
