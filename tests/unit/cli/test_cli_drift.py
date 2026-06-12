# tests/unit/cli/test_cli_drift.py
"""Unit tests for the `dqt drift` command (cmd_drift, parser, validators)."""

from __future__ import annotations

import json

import pytest

import data_quality_toolkit.adapters.cli.main as cli

_NOTE = "p-values are uncorrected for multiple testing"

_OK_RESULT = {
    "status": "ok",
    "reason": None,
    "alpha": 0.05,
    "scipy_available": True,
    "reference_rows": 60,
    "current_rows": 80,
    "columns": [
        {
            "column": "x",
            "kind": "numeric",
            "test": "ks",
            "statistic": 0.42,
            "p_value": 0.001,
            "drift_detected": True,
            "reference_n": 60,
            "current_n": 80,
            "status": "tested",
            "skip_reason": None,
            "interpretation": "p=0.001 < alpha=0.05 -> distributions differ (drift detected)",
        },
        {
            "column": "category",
            "kind": "categorical",
            "test": "chi_square",
            "statistic": 1.23,
            "p_value": 0.8,
            "drift_detected": False,
            "reference_n": 60,
            "current_n": 80,
            "status": "tested",
            "skip_reason": None,
            "interpretation": "p=0.8 >= alpha=0.05 -> no significant drift",
        },
    ],
    "summary": {
        "columns_tested": 2,
        "columns_skipped": 1,
        "columns_drifted": 1,
        "drift_detected": True,
        "note": _NOTE,
    },
    "baseline_dataset_id": "sha1:base",
    "current_dataset_id": "sha1:curr",
}

_UNAVAILABLE_RESULT = {
    "status": "unavailable",
    "reason": (
        "scipy is not installed; install the stats extra: pip install data-quality-toolkit[stats]"
    ),
    "alpha": 0.05,
    "scipy_available": False,
    "reference_rows": 0,
    "current_rows": 0,
    "columns": [],
    "summary": {
        "columns_tested": 0,
        "columns_skipped": 0,
        "columns_drifted": 0,
        "drift_detected": False,
        "note": _NOTE,
    },
}


def _patch(monkeypatch, result=_OK_RESULT):
    """Patch logging setup and run_drift; return list capturing call args."""
    calls: list[tuple[tuple, dict]] = []

    def fake_run_drift(*a, **kw):
        calls.append((a, kw))
        return result

    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "run_drift", fake_run_drift)
    return calls


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_drift_success_returns_0(monkeypatch, capsys):
    _patch(monkeypatch)
    rc = cli.main(["drift", "baseline.csv", "current.csv"])
    assert rc == 0


def test_drift_success_stdout_is_valid_json(monkeypatch, capsys):
    _patch(monkeypatch)
    cli.main(["drift", "baseline.csv", "current.csv"])
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["status"] == "ok"
    assert parsed["summary"]["columns_drifted"] == 1
    assert parsed["baseline_dataset_id"] == "sha1:base"
    assert parsed["current_dataset_id"] == "sha1:curr"


def test_drift_success_stderr_summary(monkeypatch, capsys):
    _patch(monkeypatch)
    cli.main(["drift", "baseline.csv", "current.csv"])
    err = capsys.readouterr().err
    assert "Drift check complete" in err
    assert "baseline.csv vs current.csv" in err
    assert "60 (baseline) vs 80 (current)" in err
    assert "Columns tested: 2, skipped: 1" in err
    assert "Columns drifted: 1" in err
    assert _NOTE in err


def test_drift_drifted_column_line_on_stderr_only(monkeypatch, capsys):
    _patch(monkeypatch)
    cli.main(["drift", "baseline.csv", "current.csv"])
    captured = capsys.readouterr()
    assert "x: ks" in captured.err
    assert "drift detected" in captured.err
    # non-drifted column gets no detail line
    assert "category: chi_square" not in captured.err
    # stdout stays pure JSON
    json.loads(captured.out)


