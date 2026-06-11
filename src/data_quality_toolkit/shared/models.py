"""Phase 1: Core data models and types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict


@dataclass(frozen=True)
class RunIds:
    """Immutable run identifiers."""

    run_id: str  # uuid4
    dataset_id: str  # sha1:...


class ColumnProfile(TypedDict):
    """Column profiling result."""

    # required
    name: str
    dtype: str
    # optional
    nulls: NotRequired[int]
    unique: NotRequired[int]
    min: NotRequired[Any]
    max: NotRequired[Any]


class ProfileResult(TypedDict):
    """Complete dataset profile."""

    run_id: str
    dataset_id: str
    rows: int
    cols: int
    memory_mb: float
    ts: str
    columns: list[ColumnProfile]


class Issue(TypedDict, total=False):
    """Quality issue descriptor."""

    type: str
    column: str | None
    pct: float | None
    severity: str
    category: str
    message: str


class AssessmentResult(TypedDict):
    """Quality assessment output."""

    run_id: str
    dataset_id: str
    score: float
    completeness_score: float
    quality_score: float
    issues: list[Issue]
    ts: str


class ErrorInfo(TypedDict):
    """Structured error descriptor returned by to_error_info."""

    code: str
    message: str
    exc_type: str
    hint: NotRequired[str | None]
    metadata: NotRequired[dict[str, Any] | None]
