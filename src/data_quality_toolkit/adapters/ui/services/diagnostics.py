"""Read-only diagnostics/governance helpers for the Settings page.

Pure(ish) and streamlit-free. These functions report *truthful*, redacted
runtime and capability information. They never invent placeholder values, never
expose secrets or absolute paths, and never import optional AI/model packages.

Optional-dependency presence is checked with ``importlib.util.find_spec``, which
locates a module without importing it; the optional AI/model packages are
deliberately excluded from that probe so they are never loaded here.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
from typing import Any

from data_quality_toolkit.shared.constants import (
    DEFAULT_HIGH_CARDINALITY_THRESHOLD,
    DEFAULT_NULL_THRESHOLD,
    DEFAULT_OUTLIER_FRACTION_THRESHOLD,
    DIST_PENALTY_CAP,
    SCHEMA_PENALTY_CAP,
    SEVERITY_PENALTIES,
    VERSION,
)

# Optional dependencies whose presence is safe to probe. The optional StoryLens
# AI/model packages are intentionally omitted — their state is reported via the
# default-off availability helper, never by importing or locating them here.
_OPTIONAL_DEPENDENCIES: tuple[str, ...] = (
    "streamlit",
    "scipy",
    "matplotlib",
    "duckdb",
    "openpyxl",
    "graphviz",
)


def collect_versions() -> dict[str, str]:
    """Return real toolkit/runtime version information (no placeholders)."""
    py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return {
        "data_quality_toolkit": VERSION,
        "python": py,
        "platform": sys.platform,
    }


def _module_available(name: str) -> bool:
    """Return True when ``name`` can be located, without importing it."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def collect_capability_snapshot() -> dict[str, str]:
    """Report availability of optional, non-AI dependencies (find_spec only)."""
    snapshot: dict[str, str] = {}
    for name in _OPTIONAL_DEPENDENCIES:
        snapshot[name] = "available" if _module_available(name) else "not installed"
    return snapshot


def collect_ai_availability() -> dict[str, Any]:
    """Return optional-AI state via the default-off helper (display only).

    Reads environment only; never imports model packages and never returns the
    concrete model directory path.
    """
    from data_quality_toolkit.application.explanation.ai_adapter.settings import (
        compute_availability,
    )

    availability = compute_availability()
    return {
        "enabled": bool(availability.enabled),
        "reason": availability.reason,
        "default": "off",
    }


def collect_thresholds() -> dict[str, Any]:
    """Surface the deterministic scoring/detection thresholds (read-only)."""
    return {
        "null_threshold": DEFAULT_NULL_THRESHOLD,
        "high_cardinality_threshold": DEFAULT_HIGH_CARDINALITY_THRESHOLD,
        "outlier_fraction_threshold": DEFAULT_OUTLIER_FRACTION_THRESHOLD,
        "schema_penalty_cap": SCHEMA_PENALTY_CAP,
        "distribution_penalty_cap": DIST_PENALTY_CAP,
        "severity_penalties": dict(SEVERITY_PENALTIES),
    }


def privacy_posture() -> dict[str, str]:
    """Return the fixed, user-facing privacy/compute posture statements."""
    return {
        "path_redaction": "Artifact and dataset paths are shown as basenames only.",
        "local_only": "Datasets are read from local paths; nothing is uploaded.",
        "large_file_mode": "Large-file mode profiles via chunked streaming and discloses "
        "which metrics are unavailable.",
        "server_writes": "Server-side exports require an absolute path and explicit confirmation.",
        "optional_ai": "Optional local AI is default-off and is not activated by this UI.",
    }


def probe_writable_dir(path_str: str) -> tuple[bool, str | None]:
    """Probe whether ``path_str`` is an existing, writable directory.

    Creates and immediately deletes a temporary file; writes nothing durable.
    Returns ``(True, None)`` on success or ``(False, message)`` on failure.
    """
    path = Path(path_str.strip()) if path_str else Path()
    if not path.exists() or not path.is_dir():
        return False, f"Directory not found: {path_str}"
    try:
        with tempfile.NamedTemporaryFile(dir=path, delete=True):
            return True, None
    except OSError as exc:
        return False, str(exc)
