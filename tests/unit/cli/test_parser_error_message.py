"""Tests for ParserError-specific message in main().

pd.errors.ParserError is a ValueError subclass, so it is already caught by
the existing except ValueError handler. Patch B adds a more specific, actionable
message for that case instead of printing the raw pandas error string.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import data_quality_toolkit.adapters.cli.main as cli


def _make_parser_raising(exc):
    """Return a fake parser whose func raises the given exception."""

    class _FakeParser:
        def parse_args(self, argv=None):  # noqa: ARG002
            def _raiser(_args):
                raise exc

            return SimpleNamespace(
                func=_raiser,
                log_level="INFO",
                log_format="json",
                csv="data.csv",
            )

    return _FakeParser()


class _FakeParserError(ValueError):
    """Minimal stand-in for pd.errors.ParserError (same __name__, same MRO)."""

    pass


_FakeParserError.__name__ = "ParserError"


def test_parser_error_returns_1(monkeypatch, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(
        cli,
        "build_parser",
        lambda: _make_parser_raising(_FakeParserError("Expected 3 fields, saw 4")),
    )
    rc = cli.main([])
    assert rc == 1


def test_parser_error_message_contains_detail(monkeypatch, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(
        cli,
        "build_parser",
        lambda: _make_parser_raising(_FakeParserError("Expected 3 fields, saw 4")),
    )
    cli.main([])
    err = capsys.readouterr().err
    assert "could not be parsed" in err
    assert "Expected 3 fields, saw 4" in err


def test_parser_error_message_contains_hint(monkeypatch, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(
        cli,
        "build_parser",
        lambda: _make_parser_raising(_FakeParserError("bad csv")),
    )
    cli.main([])
    err = capsys.readouterr().err
    assert "Hint:" in err
    assert "--sep" in err


def test_generic_value_error_unaffected(monkeypatch, capsys):
    """Non-ParserError ValueErrors still use the original handler."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(
        cli,
        "build_parser",
        lambda: _make_parser_raising(ValueError("something else went wrong")),
    )
    rc = cli.main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert "something else went wrong" in err
    # Must NOT claim it couldn't be parsed
    assert "could not be parsed" not in err


@pytest.mark.parametrize(
    "exc, code",
    [
        (FileNotFoundError("nope.csv"), 2),
        (PermissionError("blocked"), 13),
        (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "reason"), 22),
    ],
)
def test_other_exception_handlers_unaffected(monkeypatch, capsys, exc, code):
    """Existing exception mappings still work after the ParserError branch."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "build_parser", lambda: _make_parser_raising(exc))
    rc = cli.main([])
    assert rc == code
    assert "Error:" in capsys.readouterr().err
