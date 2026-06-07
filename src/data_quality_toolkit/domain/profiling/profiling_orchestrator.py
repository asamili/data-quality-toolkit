# src/data_quality_toolkit/profiling/profiling_orchestrator.py

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast  # <-- add

import pandas as pd

from data_quality_toolkit.profiling.core.column_profiler import profile_columns
from data_quality_toolkit.profiling.core.dataset_profiler import profile_dataset
from data_quality_toolkit.shared.constants import DEFAULT_TS_FORMAT
from data_quality_toolkit.shared.models import ColumnProfile, ProfileResult  # <-- add
from data_quality_toolkit.shared.settings import load_settings
from data_quality_toolkit.utils.helpers import stable_seed
from data_quality_toolkit.utils.logging import get_logger

logger = get_logger(__name__)


def _now_utc() -> str:
    """Get current UTC timestamp."""
    return datetime.now(tz=UTC).strftime(DEFAULT_TS_FORMAT)


def run_profiling(df: pd.DataFrame, dataset_id: str) -> ProfileResult:
    """
    Execute complete profiling pipeline.
    Returns: ProfileResult (TypedDict) with rows/cols/memory_mb/columns, run_id, ts.
    """
    logger.info(f"Starting profiling for dataset: {dataset_id}")
    settings = load_settings()

    # Deterministic sampling for optional heavy ops (only if > 0)
    sample: pd.DataFrame | None = None
    if settings.sample_size and settings.sample_size > 0 and len(df) > settings.sample_size:
        seed = stable_seed(dataset_id, "profiling")
        sample = df.sample(n=settings.sample_size, random_state=seed, replace=False)
        logger.info(f"Using sample of {settings.sample_size} rows for column extras")

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
