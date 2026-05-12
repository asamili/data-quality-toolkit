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

        # Resolve settings (sampling, logging level/format already set via CLI)
        settings = load_settings()

        # Compute dataset_id first (used for deterministic sampling)
        dataset_id = _dataset_id_from_file(path)

        logger.info(f"Loading CSV: {path}")
        try:
            df = pd.read_csv(path, **read_csv_kwargs)
        except pd.errors.EmptyDataError:
            raise ValueError(
                f"'{path}' is empty or has no columns to parse. "
                "Provide a CSV with at least a header row."
            ) from None

        # Optional deterministic sampling (Phase 1: in-memory)
        sample_applied = False
        # Only sample if the user explicitly set SAMPLE_SIZE (env or CLI wrapper)
        env_explicit = os.getenv("SAMPLE_SIZE")
        if env_explicit is not None and settings.sample_size and len(df) > settings.sample_size:
            rs = stable_seed(dataset_id, "csv_loader.sample")
            df = df.sample(n=settings.sample_size, random_state=rs).reset_index(drop=True)
            sample_applied = True

        stat = path.stat()
        meta: dict[str, Any] = {
            "dataset_id": dataset_id,
            "source_path": str(path.resolve()),
            "rows": int(len(df)),
            "cols": int(df.shape[1]),
            "file_size_bytes": int(stat.st_size),
            "modified_ts": _utc_iso(stat.st_mtime),
            "sample_applied": sample_applied,
            "sample_size": int(settings.sample_size) if sample_applied else None,
        }

        logger.info(f"Loaded {meta['rows']} rows, {meta['cols']} columns")
        return df, meta


def load_csv(source: str, **read_csv_kwargs: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Convenience function for callers/tests that prefer function style."""
    return CsvLoader().load(source, **read_csv_kwargs)
