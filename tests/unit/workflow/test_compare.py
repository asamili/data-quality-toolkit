# tests/unit/workflow/test_compare.py
"""Targeted tests for the compare-last-two-runs helper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_quality_toolkit.workflow.compare import (
    _dict_delta,
    _load_history,
    _safe_delta,
    compare_last_two_runs,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RUN_A = {
    "run_id": "run-aaa",
    "dataset_id": "sha1:abc",
    "ts": "2026-04-01T10:00:00Z",
    "score": 0.80,
    "issues_total": 5,
    "duration_secs": 1.2,
}

RUN_B = {
    "run_id": "run-bbb",
    "dataset_id": "sha1:abc",
    "ts": "2026-04-02T10:00:00Z",
    "score": 0.90,
    "issues_total": 2,
    "duration_secs": 1.0,
}

OTHER_DATASET = {
    "run_id": "run-zzz",
    "dataset_id": "sha1:zzz",
    "ts": "2026-04-02T11:00:00Z",
    "score": 0.50,
    "issues_total": 10,
    "duration_secs": 2.0,
}


def _write_history(tmp_path: Path, records: list[dict]) -> Path:
    p = tmp_path / "quality_history.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return p


# ---------------------------------------------------------------------------
# _load_history
# ---------------------------------------------------------------------------


def test_load_history_missing_file(tmp_path: Path) -> None:
    records = _load_history(tmp_path / "nonexistent.jsonl")
    assert records == []


def test_load_history_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "h.jsonl"
    p.write_text("", encoding="utf-8")
    assert _load_history(p) == []


def test_load_history_skips_malformed_lines(tmp_path: Path) -> None:
    p = tmp_path / "h.jsonl"
    p.write_text('{"ok": 1}\nnot-json\n{"ok": 2}\n', encoding="utf-8")
    records = _load_history(p)
    assert len(records) == 2
    assert records[0] == {"ok": 1}
    assert records[1] == {"ok": 2}


# ---------------------------------------------------------------------------
# _safe_delta
# ---------------------------------------------------------------------------


def test_safe_delta_positive() -> None:
    assert _safe_delta(0.80, 0.90) == pytest.approx(0.10, abs=1e-5)


def test_safe_delta_negative() -> None:
    assert _safe_delta(5, 2) == pytest.approx(-3.0)


def test_safe_delta_none_input() -> None:
    assert _safe_delta(None, 1.0) is None
    assert _safe_delta(1.0, None) is None


# ---------------------------------------------------------------------------
# compare_last_two_runs — error cases
# ---------------------------------------------------------------------------


def test_compare_no_history_file(tmp_path: Path) -> None:
    result = compare_last_two_runs("sha1:abc", tmp_path / "quality_history.jsonl")
    assert result["error"] == "not_enough_runs"
    assert result["runs_found"] == 0
    assert "same --outdir" in result["message"]
    assert "export-star" in result["message"]


def test_compare_only_one_run(tmp_path: Path) -> None:
    p = _write_history(tmp_path, [RUN_A])
    result = compare_last_two_runs("sha1:abc", p)
    assert result["error"] == "not_enough_runs"
    assert result["runs_found"] == 1
    assert "same --outdir" in result["message"]
    assert "retry compare" in result["message"]


def test_compare_wrong_dataset_id(tmp_path: Path) -> None:
    p = _write_history(tmp_path, [RUN_A, RUN_B])
    result = compare_last_two_runs("sha1:unknown", p)
    assert result["error"] == "not_enough_runs"


# ---------------------------------------------------------------------------
# compare_last_two_runs — success cases
# ---------------------------------------------------------------------------


def test_compare_two_runs_returns_deltas(tmp_path: Path) -> None:
    p = _write_history(tmp_path, [RUN_A, RUN_B])
    result = compare_last_two_runs("sha1:abc", p)

    assert "error" not in result
    assert result["dataset_id"] == "sha1:abc"
    assert result["previous_run_id"] == "run-aaa"
    assert result["current_run_id"] == "run-bbb"
    assert result["previous_score"] == pytest.approx(0.80)
    assert result["current_score"] == pytest.approx(0.90)
    assert result["score_delta"] == pytest.approx(0.10, abs=1e-5)
    assert result["previous_issues_total"] == 5
    assert result["current_issues_total"] == 2
    assert result["issues_delta"] == pytest.approx(-3.0)
    assert result["current_ts"] == "2026-04-02T10:00:00Z"
    assert result["previous_ts"] == "2026-04-01T10:00:00Z"


def test_compare_filters_by_dataset_id(tmp_path: Path) -> None:
    """Records from other datasets must not pollute the comparison."""
    p = _write_history(tmp_path, [RUN_A, OTHER_DATASET, RUN_B])
    result = compare_last_two_runs("sha1:abc", p)
    assert "error" not in result
    assert result["previous_run_id"] == "run-aaa"
    assert result["current_run_id"] == "run-bbb"


def test_compare_three_runs_uses_latest_two(tmp_path: Path) -> None:
    run_c = {**RUN_B, "run_id": "run-ccc", "ts": "2026-04-03T10:00:00Z", "score": 0.95}
    p = _write_history(tmp_path, [RUN_A, RUN_B, run_c])
    result = compare_last_two_runs("sha1:abc", p)
    assert result["previous_run_id"] == "run-bbb"
    assert result["current_run_id"] == "run-ccc"


def test_compare_missing_duration_secs(tmp_path: Path) -> None:
    """duration_secs may be absent from old records — delta should be None."""
    run_no_dur = {k: v for k, v in RUN_A.items() if k != "duration_secs"}
    p = _write_history(tmp_path, [run_no_dur, RUN_B])
    result = compare_last_two_runs("sha1:abc", p)
    assert "error" not in result
    assert result["duration_delta"] is None


# ---------------------------------------------------------------------------
# _dict_delta
# ---------------------------------------------------------------------------

RUN_A_WITH_BREAKDOWN = {
    **RUN_A,
    "issues_by_severity": {"high": 2, "medium": 1},
    "issues_by_category": {"Completeness": 2, "Schema": 1},
}

RUN_B_WITH_BREAKDOWN = {
    **RUN_B,
    "issues_by_severity": {"high": 1, "medium": 3, "low": 1},
    "issues_by_category": {"Completeness": 4, "Schema": 1},
}


def test_dict_delta_per_key_deltas() -> None:
    a = {"high": 2, "medium": 1}
    b = {"high": 1, "medium": 3, "low": 1}
    result = _dict_delta(a, b)
    assert result == {"high": -1, "low": 1, "medium": 2}


def test_dict_delta_key_only_in_prev() -> None:
    result = _dict_delta({"high": 3}, {"medium": 1})
    assert result == {"high": -3, "medium": 1}


def test_dict_delta_none_input_returns_none() -> None:
    assert _dict_delta(None, {"high": 1}) is None
    assert _dict_delta({"high": 1}, None) is None
    assert _dict_delta(None, None) is None


def test_dict_delta_non_dict_input_returns_none() -> None:
    assert _dict_delta("not-a-dict", {"high": 1}) is None
    assert _dict_delta({"high": 1}, 42) is None


# ---------------------------------------------------------------------------
# compare_last_two_runs — breakdown fields
# ---------------------------------------------------------------------------


def test_compare_returns_breakdown_deltas(tmp_path: Path) -> None:
    p = _write_history(tmp_path, [RUN_A_WITH_BREAKDOWN, RUN_B_WITH_BREAKDOWN])
    result = compare_last_two_runs("sha1:abc", p)

    assert "error" not in result
    assert result["issues_by_severity_delta"] == {"high": -1, "low": 1, "medium": 2}
    assert result["issues_by_category_delta"] == {"Completeness": 2, "Schema": 0}
    assert result["previous_issues_by_severity"] == {"high": 2, "medium": 1}
    assert result["current_issues_by_severity"] == {"high": 1, "medium": 3, "low": 1}


def test_compare_old_records_produce_none_breakdown_deltas(tmp_path: Path) -> None:
    """Old-style records without breakdown fields must not crash; deltas are None."""
    p = _write_history(tmp_path, [RUN_A, RUN_B])
    result = compare_last_two_runs("sha1:abc", p)

    assert "error" not in result
    assert result["issues_by_severity_delta"] is None
    assert result["issues_by_category_delta"] is None
    assert result["previous_issues_by_severity"] is None
    assert result["current_issues_by_severity"] is None


def test_compare_mixed_old_new_records_produce_none_delta(tmp_path: Path) -> None:
    """One run with breakdown, one without — delta must be None, no crash."""
    p = _write_history(tmp_path, [RUN_A, RUN_B_WITH_BREAKDOWN])
    result = compare_last_two_runs("sha1:abc", p)

    assert "error" not in result
    assert result["issues_by_severity_delta"] is None
    assert result["issues_by_category_delta"] is None
