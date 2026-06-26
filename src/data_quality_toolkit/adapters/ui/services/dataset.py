"""UI-facing dataset-context validation helpers.

This service performs filesystem metadata validation only. It does not load a
DataFrame, profile data, run assessment, persist files, or calculate metrics.
"""

from __future__ import annotations

from pathlib import Path

from data_quality_toolkit.adapters.ui.state.context import DatasetContext


def build_dataset_context(
    path_str: str,
    *,
    large_file_mode: bool = False,
) -> tuple[DatasetContext | None, str | None]:
    """Validate a local CSV path and return lightweight context metadata."""
    cleaned = path_str.strip()
    if not cleaned:
        return None, "Enter a CSV path."

    path = Path(cleaned).expanduser()
    if path.suffix.lower() != ".csv":
        return None, "Dataset must be a .csv file."

    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            return None, f"Dataset is not a file: {cleaned}"
        stat = resolved.stat()
    except (OSError, RuntimeError):
        return None, f"Dataset not found or unreadable: {cleaned}"

    return (
        DatasetContext(
            source_path=str(resolved),
            display_name=resolved.name,
            size_bytes=int(stat.st_size),
            modified_ns=int(stat.st_mtime_ns),
            large_file_mode=bool(large_file_mode),
        ),
        None,
    )
