"""Tests for blank/whitespace-only CSV path validation in the CLI."""

from types import SimpleNamespace

import pytest

import data_quality_toolkit.cli.main as cli


@pytest.mark.parametrize("blank", ["", "   ", "\t", " \t "])
def test_blank_csv_path_returns_2(monkeypatch, blank, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    rc = cli.main(["profile", blank])
    assert rc == 2
    assert "blank" in capsys.readouterr().err.lower()


def test_whitespace_only_path_message(monkeypatch, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    rc = cli.main(["assess", "   "])
    assert rc == 2
    stderr = capsys.readouterr().err
    assert "Error:" in stderr


def test_valid_path_not_intercepted(monkeypatch):
    """A non-blank path passes validation (handler may fail for other reasons)."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "run_profile", lambda *a, **kw: {"columns": []})
    cli.main(["profile", "data.csv"])
    # The blank-path guard should not fire — verify directly via the helper
    args = SimpleNamespace(csv="data.csv")
    assert cli._validate_csv_path(args) is None


def test_no_csv_attr_is_safe():
    """Commands without a csv arg (e.g. version) are not affected."""
    args = SimpleNamespace()  # no csv attribute
    assert cli._validate_csv_path(args) is None


@pytest.mark.parametrize("blank", ["", "   "])
def test_validate_csv_path_helper_returns_message(blank):
    args = SimpleNamespace(csv=blank)
    result = cli._validate_csv_path(args)
    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0
