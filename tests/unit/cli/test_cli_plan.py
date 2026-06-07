"""Tests for cmd_plan: stdout JSON, stderr summary, --no-json suppression, registration."""

from __future__ import annotations

import argparse
import json

import data_quality_toolkit.adapters.cli.main as cli


def _ns(**kwargs):
    d = dict(sep=None, encoding=None, no_header=False, na_values=None, sample_size=None)
    d.update(kwargs)
    return argparse.Namespace(**d)


def _plan_out(dataset_id="sha1:abc", cols=None):
    if cols is None:
        cols = [
            {
                "column": "a",
                "dtype": "int64",
                "issues": "none",
                "recommendations": "consider scaling",
            },
            {
                "column": "b",
                "dtype": "object",
                "issues": "nulls (20%)",
                "recommendations": "impute with mode or 'Unknown'",
            },
        ]
    return {"dataset_id": dataset_id, "columns": cols}


# ---------------------------------------------------------------------------
# stderr summary
# ---------------------------------------------------------------------------


def test_cmd_plan_stderr_contains_plan_complete(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_plan", lambda *a, **k: _plan_out())
    cli.cmd_plan(_ns(csv="data.csv"))
    assert "Plan complete" in capsys.readouterr().err


def test_cmd_plan_stderr_shows_column_count(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_plan", lambda *a, **k: _plan_out())
    cli.cmd_plan(_ns(csv="data.csv"))
    assert "Columns: 2" in capsys.readouterr().err


def test_cmd_plan_stderr_shows_issues_count(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_plan", lambda *a, **k: _plan_out())
    cli.cmd_plan(_ns(csv="data.csv"))
    assert "Columns with issues: 1" in capsys.readouterr().err


def test_cmd_plan_stderr_zero_issues(monkeypatch, capsys):
    out = _plan_out(
        cols=[
            {
                "column": "a",
                "dtype": "int64",
                "issues": "none",
                "recommendations": "consider scaling",
            },
        ]
    )
    monkeypatch.setattr(cli, "run_plan", lambda *a, **k: out)
    cli.cmd_plan(_ns(csv="data.csv"))
    assert "Columns with issues: 0" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# stdout JSON
# ---------------------------------------------------------------------------


def test_cmd_plan_stdout_is_valid_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_plan", lambda *a, **k: _plan_out())
    rc = cli.cmd_plan(_ns(csv="data.csv"))
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert "dataset_id" in parsed
    assert "columns" in parsed


def test_cmd_plan_stdout_columns_shape(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_plan", lambda *a, **k: _plan_out())
    cli.cmd_plan(_ns(csv="data.csv"))
    parsed = json.loads(capsys.readouterr().out)
    row = parsed["columns"][0]
    assert {"column", "dtype", "issues", "recommendations"} <= row.keys()


# ---------------------------------------------------------------------------
# --no-json suppresses stdout
# ---------------------------------------------------------------------------


def test_cmd_plan_no_json_suppresses_stdout(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_plan", lambda *a, **k: _plan_out())
    rc = cli.cmd_plan(_ns(csv="data.csv", no_json=True))
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_cmd_plan_no_json_stderr_intact(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_plan", lambda *a, **k: _plan_out())
    cli.cmd_plan(_ns(csv="data.csv", no_json=True))
    assert "Plan complete" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Parser registration
# ---------------------------------------------------------------------------


def test_plan_subcommand_is_registered():
    parser = cli.build_parser()
    args = parser.parse_args(["plan", "data.csv"])
    assert args.command == "plan"
    assert args.csv == "data.csv"
    assert args.func is cli.cmd_plan


def test_plan_accepts_csv_options():
    parser = cli.build_parser()
    args = parser.parse_args(["plan", "data.csv", "--sep", ";", "--encoding", "latin-1"])
    assert args.sep == ";"
    assert args.encoding == "latin-1"
