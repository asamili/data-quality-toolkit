from __future__ import annotations

from typing import Any, Protocol

import numpy as np
import pandas as pd


class Aggregator(Protocol):
    """Protocol for stateful chunked aggregators."""

    def update(self, chunk: pd.DataFrame) -> None: ...

    def finalize(self) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Dtype inference helpers
# ---------------------------------------------------------------------------

_WIDEN_RANK: dict[str, int] = {"bool": 0, "int64": 1, "float64": 2}


def _normalize_dtype(dtype: Any) -> str:
    """Map a pandas dtype to its canonical inference string."""
    if pd.api.types.is_bool_dtype(dtype):
        return "bool"
    if pd.api.types.is_integer_dtype(dtype):
        return "int64"
    if pd.api.types.is_float_dtype(dtype):
        return "float64"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime64[ns]"
    return "object"


def _widen(current: str, incoming: str) -> str:
    """Return the wider dtype under the inference lattice.

    Lattice: bool < int64 < float64; object is the top.
    datetime64 only merges with itself; any mismatch widens to object.
    """
    if current == incoming:
        return current
    if "datetime64" in current or "datetime64" in incoming:
        return "object"
    if current in _WIDEN_RANK and incoming in _WIDEN_RANK:
        return current if _WIDEN_RANK[current] >= _WIDEN_RANK[incoming] else incoming
    return "object"


class RowCounter:
    """Aggregator for total row count."""

    def __init__(self) -> None:
        self.count = 0

    def update(self, chunk: pd.DataFrame) -> None:
        self.count += len(chunk)

    def finalize(self) -> dict[str, int]:
        return {"rows": self.count}


class NullCounter:
    """Aggregator for column-wise null counts."""

    def __init__(self, columns: list[str]) -> None:
        self.null_counts = pd.Series(0, index=columns)

    def update(self, chunk: pd.DataFrame) -> None:
        self.null_counts += chunk.isna().sum()

    def finalize(self) -> dict[str, dict[str, int]]:
        return {"null_counts": self.null_counts.to_dict()}


class NumericStats:
    """Aggregator for column-wise min, max, and sum."""

    def __init__(self, columns: list[str]) -> None:
        self.columns = columns
        self.mins = pd.Series(np.inf, index=columns)
        self.maxs = pd.Series(-np.inf, index=columns)
        self.sums = pd.Series(0.0, index=columns)

    def update(self, chunk: pd.DataFrame) -> None:
        numeric_cols = [c for c in self.columns if pd.api.types.is_numeric_dtype(chunk[c])]
        if not numeric_cols:
            return

        chunk_num = chunk[numeric_cols]
        self.mins[numeric_cols] = np.minimum(self.mins[numeric_cols], chunk_num.min())
        self.maxs[numeric_cols] = np.maximum(self.maxs[numeric_cols], chunk_num.max())
        self.sums[numeric_cols] += chunk_num.sum()

    def finalize(self) -> dict[str, dict[str, float | None]]:
        # Clean up infinity for numeric columns that had no data
        results: dict[str, dict[str, float | None]] = {}
        for col in self.columns:
            if self.mins[col] == np.inf:
                results[col] = {"min": None, "max": None, "sum": 0.0}
            else:
                results[col] = {
                    "min": float(self.mins[col]),
                    "max": float(self.maxs[col]),
                    "sum": float(self.sums[col]),
                }
        return results


class DtypeInferencer:
    """Aggregator for per-column dtype inference via a widening lattice.

    For each column the observed per-chunk dtype is widened monotonically:
      bool < int64 < float64 < object  (object is the ceiling)
    datetime64 columns stay datetime as long as all chunks agree; any
    mismatch with a non-datetime dtype widens to object.
    Columns never seen (all chunks missing the column) default to "object".
    """

    def __init__(self, columns: list[str]) -> None:
        self.columns = columns
        self._seen: dict[str, str | None] = dict.fromkeys(columns)

    def update(self, chunk: pd.DataFrame) -> None:
        for col in self.columns:
            if col not in chunk.columns:
                continue
            incoming = _normalize_dtype(chunk[col].dtype)
            current = self._seen[col]
            self._seen[col] = incoming if current is None else _widen(current, incoming)

    def finalize(self) -> dict[str, str]:
        """Return {col: dtype_string}."""
        return {
            col: (dtype if dtype is not None else "object") for col, dtype in self._seen.items()
        }
