"""Phase 1: Shared constants (minimal for now)."""

from __future__ import annotations

# Package metadata — resolved from installed package to stay in sync with pyproject.toml.
try:
    from importlib.metadata import version as _pkg_version

    VERSION: str = _pkg_version("data-quality-toolkit")
except Exception:
    VERSION = "0.6.6"

# Timestamps
DEFAULT_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Limits
DEFAULT_MAX_ROWS_IN_MEMORY = 1_000_000
DEFAULT_SAMPLE_SIZE = 1_000
DEFAULT_NULL_THRESHOLD = 0.2
DEFAULT_UNIQUENESS_THRESHOLD = 0.95
DEFAULT_HIGH_CARDINALITY_THRESHOLD = 0.9
DEFAULT_OUTLIER_FRACTION_THRESHOLD = 0.05
SEVERITY_LEVELS = ["low", "medium", "high", "critical"]

ARTIFACT_SCHEMA_VERSION = "1"

# Quality score penalty weights
SEVERITY_PENALTIES: dict[str, float] = {
    "critical": 0.05,
    "high": 0.03,
    "medium": 0.02,
    "low": 0.01,
}
SCHEMA_PENALTY_CAP: float = 0.30
DIST_PENALTY_CAP: float = 0.15
EXCLUDED_PENALTY_TYPES: frozenset[str] = frozenset({"missing", "all_null_column"})


__all__ = [
    "VERSION",
    "DEFAULT_TS_FORMAT",
    "DEFAULT_MAX_ROWS_IN_MEMORY",
    "DEFAULT_SAMPLE_SIZE",
    "DEFAULT_NULL_THRESHOLD",
    "DEFAULT_UNIQUENESS_THRESHOLD",
    "DEFAULT_HIGH_CARDINALITY_THRESHOLD",
    "DEFAULT_OUTLIER_FRACTION_THRESHOLD",
    "SEVERITY_LEVELS",
    "ARTIFACT_SCHEMA_VERSION",
    "SEVERITY_PENALTIES",
    "SCHEMA_PENALTY_CAP",
    "DIST_PENALTY_CAP",
    "EXCLUDED_PENALTY_TYPES",
]
