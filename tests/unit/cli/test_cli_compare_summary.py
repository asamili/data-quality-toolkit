# tests/unit/cli/test_cli_compare_summary.py
"""Unit tests for cmd_compare stderr summary and stdout JSON output."""

from __future__ import annotations

import argparse
import json

import data_quality_toolkit.adapters.cli.main as cli

_DATASET_ID = "sha1:abc123"

_ERROR_RESULT = {
    "error": "not_enough_runs",
    "message": (
        "Found 1 run(s) for dataset 'sha1:abc123'. "
        "Need at least 2 completed export-star runs for the same dataset "
        "in the same --outdir. "
        "Run 'dqt export-star <csv> --outdir <dir>' at least twice, "
        "then retry compare."
    ),
    "dataset_id": _DATASET_ID,
    "runs_found": 1,
}

_SUCCESS_RESULT = {
    "dataset_id": _DATASET_ID,
    "current_run_id": "run-bbb",
    "previous_run_id": "run-aaa",
    "current_score": 0.90,
    "previous_score": 0.80,
    "score_delta": 0.10,
    "current_issues_total": 2,
    "previous_issues_total": 5,
    "issues_delta": -3.0,
    "previous_issues_by_severity": {"high": 2, "medium": 1},
    "current_issues_by_severity": {"high": 1, "medium": 3},
    "issues_by_severity_delta": {"high": -1, "medium": 2},
    "previous_issues_by_category": {"Completeness": 3, "Schema": 2},
    "current_issues_by_category": {"Completeness": 1, "Schema": 1},
    "issues_by_category_delta": {"Completeness": -2, "Schema": -1},
    "current_duration_secs": 1.0,
    "previous_duration_secs": 1.2,
    "duration_delta": -0.2,
    "current_ts": "2026-04-02T10:00:00Z",
    "previous_ts": "2026-04-01T10:00:00Z",
}


def _ns(**kwargs):
    d = dict(csv="data.csv", outdir="dist")
    d.update(kwargs)
    return argparse.Namespace(**d)


def _patch(monkeypatch, compare_result):
    monkeypatch.setattr(
        "data_quality_toolkit.workflow.compare.compare_last_two_runs",
        lambda *a, **k: compare_result,
    )
    monkeypatch.setattr(
        "data_quality_toolkit.loaders.file.csv_loader._dataset_id_from_file",
        lambda *a, **k: _DATASET_ID,
    )


# ---------------------------------------------------------------------------
# Error path: not_enough_runs
# ---------------------------------------------------------------------------


def test_compare_not_enough_runs_returns_1(monkeypatch, capsys):
    _patch(monkeypatch, _ERROR_RESULT)
    rc = cli.cmd_compare(_ns())
    assert rc == 1


def test_compare_not_enough_runs_stderr_message(monkeypatch, capsys):
    _patch(monkeypatch, _ERROR_RESULT)
    cli.cmd_compare(_ns())
    err = capsys.readouterr().err
    assert "not enough history" in err.lower() or "Compare" in err


def test_compare_not_enough_runs_stdout_is_json(monkeypatch, capsys):
    _patch(monkeypatch, _ERROR_RESULT)
    cli.cmd_compare(_ns())
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["error"] == "not_enough_runs"
    assert parsed["runs_found"] == 1


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_compare_success_returns_0(monkeypatch, capsys):
    _patch(monkeypatch, _SUCCESS_RESULT)
    rc = cli.cmd_compare(_ns())
    assert rc == 0


def test_compare_success_stderr_header(monkeypatch, capsys):
    _patch(monkeypatch, _SUCCESS_RESULT)
    cli.cmd_compare(_ns())
    err = capsys.readouterr().err
    assert "Compare" in err


def test_compare_success_stderr_score_delta(monkeypatch, capsys):
    _patch(monkeypatch, _SUCCESS_RESULT)
    cli.cmd_compare(_ns())
    err = capsys.readouterr().err
    assert "0.800" in err
    assert "0.900" in err
    assert "up" in err


