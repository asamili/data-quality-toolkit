"""Tests for the actionable FileNotFoundError message in the CLI."""

from types import SimpleNamespace

import data_quality_toolkit.cli.main as cli


def _make_fnf_parser(path: str, log_level: str = "INFO", log_format: str = "json"):
    """Fake parser that raises FileNotFoundError with a filename attribute."""

    class _FakeParser:
        def parse_args(self, argv=None):  # noqa: ARG002
            exc = FileNotFoundError(2, "No such file or directory", path)

            def _raiser(_args):  # noqa: ANN001
                raise exc

            return SimpleNamespace(
                func=_raiser,
                log_level=log_level,
                log_format=log_format,
                csv=path,
            )

    return _FakeParser()


def test_file_not_found_returns_2(monkeypatch, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "build_parser", lambda: _make_fnf_parser("missing.csv"))
    rc = cli.main([])
    assert rc == 2


def test_file_not_found_shows_path(monkeypatch, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "build_parser", lambda: _make_fnf_parser("sales_2024.csv"))
    cli.main([])
    stderr = capsys.readouterr().err
    assert "sales_2024.csv" in stderr


def test_file_not_found_shows_hint(monkeypatch, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "build_parser", lambda: _make_fnf_parser("data.csv"))
    cli.main([])
    stderr = capsys.readouterr().err
    assert "Hint:" in stderr


def test_file_not_found_shows_example(monkeypatch, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "build_parser", lambda: _make_fnf_parser("data.csv"))
    cli.main([])
    stderr = capsys.readouterr().err
    assert "Example:" in stderr
    assert "dqt profile" in stderr
