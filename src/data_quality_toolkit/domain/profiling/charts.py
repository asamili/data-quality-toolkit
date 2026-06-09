"""Domain logic for profiling charts data computation."""

from __future__ import annotations

from typing import Any

import pandas as pd


def compute_univariate_chart_data(
    df: pd.DataFrame, col: str, bins: int = 10, top_n: int = 20
) -> dict[str, Any]:
    """
    Compute chart data for a single column.
    Returns a dict with 'type' ('numeric' or 'categorical') and 'data' (list of label/count pairs).
    """
    if col not in df.columns:
        raise ValueError(f"Column '{col}' not found in dataset.")

    series = df[col].dropna()
    if series.empty:
        return {"type": "empty", "data": [], "column": col}

    is_numeric = pd.api.types.is_numeric_dtype(df[col])

    if is_numeric:
        # Numeric: Binned distribution
        if series.nunique() < 2:
            # Fallback to categorical if everything is the same value or too few values
            return _compute_categorical(series, col, top_n)

        try:
            counts = pd.cut(series, bins=bins, duplicates="drop").value_counts().sort_index()
            data = [(str(label), int(count)) for label, count in counts.items()]
            return {"type": "numeric", "data": data, "column": col}
        except (ValueError, TypeError):
            # Fallback if binning fails
            return _compute_categorical(series, col, top_n)
    else:
        # Categorical: Top-N value counts
        return _compute_categorical(series, col, top_n)


def _compute_categorical(series: pd.Series, col: str, top_n: int) -> dict[str, Any]:
    """Compute top-N value counts for a series."""
    counts = series.value_counts().head(top_n)
    data = [(str(label), int(count)) for label, count in counts.items()]
    return {"type": "categorical", "data": data, "column": col}
