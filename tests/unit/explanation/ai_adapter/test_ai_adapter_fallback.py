"""Unit tests for StoryLens AI adapter deterministic fallback wrapper."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from data_quality_toolkit.application.explanation.ai_adapter.facts import (
    StoryLensFacts,
    StoryLensMetric,
)
from data_quality_toolkit.application.explanation.ai_adapter.fallback import (
    _merge_ai_summary,
    get_fallback,
    try_explain,
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
        metrics=(StoryLensMetric(key="score", label="Score", formatted_value="95%"),),
        evidence_items=("score=0.9500", "rows=1000"),
        limitations=("Completeness-weighted.",),
        safety_notes=(),
        recommended_action_context="",
        forbidden_claims=(),
        formatting_rules=(),
        source_timestamps=(),
        deterministic_fallback=_FALLBACK,
    )
    defaults.update(kw)
    return StoryLensFacts(**defaults)  # type: ignore[arg-type]


def _enable_env(tmp_path: Path) -> dict[str, str]:
    return {"DQT_STORYLENS_AI_ENABLED": "1", "DQT_STORYLENS_MODEL_DIR": str(tmp_path)}


def _fake_ai_module(return_value: str = "AI text.", side_effect=None) -> MagicMock:
    fake = MagicMock()
    if side_effect is not None:
        fake.generate_narrative.side_effect = side_effect
    else:
        fake.generate_narrative.return_value = return_value
    return fake


class TestGetFallback:
    def test_returns_deterministic_fallback(self) -> None:
        facts = _make_facts()
        assert get_fallback(facts) is facts.deterministic_fallback

    def test_never_raises(self) -> None:
        facts = _make_facts()
        result = get_fallback(facts)
        assert isinstance(result, Explanation)


class TestTryExplainFlagOff:
    def test_default_off_returns_fallback(self) -> None:
        facts = _make_facts()
        result = try_explain(facts, env={})
        assert result == facts.deterministic_fallback

    def test_generate_narrative_not_called_when_flag_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_ai = _fake_ai_module()
        monkeypatch.setitem(
            sys.modules,
            "data_quality_toolkit.application.explanation.ai_narrator",
            fake_ai,
        )
        facts = _make_facts()
        try_explain(facts, env={})
        fake_ai.generate_narrative.assert_not_called()

    def test_returns_explanation_type(self) -> None:
        facts = _make_facts()
        result = try_explain(facts, env={})
        assert isinstance(result, Explanation)


class TestTryExplainMissingModelDir:
    def test_missing_model_dir_returns_fallback(self) -> None:
        facts = _make_facts()
        result = try_explain(facts, env={"DQT_STORYLENS_AI_ENABLED": "1"})
        assert result == facts.deterministic_fallback

    def test_nonexistent_model_dir_returns_fallback(self) -> None:
        facts = _make_facts()
        result = try_explain(
            facts,
            env={
                "DQT_STORYLENS_AI_ENABLED": "1",
                "DQT_STORYLENS_MODEL_DIR": "/nonexistent/abc123",
            },
        )
        assert result == facts.deterministic_fallback


class TestTryExplainMissingDeps:
    def test_missing_optional_dep_returns_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from data_quality_toolkit.application.explanation.ai_narrator import (
            LocalAIUnavailableError,
        )

        fake_ai = _fake_ai_module(side_effect=LocalAIUnavailableError("missing deps"))
        monkeypatch.setitem(
            sys.modules,
            "data_quality_toolkit.application.explanation.ai_narrator",
            fake_ai,
        )
        facts = _make_facts()
        result = try_explain(facts, env=_enable_env(tmp_path))
        assert result == facts.deterministic_fallback

    def test_model_unavailable_returns_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from data_quality_toolkit.application.explanation.ai_narrator import (
            LocalAIUnavailableError,
        )

        fake_ai = _fake_ai_module(side_effect=LocalAIUnavailableError("local model files absent"))
        monkeypatch.setitem(
            sys.modules,
            "data_quality_toolkit.application.explanation.ai_narrator",
            fake_ai,
        )
        facts = _make_facts()
        result = try_explain(facts, env=_enable_env(tmp_path))
        assert result == facts.deterministic_fallback


class TestTryExplainValidatorRejects:
    def test_invalid_ai_output_returns_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        invented = "Quality score is 42% which is very bad."
        fake_ai = _fake_ai_module(return_value=invented)
        monkeypatch.setitem(
            sys.modules,
            "data_quality_toolkit.application.explanation.ai_narrator",
            fake_ai,
        )
        facts = _make_facts()
        result = try_explain(facts, env=_enable_env(tmp_path))
        assert result == facts.deterministic_fallback

    def test_empty_ai_output_returns_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake_ai = _fake_ai_module(return_value="")
        monkeypatch.setitem(
            sys.modules,
            "data_quality_toolkit.application.explanation.ai_narrator",
            fake_ai,
        )
        facts = _make_facts()
        result = try_explain(facts, env=_enable_env(tmp_path))
        assert result == facts.deterministic_fallback


class TestTryExplainValidOutput:
    def test_valid_output_returns_explanation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        valid = "Data quality metrics indicate the dataset is within acceptable ranges."
        fake_ai = _fake_ai_module(return_value=valid)
        monkeypatch.setitem(
            sys.modules,
            "data_quality_toolkit.application.explanation.ai_narrator",
            fake_ai,
        )
        facts = _make_facts(evidence_items=(), metrics=())
        result = try_explain(facts, env=_enable_env(tmp_path))
        assert isinstance(result, Explanation)

    def test_valid_output_preserves_fallback_title(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        valid = "Data quality metrics indicate the dataset is within acceptable ranges."
        fake_ai = _fake_ai_module(return_value=valid)
        monkeypatch.setitem(
            sys.modules,
            "data_quality_toolkit.application.explanation.ai_narrator",
            fake_ai,
        )
        facts = _make_facts(evidence_items=(), metrics=())
        result = try_explain(facts, env=_enable_env(tmp_path))
        assert result.title == facts.deterministic_fallback.title

    def test_valid_output_preserves_fallback_evidence(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        valid = "Data quality metrics indicate the dataset is within acceptable ranges."
        fake_ai = _fake_ai_module(return_value=valid)
        monkeypatch.setitem(
            sys.modules,
            "data_quality_toolkit.application.explanation.ai_narrator",
            fake_ai,
        )
        facts = _make_facts(evidence_items=(), metrics=())
        result = try_explain(facts, env=_enable_env(tmp_path))
        assert result.evidence == facts.deterministic_fallback.evidence

    def test_valid_output_preserves_fallback_limitations(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        valid = "Data quality metrics indicate the dataset is within acceptable ranges."
        fake_ai = _fake_ai_module(return_value=valid)
        monkeypatch.setitem(
            sys.modules,
            "data_quality_toolkit.application.explanation.ai_narrator",
            fake_ai,
        )
        facts = _make_facts(evidence_items=(), metrics=())
        result = try_explain(facts, env=_enable_env(tmp_path))
        assert result.limitations == facts.deterministic_fallback.limitations

    def test_valid_output_preserves_fallback_severity(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        valid = "Data quality metrics indicate the dataset is within acceptable ranges."
        fake_ai = _fake_ai_module(return_value=valid)
        monkeypatch.setitem(
            sys.modules,
            "data_quality_toolkit.application.explanation.ai_narrator",
            fake_ai,
        )
        facts = _make_facts(evidence_items=(), metrics=())
        result = try_explain(facts, env=_enable_env(tmp_path))
        assert result.severity == facts.deterministic_fallback.severity


class TestTryExplainNeverRaises:
    def test_does_not_raise_on_generic_exception(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake_ai = _fake_ai_module(side_effect=RuntimeError("unexpected"))
        monkeypatch.setitem(
            sys.modules,
            "data_quality_toolkit.application.explanation.ai_narrator",
            fake_ai,
        )
        facts = _make_facts()
        result = try_explain(facts, env=_enable_env(tmp_path))
        assert isinstance(result, Explanation)

    def test_no_real_inference_in_tests(self) -> None:
        facts = _make_facts()
        result = try_explain(facts, env={})
        assert result == facts.deterministic_fallback


class TestMergeAiSummary:
    def test_truncates_long_output_to_400_chars(self) -> None:
        long_text = "A" * 401
        result = _merge_ai_summary(long_text, _FALLBACK)
        assert len(result.summary) == 400

    def test_strips_leading_whitespace_before_truncating(self) -> None:
        padded = "  " + "B" * 401
        result = _merge_ai_summary(padded, _FALLBACK)
        assert len(result.summary) == 400
        assert result.summary.startswith("B")

    def test_short_output_not_truncated(self) -> None:
        short_text = "Short summary."
        result = _merge_ai_summary(short_text, _FALLBACK)
        assert result.summary == short_text.strip()

    def test_preserves_title_from_base(self) -> None:
        result = _merge_ai_summary("AI text.", _FALLBACK)
        assert result.title == _FALLBACK.title

    def test_preserves_evidence_from_base(self) -> None:
        result = _merge_ai_summary("AI text.", _FALLBACK)
        assert result.evidence == _FALLBACK.evidence

    def test_preserves_why_it_matters_from_base(self) -> None:
        result = _merge_ai_summary("AI text.", _FALLBACK)
        assert result.why_it_matters == _FALLBACK.why_it_matters

    def test_preserves_recommended_action_from_base(self) -> None:
        result = _merge_ai_summary("AI text.", _FALLBACK)
        assert result.recommended_action == _FALLBACK.recommended_action

    def test_preserves_limitations_from_base(self) -> None:
        result = _merge_ai_summary("AI text.", _FALLBACK)
        assert result.limitations == _FALLBACK.limitations

    def test_preserves_severity_from_base(self) -> None:
        result = _merge_ai_summary("AI text.", _FALLBACK)
        assert result.severity == _FALLBACK.severity

    def test_uses_ai_text_as_summary(self) -> None:
        result = _merge_ai_summary("AI generated summary.", _FALLBACK)
        assert result.summary == "AI generated summary."
