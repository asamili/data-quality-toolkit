"""Tests for cmd_assess and cmd_export_star stderr summaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import data_quality_toolkit.cli.main as cli


def _ns(**kwargs):
    d = dict(sep=None, encoding=None, no_header=False, na_values=None, sample_size=None, db=None)
    d.update(kwargs)
    return argparse.Namespace(**d)


def _assess_out(score=0.85, issues=None, rows=100, cols=3):
    return {
        "profile": {"rows": rows, "cols": cols},
        "assessment": {
            "score": score,
            "issues": issues if issues is not None else [],
        },
    }


# ── cmd_assess ────────────────────────────────────────────────────────────────


def test_cmd_assess_stderr_contains_header(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out())
    args = _ns(csv="data.csv")
    cli.cmd_assess(args)
    err = capsys.readouterr().err
    assert "Assessment complete" in err


def test_cmd_assess_stderr_rows_and_cols(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out(rows=42, cols=7))
    args = _ns(csv="data.csv")
    cli.cmd_assess(args)
    err = capsys.readouterr().err
    assert "Rows: 42" in err
    assert "Columns: 7" in err


def test_cmd_assess_stderr_quality_score(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out(score=0.75))
    args = _ns(csv="data.csv")
    cli.cmd_assess(args)
    err = capsys.readouterr().err
    assert "75.00%" in err


def test_cmd_assess_stderr_issue_count_zero(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out(issues=[]))
    args = _ns(csv="data.csv")
    cli.cmd_assess(args)
    err = capsys.readouterr().err
    assert "Issues flagged: 0" in err


def test_cmd_assess_stderr_issue_count_nonzero(monkeypatch, capsys):
    issues = [
        {
            "type": "missing",
            "column": "a",
            "severity": "high",
            "category": "Completeness",
            "message": "x",
        },
        {
            "type": "duplicate_column_name",
            "column": "b",
            "severity": "high",
            "category": "Schema",
            "message": "y",
        },
    ]
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out(issues=issues))
    args = _ns(csv="data.csv")
    cli.cmd_assess(args)
    err = capsys.readouterr().err
    assert "Issues flagged: 2" in err


def test_cmd_assess_stdout_is_still_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out())
    args = _ns(csv="data.csv")
    rc = cli.cmd_assess(args)
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "assessment" in parsed


def test_cmd_assess_no_profile_key_does_not_crash(monkeypatch, capsys):
    """Output without profile/assessment keys must not raise."""
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: {"status": "ok"})
    args = _ns(csv="data.csv")
    rc = cli.cmd_assess(args)
    assert rc == 0


# ── cmd_assess --db flag ──────────────────────────────────────────────────────


def test_cmd_assess_without_db_passes_no_db_path(monkeypatch, capsys):
    """--db absent → run_assessment receives db_path=None."""
    captured: dict = {}

    def fake_run_assessment(*a, **k):
        captured.update(k)
        return _assess_out()

    monkeypatch.setattr(cli, "run_assessment", fake_run_assessment)
    cli.cmd_assess(_ns(csv="data.csv"))
    assert captured.get("db_path") is None


def test_cmd_assess_with_db_flag_passes_path(monkeypatch, capsys, tmp_path):
    """--db PATH → run_assessment receives db_path=Path(PATH)."""
    captured: dict = {}

    def fake_run_assessment(*a, **k):
        captured.update(k)
        return _assess_out()

    monkeypatch.setattr(cli, "run_assessment", fake_run_assessment)
    db = str(tmp_path / "test.db")
    cli.cmd_assess(_ns(csv="data.csv", db=db))
    assert captured.get("db_path") == Path(db)


def test_cmd_assess_with_db_flag_still_returns_json(monkeypatch, capsys, tmp_path):
    """--db flag must not suppress stdout JSON."""
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out())
    db = str(tmp_path / "test.db")
    rc = cli.cmd_assess(_ns(csv="data.csv", db=db))
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "assessment" in parsed


def test_cmd_assess_with_db_flag_null_threshold_forwarded(monkeypatch, capsys, tmp_path):
    """--db + --null-threshold both forwarded to run_assessment."""
    captured: dict = {}

    def fake_run_assessment(*a, **k):
        captured.update(k)
        return _assess_out()

    monkeypatch.setattr(cli, "run_assessment", fake_run_assessment)
    db = str(tmp_path / "test.db")
    cli.cmd_assess(_ns(csv="data.csv", db=db, null_threshold=0.1))
    assert captured.get("db_path") == Path(db)
    assert captured.get("null_threshold") == 0.1


# ── cmd_export_star ────────────────────────────────────────────────────────────


def _star_out(score=0.9, issues=None):
    return {
        "profile": {"rows": 10, "cols": 2},
        "assessment": {
            "score": score,
            "issues": issues if issues is not None else [],
        },
        "export_paths": {"dim_dataset": "dist/star/dim_dataset.csv"},
    }


def test_cmd_export_star_stderr_issue_count_zero(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_export_star", lambda *a, **k: _star_out(issues=[]))
    args = _ns(csv="data.csv", outdir="dist")
    cli.cmd_export_star(args)
    err = capsys.readouterr().err
    assert "Issues flagged: 0" in err


def test_cmd_export_star_stderr_issue_count_nonzero(monkeypatch, capsys):
    issues = [
        {
            "type": "missing",
            "column": "x",
            "severity": "high",
            "category": "Completeness",
            "message": "m",
        }
    ] * 3
    monkeypatch.setattr(cli, "run_export_star", lambda *a, **k: _star_out(issues=issues))
    args = _ns(csv="data.csv", outdir="dist")
    cli.cmd_export_star(args)
    err = capsys.readouterr().err
    assert "Issues flagged: 3" in err


def test_cmd_export_star_stdout_still_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_export_star", lambda *a, **k: _star_out())
    args = _ns(csv="data.csv", outdir="dist")
    rc = cli.cmd_export_star(args)
    assert rc == 0
    json.loads(capsys.readouterr().out)  # must not raise
