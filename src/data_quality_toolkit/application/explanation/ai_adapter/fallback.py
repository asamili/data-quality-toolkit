"""StoryLens AI adapter — deterministic fallback wrapper.

``try_explain`` is the single public entry point. It always returns an
``Explanation`` and never raises expected AI-backend errors to its caller.
Deterministic fallback is returned on flag OFF, missing model directory,
missing optional dependencies, generation error, or validator rejection.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING

from data_quality_toolkit.application.explanation.ai_adapter.facts import StoryLensFacts
from data_quality_toolkit.application.explanation.ai_adapter.prompts import build_prompt
from data_quality_toolkit.application.explanation.ai_adapter.settings import compute_availability
from data_quality_toolkit.application.explanation.ai_adapter.validator import validate_output
from data_quality_toolkit.application.explanation.models import Explanation

if TYPE_CHECKING:
    from data_quality_toolkit.application.explanation.ai_narrator import LocalAINarratorConfig

_log = logging.getLogger(__name__)


def get_fallback(facts: StoryLensFacts) -> Explanation:
    """Return the deterministic fallback Explanation. Never raises."""
    return facts.deterministic_fallback


def _merge_ai_summary(ai_text: str, base: Explanation) -> Explanation:
    """Merge AI-generated text as bounded summary supplement.

    Preserves safety-critical fields from base: title, evidence, limitations, severity.
    AI text is used only as ``summary`` (≤400 chars). All other fields from base.
    """
    ai_summary = ai_text.strip()[:400]
    return Explanation(
        title=base.title,
        summary=ai_summary,
        evidence=base.evidence,
        why_it_matters=base.why_it_matters,
        recommended_action=base.recommended_action,
        limitations=base.limitations,
        severity=base.severity,
        provenance=base.provenance,
    )


def try_explain(
    facts: StoryLensFacts,
    *,
    config: LocalAINarratorConfig | None = None,
    env: Mapping[str, str] | None = None,
) -> Explanation:
    """Try AI explanation; always return an ``Explanation``. Never raises.

    Falls back to ``facts.deterministic_fallback`` when:
    - AI flag is OFF (default)
    - Model directory is missing / unavailable
    - Optional AI dependencies are absent
    - Local model files are not present
    - Generation raises any expected error
    - Validator rejects the generated output
    """
    availability = compute_availability(env)
    if not availability.enabled:
        _log.debug("StoryLens AI unavailable: %s", availability.reason)
        return get_fallback(facts)

    try:
        prompt = build_prompt(facts)
    except Exception as exc:  # noqa: BLE001
        _log.warning("StoryLens prompt build failed: %s", exc)
        return get_fallback(facts)

    try:
        from data_quality_toolkit.application.explanation.ai_narrator import (  # noqa: PLC0415
            generate_narrative,
        )

        raw = generate_narrative(prompt=prompt, config=config)
    except Exception as exc:  # noqa: BLE001
        _log.warning("StoryLens AI generation unavailable: %s", type(exc).__name__)
        return get_fallback(facts)

    result = validate_output(raw, facts)
    if not result.ok:
        _log.warning(
            "StoryLens AI output rejected (reasons: %s)",
            ", ".join(result.rejected_reasons),
        )
        return get_fallback(facts)

    return _merge_ai_summary(raw, facts.deterministic_fallback)
