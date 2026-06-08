"""Phase 1: Export star schema to CSV files."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from data_quality_toolkit.utils.helpers import ensure_dir
from data_quality_toolkit.utils.logging import get_logger

logger = get_logger(__name__)


def write_star_csvs(tables: dict[str, pd.DataFrame], output_dir: str) -> dict[str, str]:
    """
    Write star schema tables to CSV files.

    Args:
        tables: Dictionary of table_name -> DataFrame
        output_dir: Base output directory

    Returns:
        Dictionary of table_name -> file_path
    """
    output_paths = {}
    base_path = ensure_dir(Path(output_dir))
    star_path = ensure_dir(base_path / "star")

    for table_name, df in tables.items():
        file_path = star_path / f"{table_name}.csv"
        df.to_csv(file_path, index=False)
        output_paths[table_name] = str(file_path)
        logger.info(f"Exported {table_name}: {len(df)} rows to {file_path}")

    return output_paths
