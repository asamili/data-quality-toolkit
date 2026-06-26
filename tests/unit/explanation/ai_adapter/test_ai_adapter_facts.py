"""Unit tests for StoryLensFacts and StoryLensMetric typed contracts."""

from __future__ import annotations

import pytest

from data_quality_toolkit.application.explanation.ai_adapter.facts import (
    StoryLensFacts,
    StoryLensMetric,
)
from data_quality_toolkit.application.explanation.models import Explanation

_FALLBACK = Explanation(
    title="Quality score: 95% (good)",
    summary="Quality score is 95% with 0 issues flagged.",
    evidence=("score=0.9500", "rows=1000", "columns=5", "issues_total=0"),
    why_it_matters="Quality score is the primary trust signal.",
    recommended_action="Proceed to export.",
    limitations="Score is completeness-weighted.",
    severity="ok",
)


def _make_metric(**kw) -> StoryLensMetric:
    defaults = dict(key="score", label="Quality Score", formatted_value="95%")
    defaults.update(kw)
    return StoryLensMetric(**defaults)  # type: ignore[arg-type]


def _make_facts(**kw) -> StoryLensFacts:
    defaults = dict(
        schema_version="1.0",
        feature_id="data_overview",
        surface="data_overview",
        source_module="data_quality_toolkit.application.explanation",
        deterministic_summary="Quality score is 95% with 0 issues.",
        metrics=(_make_metric(),),
        evidence_items=("score=0.9500", "rows=1000"),
        limitations=("Score is completeness-weighted.",),
        safety_notes=(),
        recommended_action_context="Review flagged issues.",
        forbidden_claims=(),
        formatting_rules=(),
        source_timestamps=(),
        deterministic_fallback=_FALLBACK,
    )
    defaults.update(kw)
    return StoryLensFacts(**defaults)  # type: ignore[arg-type]


class TestStoryLensMetric:
    def test_metric_is_frozen(self) -> None:
        m = _make_metric()
        with pytest.raises((AttributeError, TypeError)):
            m.key = "other"  # type: ignore[misc]

    def test_metric_preserves_formatted_value(self) -> None:
        m = StoryLensMetric(key="psi", label="PSI", formatted_value="0.2800")
        assert m.formatted_value == "0.2800"

    def test_metric_raw_value_optional(self) -> None:
        m = StoryLensMetric(key="psi", label="PSI", formatted_value="0.2800")
        assert m.raw_value is None

    def test_metric_raw_value_stored(self) -> None:
        m = StoryLensMetric(key="psi", label="PSI", formatted_value="0.2800", raw_value=0.28)
        assert m.raw_value == 0.28

    def test_metric_unit_optional(self) -> None:
        m = _make_metric()
        assert m.unit is None

    def test_metric_unit_stored(self) -> None:
        m = StoryLensMetric(key="score", label="Score", formatted_value="95%", unit="percent")
        assert m.unit == "percent"


class TestStoryLensFacts:
    def test_facts_is_frozen(self) -> None:
        facts = _make_facts()
        with pytest.raises((AttributeError, TypeError)):
            facts.feature_id = "other"  # type: ignore[misc]

    def test_facts_metrics_is_tuple(self) -> None:
        facts = _make_facts()
        assert isinstance(facts.metrics, tuple)

    def test_facts_evidence_items_is_tuple(self) -> None:
        facts = _make_facts()
        assert isinstance(facts.evidence_items, tuple)

    def test_facts_limitations_is_tuple(self) -> None:
        facts = _make_facts()
        assert isinstance(facts.limitations, tuple)

    def test_facts_safety_notes_is_tuple(self) -> None:
        facts = _make_facts()
        assert isinstance(facts.safety_notes, tuple)

    def test_facts_forbidden_claims_is_tuple(self) -> None:
        facts = _make_facts()
        assert isinstance(facts.forbidden_claims, tuple)

    def test_facts_formatting_rules_is_tuple(self) -> None:
        facts = _make_facts()
        assert isinstance(facts.formatting_rules, tuple)

    def test_facts_source_timestamps_is_tuple(self) -> None:
        facts = _make_facts()
        assert isinstance(facts.source_timestamps, tuple)

    def test_deterministic_fallback_is_explanation(self) -> None:
        facts = _make_facts()
        assert isinstance(facts.deterministic_fallback, Explanation)

    def test_deterministic_fallback_required(self) -> None:
        with pytest.raises(TypeError):
            StoryLensFacts(
                schema_version="1.0",
                feature_id="data_overview",
                surface="data_overview",
                source_module="test",
                deterministic_summary="summary",
                metrics=(),
                evidence_items=(),
                limitations=(),
                safety_notes=(),
                recommended_action_context="",
                forbidden_claims=(),
                formatting_rules=(),
                source_timestamps=(),
                # missing deterministic_fallback
            )  # type: ignore[call-arg]

    def test_facts_equality_for_same_values(self) -> None:
        f1 = _make_facts()
        f2 = _make_facts()
        assert f1 == f2

    def test_no_dataframe_field(self) -> None:
        fields = {f.name for f in StoryLensFacts.__dataclass_fields__.values()}
        assert "dataframe" not in fields
        assert "df" not in fields
        assert "rows_data" not in fields
