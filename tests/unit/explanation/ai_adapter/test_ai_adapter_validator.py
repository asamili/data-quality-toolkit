"""Unit tests for StoryLens AI adapter output grounding validator."""

from __future__ import annotations

import pytest

from data_quality_toolkit.application.explanation.ai_adapter.facts import (
    StoryLensFacts,
    StoryLensMetric,
)
from data_quality_toolkit.application.explanation.ai_adapter.validator import (
    ValidationResult,
    validate_output,
)
from data_quality_toolkit.application.explanation.models import Explanation

_DRIFT_SAFETY_PHRASE = "Drift is a distribution change, not a defect or a cause."


def _make_fallback(severity="ok") -> Explanation:
    return Explanation(
        title="Quality score: 95% (good)",
        summary="Quality score is 95% with 0 issues.",
        evidence=("score=0.9500", "rows=1000"),
        why_it_matters="Score is the trust signal.",
        recommended_action="Review issues.",
        limitations="Completeness-weighted only.",
        severity=severity,
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
        limitations=("Completeness-weighted only.",),
        safety_notes=(),
        recommended_action_context="",
        forbidden_claims=(),
        formatting_rules=(),
        source_timestamps=(),
        deterministic_fallback=_make_fallback(),
    )
    defaults.update(kw)
    return StoryLensFacts(**defaults)  # type: ignore[arg-type]


class TestValidationResult:
    def test_result_is_frozen(self) -> None:
        r = ValidationResult(ok=True, rejected_reasons=())
        with pytest.raises((AttributeError, TypeError)):
            r.ok = False  # type: ignore[misc]

    def test_ok_result(self) -> None:
        r = ValidationResult(ok=True, rejected_reasons=())
        assert r.ok is True
        assert r.rejected_reasons == ()


class TestRejectsEmptyOutput:
    def test_empty_string(self) -> None:
        result = validate_output("", _make_facts())
        assert result.ok is False
        assert "empty_output" in result.rejected_reasons

    def test_whitespace_only(self) -> None:
        result = validate_output("   \n  ", _make_facts())
        assert result.ok is False
        assert "empty_output" in result.rejected_reasons


class TestRejectsTooLong:
    def test_rejects_output_over_2000_chars(self) -> None:
        long_text = "a" * 2001
        result = validate_output(long_text, _make_facts())
        assert result.ok is False
        assert any("output_too_long" in r for r in result.rejected_reasons)


class TestRejectsScientificNotationNumbers:
    def test_rejects_sci_notation_lowercase_e(self) -> None:
        facts = _make_facts(metrics=(), evidence_items=())
        output = "The p-value is 5.2e-4, which is highly significant."
        result = validate_output(output, facts)
        assert result.ok is False
        assert any("invented_numbers" in r for r in result.rejected_reasons)

    def test_rejects_sci_notation_upper_e_exponent(self) -> None:
        facts = _make_facts(metrics=(), evidence_items=())
        output = "Total count is approximately 1.23E+5 records."
        result = validate_output(output, facts)
        assert result.ok is False
        assert any("invented_numbers" in r for r in result.rejected_reasons)

    def test_rejects_integer_sci_notation(self) -> None:
        facts = _make_facts(metrics=(), evidence_items=())
        output = "The dataset has 1e6 rows estimated."
        result = validate_output(output, facts)
        assert result.ok is False
        assert any("invented_numbers" in r for r in result.rejected_reasons)

    def test_allows_sci_notation_present_in_facts(self) -> None:
        metric = StoryLensMetric(key="pval", label="P-value", formatted_value="5.2e-4")
        facts = _make_facts(metrics=(metric,), evidence_items=())
        output = "The p-value is 5.2e-4 which was provided by DQT."
        result = validate_output(output, facts)
        assert result.ok is True


class TestRejectsInventedNumbers:
    def test_invented_number_not_in_facts(self) -> None:
        facts = _make_facts(
            metrics=(StoryLensMetric(key="score", label="Score", formatted_value="95%"),),
            evidence_items=("score=0.9500", "rows=1000"),
        )
        output = "Quality score is 85% which is concerning."
        result = validate_output(output, facts)
        assert result.ok is False
        assert any("invented_numbers" in r for r in result.rejected_reasons)

    def test_numbers_from_facts_are_allowed(self) -> None:
        facts = _make_facts(
            metrics=(StoryLensMetric(key="score", label="Score", formatted_value="95%"),),
            evidence_items=("rows=1000",),
        )
        output = "Quality score is 95% with 1000 rows analyzed."
        result = validate_output(output, facts)
        assert "invented_numbers:85" not in str(result.rejected_reasons)

    def test_no_numbers_in_output_passes(self) -> None:
        output = "Data quality metrics indicate the dataset is within acceptable ranges."
        result = validate_output(output, _make_facts())
        assert result.ok is True


