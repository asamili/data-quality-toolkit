"""StoryLens AI adapter — output grounding validator.

Deterministic: same (text, facts) always produces the same ValidationResult.
Rejects AI output that invents data, makes causal claims, leaks internal
details, or contradicts the deterministic facts. On rejection, the caller
must return the deterministic fallback.

No AI dependencies. No model calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from data_quality_toolkit.application.explanation.ai_adapter.facts import StoryLensFacts

_MAX_OUTPUT_LEN = 2000

_DRIFT_SAFETY_PHRASE = "Drift is a distribution change, not a defect or a cause."

_DRIFT_CAUSALITY_PHRASES: tuple[str, ...] = (
    "caused by",
    "because of",
    "due to",
    "root cause",
    "responsible for",
)

_PROMPT_LEAK_MARKERS: tuple[str, ...] = (
    "[DQT StoryLens v",
    "[INST]",
    "[/INST]",
    "<<SYS>>",
    "## Metrics",
    "## Evidence",
    "## Limitations",
    "## Safety Notes",
    "## Forbidden Claims",
    "## Task",
    "## Context for Recommendation",
)

_BREACH_CONTRADICTION_KEYWORDS: tuple[str, ...] = (
    "no issue",
    "no problem",
    "looks good",
    "all ok",
    "no errors",
    "everything is fine",
)

_OK_CONTRADICTION_KEYWORDS: tuple[str, ...] = (
    "critical issue",
    "serious problem",
    "data breach",
    "severe failure",
)

_MODEL_ID = "HuggingFaceTB/SmolLM2-135M-Instruct"
_MODEL_REVISION = "12fd25f77366fa6b3b4b768ec3050bf629380bac"
_MODEL_REVISION_SHORT = "12fd25f"

_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b")
_ENV_VAR_RE = re.compile(r"\bDQT_[A-Z_]+\b")
_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/[a-z]+/[a-z]+)")


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Result of validating one AI output against the source facts."""

    ok: bool
    rejected_reasons: tuple[str, ...]


def _numbers_from_text(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text))


def _numbers_from_facts(facts: StoryLensFacts) -> set[str]:
    nums: set[str] = set()
    for m in facts.metrics:
        nums.update(_NUMBER_RE.findall(m.formatted_value))
    for e in facts.evidence_items:
        nums.update(_NUMBER_RE.findall(e))
    nums.update(_NUMBER_RE.findall(facts.deterministic_summary))
    nums.update(_NUMBER_RE.findall(facts.recommended_action_context))
    for note in facts.safety_notes:
        nums.update(_NUMBER_RE.findall(note))
    return nums


def _check_length(text: str) -> list[str]:
    return ["output_too_long"] if len(text) > _MAX_OUTPUT_LEN else []


def _check_invented_numbers(text: str, facts: StoryLensFacts) -> list[str]:
    invented = _numbers_from_text(text) - _numbers_from_facts(facts)
    if invented:
        return [f"invented_numbers:{','.join(sorted(invented))}"]
    return []


def _check_severity(text_lower: str, facts: StoryLensFacts) -> list[str]:
    severity = facts.deterministic_fallback.severity
    if severity in ("breach", "warn") and any(
        kw in text_lower for kw in _BREACH_CONTRADICTION_KEYWORDS
    ):
        return ["severity_contradiction"]
    if severity in ("ok", "info") and any(kw in text_lower for kw in _OK_CONTRADICTION_KEYWORDS):
        return ["severity_contradiction"]
    return []


def _check_causality(text_lower: str) -> list[str]:
    for phrase in _DRIFT_CAUSALITY_PHRASES:
        if phrase in text_lower:
            return [f"causality_phrase:{phrase!r}"]
    return []


def _check_drift_limitation(text_lower: str, facts: StoryLensFacts) -> list[str]:
    drift_required = facts.feature_id == "drift_explorer" or any(
        _DRIFT_SAFETY_PHRASE in note for note in facts.safety_notes
    )
    if drift_required and _DRIFT_SAFETY_PHRASE.lower() not in text_lower:
        return ["missing_drift_limitation"]
    return []


def _check_leakage(text: str, text_lower: str, facts: StoryLensFacts) -> list[str]:
    reasons: list[str] = []
    for marker in _PROMPT_LEAK_MARKERS:
        if marker in text:
            reasons.append(f"prompt_leakage:{marker!r}")
            break
    if _PATH_RE.search(text):
        reasons.append("path_leakage")
    if _ENV_VAR_RE.search(text):
        reasons.append("env_var_leakage")
    if _MODEL_ID in text:
        reasons.append("model_id_leakage")
    if _MODEL_REVISION in text or _MODEL_REVISION_SHORT in text:
        reasons.append("revision_hash_leakage")
    for claim in facts.forbidden_claims:
        if claim.lower() in text_lower:
            reasons.append(f"forbidden_claim:{claim!r}")
            break
    return reasons


def validate_output(text: str, facts: StoryLensFacts) -> ValidationResult:
    """Apply all grounding rules; return ValidationResult with ok=False on any violation."""
    if not text or not text.strip():
        return ValidationResult(ok=False, rejected_reasons=("empty_output",))

    text_lower = text.lower()
    reasons: list[str] = []
    reasons += _check_length(text)
    reasons += _check_invented_numbers(text, facts)
    reasons += _check_severity(text_lower, facts)
    reasons += _check_causality(text_lower)
    reasons += _check_drift_limitation(text_lower, facts)
    reasons += _check_leakage(text, text_lower, facts)

    if reasons:
        return ValidationResult(ok=False, rejected_reasons=tuple(reasons))
    return ValidationResult(ok=True, rejected_reasons=())
