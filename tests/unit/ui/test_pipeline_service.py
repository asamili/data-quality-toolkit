"""Tests for the Pipeline Runner dry-run plan helpers (pure, streamlit-free)."""

from __future__ import annotations

import inspect
import json

from data_quality_toolkit.adapters.ui.services import pipeline
from data_quality_toolkit.adapters.ui.services.pipeline import (
    CANONICAL_STEP_IDS,
    STATUS_BLOCKED,
    STATUS_DEFERRED,
    STATUS_READY,
    STATUS_SKIPPED,
    build_cli_equivalent,
    build_pipeline_plan,
    default_pipeline_steps,
    normalize_step_selection,
    pipeline_plan_to_json_payload,
    summarize_pipeline_evidence,
    validate_pipeline_readiness,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext

_REQUIRED_STEP_FIELDS = {
    "step_id",
    "label",
    "category",
    "description",
    "input_summary",
    "output_summary",
    "evidence_items",
    "related_page",
    "cli_hint",
}

_CTX = DatasetContext(
    source_path="C:\\Users\\example_user\\data\\sales.csv",
    display_name="sales.csv",
    size_bytes=2048,
    modified_ns=1,
)
_CTX_LARGE = DatasetContext(
    source_path="/home/example_user/data/big.csv",
    display_name="big.csv",
    size_bytes=999_999,
    modified_ns=2,
    large_file_mode=True,
)


# ── structural / determinism ─────────────────────────────────────────────────


def test_service_stays_streamlit_free() -> None:
    assert "import streamlit" not in inspect.getsource(pipeline)


def test_default_steps_order_and_fields_are_stable() -> None:
    steps = default_pipeline_steps()
    assert [s["step_id"] for s in steps] == list(CANONICAL_STEP_IDS)
    for step in steps:
        assert _REQUIRED_STEP_FIELDS <= set(step)
        assert isinstance(step["evidence_items"], list)


def test_default_steps_return_fresh_copies() -> None:
    first = default_pipeline_steps()
    first[0]["evidence_items"].append("mutated")
    second = default_pipeline_steps()
    assert "mutated" not in second[0]["evidence_items"]


# ── normalize_step_selection ─────────────────────────────────────────────────


def test_normalize_none_defaults_to_all() -> None:
    assert normalize_step_selection(None) == list(CANONICAL_STEP_IDS)


def test_normalize_empty_defaults_to_all() -> None:
    assert normalize_step_selection([]) == list(CANONICAL_STEP_IDS)


def test_normalize_dedupes_orders_and_drops_unknown() -> None:
    out = normalize_step_selection(["manifest", "quality", "quality", "bogus"])
    assert out == ["quality", "manifest"]


# ── readiness ────────────────────────────────────────────────────────────────


def test_readiness_blocks_without_context() -> None:
    result = validate_pipeline_readiness(None, None)
    assert result["ready"] is False
    assert result["blockers"]


def test_readiness_ready_with_context() -> None:
    result = validate_pipeline_readiness(_CTX, ["quality"])
    assert result["ready"] is True
    assert result["blockers"] == []


def test_readiness_warns_on_large_file_mode() -> None:
    result = validate_pipeline_readiness(_CTX_LARGE, ["quality"])
    assert any("large-file" in w.lower() for w in result["warnings"])


# ── build_pipeline_plan ──────────────────────────────────────────────────────


def test_plan_blocks_every_enabled_step_without_context() -> None:
    plan = build_pipeline_plan(None, None, "run-1")
    assert plan["dataset_ready"] is False
    assert all(s["status"] == STATUS_BLOCKED for s in plan["steps"] if s["enabled"])


def test_plan_marks_ready_deferred_and_skipped() -> None:
    plan = build_pipeline_plan(_CTX, ["quality", "drift"], "run-1")
    by_id = {s["step_id"]: s for s in plan["steps"]}
    assert by_id["quality"]["status"] == STATUS_READY
    assert by_id["drift"]["status"] == STATUS_DEFERRED
    assert by_id["load"]["status"] == STATUS_SKIPPED
    assert by_id["load"]["enabled"] is False


def test_plan_load_evidence_is_concrete_and_path_free() -> None:
    plan = build_pipeline_plan(_CTX, ["load"], "run-1")
    load = next(s for s in plan["steps"] if s["step_id"] == "load")
    joined = " ".join(load["evidence_items"])
    assert "sales.csv" in joined
    assert "C:\\Users" not in joined


def test_plan_never_leaks_absolute_paths() -> None:
    plan = build_pipeline_plan(_CTX, None, "run-1")
    blob = json.dumps(pipeline_plan_to_json_payload(plan))
    assert "C:\\Users" not in blob
    assert "/home/" not in blob


def test_plan_payload_is_json_serializable() -> None:
    plan = build_pipeline_plan(_CTX, None, "run-1")
    payload = pipeline_plan_to_json_payload(plan)
    # Must not raise.
    json.dumps(payload)
    assert payload["kind"] == "pipeline_dry_run_plan"
    assert payload["generated_step_count"] == len(CANONICAL_STEP_IDS)


# ── cli equivalence ──────────────────────────────────────────────────────────


def test_cli_equivalent_is_deterministic_and_path_free() -> None:
    cli = build_cli_equivalent("my run", ["quality", "manifest"])
    assert cli == build_cli_equivalent("my run", ["manifest", "quality"])
    assert "my-run" in cli
    assert "--assess" in cli and "--manifest" in cli
    assert "<sessions-root>" in cli
    assert ":\\" not in cli and "/home/" not in cli


def test_cli_equivalent_placeholder_for_empty_run_id() -> None:
    assert "<run-id>" in build_cli_equivalent("", None)


# ── evidence summary ─────────────────────────────────────────────────────────


def test_summarize_counts_match_plan() -> None:
    plan = build_pipeline_plan(_CTX, ["quality", "drift"], "run-1")
    summary = summarize_pipeline_evidence(plan)
    assert summary["total_steps"] == len(CANONICAL_STEP_IDS)
    assert summary["selected_steps"] == 2
    assert summary["ready_steps"] == 1
    assert summary["deferred_steps"] == 1
    assert summary["evidence_items_total"] > 0
