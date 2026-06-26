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


# ---------------------------------------------------------------------------
# drift-history trend --fail-on-drift-rate
# ---------------------------------------------------------------------------

_TREND_SUMMARY_LOW = {
    "total_runs": 5,
    "drifted_runs": 1,
    "non_drifted_runs": 4,
    "drift_rate": 0.2,
    "latest_run_id": "r5",
    "latest_created_at": "2026-01-01T00:00:00+00:00",
    "latest_drift_detected": False,
    "columns_tested_total": 20,
    "columns_tested_average": 4.0,
    "columns_drifted_total": 2,
    "columns_drifted_average": 0.4,
}

_TREND_SUMMARY_HIGH = dict(_TREND_SUMMARY_LOW, drift_rate=0.5, drifted_runs=3)


def _patch_trend(monkeypatch, summary=_TREND_SUMMARY_LOW):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "summarize_drift_trends_sqlite", lambda *a, **kw: summary)


def test_trend_flag_absent_exits_0(monkeypatch, capsys):
    _patch_trend(monkeypatch)
    rc = cli.main(["drift-history", "trend", "--db", "monitoring.db"])
    assert rc == 0


def test_trend_below_threshold_exits_0(monkeypatch, capsys):
    _patch_trend(monkeypatch)
    rc = cli.main(
        ["drift-history", "trend", "--db", "monitoring.db", "--fail-on-drift-rate", "0.3"]
    )
    assert rc == 0


def test_trend_equal_threshold_exits_0(monkeypatch, capsys):
    _patch_trend(monkeypatch)
    rc = cli.main(
        ["drift-history", "trend", "--db", "monitoring.db", "--fail-on-drift-rate", "0.2"]
    )
    assert rc == 0


def test_trend_above_threshold_exits_2(monkeypatch, capsys):
    _patch_trend(monkeypatch, _TREND_SUMMARY_HIGH)
    rc = cli.main(
        ["drift-history", "trend", "--db", "monitoring.db", "--fail-on-drift-rate", "0.3"]
    )
    assert rc == 2


def test_trend_breach_message_on_stderr(monkeypatch, capsys):
    _patch_trend(monkeypatch, _TREND_SUMMARY_HIGH)
    cli.main(["drift-history", "trend", "--db", "monitoring.db", "--fail-on-drift-rate", "0.3"])
    err = capsys.readouterr().err
    assert "Drift rate threshold breached" in err
    assert "threshold=0.3" in err


def test_trend_invalid_threshold_exits_1(monkeypatch, capsys):
    _patch_trend(monkeypatch)
    rc = cli.main(
        ["drift-history", "trend", "--db", "monitoring.db", "--fail-on-drift-rate", "1.5"]
    )
    assert rc == 1


def test_trend_empty_summary_no_breach_exits_0(monkeypatch, capsys):
    empty = dict(_TREND_SUMMARY_LOW, drift_rate=0.0, total_runs=0, drifted_runs=0)
    _patch_trend(monkeypatch, empty)
    rc = cli.main(
        ["drift-history", "trend", "--db", "monitoring.db", "--fail-on-drift-rate", "0.3"]
    )
    assert rc == 0


# ---------------------------------------------------------------------------
# drift-history columns --fail-on-psi
# ---------------------------------------------------------------------------

_COLUMNS_LOW = [
    {
        "column_name": "amount",
        "kind": "numeric",
        "test": "ks",
        "drift_detected": True,
        "psi": 0.1,
        "js_distance": None,
        "wasserstein": None,
        "p_value": 0.01,
        "statistic": 0.4,
        "reference_n": 100,
        "current_n": 100,
        "status": "tested",
        "skip_reason": None,
    }
]

_COLUMNS_HIGH = [dict(_COLUMNS_LOW[0], psi=0.35)]
_COLUMNS_NONE_PSI = [dict(_COLUMNS_LOW[0], psi=None)]


def _patch_columns(monkeypatch, rows=_COLUMNS_LOW):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "read_drift_columns_sqlite", lambda *a, **kw: rows)


def test_columns_flag_absent_exits_0(monkeypatch, capsys):
    _patch_columns(monkeypatch)
    rc = cli.main(["drift-history", "columns", "--db", "monitoring.db"])
    assert rc == 0


def test_columns_below_threshold_exits_0(monkeypatch, capsys):
    _patch_columns(monkeypatch)
    rc = cli.main(["drift-history", "columns", "--db", "monitoring.db", "--fail-on-psi", "0.2"])
    assert rc == 0


def test_columns_equal_threshold_exits_0(monkeypatch, capsys):
    _patch_columns(monkeypatch)
    rc = cli.main(["drift-history", "columns", "--db", "monitoring.db", "--fail-on-psi", "0.1"])
    assert rc == 0


def test_columns_above_threshold_exits_2(monkeypatch, capsys):
    _patch_columns(monkeypatch, _COLUMNS_HIGH)
    rc = cli.main(["drift-history", "columns", "--db", "monitoring.db", "--fail-on-psi", "0.2"])
    assert rc == 2


def test_columns_breach_message_on_stderr(monkeypatch, capsys):
    _patch_columns(monkeypatch, _COLUMNS_HIGH)
    cli.main(["drift-history", "columns", "--db", "monitoring.db", "--fail-on-psi", "0.2"])
    err = capsys.readouterr().err
    assert "PSI threshold breached" in err
    assert "offenders=1" in err
    assert "threshold=0.2" in err


def test_columns_invalid_threshold_exits_1(monkeypatch, capsys):
    _patch_columns(monkeypatch)
    rc = cli.main(["drift-history", "columns", "--db", "monitoring.db", "--fail-on-psi", "-0.1"])
    assert rc == 1


def test_columns_none_psi_skipped_exits_0(monkeypatch, capsys):
    _patch_columns(monkeypatch, _COLUMNS_NONE_PSI)
    rc = cli.main(["drift-history", "columns", "--db", "monitoring.db", "--fail-on-psi", "0.2"])
    assert rc == 0


def test_columns_empty_rows_no_breach_exits_0(monkeypatch, capsys):
    _patch_columns(monkeypatch, [])
    rc = cli.main(["drift-history", "columns", "--db", "monitoring.db", "--fail-on-psi", "0.2"])
    assert rc == 0
