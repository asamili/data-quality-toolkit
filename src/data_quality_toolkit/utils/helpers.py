# src/data_quality_toolkit/utils/helpers.py
"""Phase 1: Helper utilities."""

from __future__ import annotations

from hashlib import blake2b
from pathlib import Path

__all__ = ["stable_seed", "ensure_dir", "make_column_id"]


def stable_seed(dataset_id: str, step: str) -> int:
    """Generate deterministic seed for sampling (32-bit)."""
    digest = blake2b(f"{dataset_id}|{step}".encode(), digest_size=4).hexdigest()
    return int(digest, 16) & 0xFFFFFFFF


def ensure_dir(path: str | Path) -> Path:
    """Ensure directory exists, return Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def make_column_id(dataset_id: str, column_name: str) -> str:
    """Create unique column identifier."""
    return f"{dataset_id}:{column_name}"
