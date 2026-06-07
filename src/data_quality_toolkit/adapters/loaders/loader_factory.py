# src/data_quality_toolkit/loaders/loader_factory.py
"""Phase 1: Loader factory (CSV only)."""

from data_quality_toolkit.loaders.base_loader import BaseLoader
from data_quality_toolkit.loaders.file.csv_loader import CsvLoader

__all__ = ["get_loader"]


def get_loader(source_type: str = "csv") -> BaseLoader:
    if source_type == "csv":
        return CsvLoader()
    raise ValueError(f"Unsupported source type: {source_type}")
