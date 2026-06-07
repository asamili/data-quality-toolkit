"""Tests for dqt.yaml integration with the CLI.

Verifies opt-in behavior, precedence (explicit CLI > dqt.yaml > default),
and error handling when dqt.yaml is malformed.
"""

from __future__ import annotations

import argparse

import pytest

import data_quality_toolkit.adapters.cli.main as cli
from data_quality_toolkit.adapters.cli.main import DEFAULT_DIST
from data_quality_toolkit.shared.exceptions import ConfigError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONFIG_FILENAME = "dqt.yaml"


def _write_yaml(tmp_path, content: str):
    p = tmp_path / CONFIG_FILENAME
    p.write_text(content, encoding="utf-8")
    return p


def _ns(**kwargs) -> argparse.Namespace:
    defaults = {
        "null_threshold": None,
        "fail_under": None,
        "outdir": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# _apply_dqt_config — unit tests (direct, using monkeypatch.chdir)
# ---------------------------------------------------------------------------


class TestApplyDqtConfigAbsent:
    """No dqt.yaml → no changes except outdir resolves to DEFAULT_DIST."""

    def test_null_threshold_stays_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ns = _ns()
        cli._apply_dqt_config(ns)
        assert ns.null_threshold is None

    def test_fail_under_stays_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ns = _ns()
        cli._apply_dqt_config(ns)
        assert ns.fail_under is None

    def test_outdir_resolves_to_default_dist(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ns = _ns()
        cli._apply_dqt_config(ns)
        assert ns.outdir == DEFAULT_DIST

    def test_namespace_without_outdir_is_unaffected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ns = argparse.Namespace(null_threshold=None)
        cli._apply_dqt_config(ns)
        assert not hasattr(ns, "outdir")


class TestApplyDqtConfigFills:
    """dqt.yaml fills unset CLI options."""

    def test_fills_null_threshold(self, tmp_path, monkeypatch):
        _write_yaml(tmp_path, "null_threshold: 0.3\n")
        monkeypatch.chdir(tmp_path)
        ns = _ns()
        cli._apply_dqt_config(ns)
        assert ns.null_threshold == 0.3

    def test_fills_fail_under(self, tmp_path, monkeypatch):
        _write_yaml(tmp_path, "fail_under: 0.75\n")
        monkeypatch.chdir(tmp_path)
        ns = _ns()
        cli._apply_dqt_config(ns)
        assert ns.fail_under == 0.75

    def test_fills_outdir(self, tmp_path, monkeypatch):
        _write_yaml(tmp_path, "outdir: ./custom_out\n")
        monkeypatch.chdir(tmp_path)
        ns = _ns()
        cli._apply_dqt_config(ns)
        assert ns.outdir == "./custom_out"

    def test_fills_all_three(self, tmp_path, monkeypatch):
        _write_yaml(tmp_path, "null_threshold: 0.1\nfail_under: 0.9\noutdir: ./prod\n")
        monkeypatch.chdir(tmp_path)
        ns = _ns()
        cli._apply_dqt_config(ns)
        assert ns.null_threshold == 0.1
        assert ns.fail_under == 0.9
        assert ns.outdir == "./prod"


class TestApplyDqtConfigPrecedence:
    """Explicit CLI args override dqt.yaml."""

    def test_cli_null_threshold_wins(self, tmp_path, monkeypatch):
        _write_yaml(tmp_path, "null_threshold: 0.5\n")
        monkeypatch.chdir(tmp_path)
        ns = _ns(null_threshold=0.1)
        cli._apply_dqt_config(ns)
        assert ns.null_threshold == 0.1

    def test_cli_fail_under_wins(self, tmp_path, monkeypatch):
        _write_yaml(tmp_path, "fail_under: 0.9\n")
        monkeypatch.chdir(tmp_path)
        ns = _ns(fail_under=0.5)
        cli._apply_dqt_config(ns)
        assert ns.fail_under == 0.5

    def test_cli_outdir_wins(self, tmp_path, monkeypatch):
        _write_yaml(tmp_path, "outdir: ./from_yaml\n")
        monkeypatch.chdir(tmp_path)
        ns = _ns(outdir="./from_cli")
        cli._apply_dqt_config(ns)
        assert ns.outdir == "./from_cli"

    def test_zero_float_cli_wins(self, tmp_path, monkeypatch):
        """Falsy-but-valid 0.0 from CLI must not be overridden."""
        _write_yaml(tmp_path, "null_threshold: 0.5\n")
        monkeypatch.chdir(tmp_path)
        ns = _ns(null_threshold=0.0)
        cli._apply_dqt_config(ns)
        assert ns.null_threshold == 0.0


class TestApplyDqtConfigErrors:
    """Malformed dqt.yaml raises ConfigError."""

    def test_malformed_yaml_raises(self, tmp_path, monkeypatch):
        _write_yaml(tmp_path, "key: [\n")
        monkeypatch.chdir(tmp_path)
        ns = _ns()
        with pytest.raises(ConfigError):
            cli._apply_dqt_config(ns)

    def test_unknown_key_raises(self, tmp_path, monkeypatch):
        _write_yaml(tmp_path, "bad_key: 99\n")
        monkeypatch.chdir(tmp_path)
        ns = _ns()
        with pytest.raises(ConfigError, match="bad_key"):
            cli._apply_dqt_config(ns)


# ---------------------------------------------------------------------------
# main() integration — dqt.yaml ConfigError → exit 2
# ---------------------------------------------------------------------------


class TestMainConfigError:
    """main() catches ConfigError from dqt.yaml and returns 2."""

    def test_malformed_yaml_returns_2(self, tmp_path, monkeypatch, capsys):
        _write_yaml(tmp_path, "key: [\n")
        monkeypatch.chdir(tmp_path)
        # Use a real subcommand with a real CSV arg; error happens before any file access
        code = cli.main(["assess", "dummy.csv"])
        assert code == 2
        assert "Error:" in capsys.readouterr().err

    def test_unknown_key_returns_2(self, tmp_path, monkeypatch, capsys):
        _write_yaml(tmp_path, "not_a_real_key: 1\n")
        monkeypatch.chdir(tmp_path)
        code = cli.main(["assess", "dummy.csv"])
        assert code == 2
        captured = capsys.readouterr()
        assert "Error:" in captured.err


# ---------------------------------------------------------------------------
# Parser defaults — --outdir produces None before _apply_dqt_config
# ---------------------------------------------------------------------------


class TestParserOutdirDefault:
    """After plan change, argparse --outdir default is None."""

    def test_export_star_outdir_defaults_to_none(self):
        parser = cli.build_parser()
        args = parser.parse_args(["export-star", "data.csv"])
        assert args.outdir is None

    def test_export_outdir_defaults_to_none(self):
        parser = cli.build_parser()
        args = parser.parse_args(["export", "data.csv"])
        assert args.outdir is None

    def test_compare_outdir_defaults_to_none(self):
        parser = cli.build_parser()
        args = parser.parse_args(["compare", "data.csv"])
        assert args.outdir is None

    def test_explicit_outdir_propagates(self):
        parser = cli.build_parser()
        args = parser.parse_args(["export-star", "data.csv", "--outdir", "./custom"])
        assert args.outdir == "./custom"
