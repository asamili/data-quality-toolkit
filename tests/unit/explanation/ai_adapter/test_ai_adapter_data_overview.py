"""Unit tests for the Data Overview StoryLensFacts builder."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from data_quality_toolkit.application.explanation.ai_adapter.data_overview import (
    build_data_overview_facts,
)
from data_quality_toolkit.application.explanation.ai_adapter.facts import StoryLensFacts
from data_quality_toolkit.application.explanation.ai_adapter.prompts import build_prompt
from data_quality_toolkit.application.explanation.ai_adapter.validator import validate_output
from data_quality_toolkit.application.explanation.models import Explanation
from data_quality_toolkit.application.explanation.narrator import explain_quality_score

_FALLBACK = Explanation(
    title="Quality score: 95% (good)",
    summary="Profiled 1000 rows × 5 columns. Quality score is 95% with 0 issue(s) flagged.",
    evidence=("score=0.9500", "rows=1000", "columns=5", "issues_total=0"),
    why_it_matters=(
        "The quality score is the primary trust signal before data reaches "
        "a report or dashboard."
    ),
    recommended_action=(
        "Review the flagged issues. If score meets the publish threshold, "
        "proceed to EDA or export."
    ),
    limitations=(
        "Score is completeness-weighted across all columns. "
        "It does not check business correctness, referential integrity, "
        "or values within expected ranges."
    ),
    severity="ok",
)

# Issue fixtures — deliberately include forbidden fields to prove they are excluded.
_MISSING_ISSUE: dict[str, object] = {
    "type": "missing",
    "column": "email",
    "pct": 0.4567,
    "severity": "critical",
    "category": "Completeness",
    "message": "Column 'email' has 45.7% missing values",  # must NOT appear in facts
}

_CONSTANT_ISSUE: dict[str, object] = {
    "type": "constant_column",
    "column": "status",
    "pct": None,
    "severity": "medium",
    "category": "Completeness",
    "message": "Column 'status' has only one distinct non-null value",  # must NOT appear
}

_ACCEPTED_VALUES_ISSUE: dict[str, object] = {
    "type": "accepted_values_violation",
    "column": "country",
    "violation_count": 9999,  # unique value to prove exclusion
    "examples": ["INVALID_CELL", "UNKNOWN_CELL", "N/A_CELL"],  # cell values — must NOT appear
    "severity": "high",
    "category": "Schema",
    "message": "Column 'country' has 9999 value(s) outside accepted set",  # must NOT appear
}

_UNIQUENESS_ISSUE: dict[str, object] = {
    "type": "uniqueness_violation",
    "column": "order_id",
    "duplicate_count": 7777,  # unique value to prove exclusion
    "severity": "medium",
    "category": "Schema",
    "message": "Column 'order_id' has 7777 duplicate non-null value(s)",  # must NOT appear
}


def _make_facts(**kw: object) -> StoryLensFacts:
    defaults: dict[str, object] = dict(
        score=0.95,
        rows=1000,
        columns=5,
        issues=[],
        deterministic_fallback=_FALLBACK,
    )
    defaults.update(kw)
    return build_data_overview_facts(**defaults)  # type: ignore[arg-type]


class TestBuildDataOverviewFactsBasic:
    def test_returns_story_lens_facts(self) -> None:
        assert isinstance(_make_facts(), StoryLensFacts)

    def test_feature_id_is_data_overview(self) -> None:
        assert _make_facts().feature_id == "data_overview"

    def test_surface_is_data_overview(self) -> None:
        assert _make_facts().surface == "data_overview"

    def test_deterministic_fallback_preserved(self) -> None:
        result = _make_facts()
        assert result.deterministic_fallback is _FALLBACK

    def test_same_inputs_produce_equal_facts(self) -> None:
        f1 = _make_facts()
        f2 = _make_facts()
        assert f1 == f2


class TestScoreFormatting:
    def test_score_formatted_as_percent(self) -> None:
        result = _make_facts(score=0.95)
        metric = next(m for m in result.metrics if m.key == "quality_score")
        assert metric.formatted_value == "95%"

    def test_score_zero_formatted(self) -> None:
        result = _make_facts(score=0.0)
        metric = next(m for m in result.metrics if m.key == "quality_score")
        assert metric.formatted_value == "0%"

    def test_score_raw_value_stored(self) -> None:
        result = _make_facts(score=0.9500)
        metric = next(m for m in result.metrics if m.key == "quality_score")
        assert metric.raw_value == 0.9500

    def test_score_in_evidence_from_fallback(self) -> None:
        result = _make_facts()
        assert any("score=0.9500" in e for e in result.evidence_items)


class TestDimensionMetrics:
    def test_rows_metric_formatted_as_integer_string(self) -> None:
        result = _make_facts(rows=1000)
        metric = next(m for m in result.metrics if m.key == "rows")
        assert metric.formatted_value == "1000"

    def test_columns_metric_formatted_as_integer_string(self) -> None:
        result = _make_facts(columns=5)
        metric = next(m for m in result.metrics if m.key == "columns")
        assert metric.formatted_value == "5"

    def test_issues_total_metric_formatted_as_integer_string(self) -> None:
        result = _make_facts(issues=[_MISSING_ISSUE, _CONSTANT_ISSUE])
        metric = next(m for m in result.metrics if m.key == "issues_total")
        assert metric.formatted_value == "2"


class TestMemoryMb:
    def test_memory_mb_omitted_produces_valid_facts(self) -> None:
        result = _make_facts()
        assert isinstance(result, StoryLensFacts)
        assert not any(m.key == "memory_mb" for m in result.metrics)

    def test_memory_mb_included_formatted_to_two_decimals(self) -> None:
        result = _make_facts(memory_mb=1.5)
        metric = next((m for m in result.metrics if m.key == "memory_mb"), None)
        assert metric is not None
        assert metric.formatted_value == "1.50 MB"

    def test_memory_mb_large_value_rounds_correctly(self) -> None:
        result = _make_facts(memory_mb=123.456)
        metric = next(m for m in result.metrics if m.key == "memory_mb")
        assert metric.formatted_value == "123.46 MB"


class TestIssueSummaries:
    def test_issue_summaries_limited_to_max(self) -> None:
        result = _make_facts(issues=[_MISSING_ISSUE] * 10, max_issue_summaries=3)
        issue_ev = [e for e in result.evidence_items if e.startswith("issue:")]
        assert len(issue_ev) == 3

    def test_default_max_is_three(self) -> None:
        result = _make_facts(issues=[_MISSING_ISSUE] * 10)
        issue_ev = [e for e in result.evidence_items if e.startswith("issue:")]
        assert len(issue_ev) == 3

    def test_max_zero_produces_no_issue_evidence(self) -> None:
        result = _make_facts(issues=[_MISSING_ISSUE, _CONSTANT_ISSUE], max_issue_summaries=0)
        issue_ev = [e for e in result.evidence_items if e.startswith("issue:")]
        assert issue_ev == []

    def test_negative_max_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            _make_facts(max_issue_summaries=-1)

    def test_missing_issue_pct_in_evidence(self) -> None:
        result = _make_facts(issues=[_MISSING_ISSUE])
        issue_ev = [e for e in result.evidence_items if e.startswith("issue:missing")]
        assert len(issue_ev) == 1
        assert "null_pct=0.4567" in issue_ev[0]

    def test_non_numeric_pct_excluded_issue_still_present(self) -> None:
        bad = {**_MISSING_ISSUE, "pct": "not_a_number"}
        result = _make_facts(issues=[bad])
        issue_ev = [e for e in result.evidence_items if e.startswith("issue:missing")]
        assert issue_ev  # issue present
        assert all("null_pct" not in e for e in issue_ev)

    def test_bool_pct_excluded_issue_still_present(self) -> None:
        bool_issue = {**_MISSING_ISSUE, "pct": True}
        result = _make_facts(issues=[bool_issue])
        issue_ev = [e for e in result.evidence_items if e.startswith("issue:missing")]
        assert issue_ev  # issue present
        assert all("null_pct" not in e for e in issue_ev)

    def test_constant_column_issue_in_evidence(self) -> None:
        result = _make_facts(issues=[_CONSTANT_ISSUE])
        issue_ev = [e for e in result.evidence_items if e.startswith("issue:constant_column")]
        assert len(issue_ev) == 1
        assert "status" in issue_ev[0]


class TestForbiddenInputsExcluded:
    def test_issue_message_not_in_evidence(self) -> None:
        result = _make_facts(issues=[_MISSING_ISSUE])
        msg = "Column 'email' has 45.7% missing values"
        for e in result.evidence_items:
            assert msg not in e

    def test_issue_message_not_in_prompt(self) -> None:
        result = _make_facts(issues=[_MISSING_ISSUE])
        assert "has 45.7% missing values" not in build_prompt(result)

    def test_issue_examples_not_in_evidence(self) -> None:
        result = _make_facts(issues=[_ACCEPTED_VALUES_ISSUE])
        all_ev = " ".join(result.evidence_items)
        assert "INVALID_CELL" not in all_ev
        assert "UNKNOWN_CELL" not in all_ev
        assert "N/A_CELL" not in all_ev

    def test_issue_examples_not_in_prompt(self) -> None:
        result = _make_facts(issues=[_ACCEPTED_VALUES_ISSUE])
        prompt = build_prompt(result)
        assert "INVALID_CELL" not in prompt
        assert "UNKNOWN_CELL" not in prompt

    def test_violation_count_not_in_evidence(self) -> None:
        result = _make_facts(issues=[_ACCEPTED_VALUES_ISSUE])
        for e in result.evidence_items:
            assert "violation_count" not in e
            assert "9999" not in e

    def test_duplicate_count_not_in_evidence(self) -> None:
        result = _make_facts(issues=[_UNIQUENESS_ISSUE])
        for e in result.evidence_items:
            assert "duplicate_count" not in e
            assert "7777" not in e

    def test_raw_path_not_in_prompt(self, tmp_path: Path) -> None:
        result = _make_facts()
        prompt = build_prompt(result)
        assert str(tmp_path) not in prompt
        assert ":\\" not in prompt
        assert "/home/" not in prompt

    def test_no_env_var_in_prompt(self) -> None:
        result = _make_facts()
        prompt = build_prompt(result)
        assert "DQT_STORYLENS_AI_ENABLED" not in prompt
        assert "DQT_STORYLENS_MODEL_DIR" not in prompt

    def test_no_model_id_in_prompt(self) -> None:
        result = _make_facts()
        prompt = build_prompt(result)
        assert "HuggingFaceTB" not in prompt
        assert "SmolLM2" not in prompt


class TestPromptAndValidatorCompatibility:
    def test_build_prompt_succeeds(self) -> None:
        result = _make_facts()
        prompt = build_prompt(result)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_validator_rejects_invented_metric(self) -> None:
        fallback = explain_quality_score(score=0.95, rows=100, columns=3, issues_total=0)
        result = build_data_overview_facts(
            score=0.95,
            rows=100,
            columns=3,
            issues=[],
            deterministic_fallback=fallback,
        )
        invented = "The dataset quality score is 87% which is acceptable."
        assert not validate_output(invented, result).ok

    def test_validator_accepts_grounded_output(self) -> None:
        fallback = explain_quality_score(score=0.95, rows=100, columns=3, issues_total=0)
        result = build_data_overview_facts(
            score=0.95,
            rows=100,
            columns=3,
            issues=[],
            deterministic_fallback=fallback,
        )
        grounded = "Data quality metrics indicate the dataset is within acceptable ranges."
        assert validate_output(grounded, result).ok


class TestImportIsolation:
    _FORBIDDEN = [
        "streamlit",
        "pandas",
        "transformers",
        "torch",
        "huggingface_hub",
        "tokenizers",
        "safetensors",
        "sentence_transformers",
    ]

    def test_importing_builder_does_not_load_forbidden_modules(self) -> None:
        before = set(sys.modules)
        import data_quality_toolkit.application.explanation.ai_adapter.data_overview  # noqa: F401

        loaded = [m for m in self._FORBIDDEN if m in sys.modules and m not in before]
        assert not loaded, f"Forbidden modules loaded at builder import: {loaded}"


class TestBoundaryPreservation:
    def test_api_does_not_export_build_data_overview_facts(self) -> None:
        import data_quality_toolkit.api as api

        assert not hasattr(api, "build_data_overview_facts")

    def test_parent_explanation_does_not_export_build_data_overview_facts(self) -> None:
        import data_quality_toolkit.application.explanation as pkg

        assert not hasattr(pkg, "build_data_overview_facts")
