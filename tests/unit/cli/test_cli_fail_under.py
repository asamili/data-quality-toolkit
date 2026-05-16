"""Tests for --fail-under quality gate CLI option on assess, export-star, and export."""

from __future__ import annotations

import argparse

import pytest

import data_quality_toolkit.cli.main as cli


def _ns(**kwargs):
    defaults = dict(
        csv="data.csv",
        sep=None,
        encoding=None,
        no_header=False,
        na_values=None,
        sample_size=None,
        null_threshold=None,
        fail_under=None,
        no_json=True,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _assess_out(score=0.9):
    return {
        "profile": {"rows": 10, "cols": 2},
        "assessment": {"score": score, "issues": []},
    }


def _star_out(score=0.9):
    return {
        "profile": {"rows": 10, "cols": 2},
        "assessment": {"score": score, "issues": []},
        "export_paths": {},
    }


# ── parser exposes the flag ────────────────────────────────────────────────────


def test_parser_assess_accepts_fail_under():
    p = cli.build_parser()
    args = p.parse_args(["assess", "data.csv", "--fail-under", "0.8"])
    assert args.fail_under == pytest.approx(0.8)


def test_parser_export_star_accepts_fail_under():
    p = cli.build_parser()
    args = p.parse_args(["export-star", "data.csv", "--fail-under", "0.7"])
    assert args.fail_under == pytest.approx(0.7)


def test_parser_export_alias_accepts_fail_under():
    p = cli.build_parser()
    args = p.parse_args(["export", "data.csv", "--fail-under", "0.6"])
    assert args.fail_under == pytest.approx(0.6)


def test_parser_fail_under_default_is_none():
    p = cli.build_parser()
    args = p.parse_args(["assess", "data.csv"])
    assert args.fail_under is None


# ── _extract_fail_under validates bounds ──────────────────────────────────────


def test_extract_returns_none_when_absent():
    assert cli._extract_fail_under(_ns()) is None


def test_extract_returns_value_when_valid():
    assert cli._extract_fail_under(_ns(fail_under=0.75)) == pytest.approx(0.75)


def test_extract_accepts_boundary_zero():
    assert cli._extract_fail_under(_ns(fail_under=0.0)) == pytest.approx(0.0)


def test_extract_accepts_boundary_one():
    assert cli._extract_fail_under(_ns(fail_under=1.0)) == pytest.approx(1.0)


def test_extract_rejects_below_zero():
    with pytest.raises(ValueError, match="0.0 and 1.0"):
        cli._extract_fail_under(_ns(fail_under=-0.01))


def test_extract_rejects_above_one():
    with pytest.raises(ValueError, match="0.0 and 1.0"):
        cli._extract_fail_under(_ns(fail_under=1.01))


# ── cmd_assess gate behaviour ─────────────────────────────────────────────────


def test_cmd_assess_passes_when_score_meets_threshold(monkeypatch):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out(score=0.8))
    assert cli.cmd_assess(_ns(fail_under=0.8)) == 0


def test_cmd_assess_passes_when_flag_absent(monkeypatch):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out(score=0.5))
    assert cli.cmd_assess(_ns()) == 0


def test_cmd_assess_fails_when_score_below_threshold(monkeypatch):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out(score=0.5))
    assert cli.cmd_assess(_ns(fail_under=0.8)) == 2


def test_cmd_assess_failure_stderr_message(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out(score=0.5))
    cli.cmd_assess(_ns(fail_under=0.8))
    err = capsys.readouterr().err
    assert "Quality gate FAILED" in err
    assert "50.00%" in err
    assert "80.00%" in err


def test_cmd_assess_invalid_threshold_raises(monkeypatch):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out())
    with pytest.raises(ValueError, match="0.0 and 1.0"):
        cli.cmd_assess(_ns(fail_under=1.5))


# ── cmd_export_star gate behaviour ────────────────────────────────────────────


def test_cmd_export_star_passes_when_score_meets_threshold(monkeypatch):
    monkeypatch.setattr(cli, "run_export_star", lambda *a, **k: _star_out(score=0.9))
    assert cli.cmd_export_star(_ns(outdir="dist", fail_under=0.9)) == 0


def test_cmd_export_star_passes_when_flag_absent(monkeypatch):
    monkeypatch.setattr(cli, "run_export_star", lambda *a, **k: _star_out(score=0.3))
    assert cli.cmd_export_star(_ns(outdir="dist")) == 0


def test_cmd_export_star_fails_when_score_below_threshold(monkeypatch):
    monkeypatch.setattr(cli, "run_export_star", lambda *a, **k: _star_out(score=0.6))
    assert cli.cmd_export_star(_ns(outdir="dist", fail_under=0.8)) == 2


def test_cmd_export_star_failure_stderr_message(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_export_star", lambda *a, **k: _star_out(score=0.6))
    cli.cmd_export_star(_ns(outdir="dist", fail_under=0.8))
    err = capsys.readouterr().err
    assert "Quality gate FAILED" in err
    assert "60.00%" in err
    assert "80.00%" in err


def test_cmd_export_star_invalid_threshold_raises(monkeypatch):
    monkeypatch.setattr(cli, "run_export_star", lambda *a, **k: _star_out())
    with pytest.raises(ValueError, match="0.0 and 1.0"):
        cli.cmd_export_star(_ns(outdir="dist", fail_under=-0.1))
