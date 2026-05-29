# src/data_quality_toolkit/loaders/file/csv_loader.py
"""Phase 1: CSV file loader implementation."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from data_quality_toolkit.loaders.base_loader import BaseLoader
from data_quality_toolkit.shared.settings import load_settings
from data_quality_toolkit.utils.helpers import stable_seed
from data_quality_toolkit.utils.logging import get_logger
from data_quality_toolkit.utils.validators import validate_csv_path

logger = get_logger(__name__)

__all__ = ["CsvLoader", "load_csv"]


def _dataset_id_from_file(path: Path) -> str:
    """Generate dataset ID from file content (first MB for speed)."""
    h = hashlib.sha1(usedforsecurity=False)
    with path.open("rb") as f:
        # Hash first MB only for speed in Phase 1
        chunk = f.read(1024 * 1024)
        if chunk:
            h.update(chunk)
    return f"sha1:{h.hexdigest()}"


def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class CsvLoader(BaseLoader):
    """CSV file loader."""

    def load(self, source: str, **read_csv_kwargs: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
        """
        Load CSV file into DataFrame.

        Args:
            source: Path to CSV file
            **read_csv_kwargs: forwarded to pandas.read_csv

        Returns:
            Tuple of (DataFrame, metadata)
        """
        path = Path(source)

        if not validate_csv_path(str(path)):
            raise FileNotFoundError(f"CSV file not found or not a .csv: {source}")

        settings = load_settings()
        dataset_id = _dataset_id_from_file(path)

        # Load full file then draw a deterministic random sample when SAMPLE_SIZE
        # is explicitly set and file rows exceed the target size.
        # Trade-off: the full file is materialised before sampling; this is
        # unavoidable for representative (non-head-N) sampling in a single pass.
        env_explicit = os.getenv("SAMPLE_SIZE")
        target_n: int | None = (
            settings.sample_size if (env_explicit is not None and settings.sample_size) else None
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


def load_csv(source: str, **read_csv_kwargs: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Convenience function for callers/tests that prefer function style."""
    return CsvLoader().load(source, **read_csv_kwargs)
