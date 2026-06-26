"""StoryLens AI adapter — Data Overview fact builder.

Converts deterministic Data Overview assessment outputs into a safe
StoryLensFacts payload for the optional AI adapter.

Deterministic: same inputs always produce equal StoryLensFacts.
UI-independent: no Streamlit, no pandas, no AI backend.
No raw DataFrame, no CSV path, no full profile dict.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from data_quality_toolkit.application.explanation.ai_adapter.facts import (
    StoryLensFacts,
    StoryLensMetric,
)
from data_quality_toolkit.application.explanation.models import Explanation

_SCHEMA_VERSION = "1.0"
_FEATURE_ID = "data_overview"
_SURFACE = "data_overview"
_SOURCE_MODULE = "data_quality_toolkit.application.explanation.ai_adapter.data_overview"
_SAFETY_NOTE = "Explanation of DQT metrics — explanation only, not validation."


def _extract_issue_evidence(issue: Mapping[str, object]) -> str | None:
    """Extract a safe evidence string from one issue mapping.

    Extracts only: type, column, severity, pct (missing type + numeric non-bool only).
    Skips issues with no type or column.
    Explicitly excludes: message, examples, violation_count, duplicate_count,
    expected_dtype, actual_dtype, and all other arbitrary keys.
    """
    itype = issue.get("type")
    column = issue.get("column")
    if not itype or not column:
        return None
    itype_str = str(itype)
    column_str = str(column)
    severity_str = str(issue.get("severity", "medium"))

    if itype_str == "missing":
        pct = issue.get("pct")
        if pct is not None and isinstance(pct, int | float) and not isinstance(pct, bool):
            return (
                f"issue:missing|column={column_str}"
                f"|null_pct={float(pct):.4f}|severity={severity_str}"
            )
        return f"issue:missing|column={column_str}|severity={severity_str}"

    if itype_str == "constant_column":
        return f"issue:constant_column|column={column_str}|severity={severity_str}"

    return f"issue:{itype_str}|column={column_str}|severity={severity_str}"


def build_data_overview_facts(
    *,
    score: float,
    rows: int,
    columns: int,
    issues: Sequence[Mapping[str, object]],
    deterministic_fallback: Explanation,
    max_issue_summaries: int = 3,
    memory_mb: float | None = None,
) -> StoryLensFacts:
    """Build a StoryLensFacts payload for a Data Overview quality assessment.

    Deterministic: same inputs always produce an equal StoryLensFacts.
    UI-independent: no Streamlit, no pandas, no AI backend.
    No raw DataFrame, no CSV path, no full profile dict.

    Args:
        score: Quality score in [0, 1].
        rows: Row count.
        columns: Column count.
        issues: Issue list from assessment. Only type/column/severity/pct extracted.
        deterministic_fallback: Pre-computed L0 Explanation; returned on AI failure.
        max_issue_summaries: Max issues to include in evidence (must be >= 0).
        memory_mb: Optional memory usage; formatted to 2 decimal places with " MB".

    Returns:
        StoryLensFacts ready for build_prompt / validate_output / try_explain.

    Raises:
        ValueError: If max_issue_summaries is negative.
    """
    if max_issue_summaries < 0:
        raise ValueError(f"max_issue_summaries must be >= 0, got {max_issue_summaries}")

    metrics: list[StoryLensMetric] = [
        StoryLensMetric(
            key="quality_score",
            label="Quality Score",
            formatted_value=f"{score * 100:.0f}%",
            raw_value=score,
        ),
        StoryLensMetric(
            key="rows",
            label="Rows",
            formatted_value=str(rows),
            raw_value=rows,
        ),
        StoryLensMetric(
            key="columns",
            label="Columns",
            formatted_value=str(columns),
            raw_value=columns,
        ),
        StoryLensMetric(
            key="issues_total",
            label="Issues Flagged",
            formatted_value=str(len(issues)),
            raw_value=len(issues),
        ),
    ]
    if memory_mb is not None:
        metrics.append(
            StoryLensMetric(
                key="memory_mb",
                label="Memory",
                formatted_value=f"{memory_mb:.2f} MB",
                raw_value=memory_mb,
            )
        )

    evidence: list[str] = list(deterministic_fallback.evidence)
    issue_count = 0
    for issue in issues:
        if issue_count >= max_issue_summaries:
            break
        entry = _extract_issue_evidence(issue)
        if entry is not None:
            evidence.append(entry)
            issue_count += 1

    return StoryLensFacts(
        schema_version=_SCHEMA_VERSION,
        feature_id=_FEATURE_ID,
        surface=_SURFACE,
        source_module=_SOURCE_MODULE,
        deterministic_summary=deterministic_fallback.summary,
        metrics=tuple(metrics),
        evidence_items=tuple(evidence),
        limitations=(deterministic_fallback.limitations,),
        safety_notes=(_SAFETY_NOTE,),
        recommended_action_context=deterministic_fallback.recommended_action,
        forbidden_claims=(),
        formatting_rules=(),
        source_timestamps=(),
        deterministic_fallback=deterministic_fallback,
    )
