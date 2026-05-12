"""Phase 1: Quality assessment implementation."""

from __future__ import annotations

from typing import Any, cast

from data_quality_toolkit.assessment import issue_detector as _issue_detector
from data_quality_toolkit.shared.constants import DEFAULT_NULL_THRESHOLD
from data_quality_toolkit.shared.models import AssessmentResult, Issue
from data_quality_toolkit.utils.logging import get_logger

logger = get_logger(__name__)


def compute_score(profile: dict[str, Any]) -> float:
    """
    Compute overall quality score (0-1).
    """
    rows = int(profile.get("rows", 1) or 1)
    rows = max(rows, 1)

    completeness_scores: list[float] = []
    for column in profile.get("columns", []):
        # nulls may come as Any; coerce to int then compute
        nulls = int(column.get("nulls", 0) or 0)
        null_pct: float = nulls / float(rows)
        completeness = max(0.0, 1.0 - null_pct)
        completeness_scores.append(completeness)

    if not completeness_scores:
        return 0.0

    return float(round(sum(completeness_scores) / len(completeness_scores), 4))


def detect_issues(
    profile: dict[str, Any], null_threshold: float = DEFAULT_NULL_THRESHOLD
) -> list[Issue]:
    """
    Detect quality issues in the dataset.

    Args:
        profile: Profile result dict
        null_threshold: Threshold for flagging missing data issues

    Returns:
        List of detected issues
    """
    rows = max(profile["rows"], 1)
    issues: list[Issue] = []

    for column in profile["columns"]:
        nulls = column.get("nulls", 0) or 0
        null_pct = nulls / rows

        if nulls >= rows:  # all-null: reported as all_null_column by issue_detector
            continue

        if null_pct >= null_threshold:
            severity = "critical" if null_pct >= 0.5 else "high"
            pct_display = round(null_pct * 100, 1)
            null_issue: dict[str, Any] = {
                "type": "missing",
                "column": column["name"],
                "pct": round(null_pct, 6),
                "severity": severity,
                "category": "Completeness",
                "message": f"Column '{column['name']}' has {pct_display}% missing values",
            }
            issues.append(cast(Issue, null_issue))

    return issues


def assess(
    profile: dict[str, Any], null_threshold: float = DEFAULT_NULL_THRESHOLD
) -> AssessmentResult:
    """
    Perform quality assessment on profile results.

    Args:
        profile: Profile result dict
        null_threshold: Fraction of missing values that triggers a completeness issue

    Returns:
        Assessment result with score and issues
    """
    logger.info(f"Assessing quality for dataset: {profile['dataset_id']}")

    score = compute_score(profile)
    null_issues: list[Issue] = detect_issues(profile, null_threshold)
    schema_issues: list[Issue] = cast(list[Issue], _issue_detector.detect_issues(profile))
    all_issues = null_issues + schema_issues

    result: AssessmentResult = {
        "run_id": profile["run_id"],
        "dataset_id": profile["dataset_id"],
        "score": score,
        "issues": all_issues,
        "ts": profile["ts"],
    }

    logger.info(f"Assessment complete: score={score}, issues={len(all_issues)}")
    return result
