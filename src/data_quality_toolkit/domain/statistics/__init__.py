"""Statistical analysis domain modules (drift detection, inferential tests)."""

from data_quality_toolkit.domain.statistics.drift import detect_drift_frames
from data_quality_toolkit.domain.statistics.inferential import (
    ab_compare,
    check_normality,
    compare_multi_group,
    compare_two_groups,
)

__all__ = [
    "ab_compare",
    "check_normality",
    "compare_multi_group",
    "compare_two_groups",
    "detect_drift_frames",
]
