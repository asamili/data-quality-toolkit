# src/data_quality_toolkit/profiling/core/dataset_profiler.py
"""Phase 1: Dataset-level profiling."""

from __future__ import annotations

from typing import Any

import pandas as pd

__all__ = ["profile_dataset", "dataset_stats"]


def profile_dataset(df: pd.DataFrame) -> dict[str, Any]:
    """Profile dataset-level metrics."""
    memory_bytes = df.memory_usage(deep=True).sum()
    memory_mb = float(memory_bytes) / (1024 * 1024)
    return {
        "rows": int(len(df)),
        "cols": int(df.shape[1]),
        "memory_mb": memory_mb,  # keep full precision; round in presentation if needed
    }


# Back-compat alias used by existing tests/imports
def dataset_stats(df: pd.DataFrame) -> dict[str, Any]:
    return profile_dataset(df)
