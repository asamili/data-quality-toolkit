"""Tests for the actionable missing-CSV-argument error message in the CLI."""

import pytest

import data_quality_toolkit.adapters.cli.main as cli


def _run_missing_csv(monkeypatch, command: str):
    """Run a command that requires csv but omit the path; return (exit_code, stderr)."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    with pytest.raises(SystemExit) as exc_info:
        cli.main([command])
    return exc_info.value.code, exc_info.value


@pytest.mark.parametrize("command", ["profile", "assess", "export-star", "export"])
def test_missing_csv_exits_with_2(monkeypatch, command):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    with pytest.raises(SystemExit) as exc_info:
        cli.main([command])
    assert exc_info.value.code == 2


@pytest.mark.parametrize("command", ["profile", "assess"])
def test_missing_csv_shows_hint(monkeypatch, capsys, command):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    with pytest.raises(SystemExit):
        cli.main([command])
    stderr = capsys.readouterr().err
    assert "Hint:" in stderr


@pytest.mark.parametrize("command", ["profile", "assess"])
def test_missing_csv_shows_example(monkeypatch, capsys, command):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    with pytest.raises(SystemExit):
        cli.main([command])
    stderr = capsys.readouterr().err
    assert "Example:" in stderr
    assert "dqt profile" in stderr


def test_missing_csv_shows_prog_name(monkeypatch, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    with pytest.raises(SystemExit):
        cli.main(["profile"])
    stderr = capsys.readouterr().err
    assert "dqt" in stderr


def test_unrelated_error_no_hint(monkeypatch, capsys):
    """Errors unrelated to missing csv should not show the csv hint."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    # Omit the top-level command entirely — triggers "command required" error, not csv
    with pytest.raises(SystemExit):
        cli.main([])
    stderr = capsys.readouterr().err
    assert "Hint:" not in stderr
