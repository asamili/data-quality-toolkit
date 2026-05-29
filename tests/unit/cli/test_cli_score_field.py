"""Tests for --score-field option in the quality gate CLI."""

from __future__ import annotations

import argparse
import json

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
        score_field="score",
        no_json=True,
        db=None,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _assess_out(score=0.9, completeness_score=None, quality_score=None):
    a: dict = {"score": score, "issues": []}
    if completeness_score is not None:
        a["completeness_score"] = completeness_score
    if quality_score is not None:
        a["quality_score"] = quality_score
    return {"profile": {"rows": 10, "cols": 2}, "assessment": a}


# ── parser exposes --score-field ───────────────────────────────────────────────


def test_parser_assess_accepts_score_field():
    p = cli.build_parser()
    args = p.parse_args(["assess", "data.csv", "--score-field", "quality_score"])
    assert args.score_field == "quality_score"


def test_parser_score_field_default_is_score():
    p = cli.build_parser()
    args = p.parse_args(["assess", "data.csv"])
    assert args.score_field == "score"


def test_parser_export_star_accepts_score_field():
    p = cli.build_parser()
    args = p.parse_args(["export-star", "data.csv", "--score-field", "completeness_score"])
    assert args.score_field == "completeness_score"


def test_parser_export_alias_accepts_score_field():
    p = cli.build_parser()
    args = p.parse_args(["export", "data.csv", "--score-field", "quality_score"])
    assert args.score_field == "quality_score"


def test_parser_score_field_rejects_invalid_choice():
    p = cli.build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["assess", "data.csv", "--score-field", "bad_field"])


# ── _check_quality_gate with score_field ──────────────────────────────────────


def test_check_quality_gate_default_uses_score():
    out = _assess_out(score=0.5, quality_score=0.9)
    # default score_field="score" → 0.5 < 0.8 → fail
    assert cli._check_quality_gate(0.8, out) == 2


def test_check_quality_gate_score_field_score():
    out = _assess_out(score=0.5, quality_score=0.9)
    assert cli._check_quality_gate(0.8, out, score_field="score") == 2


def test_check_quality_gate_score_field_completeness_score():
    out = _assess_out(score=0.5, completeness_score=0.9)
    # completeness_score=0.9 >= 0.8 → pass
    assert cli._check_quality_gate(0.8, out, score_field="completeness_score") == 0


def test_check_quality_gate_score_field_quality_score_fail():
    out = _assess_out(score=0.9, quality_score=0.5)
    # quality_score=0.5 < 0.8 → fail
    assert cli._check_quality_gate(0.8, out, score_field="quality_score") == 2


def test_check_quality_gate_score_field_quality_score_pass():
    out = _assess_out(score=0.5, quality_score=0.9)
    # quality_score=0.9 >= 0.8 → pass
    assert cli._check_quality_gate(0.8, out, score_field="quality_score") == 0


def test_check_quality_gate_missing_field_falls_back_to_score():
    # quality_score absent → falls back to score (1.0 default) → pass
    out = _assess_out(score=0.9)
    assert cli._check_quality_gate(0.8, out, score_field="quality_score") == 0


# ── cmd_assess gate behaviour with score_field ────────────────────────────────


def test_cmd_assess_default_score_field_uses_score(monkeypatch):
    monkeypatch.setattr(
        cli, "run_assessment", lambda *a, **k: _assess_out(score=0.5, quality_score=0.9)
    )
    # score=0.5 < 0.8, quality_score not used with default field
    assert cli.cmd_assess(_ns(fail_under=0.8, score_field="score")) == 2


def test_cmd_assess_score_field_quality_score_fails(monkeypatch):
    monkeypatch.setattr(
        cli, "run_assessment", lambda *a, **k: _assess_out(score=0.9, quality_score=0.5)
    )
    assert cli.cmd_assess(_ns(fail_under=0.8, score_field="quality_score")) == 2


def test_cmd_assess_score_above_quality_below_passes_with_default_field(monkeypatch):
    monkeypatch.setattr(
        cli, "run_assessment", lambda *a, **k: _assess_out(score=0.9, quality_score=0.5)
    )
    # Default score_field=score: score=0.9 >= 0.8 → pass
    assert cli.cmd_assess(_ns(fail_under=0.8)) == 0


def test_cmd_assess_score_field_completeness_score_passes(monkeypatch):
    monkeypatch.setattr(
        cli, "run_assessment", lambda *a, **k: _assess_out(score=0.5, completeness_score=0.9)
    )
    # completeness_score=0.9 >= 0.8 → pass
    assert cli.cmd_assess(_ns(fail_under=0.8, score_field="completeness_score")) == 0


def test_cmd_assess_score_field_completeness_score_fails(monkeypatch):
    monkeypatch.setattr(
        cli, "run_assessment", lambda *a, **k: _assess_out(score=0.9, completeness_score=0.5)
    )
    assert cli.cmd_assess(_ns(fail_under=0.8, score_field="completeness_score")) == 2