class TestRejectsDriftCausality:
    @pytest.mark.parametrize(
        "phrase",
        ["caused by", "because of", "due to", "root cause", "responsible for"],
    )
    def test_rejects_causality_phrase(self, phrase: str) -> None:
        output = f"The drift was {phrase} a schema change."
        result = validate_output(output, _make_facts())
        assert result.ok is False
        assert any("causality_phrase" in r for r in result.rejected_reasons)


class TestDriftLimitationPhrase:
    def test_requires_drift_limitation_for_drift_feature(self) -> None:
        facts = _make_facts(feature_id="drift_explorer")
        output = "Drift was detected on column age."
        result = validate_output(output, facts)
        assert result.ok is False
        assert any("missing_drift_limitation" in r for r in result.rejected_reasons)

    def test_requires_drift_limitation_when_in_safety_notes(self) -> None:
        facts = _make_facts(
            feature_id="data_overview",
            safety_notes=(_DRIFT_SAFETY_PHRASE,),
        )
        output = "Some drift was observed but not caused by anything."
        result = validate_output(output, facts)
        assert result.ok is False
        assert any("missing_drift_limitation" in r for r in result.rejected_reasons)

    def test_accepts_drift_output_with_safety_phrase(self) -> None:
        facts = _make_facts(feature_id="drift_explorer", evidence_items=())
        output = (
            f"Statistical drift was detected. "
            f"{_DRIFT_SAFETY_PHRASE} "
            "Review distribution charts for details."
        )
        result = validate_output(output, facts)
        assert "missing_drift_limitation" not in str(result.rejected_reasons)

    def test_non_drift_feature_no_limitation_required(self) -> None:
        facts = _make_facts(feature_id="data_overview", safety_notes=())
        output = "Data quality is acceptable. Review the flagged issues."
        result = validate_output(output, facts)
        assert "missing_drift_limitation" not in str(result.rejected_reasons)


class TestRejectsPathLeakage:
    def test_rejects_windows_path(self) -> None:
        output = r"Model loaded from C:\Users\models\smollm."
        result = validate_output(output, _make_facts())
        assert result.ok is False
        assert any("path_leakage" in r for r in result.rejected_reasons)

    def test_rejects_unix_path(self) -> None:
        output = "Model loaded from /home/user/models/smollm."
        result = validate_output(output, _make_facts())
        assert result.ok is False
        assert any("path_leakage" in r for r in result.rejected_reasons)


class TestRejectsEnvVarLeakage:
    def test_rejects_env_var_name(self) -> None:
        output = "Set DQT_STORYLENS_AI_ENABLED to enable this feature."
        result = validate_output(output, _make_facts())
        assert result.ok is False
        assert any("env_var_leakage" in r for r in result.rejected_reasons)


class TestRejectsModelIdLeakage:
    def test_rejects_model_id(self) -> None:
        output = "This analysis uses HuggingFaceTB/SmolLM2-135M-Instruct."
        result = validate_output(output, _make_facts())
        assert result.ok is False
        assert any("model_id_leakage" in r for r in result.rejected_reasons)


class TestRejectsRevisionHashLeakage:
    def test_rejects_full_revision_hash(self) -> None:
        output = "Model revision 12fd25f77366fa6b3b4b768ec3050bf629380bac was used."
        result = validate_output(output, _make_facts())
        assert result.ok is False
        assert any("revision_hash_leakage" in r for r in result.rejected_reasons)

    def test_rejects_short_revision_hash(self) -> None:
        output = "Using model at revision 12fd25f for this analysis."
        result = validate_output(output, _make_facts())
        assert result.ok is False
        assert any("revision_hash_leakage" in r for r in result.rejected_reasons)


class TestRejectsForbiddenClaims:
    def test_rejects_forbidden_claim_from_facts(self) -> None:
        facts = _make_facts(forbidden_claims=("data is completely broken",))
        output = "The analysis shows data is completely broken."
        result = validate_output(output, facts)
        assert result.ok is False
        assert any("forbidden_claim" in r for r in result.rejected_reasons)


