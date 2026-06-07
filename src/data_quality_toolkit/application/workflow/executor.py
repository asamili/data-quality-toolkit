# src/data_quality_toolkit/workflow/executor.py
"""Phase 1: Thin executor (reserved for future concurrency)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from data_quality_toolkit.utils.logging import get_logger

logger = get_logger(__name__)


def execute(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Execute a callable; hook for retries/metrics later."""
    logger.debug("Executing %s", getattr(fn, "__name__", str(fn)))
    return fn(*args, **kwargs)
