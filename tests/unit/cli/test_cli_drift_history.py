# tests/unit/cli/test_cli_drift_history.py
"""Unit tests for the `dqt drift-history` command."""

from __future__ import annotations

import json

import data_quality_toolkit.adapters.cli.main as cli

_RECORDS = [
    {
        "schema_version": "1",
        "kind": "drift_history_record",
        "run_id": "abc123",
        "created_at": "2026-01-01T00:00:00+00:00",
        "baseline_path": "baseline.csv",
        "current_path": "current.csv",
        "status": "ok",
        "alpha": 0.05,
        "columns_tested": 2,
        "columns_skipped": 0,
        "columns_drifted": 1,
        "drift_detected": True,
        "report_path": None,
    }
]


def _patch(monkeypatch, records=_RECORDS):
    calls: list[tuple] = []

    def fake_read(history_path: str):
        calls.append((history_path,))
        return records

    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "read_drift_history", fake_read)
    return calls


def test_drift_history_stdout_is_json_list(monkeypatch, capsys):
    _patch(monkeypatch)
    rc = cli.main(["drift-history", "read", "drift_history.jsonl"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["run_id"] == "abc123"


def test_drift_history_records_summary_on_stderr(monkeypatch, capsys):
    _patch(monkeypatch)
    cli.main(["drift-history", "read", "drift_history.jsonl"])
    err = capsys.readouterr().err
    assert "Drift history read" in err
    assert "drift_history.jsonl" in err
    assert "Records: 1" in err


def test_drift_history_missing_file_returns_0_empty_list(monkeypatch, capsys):
    _patch(monkeypatch, records=[])
    rc = cli.main(["drift-history", "read", "missing.jsonl"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed == []


def test_drift_history_empty_file_returns_0(monkeypatch, capsys):
    _patch(monkeypatch, records=[])
    rc = cli.main(["drift-history", "read", "empty.jsonl"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_drift_history_no_json_suppresses_stdout(monkeypatch, capsys):
    _patch(monkeypatch)
    rc = cli.main(["--no-json", "drift-history", "read", "drift_history.jsonl"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert "Drift history read" in captured.err


def test_drift_history_path_forwarded(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(["drift-history", "read", "path/to/hist.jsonl"])
    assert calls == [("path/to/hist.jsonl",)]
