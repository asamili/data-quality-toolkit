# src/data_quality_toolkit/profiling/profiling_orchestrator.py

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import cast

import pandas as pd

from data_quality_toolkit.domain.profiling.core.chunked_aggregators import (
    DtypeInferencer,
    NullCounter,
    NumericStats,
    RowCounter,
)
from data_quality_toolkit.domain.profiling.core.column_profiler import profile_columns
from data_quality_toolkit.domain.profiling.core.dataset_profiler import profile_dataset
from data_quality_toolkit.shared.constants import DEFAULT_TS_FORMAT
from data_quality_toolkit.shared.models import ColumnProfile, ProfileResult  # <-- add
from data_quality_toolkit.shared.settings import load_settings
from data_quality_toolkit.utils.helpers import stable_seed
from data_quality_toolkit.utils.logging import get_logger

logger = get_logger(__name__)


def run_chunked_profiling(
    chunk_iterator: Iterator[pd.DataFrame],
    dataset_id: str,
    columns: list[str],
) -> ProfileResult:
    """Execute profiling pipeline on an iterator of DataFrame chunks."""
    logger.info(f"Starting chunked profiling for dataset: {dataset_id}")

    # Initialize aggregators
    row_counter = RowCounter()
    null_counter = NullCounter(columns=columns)
    numeric_stats = NumericStats(columns=columns)
    dtype_inferencer = DtypeInferencer(columns=columns)

    # Process chunks
    for chunk in chunk_iterator:
        row_counter.update(chunk)
        null_counter.update(chunk)
        numeric_stats.update(chunk)
        dtype_inferencer.update(chunk)

    # Finalize aggregations
    rows = row_counter.finalize()["rows"]
    nulls = null_counter.finalize()["null_counts"]
    num_stats = numeric_stats.finalize()
    inferred_dtypes = dtype_inferencer.finalize()

    # Construct ColumnProfile list (V1: simplified metrics)
    column_profiles: list[ColumnProfile] = []
    for col in columns:
        prof: ColumnProfile = {
            "name": col,
            "dtype": inferred_dtypes.get(col, "object"),
            "nulls": nulls.get(col, 0),
            # unique omitted — unsupported in chunked mode (NotRequired)
        }
        if col in num_stats:
            col_min = num_stats[col]["min"]
            col_max = num_stats[col]["max"]
            # NaN can arise when a nominally non-numeric column appears numeric in some
            # chunks but not others (mixed-type edge case). Treat NaN as no data → None.
            if col_min is not None and not pd.isna(col_min):
                prof["min"] = col_min
            if col_max is not None and not pd.isna(col_max):
                prof["max"] = col_max
        column_profiles.append(prof)

    result: ProfileResult = {
        "run_id": str(uuid.uuid4()),
        "dataset_id": dataset_id,
        "rows": rows,
        "cols": len(columns),
        "memory_mb": 0.0,  # Placeholder, memory profiling across chunks requires separate logic
        "ts": _now_utc(),
        "columns": column_profiles,
    }
    logger.info(f"Chunked profiling complete: {result['rows']} rows, {result['cols']} cols")
    return result


def _now_utc() -> str:
    """Get current UTC timestamp."""
    return datetime.now(tz=UTC).strftime(DEFAULT_TS_FORMAT)


def run_profiling(
    df: pd.DataFrame, dataset_id: str, sample_size: int | None = None
) -> ProfileResult:
    """
    Execute complete profiling pipeline.
    Returns: ProfileResult (TypedDict) with rows/cols/memory_mb/columns, run_id, ts.
    """
    logger.info(f"Starting profiling for dataset: {dataset_id}")
    settings = load_settings()

    # Explicit sample_size wins; fall back to env/settings when not provided.
    effective = sample_size if sample_size is not None else settings.sample_size

    # Deterministic sampling for optional heavy ops (only if > 0)
    sample: pd.DataFrame | None = None
    if effective and effective > 0 and len(df) > effective:
        seed = stable_seed(dataset_id, "profiling")
        sample = df.sample(n=effective, random_state=seed, replace=False)
        logger.info(f"Using sample of {effective} rows for column extras")

    dataset_metrics = profile_dataset(df)

    # Narrow the static type to what ProfileResult expects.
    # profile_columns returns the correct runtime shape; we inform the checker.
    column_profiles = cast(list[ColumnProfile], profile_columns(df, sample))

    result: ProfileResult = {
        "run_id": str(uuid.uuid4()),
        "dataset_id": dataset_id,
        "rows": dataset_metrics["rows"],
        "cols": dataset_metrics["cols"],
        "memory_mb": dataset_metrics["memory_mb"],
        "ts": _now_utc(),
        "columns": column_profiles,
    }
    logger.info(f"Profiling complete: {result['rows']} rows, {result['cols']} cols")
    return result
