"""Quality-score explainability helpers for the dashboard UI.

Pure, deterministic, streamlit-free. These functions read an existing
assessment result (as produced by ``domain.assessment.quality_checker.assess``)
and the shared scoring constants, then derive a user-facing explanation of how
the overall quality score was reached. They do not recompute the authoritative
score and do not change domain scoring logic — they mirror the published
penalty rules so the UI can show *why* a score is what it is.

The critical-column penalty multiplier is config-driven in the domain layer and
is not reproduced here; rows note when a penalty would be amplified by config.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from data_quality_toolkit.shared.constants import (
    DEFAULT_NULL_THRESHOLD,
    DIST_PENALTY_CAP,
    EXCLUDED_PENALTY_TYPES,
    SCHEMA_PENALTY_CAP,
    SEVERITY_PENALTIES,
)

# Mirrors narrator.explain_quality_score: score >= this is reported as "good".
PUBLISH_THRESHOLD: float = 0.90

_SCHEMA_CATEGORY = "Schema"


def _as_float(value: Any) -> float | None:
    """Return a finite float for ints/floats (not bools), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def score_overview(assessment: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize completeness vs penalty-adjusted quality score for display.

    ``quality_score`` may be absent in older/partial assessment dicts; it is
    reported as ``None`` rather than silently falling back to completeness.
    """
    completeness = _as_float(assessment.get("score"))
    if completeness is None:
        completeness = _as_float(assessment.get("completeness_score"))
    quality = _as_float(assessment.get("quality_score"))
    issues = assessment.get("issues") or []
    headline = quality if quality is not None else completeness
    meets = headline is not None and headline >= PUBLISH_THRESHOLD
    return {
        "completeness_score": completeness,
        "quality_score": quality,
        "headline_score": headline,
        "issues_total": len(list(issues)),
        "publish_threshold": PUBLISH_THRESHOLD,
        "meets_threshold": meets,
    }


def severity_penalty_table() -> list[dict[str, Any]]:
    """Return the severity → penalty mapping as ordered display rows."""
    order = ["critical", "high", "medium", "low"]
    rows: list[dict[str, Any]] = []
    for severity in order:
        if severity in SEVERITY_PENALTIES:
            rows.append(
                {"severity": severity, "penalty_points": round(SEVERITY_PENALTIES[severity], 4)}
            )
    return rows


def _bucket(category: str) -> str:
    return "schema" if category == _SCHEMA_CATEGORY else "distribution"


def rule_contribution_rows(assessment: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build a per-issue penalty-contribution table mirroring the score rules.

    Each row reports the issue type, column, severity, category, which penalty
    bucket it falls in (schema vs distribution), whether it is excluded from the
    score, and the base penalty applied. Excluded completeness issues
    (``missing``/``all_null_column``) carry a 0.0 penalty because completeness is
    already reflected in the completeness score.
    """
    rows: list[dict[str, Any]] = []
    issues = assessment.get("issues") or []
    for issue in issues:
        if not isinstance(issue, Mapping):
            continue
        itype = str(issue.get("type", ""))
        severity = str(issue.get("severity", "low"))
        category = str(issue.get("category", ""))
        excluded = itype in EXCLUDED_PENALTY_TYPES
        base_penalty = 0.0 if excluded else SEVERITY_PENALTIES.get(severity, 0.0)
        rows.append(
            {
                "type": itype,
                "column": issue.get("column", ""),
                "severity": severity,
                "category": category or "—",
                "penalty_bucket": "n/a" if excluded else _bucket(category),
                "counted_in_score": not excluded,
                "penalty_points": round(base_penalty, 4),
            }
        )
    return rows


def penalty_breakdown(assessment: Mapping[str, Any]) -> dict[str, Any]:
    """Derive capped schema/distribution penalties and the resulting score.

    Mirrors ``compute_quality_score`` without the config-driven critical-column
    multiplier. ``derived_quality_score`` is the value those published rules
    yield from the displayed issues; it is compared against the authoritative
    ``quality_score`` so any config-only divergence is visible rather than hidden.
    """
    completeness = _as_float(assessment.get("score"))
    if completeness is None:
        completeness = _as_float(assessment.get("completeness_score")) or 0.0

    schema_raw = 0.0
    dist_raw = 0.0
    for row in rule_contribution_rows(assessment):
        if not row["counted_in_score"]:
            continue
        if row["penalty_bucket"] == "schema":
            schema_raw += float(row["penalty_points"])
        else:
            dist_raw += float(row["penalty_points"])

    schema_applied = min(schema_raw, SCHEMA_PENALTY_CAP)
    dist_applied = min(dist_raw, DIST_PENALTY_CAP)
    derived = max(0.0, min(1.0, round(completeness - schema_applied - dist_applied, 4)))
    return {
        "completeness_score": round(completeness, 4),
        "schema_penalty_raw": round(schema_raw, 4),
        "schema_penalty_applied": round(schema_applied, 4),
        "schema_penalty_cap": SCHEMA_PENALTY_CAP,
        "distribution_penalty_raw": round(dist_raw, 4),
        "distribution_penalty_applied": round(dist_applied, 4),
        "distribution_penalty_cap": DIST_PENALTY_CAP,
        "derived_quality_score": derived,
        "reported_quality_score": _as_float(assessment.get("quality_score")),
        "excluded_types": sorted(EXCLUDED_PENALTY_TYPES),
        "null_threshold": DEFAULT_NULL_THRESHOLD,
    }


def formula_caption() -> str:
    """Return a plain-language description of the quality-score formula."""
    return (
        "Quality score = completeness − schema penalties − distribution penalties, "
        "clamped to [0, 1]. Completeness is the column-weighted share of non-missing "
        f"cells. Schema penalties are capped at {SCHEMA_PENALTY_CAP:.2f} and distribution "
        f"penalties at {DIST_PENALTY_CAP:.2f}. Missing-value and all-null issues are "
        "excluded from penalties because completeness already accounts for them."
    )


def evidence_lines(assessment: Mapping[str, Any]) -> Sequence[str]:
    """Return compact, path-free evidence lines for the score (display only)."""
    overview = score_overview(assessment)
    completeness = overview["completeness_score"]
    quality = overview["quality_score"]
    return (
        (
            f"completeness_score={completeness:.4f}"
            if completeness is not None
            else "completeness=N/A"
        ),
        f"quality_score={quality:.4f}" if quality is not None else "quality_score=N/A",
        f"issues_total={overview['issues_total']}",
        f"publish_threshold={overview['publish_threshold']:.2f}",
    )
