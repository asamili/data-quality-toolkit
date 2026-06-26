"""StoryLens provenance — frozen, dependency-free generation-mode contract.

Narrators must not generate timestamps; callers supply them when available.
Must not contain raw rows, cell values, absolute paths, secrets, or tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ----------------------------------------------------------------------------
# Drift-monitoring provenance constants (G27H-A). Source-local, dependency-free
# identifiers reused by the deterministic drift narrators. These name metric
# keys only — never paths, values, bin labels, or timestamps.
# ----------------------------------------------------------------------------

DRIFT_FEATURE = "drift_monitoring"
DRIFT_HISTORY_METRIC_KEYS: tuple[str, ...] = ("total_runs", "drifted_runs")
DRIFT_STATUS_METRIC_KEYS: tuple[str, ...] = (
    "drift_detected",
    "columns_drifted",
    "columns_tested",
)


@dataclass(frozen=True, slots=True)
class ExplanationProvenance:
    """Source and generation-mode metadata for a StoryLens Explanation.

    Fields are read-only and the whole object is hashable.
    ``generation_mode`` distinguishes deterministic narrator output from
    optional local AI output (optional_ai is default-off and validator-gated).
    """

    source_feature: str
    source_metric_keys: tuple[str, ...]
    generation_mode: Literal["deterministic", "optional_ai"]
    dataset_id: str | None = None
    run_id: str | None = None