class TestRejectsSeverityContradiction:
    def test_breach_severity_with_no_issue_language(self) -> None:
        facts = _make_facts(
            evidence_items=(),
            metrics=(),
            deterministic_fallback=_make_fallback(severity="breach"),
        )
        output = "Everything looks good and there is no issue with the data."
        result = validate_output(output, facts)
        assert result.ok is False
        assert "severity_contradiction" in result.rejected_reasons

    def test_warn_severity_with_no_issue_language(self) -> None:
        facts = _make_facts(
            evidence_items=(),
            metrics=(),
            deterministic_fallback=_make_fallback(severity="warn"),
        )
        output = "Everything looks good and there is no issue with the data."
        result = validate_output(output, facts)
        assert result.ok is False
        assert "severity_contradiction" in result.rejected_reasons

    def test_warn_severity_with_looks_good_language(self) -> None:
        facts = _make_facts(
            evidence_items=(),
            metrics=(),
            deterministic_fallback=_make_fallback(severity="warn"),
        )
        output = "The dataset looks good overall with minor gaps noted."
        result = validate_output(output, facts)
        assert result.ok is False
        assert "severity_contradiction" in result.rejected_reasons

    def test_ok_severity_with_critical_issue_language(self) -> None:
        facts = _make_facts(
            evidence_items=(),
            metrics=(),
            deterministic_fallback=_make_fallback(severity="ok"),
        )
        output = "This is a critical issue that must be resolved immediately."
        result = validate_output(output, facts)
        assert result.ok is False
        assert "severity_contradiction" in result.rejected_reasons

    def test_info_severity_with_critical_issue_language(self) -> None:
        facts = _make_facts(
            evidence_items=(),
            metrics=(),
            deterministic_fallback=_make_fallback(severity="info"),
        )
        output = "This is a critical issue that must be resolved immediately."
        result = validate_output(output, facts)
        assert result.ok is False
        assert "severity_contradiction" in result.rejected_reasons

    def test_info_severity_not_over_restricted_for_normal_language(self) -> None:
        facts = _make_facts(
            evidence_items=(),
            metrics=(),
            deterministic_fallback=_make_fallback(severity="info"),
        )
        output = "The column appears constant. Review if this is expected for this dataset."
        result = validate_output(output, facts)
        assert result.ok is True

    def test_warn_severity_not_restricted_for_acknowledged_concern(self) -> None:
        facts = _make_facts(
            evidence_items=(),
            metrics=(),
            deterministic_fallback=_make_fallback(severity="warn"),
        )
        output = "Missing values were detected. Consider reviewing upstream data sources."
        result = validate_output(output, facts)
        assert result.ok is True


class TestMultipleSimultaneousViolations:
    def test_multiple_reasons_when_invented_number_and_causality(self) -> None:
        facts = _make_facts(evidence_items=(), metrics=())
        output = "Quality dropped to 42% due to upstream changes."
        result = validate_output(output, facts)
        assert result.ok is False
        reasons_str = " ".join(result.rejected_reasons)
        assert "invented_numbers" in reasons_str
        assert "causality_phrase" in reasons_str

    def test_rejected_reasons_is_tuple_with_multiple_entries(self) -> None:
        facts = _make_facts(evidence_items=(), metrics=())
        output = "Quality dropped to 42% due to upstream changes."
        result = validate_output(output, facts)
        assert isinstance(result.rejected_reasons, tuple)
        assert len(result.rejected_reasons) >= 2


class TestAcceptsValidOutput:
    def test_accepts_short_grounded_non_drift_output(self) -> None:
        facts = _make_facts(feature_id="data_overview", safety_notes=(), evidence_items=())
        output = "Data quality metrics indicate the dataset is within acceptable ranges."
        result = validate_output(output, facts)
        assert result.ok is True
        assert result.rejected_reasons == ()

    def test_accepts_grounded_drift_output_with_safety_phrase(self) -> None:
        facts = _make_facts(
            feature_id="drift_explorer",
            evidence_items=(),
            metrics=(),
            deterministic_fallback=_make_fallback(severity="warn"),
        )
        output = (
            "Statistical changes were observed in the dataset. "
            f"{_DRIFT_SAFETY_PHRASE} "
            "Review distribution charts for more details."
        )
        result = validate_output(output, facts)
        assert result.ok is True
