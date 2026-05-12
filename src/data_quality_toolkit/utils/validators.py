# src/data_quality_toolkit/utils/validators.py
"""Phase 1: Validation utilities (stubs)."""

from __future__ import annotations

from pathlib import Path

__all__ = ["validate_csv_path", "validate_pii"]


def validate_csv_path(path: str) -> bool:
    """Validate CSV file path exists and ends with .csv."""
    p = Path(path)
    return p.exists() and p.is_file() and p.suffix.lower() == ".csv"


def validate_pii(text: str) -> bool:
    """PII detection stub — always returns False in Phase 1."""
    return False
