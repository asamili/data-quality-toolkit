"""StoryLens AI adapter — deterministic prompt builder.

Builds the AI prompt from StoryLensFacts only.
Same facts object → byte-identical prompt string.
No raw rows, no filesystem paths, no environment values, no model IDs.
Numeric values come from pre-formatted metric strings, not raw floats.
"""

from __future__ import annotations

from data_quality_toolkit.application.explanation.ai_adapter.facts import (
    StoryLensFacts,
    StoryLensMetric,
)

PROMPT_TEMPLATE_VERSION = "1.0"

_DRIFT_SAFETY_PHRASE = "Drift is a distribution change, not a defect or a cause."

_ANTI_HALLUCINATION_INSTRUCTIONS = (
    "Rules:\n"
    "- Do not calculate new metrics or statistics.\n"
    "- Do not invent numbers not present in the facts above.\n"
    "- Do not infer causes, root causes, or reasons for drift.\n"
    "- Do not expose internal reasoning or chain of thought.\n"
    "- State uncertainty and limitations explicitly.\n"
    "- Do not reference filesystem paths, environment variables, or model identifiers.\n"
    "- Keep your response short and grounded in the facts provided above."
)

_DRIFT_CAUSALITY_REMINDER = (
    f"Important: {_DRIFT_SAFETY_PHRASE} " "Do not attribute drift to any cause."
)


def _metrics_section(metrics: tuple[StoryLensMetric, ...]) -> list[str]:
    if not metrics:
        return []
    lines: list[str] = ["## Metrics"]
    for m in sorted(metrics, key=lambda x: x.key):
        line = f"- {m.key} ({m.label}): {m.formatted_value}"
        if m.unit:
            line += f" [{m.unit}]"
        lines.append(line)
    lines.append("")
    return lines


def _items_section(header: str, items: tuple[str, ...]) -> list[str]:
    if not items:
        return []
    lines: list[str] = [f"## {header}"]
    for item in items:
        lines.append(f"- {item}")
    lines.append("")
    return lines


def _optional_text_section(header: str, text: str) -> list[str]:
    if not text:
        return []
    return [f"## {header}", text, ""]


def _drift_reminder_section(facts: StoryLensFacts) -> list[str]:
    drift_required = facts.feature_id == "drift_explorer" or any(
        _DRIFT_SAFETY_PHRASE in note for note in facts.safety_notes
    )
    if not drift_required:
        return []
    return [_DRIFT_CAUSALITY_REMINDER, ""]


def build_prompt(facts: StoryLensFacts) -> str:
    """Build a deterministic prompt string from StoryLensFacts.

    Deterministic: same ``facts`` object always produces byte-identical output.
    Metrics are sorted by key; evidence, limitations, safety notes, and
    forbidden claims preserve insertion order from the facts tuple.
    """
    parts: list[str] = [
        f"[DQT StoryLens v{PROMPT_TEMPLATE_VERSION}]",
        f"Feature: {facts.feature_id}",
        f"Surface: {facts.surface}",
        "",
        "## Summary",
        facts.deterministic_summary,
        "",
    ]
    parts += _metrics_section(facts.metrics)
    parts += _items_section("Evidence", facts.evidence_items)
    parts += _items_section("Limitations", facts.limitations)
    parts += _items_section("Safety Notes", facts.safety_notes)
    parts += _items_section("Forbidden Claims (must not appear in output)", facts.forbidden_claims)
    parts += _optional_text_section("Context for Recommendation", facts.recommended_action_context)
    parts += _drift_reminder_section(facts)
    parts += [
        _ANTI_HALLUCINATION_INSTRUCTIONS,
        "",
        "## Task",
        "Write a short, grounded explanation using only the facts above. "
        "State any limitations. Do not invent information.",
    ]
    return "\n".join(parts)
