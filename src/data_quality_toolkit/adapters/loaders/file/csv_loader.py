# src/data_quality_toolkit/loaders/file/csv_loader.py
"""Phase 1: CSV file loader implementation."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

from data_quality_toolkit.adapters.loaders.base_loader import BaseLoader
from data_quality_toolkit.shared.settings import load_settings
from data_quality_toolkit.utils.helpers import stable_seed
from data_quality_toolkit.utils.logging import get_logger
from data_quality_toolkit.utils.validators import validate_csv_path

logger = get_logger(__name__)

__all__ = ["CsvLoader", "load_csv", "dataset_id_from_file"]


def dataset_id_from_file(path: Path) -> str:
    """Generate a stable dataset ID from file content (hashes first MB for speed)."""
    h = hashlib.sha1(usedforsecurity=False)
    with path.open("rb") as f:
        chunk = f.read(1024 * 1024)
        if chunk:
            h.update(chunk)
    return f"sha1:{h.hexdigest()}"


# Backwards-compatible shim — callers that imported the private name still work.
_dataset_id_from_file = dataset_id_from_file


def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class CsvLoader(BaseLoader):
    """CSV file loader."""

    def load(
        self, source: str, sample_size: int | None = None, **read_csv_kwargs: Any
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """
        Load CSV file into DataFrame.

        Args:
            source: Path to CSV file
            sample_size: Explicit row sample limit (wins over env/settings fallback).
            **read_csv_kwargs: forwarded to pandas.read_csv

        Returns:
            Tuple of (DataFrame, metadata)
        """
        path = Path(source)

        if not validate_csv_path(str(path)):
            raise FileNotFoundError(f"CSV file not found or not a .csv: {source}")

        settings = load_settings()
        dataset_id = dataset_id_from_file(path)

        # Explicit sample_size wins; fall back to env/settings when not provided.
        # The env guard (env_explicit) preserves Docker/compose behaviour: when
        # SAMPLE_SIZE is absent from the environment the settings default is NOT
        # applied (full-file load), matching the pre-refactor contract.
        if sample_size is not None:
            target_n: int | None = int(sample_size) if sample_size > 0 else None
        else:
            env_explicit = os.getenv("SAMPLE_SIZE")
            target_n = (
                settings.sample_size
                if (env_explicit is not None and settings.sample_size)
                else None
            )
        csv_kwargs: dict[str, Any] = dict(read_csv_kwargs)

        logger.info(f"Loading CSV: {path}")
        try:
            df = pd.read_csv(path, **csv_kwargs)
        except pd.errors.EmptyDataError:
            raise ValueError(
                f"'{path}' is empty or has no columns to parse. "
                "Provide a CSV with at least a header row."
            ) from None

        sample_applied = False
        if target_n is not None and len(df) > target_n:
            seed = stable_seed(dataset_id, "csv_loader")
            df = df.sample(n=target_n, random_state=seed, replace=False)
            sample_applied = True

        if len(df) > settings.max_rows_in_memory:
            raise ValueError(
                f"Loaded {len(df):,} rows exceeds max_rows_in_memory="
                f"{settings.max_rows_in_memory:,}. "
                "Set SAMPLE_SIZE or increase MAX_ROWS_IN_MEMORY."
            )

        stat = path.stat()
        meta: dict[str, Any] = {
            "dataset_id": dataset_id,
            "source_path": str(path.resolve()),
            "rows": int(len(df)),
            "cols": int(df.shape[1]),
            "file_size_bytes": int(stat.st_size),
            "modified_ts": _utc_iso(stat.st_mtime),
            "sample_applied": sample_applied,
            "sample_size": int(target_n) if (sample_applied and target_n is not None) else None,
        }

        logger.info(f"Loaded {meta['rows']} rows, {meta['cols']} columns")
        return df, meta

    def load_chunks(
        self, source: str, chunksize: int = 100_000, **read_csv_kwargs: Any
    ) -> Iterator[pd.DataFrame]:
        """
        Yield CSV file in chunks.

        Args:
            source: Path to CSV file
            chunksize: Rows per chunk.
            **read_csv_kwargs: forwarded to pandas.read_csv

        Returns:
            Iterator of DataFrames
        """
        if chunksize <= 0:
            raise ValueError("chunksize must be a positive integer.")

        path = Path(source)

        if not validate_csv_path(str(path)):
            raise FileNotFoundError(f"CSV file not found or not a .csv: {source}")

        logger.info(f"Loading CSV in chunks: {path} (chunksize={chunksize})")
        return cast(
            Iterator[pd.DataFrame], pd.read_csv(path, chunksize=chunksize, **read_csv_kwargs)
        )


def load_csv(
    source: str, sample_size: int | None = None, **read_csv_kwargs: Any
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Convenience function for callers/tests that prefer function style."""
    return CsvLoader().load(source, sample_size=sample_size, **read_csv_kwargs)
