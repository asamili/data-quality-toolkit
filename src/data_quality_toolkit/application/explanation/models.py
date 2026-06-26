"""StoryLens explanation model — pure, frozen, slotted value object."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from data_quality_toolkit.application.explanation.provenance import ExplanationProvenance


@dataclass(frozen=True, slots=True)
class Explanation:
    """A single plain-English explanation of one DQT result fact.

    All fields are read-only. ``evidence`` is a tuple so the whole object
    remains hashable and equality-comparable for determinism tests.
    AI output labeled here is an explanation of evidence, not validation.
    DQT metrics/reports remain the source of truth.
    ``provenance`` is optional caller-supplied metadata; None means no
    provenance was attached. Narrators must not generate timestamps.
    """

    title: str
    summary: str
    evidence: tuple[str, ...]
    why_it_matters: str
    recommended_action: str
    limitations: str
    severity: Literal["info", "ok", "warn", "breach"]
    provenance: ExplanationProvenance | None = None
