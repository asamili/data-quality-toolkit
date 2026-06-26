"""Unit tests for StoryLens AI adapter deterministic prompt builder."""

from __future__ import annotations

from data_quality_toolkit.application.explanation.ai_adapter.facts import (
    StoryLensFacts,
    StoryLensMetric,
)
from data_quality_toolkit.application.explanation.ai_adapter.prompts import (
    PROMPT_TEMPLATE_VERSION,
    build_prompt,
)
from data_quality_toolkit.application.explanation.models import Explanation

_DRIFT_SAFETY_PHRASE = "Drift is a distribution change, not a defect or a cause."

_FALLBACK = Explanation(
    title="Quality score: 95% (good)",
    summary="Quality score is 95% with 0 issues flagged.",
    evidence=("score=0.9500", "rows=1000"),
    why_it_matters="Quality score is the primary trust signal.",
    recommended_action="Proceed to export.",
    limitations="Score is completeness-weighted.",
    severity="ok",
)


def _make_facts(**kw) -> StoryLensFacts:
    defaults = dict(
        schema_version="1.0",
        feature_id="data_overview",
        surface="data_overview",
        source_module="test",
        deterministic_summary="Quality score is 95% with 0 issues.",
        metrics=(StoryLensMetric(key="score", label="Quality Score", formatted_value="95%"),),
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


class TestBuildPrompt:
    def test_same_facts_produce_identical_prompt(self) -> None:
        facts = _make_facts()
        p1 = build_prompt(facts)
        p2 = build_prompt(facts)
        assert p1 == p2

    def test_template_version_in_prompt(self) -> None:
        facts = _make_facts()
        p = build_prompt(facts)
        assert PROMPT_TEMPLATE_VERSION in p

    def test_feature_id_in_prompt(self) -> None:
        facts = _make_facts()
        p = build_prompt(facts)
        assert "data_overview" in p

    def test_deterministic_summary_in_prompt(self) -> None:
        facts = _make_facts()
        p = build_prompt(facts)
        assert facts.deterministic_summary in p

    def test_metric_formatted_value_in_prompt(self) -> None:
        facts = _make_facts()
        p = build_prompt(facts)
        assert "95%" in p

    def test_evidence_items_in_prompt(self) -> None:
        facts = _make_facts()
        p = build_prompt(facts)
        assert "score=0.9500" in p

    def test_no_new_metrics_instruction_present(self) -> None:
        facts = _make_facts()
        p = build_prompt(facts)
        assert "Do not calculate new metrics" in p

    def test_no_causality_instruction_present(self) -> None:
        facts = _make_facts()
        p = build_prompt(facts)
        assert "Do not infer causes" in p

    def test_no_raw_float_rendering(self) -> None:
        metric = StoryLensMetric(key="score", label="Score", formatted_value="95%", raw_value=0.95)
        facts = _make_facts(metrics=(metric,))
        p = build_prompt(facts)
        assert "0.95" not in p or "score=0.9500" in p

    def test_no_model_id_in_prompt(self) -> None:
        facts = _make_facts()
        p = build_prompt(facts)
        assert "HuggingFaceTB" not in p
        assert "SmolLM2" not in p

    def test_no_env_var_names_in_prompt(self) -> None:
        facts = _make_facts()
        p = build_prompt(facts)
        assert "DQT_STORYLENS_AI_ENABLED" not in p
        assert "DQT_STORYLENS_MODEL_DIR" not in p

    def test_no_dataframe_repr_in_prompt(self) -> None:
        facts = _make_facts()
        p = build_prompt(facts)
        assert "DataFrame" not in p
        assert "   0   " not in p

    def test_metrics_sorted_by_key(self) -> None:
        m_z = StoryLensMetric(key="z_metric", label="Z", formatted_value="10")
        m_a = StoryLensMetric(key="a_metric", label="A", formatted_value="20")
        facts = _make_facts(metrics=(m_z, m_a))
        p = build_prompt(facts)
        pos_a = p.index("a_metric")
        pos_z = p.index("z_metric")
        assert pos_a < pos_z

    def test_drift_safety_phrase_included_for_drift_surface(self) -> None:
        facts = _make_facts(feature_id="drift_explorer")
        p = build_prompt(facts)
        assert _DRIFT_SAFETY_PHRASE in p

    def test_drift_safety_phrase_included_when_in_safety_notes(self) -> None:
        facts = _make_facts(
            feature_id="data_overview",
            safety_notes=(_DRIFT_SAFETY_PHRASE,),
        )
        p = build_prompt(facts)
        assert _DRIFT_SAFETY_PHRASE in p

    def test_no_drift_reminder_for_non_drift_without_note(self) -> None:
        facts = _make_facts(feature_id="data_overview", safety_notes=())
        p = build_prompt(facts)
        assert "Do not attribute drift to any cause." not in p

    def test_forbidden_claims_listed_in_prompt(self) -> None:
        facts = _make_facts(forbidden_claims=("data is completely broken",))
        p = build_prompt(facts)
        assert "data is completely broken" in p

    def test_limitations_in_prompt(self) -> None:
        facts = _make_facts(limitations=("Score is completeness-weighted.",))
        p = build_prompt(facts)
        assert "Score is completeness-weighted." in p

    def test_recommended_action_context_in_prompt(self) -> None:
        facts = _make_facts(recommended_action_context="Fix nulls first.")
        p = build_prompt(facts)
        assert "Fix nulls first." in p

    def test_surface_field_in_prompt(self) -> None:
        facts = _make_facts(surface="drift_explorer")
        p = build_prompt(facts)
        assert "Surface: drift_explorer" in p

    def test_task_section_in_prompt(self) -> None:
        facts = _make_facts()
        p = build_prompt(facts)
        assert "## Task" in p

    def test_uncertainty_instruction_in_prompt(self) -> None:
        facts = _make_facts()
        p = build_prompt(facts)
        assert "State uncertainty and limitations explicitly" in p

    def test_empty_metrics_section_not_rendered(self) -> None:
        facts = _make_facts(metrics=())
        p = build_prompt(facts)
        assert "## Metrics" not in p