def test_drift_no_json_suppresses_stdout(monkeypatch, capsys):
    _patch(monkeypatch)
    rc = cli.main(["--no-json", "drift", "baseline.csv", "current.csv"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert "Drift check complete" in captured.err


# ---------------------------------------------------------------------------
# Option passthrough
# ---------------------------------------------------------------------------


def test_drift_options_passthrough(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(
        [
            "drift",
            "baseline.csv",
            "current.csv",
            "--alpha",
            "0.01",
            "--min-samples",
            "10",
            "--max-categories",
            "5",
            "--sep",
            ";",
            "--encoding",
            "latin-1",
            "--na-values",
            "NA, null",
            "--sample-size",
            "1000",
        ]
    )
    a, kw = calls[0]
    assert a == ("baseline.csv", "current.csv")
    assert kw == {
        "alpha": 0.01,
        "min_samples": 10,
        "max_categories": 5,
        "sep": ";",
        "encoding": "latin-1",
        "na_values": ["NA", "null"],
        "sample_size": 1000,
    }


def test_drift_omitted_options_not_forwarded(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(["drift", "baseline.csv", "current.csv"])
    a, kw = calls[0]
    assert a == ("baseline.csv", "current.csv")
    assert kw == {}  # API defaults stay authoritative


def test_drift_output_option_forwarded_as_output_path(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(["drift", "baseline.csv", "current.csv", "--output", "report.json"])
    _, kw = calls[0]
    assert kw == {"output_path": "report.json"}


def test_drift_output_report_line_on_stderr(monkeypatch, capsys):
    result = dict(_OK_RESULT, output_path="report.json")
    _patch(monkeypatch, result)
    cli.main(["drift", "baseline.csv", "current.csv", "--output", "report.json"])
    assert "Report written: report.json" in capsys.readouterr().err


def test_drift_no_output_option_no_report_line(monkeypatch, capsys):
    _patch(monkeypatch)
    cli.main(["drift", "baseline.csv", "current.csv"])
    assert "Report written" not in capsys.readouterr().err


def test_drift_output_with_fail_on_drift_still_exits_2(monkeypatch, capsys):
    result = dict(_OK_RESULT, output_path="report.json")
    _patch(monkeypatch, result)
    rc = cli.main(
        ["drift", "baseline.csv", "current.csv", "--output", "report.json", "--fail-on-drift"]
    )
    assert rc == 2
    assert "Report written: report.json" in capsys.readouterr().err


def test_drift_unavailable_output_report_line_on_stderr(monkeypatch, capsys):
    result = dict(_UNAVAILABLE_RESULT, output_path="report.json")
    _patch(monkeypatch, result)
    rc = cli.main(["drift", "baseline.csv", "current.csv", "--output", "report.json"])
    assert rc == 1
    assert "Report written: report.json" in capsys.readouterr().err


def test_drift_history_option_forwarded_as_history_path(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(["drift", "baseline.csv", "current.csv", "--history", "hist.jsonl"])
    _, kw = calls[0]
    assert kw == {"history_path": "hist.jsonl"}


def test_drift_history_line_on_stderr(monkeypatch, capsys):
    result = dict(_OK_RESULT, history_path="hist.jsonl")
    _patch(monkeypatch, result)
    cli.main(["drift", "baseline.csv", "current.csv", "--history", "hist.jsonl"])
    assert "History appended: hist.jsonl" in capsys.readouterr().err


def test_drift_no_history_option_no_history_line(monkeypatch, capsys):
    _patch(monkeypatch)
    cli.main(["drift", "baseline.csv", "current.csv"])
    assert "History appended" not in capsys.readouterr().err


def test_drift_history_stdout_json_contains_history_path(monkeypatch, capsys):
    result = dict(_OK_RESULT, history_path="hist.jsonl")
    _patch(monkeypatch, result)
    cli.main(["drift", "baseline.csv", "current.csv", "--history", "hist.jsonl"])
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["history_path"] == "hist.jsonl"


def test_drift_history_with_fail_on_drift_still_exits_2(monkeypatch, capsys):
    result = dict(_OK_RESULT, history_path="hist.jsonl")
    _patch(monkeypatch, result)
    rc = cli.main(
        ["drift", "baseline.csv", "current.csv", "--history", "hist.jsonl", "--fail-on-drift"]
    )
    assert rc == 2
    assert "History appended: hist.jsonl" in capsys.readouterr().err


def test_drift_unavailable_history_line_on_stderr(monkeypatch, capsys):
    result = dict(_UNAVAILABLE_RESULT, history_path="hist.jsonl")
    _patch(monkeypatch, result)
    rc = cli.main(["drift", "baseline.csv", "current.csv", "--history", "hist.jsonl"])
    assert rc == 1
    assert "History appended: hist.jsonl" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# scipy unavailable
# ---------------------------------------------------------------------------


def test_drift_unavailable_returns_1(monkeypatch, capsys):
    _patch(monkeypatch, _UNAVAILABLE_RESULT)
    rc = cli.main(["drift", "baseline.csv", "current.csv"])
    assert rc == 1


def test_drift_unavailable_stderr_has_install_hint(monkeypatch, capsys):
    _patch(monkeypatch, _UNAVAILABLE_RESULT)
    cli.main(["drift", "baseline.csv", "current.csv"])
    err = capsys.readouterr().err
    assert "unavailable" in err.lower()
    assert "data-quality-toolkit[stats]" in err


def test_drift_unavailable_stdout_json_preserved(monkeypatch, capsys):
    _patch(monkeypatch, _UNAVAILABLE_RESULT)
    cli.main(["drift", "baseline.csv", "current.csv"])
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["status"] == "unavailable"
    assert parsed["scipy_available"] is False


def test_drift_unavailable_no_json(monkeypatch, capsys):
    _patch(monkeypatch, _UNAVAILABLE_RESULT)
    rc = cli.main(["--no-json", "drift", "baseline.csv", "current.csv"])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""


# ---------------------------------------------------------------------------
# Parser and path validation
# ---------------------------------------------------------------------------


def test_drift_missing_positional_exits_2(monkeypatch, capsys):
    _patch(monkeypatch)
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["drift", "baseline.csv"])
    assert excinfo.value.code == 2


@pytest.mark.parametrize(
    "argv",
    [
        ["drift", "   ", "current.csv"],
        ["drift", "baseline.csv", "   "],
    ],
)
def test_drift_blank_path_returns_2(monkeypatch, argv, capsys):
    _patch(monkeypatch)
    rc = cli.main(argv)
    assert rc == 2
    assert "blank" in capsys.readouterr().err.lower()


@pytest.mark.parametrize(
    "argv",
    [
        ["drift", "baseline.txt", "current.csv"],
        ["drift", "baseline.csv", "current.parquet"],
    ],
)
def test_drift_bad_extension_returns_2(monkeypatch, argv, capsys):
    _patch(monkeypatch)
    rc = cli.main(argv)
    assert rc == 2
    assert "Unsupported file extension" in capsys.readouterr().err


def test_drift_value_error_returns_1(monkeypatch, capsys):
    """Bad option values surface as ValueError -> exit 1 via existing handler."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)

    def raise_value_error(*a, **kw):
        raise ValueError("alpha must be in (0, 1), got 5.0")

    monkeypatch.setattr(cli, "run_drift", raise_value_error)
    rc = cli.main(["drift", "baseline.csv", "current.csv", "--alpha", "5.0"])
    assert rc == 1
    assert "Error:" in capsys.readouterr().err
