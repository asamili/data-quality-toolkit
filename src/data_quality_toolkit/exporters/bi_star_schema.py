"""Phase 1: Build star schema for BI."""

from __future__ import annotations

from typing import TypedDict

import pandas as pd

from data_quality_toolkit.shared.models import ProfileResult
from data_quality_toolkit.utils.helpers import make_column_id
from data_quality_toolkit.utils.logging import get_logger

logger = get_logger(__name__)


class StarTables(TypedDict):
    dim_dataset: pd.DataFrame
    dim_column: pd.DataFrame
    fact_profile_runs: pd.DataFrame
    fact_quality_metrics: pd.DataFrame


def build_star(profile: ProfileResult, _df: pd.DataFrame) -> StarTables:
    """
    Build star schema tables from profile.

    Args:
        profile: Profile result
        _df: Original DataFrame (unused in Phase 1, reserved for future fact tables)

    Returns:
        Dict of table_name -> DataFrame
    """
    dataset_id = profile["dataset_id"]
    run_id = profile["run_id"]
    ts = profile["ts"]

    # Compute day-level key from ts (safe even if ts is a string)
    ts_parsed = pd.to_datetime(ts, errors="coerce")
    time_id = int(ts_parsed.strftime("%Y%m%d")) if pd.notna(ts_parsed) else None

    # Dimension: Dataset
    dim_dataset = pd.DataFrame([{"dataset_id": dataset_id, "source_path": ""}])

    # Dimension: Columns
    dim_column_rows = []
    for col in profile["columns"]:
        dim_column_rows.append(
            {
                "column_id": make_column_id(dataset_id, col["name"]),
                "dataset_id": dataset_id,
                "column_name": col["name"],
                "dtype": col["dtype"],
            }
        )
    dim_column = (
        pd.DataFrame(dim_column_rows)
        if dim_column_rows
        else pd.DataFrame(columns=["column_id", "dataset_id", "column_name", "dtype"])
    )

    # Fact: Profile Runs
    fact_profile_runs = pd.DataFrame(
        [
            {
                "run_id": run_id,
                "dataset_id": dataset_id,
                "ts": ts,
                "time_id": time_id,
                "rows": profile["rows"],
                "cols": profile["cols"],
                "memory_mb": profile["memory_mb"],
            }
        ]
    )

    # Fact: Quality Metrics
    rows = max(int(profile["rows"]), 1)
    quality_rows = []
    for col in profile["columns"]:
        nulls = int(col.get("nulls", 0) or 0)
        unique = int(col.get("unique", 0) or 0)
        null_pct = nulls / rows
        completeness = max(0.0, 1.0 - null_pct)

        quality_rows.append(
            {
                "run_id": run_id,
                "column_id": make_column_id(dataset_id, col["name"]),
                "null_pct": round(null_pct, 6),
                "distinct_count": unique,
                "completeness": round(completeness, 4),
            }
        )
    fact_quality_metrics = (
        pd.DataFrame(quality_rows)
        if quality_rows
        else pd.DataFrame(
            columns=["run_id", "column_id", "null_pct", "distinct_count", "completeness"]
        )
    )

    tables: StarTables = {
        "dim_dataset": dim_dataset,
        "dim_column": dim_column,
        "fact_profile_runs": fact_profile_runs,
        "fact_quality_metrics": fact_quality_metrics,
    }

    validate_relationships(tables)
    logger.info("Star schema built: 2 dimensions, 2 fact tables")
    return tables


def validate_relationships(tables: StarTables) -> None:
    """
    Validate star schema relationships.

    Raises:
        ValueError: If required tables/columns are missing
    """
    # Ensure presence (use literal keys so TypedDict is happy)
    if "dim_dataset" not in tables:
        raise ValueError("Missing required table: dim_dataset")
    if "dim_column" not in tables:
        raise ValueError("Missing required table: dim_column")
    if "fact_profile_runs" not in tables:
        raise ValueError("Missing required table: fact_profile_runs")
    if "fact_quality_metrics" not in tables:
        raise ValueError("Missing required table: fact_quality_metrics")

    # Column checks with explicit literals
    dim_dataset = tables["dim_dataset"]
    dim_column = tables["dim_column"]
    fact_profile_runs = tables["fact_profile_runs"]
    fact_quality_metrics = tables["fact_quality_metrics"]

    def _require(df: pd.DataFrame, cols: list[str], name: str) -> None:
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise ValueError(f"Table '{name}' missing columns: {missing}")

    _require(dim_dataset, ["dataset_id"], "dim_dataset")
    _require(dim_column, ["column_id", "dataset_id"], "dim_column")
    _require(fact_profile_runs, ["run_id", "dataset_id"], "fact_profile_runs")
    _require(fact_quality_metrics, ["run_id", "column_id"], "fact_quality_metrics")

    logger.info("Star schema relationships validated successfully")
