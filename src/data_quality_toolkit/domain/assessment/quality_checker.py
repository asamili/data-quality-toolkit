"""Phase 1: Quality assessment implementation."""

from __future__ import annotations

from typing import Any, cast

from data_quality_toolkit.domain.assessment import issue_detector as _issue_detector
from data_quality_toolkit.shared.config import load_dqt_config
from data_quality_toolkit.shared.constants import (
    DEFAULT_NULL_THRESHOLD,
    DIST_PENALTY_CAP,
    EXCLUDED_PENALTY_TYPES,
    SCHEMA_PENALTY_CAP,
    SEVERITY_PENALTIES,
)
from data_quality_toolkit.shared.models import AssessmentResult, Issue
from data_quality_toolkit.utils.logging import get_logger

logger = get_logger(__name__)


def compute_score(profile: dict[str, Any], config: dict[str, Any] | None = None) -> float:
    """
    Compute overall quality score (0-1), supporting per-column weights.
    """
    rows = int(profile.get("rows", 1) or 1)
    rows = max(rows, 1)
    column_rules = (config or {}).get("columns", {})

    weighted_completeness_sum = 0.0
    total_weight = 0.0

    for column in profile.get("columns", []):
        name = column["name"]
        nulls = int(column.get("nulls", 0) or 0)
        null_pct: float = nulls / float(rows)
        completeness = max(0.0, 1.0 - null_pct)

        # Apply weight from config or default to 1.0
        rules = column_rules.get(name, {})
        weight = rules.get("weight", 1.0)

        weighted_completeness_sum += completeness * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0

    return float(round(weighted_completeness_sum / total_weight, 4))


def compute_quality_score(
    completeness_score: float, issues: list[Issue], config: dict[str, Any] | None = None
) -> float:
    """Penalty-weighted quality score: completeness minus bounded structural penalties."""
    schema_pen = 0.0
    dist_pen = 0.0
    column_rules = (config or {}).get("columns", {})

    for issue in issues:
        if issue.get("type", "") in EXCLUDED_PENALTY_TYPES:
            continue

        pen = SEVERITY_PENALTIES.get(issue.get("severity", "low"), 0.0)

        # Apply critical penalty multiplier if configured
        col_name = issue.get("column")
        if col_name and isinstance(col_name, str):
            rules = column_rules.get(col_name, {})
            if rules.get("critical", False):
                pen *= 2.0  # Double penalty for critical columns

        if issue.get("category", "") == "Schema":
            schema_pen += pen
        else:
            dist_pen += pen
    schema_pen = min(schema_pen, SCHEMA_PENALTY_CAP)
    dist_pen = min(dist_pen, DIST_PENALTY_CAP)
    return max(0.0, min(1.0, round(completeness_score - schema_pen - dist_pen, 4)))


def detect_issues(
    profile: dict[str, Any],
    null_threshold: float = DEFAULT_NULL_THRESHOLD,
    config: dict[str, Any] | None = None,
) -> list[Issue]:
    """
    Detect quality issues in the dataset.

    Args:
        profile: Profile result dict
        null_threshold: Threshold for flagging missing data issues
        config: DQT config mapping

    Returns:
        List of detected issues
    """
    rows = max(profile["rows"], 1)
    issues: list[Issue] = []
    column_rules = (config or {}).get("columns", {})

    for column in profile["columns"]:
        name = column["name"]
        nulls = column.get("nulls", 0) or 0
        null_pct = nulls / rows

        if nulls >= rows:  # all-null: reported as all_null_column by issue_detector
            continue

        # Per-column override or global default
        rules = column_rules.get(name, {})
        threshold = rules.get("null_threshold", null_threshold)

        if null_pct >= threshold:
            severity = "critical" if null_pct >= 0.5 else "high"
            pct_display = round(null_pct * 100, 1)
            null_issue: dict[str, Any] = {
                "type": "missing",
                "column": name,
                "pct": round(null_pct, 6),
                "severity": severity,
                "category": "Completeness",
                "message": f"Column '{name}' has {pct_display}% missing values",
            }
            issues.append(cast(Issue, null_issue))

    return issues


def assess(
    profile: dict[str, Any],
    null_threshold: float = DEFAULT_NULL_THRESHOLD,
    df: Any = None,
    config: dict[str, Any] | None = None,
) -> AssessmentResult:
    """
    Perform quality assessment on profile results.

    Args:
        profile: Profile result dict
        null_threshold: Fraction of missing values that triggers a completeness issue
        df: Optional DataFrame for advanced checks
        config: Optional DQT config mapping; if None, loads from CWD

    Returns:
        Assessment result with score and issues
    """
    logger.info(f"Assessing quality for dataset: {profile['dataset_id']}")
    if config is None:
        config = load_dqt_config()

    score = compute_score(profile, config=config)
    null_issues: list[Issue] = detect_issues(profile, null_threshold, config=config)
    schema_issues: list[Issue] = cast(
        list[Issue], _issue_detector.detect_issues(profile, config=config)
    )
    advanced_issues: list[Issue] = (
        cast(list[Issue], _issue_detector.detect_advanced_issues(df, profile, config=config))
        if df is not None
        else []
    )
    all_issues = null_issues + schema_issues + advanced_issues
    quality_score = compute_quality_score(score, all_issues, config=config)

    result: AssessmentResult = {
        "run_id": profile["run_id"],
        "dataset_id": profile["dataset_id"],
        "score": score,
        "completeness_score": score,
        "quality_score": quality_score,
        "issues": all_issues,
        "ts": profile["ts"],
    }

    logger.info(
        f"Assessment complete: score={score}, quality_score={quality_score}, issues={len(all_issues)}"
    )
    return result
