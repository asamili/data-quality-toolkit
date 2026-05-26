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
SEVERITY_LEVELS = ["low", "medium", "high", "critical"]

ARTIFACT_SCHEMA_VERSION = "1"


__all__ = [
    "VERSION",
    "DEFAULT_TS_FORMAT",
    "DEFAULT_MAX_ROWS_IN_MEMORY",
    "DEFAULT_SAMPLE_SIZE",
    "DEFAULT_NULL_THRESHOLD",
    "DEFAULT_UNIQUENESS_THRESHOLD",
    "DEFAULT_HIGH_CARDINALITY_THRESHOLD",
    "SEVERITY_LEVELS",
    "ARTIFACT_SCHEMA_VERSION",
]
