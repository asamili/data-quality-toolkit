"""Tests for --no-json flag (DQT-PATCH-004): stdout machine JSON suppression."""

from __future__ import annotations

import argparse
import json

import data_quality_toolkit.adapters.cli.main as cli

# ---------------------------------------------------------------------------
# Parser acceptance
# ---------------------------------------------------------------------------


def test_no_json_flag_accepted_by_parser():
    parser = cli.build_parser()
    args = parser.parse_args(["--no-json", "version"])
    assert args.no_json is True


def test_no_json_flag_default_is_false():
    parser = cli.build_parser()
    args = parser.parse_args(["version"])
    assert args.no_json is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATASET_ID = "sha1:abc123"

_COMPARE_SUCCESS = {
    "dataset_id": _DATASET_ID,
    "current_run_id": "run-bbb",
    "previous_run_id": "run-aaa",
    "current_score": 0.90,
    "previous_score": 0.80,
    "score_delta": 0.10,
    "current_issues_total": 2,
    "previous_issues_total": 5,
}

_COMPARE_ERROR = {
    "error": "not_enough_runs",
    "message": "Need at least 2 runs.",
    "dataset_id": _DATASET_ID,
    "runs_found": 1,
}


def _pipeline_ns(**kwargs):
    d = dict(sep=None, encoding=None, no_header=False, na_values=None, sample_size=None)
    d.update(kwargs)
    return argparse.Namespace(**d)


def _compare_ns(**kwargs):
    d = dict(csv="data.csv", outdir="dist")
    d.update(kwargs)
    return argparse.Namespace(**d)


def _patch_compare(monkeypatch, result):
    monkeypatch.setattr(
        "data_quality_toolkit.workflow.compare.compare_last_two_runs",
        lambda *a, **k: result,
    )
    monkeypatch.setattr(
        "data_quality_toolkit.loaders.file.csv_loader._dataset_id_from_file",
        lambda *a, **k: _DATASET_ID,
    )


def _profile_out():
    return {"profile": {"rows": 10, "cols": 3, "memory_mb": 0.5, "columns": []}}


def _assess_out():
    return {
        "profile": {"rows": 100, "cols": 3},
        "assessment": {"score": 0.85, "issues": []},
    }


def _star_out():
    return {
        "profile": {"rows": 10, "cols": 2},
        "assessment": {"score": 0.9, "issues": []},
        "export_paths": {"dim_dataset": "dist/star/dim_dataset.csv"},
    }


# ---------------------------------------------------------------------------
# --no-json suppresses stdout for core commands
# ---------------------------------------------------------------------------


def test_profile_no_json_stdout_empty(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_profile", lambda *a, **k: _profile_out())
    args = _pipeline_ns(csv="data.csv", no_json=True)
    rc = cli.cmd_profile(args)
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_profile_no_json_stderr_intact(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_profile", lambda *a, **k: _profile_out())
    args = _pipeline_ns(csv="data.csv", no_json=True)
    cli.cmd_profile(args)
    assert "Profile complete" in capsys.readouterr().err


def test_assess_no_json_stdout_empty(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out())
    args = _pipeline_ns(csv="data.csv", null_threshold=None, no_json=True)
    rc = cli.cmd_assess(args)
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_assess_no_json_stderr_intact(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out())
    args = _pipeline_ns(csv="data.csv", null_threshold=None, no_json=True)
    cli.cmd_assess(args)
    assert "Assessment complete" in capsys.readouterr().err


def test_export_star_no_json_stdout_empty(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_export_star", lambda *a, **k: _star_out())
    args = _pipeline_ns(csv="data.csv", outdir="dist", null_threshold=None, no_json=True)
    rc = cli.cmd_export_star(args)
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_export_star_no_json_stderr_intact(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_export_star", lambda *a, **k: _star_out())
    args = _pipeline_ns(csv="data.csv", outdir="dist", null_threshold=None, no_json=True)
    cli.cmd_export_star(args)
    assert "Star schema exported" in capsys.readouterr().err


def test_compare_success_no_json_stdout_empty(monkeypatch, capsys):
    _patch_compare(monkeypatch, _COMPARE_SUCCESS)
    rc = cli.cmd_compare(_compare_ns(no_json=True))
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_compare_success_no_json_stderr_intact(monkeypatch, capsys):
    _patch_compare(monkeypatch, _COMPARE_SUCCESS)
    cli.cmd_compare(_compare_ns(no_json=True))
    assert "Compare" in capsys.readouterr().err


def test_compare_error_no_json_stdout_empty(monkeypatch, capsys):
    _patch_compare(monkeypatch, _COMPARE_ERROR)
    rc = cli.cmd_compare(_compare_ns(no_json=True))
    assert rc == 1
    assert capsys.readouterr().out == ""


def test_compare_error_no_json_stderr_intact(monkeypatch, capsys):
    _patch_compare(monkeypatch, _COMPARE_ERROR)
    cli.cmd_compare(_compare_ns(no_json=True))
    assert capsys.readouterr().err != ""


# ---------------------------------------------------------------------------
# Regression: without --no-json, stdout JSON still present
# ---------------------------------------------------------------------------


def test_profile_without_no_json_stdout_is_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_profile", lambda *a, **k: _profile_out())
    args = _pipeline_ns(csv="data.csv")
    rc = cli.cmd_profile(args)
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert "profile" in parsed


def test_assess_without_no_json_stdout_is_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: _assess_out())
    args = _pipeline_ns(csv="data.csv", null_threshold=None)
    rc = cli.cmd_assess(args)
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert "assessment" in parsed


def test_export_star_without_no_json_stdout_is_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_export_star", lambda *a, **k: _star_out())
    args = _pipeline_ns(csv="data.csv", outdir="dist", null_threshold=None)
    rc = cli.cmd_export_star(args)
    assert rc == 0
    json.loads(capsys.readouterr().out)  # must not raise


def test_compare_without_no_json_stdout_is_json(monkeypatch, capsys):
    _patch_compare(monkeypatch, _COMPARE_SUCCESS)
    rc = cli.cmd_compare(_compare_ns())
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert "dataset_id" in parsed
