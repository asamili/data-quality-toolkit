from __future__ import annotations

import argparse
from unittest.mock import MagicMock

import data_quality_toolkit.adapters.cli.main as cli


def _base_ns(**overrides) -> argparse.Namespace:
    defaults = {
        "csv": "data.csv",
        "outdir": None,
        "null_threshold": None,
        "fail_under": None,
        "score_field": "score",
        "sample_size": None,
        "sep": None,
        "encoding": None,
        "no_header": False,
        "na_values": None,
        "no_json": True,
        "manifest": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _mock_export_star(monkeypatch, *, run_export_star_mock: MagicMock) -> None:
    monkeypatch.setattr(cli, "run_export_star", run_export_star_mock)


def _make_export_return() -> dict:
    return {
        "run_id": "test-run",
        "export_paths": {},
        "profile": {"rows": 2, "cols": 2},
        "assessment": {"score": 1.0, "completeness_score": 1.0, "quality_score": 1.0, "issues": []},
    }


def test_cmd_export_star_manifest_false_by_default(monkeypatch, capsys):
    mock = MagicMock(return_value=_make_export_return())
    _mock_export_star(monkeypatch, run_export_star_mock=mock)

    cli.cmd_export_star(_base_ns())

    _kwargs = mock.call_args.kwargs if mock.call_args.kwargs else {}
    _args = mock.call_args.args if mock.call_args.args else ()
    # emit_manifest must be False (default)
    assert _kwargs.get("emit_manifest", False) is False


def test_cmd_export_star_manifest_flag_passes_emit_manifest_true(monkeypatch, capsys):
    mock = MagicMock(return_value=_make_export_return())
    _mock_export_star(monkeypatch, run_export_star_mock=mock)

    cli.cmd_export_star(_base_ns(manifest=True))

    _kwargs = mock.call_args.kwargs if mock.call_args.kwargs else {}
    assert _kwargs.get("emit_manifest") is True


def test_cmd_export_star_manifest_not_in_csv_kwargs(monkeypatch, capsys):
    """manifest must reach run_export_star as explicit kwarg, not buried in **csv_kw."""
    captured_kwargs: dict = {}

    def capturing_run(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return _make_export_return()

    monkeypatch.setattr(cli, "run_export_star", capturing_run)

    cli.cmd_export_star(_base_ns(manifest=True))

    assert "emit_manifest" in captured_kwargs
    assert captured_kwargs["emit_manifest"] is True


def test_build_parser_export_star_has_manifest_flag():
    p = cli.build_parser()
    args = p.parse_args(["export-star", "data.csv", "--manifest"])
    assert args.manifest is True


def test_build_parser_export_star_manifest_default_false():
    p = cli.build_parser()
    args = p.parse_args(["export-star", "data.csv"])
    assert args.manifest is False


def test_build_parser_export_alias_has_manifest_flag():
    p = cli.build_parser()
    args = p.parse_args(["export", "data.csv", "--manifest"])
    assert args.manifest is True
