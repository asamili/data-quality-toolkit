"""Lightweight shared dataset context backed by Streamlit session state."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from data_quality_toolkit.adapters.ui.state.keys import (
    BIV_COL1,
    BIV_COL2,
    DATASET_CONTEXT,
)

_DERIVED_DATASET_KEYS = (BIV_COL1, BIV_COL2)


@dataclass(frozen=True, slots=True)
class DatasetContext:
    """Safe metadata identifying the dataset selected for the UI journey.

    The context intentionally contains no DataFrame, profile, assessment, raw
    rows, or derived statistics. Those remain owned by existing page services.
    """

    source_path: str
    display_name: str
    size_bytes: int
    modified_ns: int
    large_file_mode: bool = False

    @property
    def fingerprint(self) -> tuple[str, int, int, bool]:
        """Return the stable identity used to detect context changes."""
        return (self.source_path, self.size_bytes, self.modified_ns, self.large_file_mode)


def get_dataset_context(state: Mapping[str, Any]) -> DatasetContext | None:
    """Return the active typed context, ignoring malformed session values."""
    value = state.get(DATASET_CONTEXT)
    return value if isinstance(value, DatasetContext) else None


def set_dataset_context(state: MutableMapping[str, Any], context: DatasetContext) -> bool:
    """Set the active context and invalidate dataset-derived widget state.

    Returns ``True`` when the selected dataset or load mode changed.
    """
    current = get_dataset_context(state)
    changed = current is None or current.fingerprint != context.fingerprint
    if changed:
        for key in _DERIVED_DATASET_KEYS:
            state.pop(key, None)
    state[DATASET_CONTEXT] = context
    return changed


def clear_dataset_context(state: MutableMapping[str, Any]) -> bool:
    """Clear the active context and all known dataset-derived widget state."""
    existed = get_dataset_context(state) is not None
    state.pop(DATASET_CONTEXT, None)
    for key in _DERIVED_DATASET_KEYS:
        state.pop(key, None)
    return existed
