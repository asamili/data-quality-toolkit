# src/data_quality_toolkit/loaders/base_loader.py
"""Phase 1: Base loader interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

__all__ = ["BaseLoader"]


class BaseLoader(ABC):
    """Abstract base class for data loaders."""

    @abstractmethod
    def load(self, source: str, **kwargs: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Load data from source and return (DataFrame, metadata)."""
        raise NotImplementedError
