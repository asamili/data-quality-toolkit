"""Tests for --null-threshold CLI option on assess and export-star."""

from __future__ import annotations

import argparse

import pytest

import data_quality_toolkit.adapters.cli.main as cli


def _ns(**kwargs):
    defaults = dict(
        sep=None,
        encoding=None,
        no_header=False,
        na_values=None,
        sample_size=None,
        null_threshold=None,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _assess_out():
    return {
        "profile": {"rows": 10, "cols": 2},
        "assessment": {"score": 0.9, "issues": []},
    }


def _star_out():
    return {
        "profile": {"rows": 10, "cols": 2},
        "assessment": {"score": 0.9, "issues": []},
        "export_paths": {},
    }


# ── parser exposes the flag ────────────────────────────────────────────────────


def test_parser_assess_accepts_null_threshold():
    p = cli.build_parser()
    args = p.parse_args(["assess", "data.csv", "--null-threshold", "0.1"])
    assert args.null_threshold == pytest.approx(0.1)


def test_parser_export_star_accepts_null_threshold():
    p = cli.build_parser()
    args = p.parse_args(["export-star", "data.csv", "--null-threshold", "0.05"])
    assert args.null_threshold == pytest.approx(0.05)


def test_parser_export_alias_accepts_null_threshold():
    p = cli.build_parser()
    args = p.parse_args(["export", "data.csv", "--null-threshold", "0.3"])
    assert args.null_threshold == pytest.approx(0.3)


def test_parser_null_threshold_default_is_none():
    p = cli.build_parser()
    args = p.parse_args(["assess", "data.csv"])
    assert args.null_threshold is None


# ── _extract_null_threshold validates bounds ───────────────────────────────────


def test_extract_returns_none_when_absent():
    assert cli._extract_null_threshold(_ns()) is None


def test_extract_returns_value_when_valid():
    assert cli._extract_null_threshold(_ns(null_threshold=0.1)) == pytest.approx(0.1)


def test_extract_accepts_boundary_zero():
    assert cli._extract_null_threshold(_ns(null_threshold=0.0)) == pytest.approx(0.0)


def test_extract_accepts_boundary_one():
    assert cli._extract_null_threshold(_ns(null_threshold=1.0)) == pytest.approx(1.0)


def test_extract_rejects_below_zero():
    with pytest.raises(ValueError, match="0.0 and 1.0"):
        cli._extract_null_threshold(_ns(null_threshold=-0.01))


def test_extract_rejects_above_one():
    with pytest.raises(ValueError, match="0.0 and 1.0"):
        cli._extract_null_threshold(_ns(null_threshold=1.01))


# ── cmd_assess passes threshold to run_assessment ─────────────────────────────


def test_cmd_assess_passes_threshold(monkeypatch, capsys):
    captured: dict = {}

    def fake_run(csv, null_threshold=0.2, **kw):
        captured["null_threshold"] = null_threshold
        return _assess_out()

    monkeypatch.setattr(cli, "run_assessment", fake_run)
    cli.cmd_assess(_ns(csv="data.csv", null_threshold=0.05))
    assert captured["null_threshold"] == pytest.approx(0.05)


def test_cmd_assess_omits_threshold_uses_pipeline_default(monkeypatch, capsys):
    captured: dict = {}

    def fake_run(csv, null_threshold=0.2, **kw):
        captured["null_threshold"] = null_threshold
        return _assess_out()

    monkeypatch.setattr(cli, "run_assessment", fake_run)
    cli.cmd_assess(_ns(csv="data.csv"))  # null_threshold=None -> pipeline default
    assert captured["null_threshold"] == pytest.approx(0.2)


def test_cmd_assess_invalid_threshold_raises(monkeypatch):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out())
    with pytest.raises(ValueError, match="0.0 and 1.0"):
        cli.cmd_assess(_ns(csv="data.csv", null_threshold=2.0))


# ── cmd_export_star passes threshold to run_export_star ───────────────────────


def test_cmd_export_star_passes_threshold(monkeypatch, capsys):
    captured: dict = {}

    def fake_run(csv, output_dir=None, null_threshold=0.2, **kw):
        captured["null_threshold"] = null_threshold
        return _star_out()

    monkeypatch.setattr(cli, "run_export_star", fake_run)
    cli.cmd_export_star(_ns(csv="data.csv", outdir="dist", null_threshold=0.10))
    assert captured["null_threshold"] == pytest.approx(0.10)


def test_cmd_export_star_omits_threshold_uses_pipeline_default(monkeypatch, capsys):
    captured: dict = {}

    def fake_run(csv, output_dir=None, null_threshold=0.2, **kw):
        captured["null_threshold"] = null_threshold
        return _star_out()

    monkeypatch.setattr(cli, "run_export_star", fake_run)
    cli.cmd_export_star(_ns(csv="data.csv", outdir="dist"))
    assert captured["null_threshold"] == pytest.approx(0.2)
