"""Reusable factory functions for building test fixtures."""

from __future__ import annotations

import time
import uuid
from typing import Any

from data_quality_toolkit.shared.models import AssessmentResult, ColumnProfile, Issue, ProfileResult


def make_run_id() -> str:
    """Generate a unique run_id (uuid4 string)."""
    return str(uuid.uuid4())


def make_dataset_id(name: str = "test-dataset") -> str:
    """Generate a pseudo dataset_id (sha1-style placeholder)."""
    return f"sha1:{uuid.uuid5(uuid.NAMESPACE_DNS, name).hex}"


def make_column_profile(
    name: str = "col1",
    dtype: str = "int",
    nulls: int = 0,
    unique: int = 10,
    min_value: Any = 0,
    max_value: Any = 100,
) -> ColumnProfile:
    """Return a minimal valid ColumnProfile."""
    return {
        "name": name,
        "dtype": dtype,
        "nulls": nulls,
        "unique": unique,
        "min": min_value,
        "max": max_value,
    }


def make_profile_result(
    columns: list[ColumnProfile] | None = None,
    rows: int = 100,
    cols: int = 5,
    memory_mb: float = 0.1,
) -> ProfileResult:
    """Return a valid ProfileResult dict."""
    return {
        "run_id": make_run_id(),
        "dataset_id": make_dataset_id(),
        "rows": rows,
        "cols": cols,
        "memory_mb": memory_mb,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "columns": columns or [make_column_profile()],
    }


def make_issue(
    issue_type: str = "missing_values",
    column: str | None = "col1",
    pct: float | None = 0.0,
    severity: str = "low",
) -> Issue:
    """Return a minimal Issue dict."""
    return {
        "type": issue_type,
        "column": column,
        "pct": pct,
        "severity": severity,
    }


def make_assessment_result(
    issues: list[Issue] | None = None,
    score: float = 0.95,
) -> AssessmentResult:
    """Return a valid AssessmentResult dict."""
    return {
        "run_id": make_run_id(),
        "dataset_id": make_dataset_id(),
        "score": score,
        "issues": issues or [make_issue()],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
