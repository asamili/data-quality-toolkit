"""Tests that loader ValueError surfaces as a clean actionable CLI error."""

from __future__ import annotations

import pytest

import data_quality_toolkit.adapters.cli.main as cli


def _empty_csv(tmp_path):
    f = tmp_path / "empty.csv"
    f.write_bytes(b"")
    return str(f)


@pytest.mark.parametrize("command", ["profile", "assess"])
def test_empty_csv_exits_with_1(monkeypatch, tmp_path, command):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    rc = cli.main([command, _empty_csv(tmp_path)])
    assert rc == 1


@pytest.mark.parametrize("command", ["profile", "assess"])
def test_empty_csv_shows_error_message(monkeypatch, capsys, tmp_path, command):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    cli.main([command, _empty_csv(tmp_path)])
    stderr = capsys.readouterr().err
    assert "Error:" in stderr
    assert "empty" in stderr.lower() or "no columns" in stderr.lower()


@pytest.mark.parametrize("command", ["profile", "assess"])
def test_empty_csv_shows_hint_and_example(monkeypatch, capsys, tmp_path, command):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    cli.main([command, _empty_csv(tmp_path)])
    stderr = capsys.readouterr().err
    assert "Hint:" in stderr
    assert "Example:" in stderr
    assert "dqt profile" in stderr


def test_non_csv_value_error_no_hint(monkeypatch, capsys):
    """ValueError from a non-CSV command must not show the CSV hint."""
    from types import SimpleNamespace

    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)

    class _FakeParser:
        def parse_args(self, argv=None):  # noqa: ARG002
            def _raiser(_args):  # noqa: ANN001
                raise ValueError("some unrelated value error")

            return SimpleNamespace(
                func=_raiser,
                log_level=None,
                log_format=None,
                # no csv attribute — simulates a non-CSV command
            )

    monkeypatch.setattr(cli, "build_parser", lambda: _FakeParser())
    rc = cli.main([])
    assert rc == 1
    stderr = capsys.readouterr().err
    assert "Hint:" not in stderr
    assert "some unrelated value error" in stderr
