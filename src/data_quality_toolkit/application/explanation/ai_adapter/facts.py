"""StoryLens AI adapter — typed facts contract.

Allowlist-only typed contract for safe AI wrapping.
No raw DataFrames, no raw rows, no paths, no PII.
No AI dependencies imported here.
"""

from __future__ import annotations

from dataclasses import dataclass

from data_quality_toolkit.application.explanation.models import Explanation


@dataclass(frozen=True, slots=True)
class StoryLensMetric:
    """Single metric entry for the StoryLens AI prompt.

    All numeric values must be pre-formatted as strings before construction.
    ``raw_value`` is optional and used only for grounding cross-checks.
    """

    key: str
    label: str
    formatted_value: str
    raw_value: float | int | None = None
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class StoryLensFacts:
    """Typed allowlist contract for StoryLens AI wrapping.

    Holds only DQT-derived, pre-sanitised facts.
    No raw DataFrames, no raw row data, no filesystem paths, no PII.
    ``deterministic_fallback`` is always required and is what callers receive
    when AI is unavailable or output is rejected.
    """

    schema_version: str
    feature_id: str
    surface: str
    source_module: str
    deterministic_summary: str
    metrics: tuple[StoryLensMetric, ...]
    evidence_items: tuple[str, ...]
    limitations: tuple[str, ...]
    safety_notes: tuple[str, ...]
    recommended_action_context: str
    forbidden_claims: tuple[str, ...]
    formatting_rules: tuple[str, ...]
    source_timestamps: tuple[str, ...]
    deterministic_fallback: Explanation