def test_cmd_assess_quality_score_failure_stderr(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "run_assessment", lambda *a, **k: _assess_out(score=0.9, quality_score=0.5)
    )
    cli.cmd_assess(_ns(fail_under=0.8, score_field="quality_score"))
    err = capsys.readouterr().err
    assert "Quality gate FAILED" in err
    assert "50.00%" in err
    assert "80.00%" in err


# ── assess output includes quality_score and completeness_score ───────────────


def test_assess_output_includes_completeness_score(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "run_assessment", lambda *a, **k: _assess_out(score=0.8, completeness_score=0.8)
    )
    cli.cmd_assess(_ns(csv="data.csv"))
    err = capsys.readouterr().err
    assert "Completeness Score" in err
    assert "80.00%" in err


def test_assess_output_includes_quality_score(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "run_assessment", lambda *a, **k: _assess_out(score=0.8, quality_score=0.7)
    )
    cli.cmd_assess(_ns(csv="data.csv"))
    err = capsys.readouterr().err
    assert "Quality Score" in err
    assert "70.00%" in err


def test_assess_output_missing_completeness_no_crash(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out(score=0.8))
    rc = cli.cmd_assess(_ns(csv="data.csv"))
    assert rc == 0


def test_assess_output_missing_quality_no_crash(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out(score=0.8))
    rc = cli.cmd_assess(_ns(csv="data.csv"))
    assert rc == 0


# ── compare output handles quality_score/completeness_score ──────────────────

_DATASET_ID = "sha1:abc123"

_COMPARE_WITH_SCORES = {
    "dataset_id": _DATASET_ID,
    "current_run_id": "run-bbb",
    "previous_run_id": "run-aaa",
    "current_score": 0.90,
    "previous_score": 0.80,
    "score_delta": 0.10,
    "current_quality_score": 0.75,
    "previous_quality_score": 0.65,
    "current_completeness_score": 0.90,
    "previous_completeness_score": 0.80,
    "current_issues_total": 2,
    "previous_issues_total": 5,
    "issues_delta": -3.0,
    "current_duration_secs": 1.0,
    "previous_duration_secs": 1.2,
    "duration_delta": -0.2,
    "current_ts": "2026-04-02T10:00:00Z",
    "previous_ts": "2026-04-01T10:00:00Z",
}

_COMPARE_LEGACY_NONE = {
    **_COMPARE_WITH_SCORES,
    "current_quality_score": None,
    "previous_quality_score": None,
    "current_completeness_score": None,
    "previous_completeness_score": None,
}


def _patch_compare(monkeypatch, result):
    monkeypatch.setattr(
        "data_quality_toolkit.workflow.compare.compare_last_two_runs",
        lambda *a, **k: result,
    )
    monkeypatch.setattr(
        "data_quality_toolkit.loaders.file.csv_loader._dataset_id_from_file",
        lambda *a, **k: _DATASET_ID,
    )


def _cmp_ns(**kwargs):
    d = dict(csv="data.csv", outdir="dist")
    d.update(kwargs)
    return argparse.Namespace(**d)


def test_compare_shows_quality_score_if_present(monkeypatch, capsys):
    _patch_compare(monkeypatch, _COMPARE_WITH_SCORES)
    cli.cmd_compare(_cmp_ns())
    err = capsys.readouterr().err
    assert "Quality Score" in err
    assert "0.650" in err
    assert "0.750" in err


def test_compare_shows_completeness_score_if_present(monkeypatch, capsys):
    _patch_compare(monkeypatch, _COMPARE_WITH_SCORES)
    cli.cmd_compare(_cmp_ns())
    err = capsys.readouterr().err
    assert "Completeness Score" in err
    assert "0.800" in err
    assert "0.900" in err


def test_compare_legacy_none_does_not_crash(monkeypatch, capsys):
    _patch_compare(monkeypatch, _COMPARE_LEGACY_NONE)
    rc = cli.cmd_compare(_cmp_ns())
    assert rc == 0


def test_compare_legacy_none_shows_na(monkeypatch, capsys):
    _patch_compare(monkeypatch, _COMPARE_LEGACY_NONE)
    cli.cmd_compare(_cmp_ns())
    err = capsys.readouterr().err
    assert "N/A" in err


def test_compare_no_quality_score_field_no_crash(monkeypatch, capsys):
    """Legacy records with no quality_score key at all must not crash."""
    result = {
        k: v
        for k, v in _COMPARE_WITH_SCORES.items()
        if k
        not in (
            "current_quality_score",
            "previous_quality_score",
            "current_completeness_score",
            "previous_completeness_score",
        )
    }
    _patch_compare(monkeypatch, result)
    rc = cli.cmd_compare(_cmp_ns())
    assert rc == 0


def test_compare_with_scores_stdout_is_valid_json(monkeypatch, capsys):
    _patch_compare(monkeypatch, _COMPARE_WITH_SCORES)
    rc = cli.cmd_compare(_cmp_ns())
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["current_quality_score"] == pytest.approx(0.75)
    assert parsed["previous_quality_score"] == pytest.approx(0.65)
