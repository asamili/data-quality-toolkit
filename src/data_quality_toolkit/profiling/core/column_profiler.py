# src/data_quality_toolkit/profiling/core/column_profiler.py
"""Phase 1: Column-level profiling."""

from __future__ import annotations

from typing import Any

import pandas as pd

__all__ = ["profile_columns"]


def profile_columns(df: pd.DataFrame, sample: pd.DataFrame | None = None) -> list[dict[str, Any]]:
    """
    Profile each column in the dataset.
    - Accuracy: nulls/unique computed on full df
    - Optional sample for extra stats (min/max shown here)
    """
    src = sample if sample is not None else df
    out: list[dict[str, Any]] = []

    for name in df.columns:
        s_full = df[name]
        s_src = src[name] if name in src.columns else s_full

        prof: dict[str, Any] = {
            "name": name,
            "dtype": str(s_full.dtype),
            "nulls": int(s_full.isna().sum()),
            "unique": int(s_full.nunique(dropna=True)),
        }

        if pd.api.types.is_numeric_dtype(s_src):
            non_null = s_src.dropna()
            prof["min"] = float(non_null.min()) if len(non_null) else None
            prof["max"] = float(non_null.max()) if len(non_null) else None

        out.append(prof)
    return out