def test_compare_success_stderr_issues_line(monkeypatch, capsys):
    _patch(monkeypatch, _SUCCESS_RESULT)
    cli.cmd_compare(_ns())
    err = capsys.readouterr().err
    assert "5" in err
    assert "2" in err


# ---------------------------------------------------------------------------
# Machine output: stdout JSON integrity
# ---------------------------------------------------------------------------


def test_compare_success_stdout_is_valid_json(monkeypatch, capsys):
    _patch(monkeypatch, _SUCCESS_RESULT)
    cli.cmd_compare(_ns())
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["dataset_id"] == _DATASET_ID


def test_compare_success_stdout_preserves_breakdown_fields(monkeypatch, capsys):
    """Breakdown fields added by DQT-FIX-005 must pass through stdout JSON intact."""
    _patch(monkeypatch, _SUCCESS_RESULT)
    cli.cmd_compare(_ns())
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["issues_by_severity_delta"] == {"high": -1, "medium": 2}
    assert parsed["issues_by_category_delta"] == {"Completeness": -2, "Schema": -1}
    assert parsed["previous_issues_by_severity"] == {"high": 2, "medium": 1}
    assert parsed["current_issues_by_severity"] == {"high": 1, "medium": 3}


def test_compare_success_stdout_preserves_score_and_run_ids(monkeypatch, capsys):
    _patch(monkeypatch, _SUCCESS_RESULT)
    cli.cmd_compare(_ns())
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["current_run_id"] == "run-bbb"
    assert parsed["previous_run_id"] == "run-aaa"
    assert parsed["score_delta"] == 0.10
    assert parsed["issues_delta"] == -3.0


# ---------------------------------------------------------------------------
# DQT-FIX-008: severity / category breakdown deltas in stderr
# ---------------------------------------------------------------------------

_SUCCESS_RESULT_MINIMAL = {
    "dataset_id": _DATASET_ID,
    "current_run_id": "run-bbb",
    "previous_run_id": "run-aaa",
    "current_score": 0.90,
    "previous_score": 0.80,
    "score_delta": 0.10,
    "current_issues_total": 2,
    "previous_issues_total": 5,
    "issues_delta": -3.0,
    "current_duration_secs": 1.0,
    "previous_duration_secs": 1.2,
    "duration_delta": -0.2,
    "current_ts": "2026-04-02T10:00:00Z",
    "previous_ts": "2026-04-01T10:00:00Z",
}


def test_compare_success_stderr_severity_delta(monkeypatch, capsys):
    _patch(monkeypatch, _SUCCESS_RESULT)
    cli.cmd_compare(_ns())
    err = capsys.readouterr().err
    assert "Severity delta:" in err
    assert "high" in err
    assert "-1" in err


def test_compare_success_stderr_category_delta(monkeypatch, capsys):
    _patch(monkeypatch, _SUCCESS_RESULT)
    cli.cmd_compare(_ns())
    err = capsys.readouterr().err
    assert "Category delta:" in err
    assert "Completeness" in err
    assert "-2" in err


def test_compare_missing_breakdown_no_crash(monkeypatch, capsys):
    _patch(monkeypatch, _SUCCESS_RESULT_MINIMAL)
    rc = cli.cmd_compare(_ns())
    captured = capsys.readouterr()
    assert rc == 0
    assert json.loads(captured.out)["dataset_id"] == _DATASET_ID
    assert "Severity delta:" not in captured.err
    assert "Category delta:" not in captured.err


def test_compare_new_stderr_does_not_pollute_stdout(monkeypatch, capsys):
    _patch(monkeypatch, _SUCCESS_RESULT)
    cli.cmd_compare(_ns())
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert "Severity delta:" not in captured.out
    assert "Category delta:" not in captured.out
    assert parsed["dataset_id"] == _DATASET_ID
