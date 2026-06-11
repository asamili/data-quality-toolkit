"""Tests for the --json-errors global flag."""

from __future__ import annotations

import json

import pytest

import data_quality_toolkit.adapters.cli.main as cli_mod
from data_quality_toolkit.adapters.cli.main import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_csv(tmp_path, content: str = "col\n1\n2\n") -> str:
    p = tmp_path / "test.csv"
    p.write_text(content, encoding="utf-8")
    return str(p)


class _FakeParserError(ValueError):
    """Stand-in for pd.errors.ParserError (ValueError subclass with __name__ == "ParserError")."""


_FakeParserError.__name__ = "ParserError"
_FakeParserError.__qualname__ = "ParserError"


# ---------------------------------------------------------------------------
# FileNotFoundError → exit 2, stderr JSON, stdout empty
# ---------------------------------------------------------------------------


def test_json_errors_file_not_found(tmp_path, capsys):
    missing = str(tmp_path / "does_not_exist.csv")
    rc = main(["--json-errors", "profile", missing])
    assert rc == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    parsed = json.loads(captured.err)
    assert parsed["error"]["code"] == "FILE_NOT_FOUND"
    assert parsed["error"]["exc_type"] == "FileNotFoundError"
    assert "message" in parsed["error"]


# ---------------------------------------------------------------------------
# PermissionError → exit 13, stderr JSON, stdout empty
# ---------------------------------------------------------------------------


def test_json_errors_permission_error(tmp_path, capsys, monkeypatch):
    csv = _make_csv(tmp_path)

    def _raise(*a, **kw):
        raise PermissionError("access denied")

    monkeypatch.setattr(cli_mod, "run_profile", _raise)
    rc = main(["--json-errors", "profile", csv])
    assert rc == 13
    captured = capsys.readouterr()
    assert captured.out == ""
    parsed = json.loads(captured.err)
    assert parsed["error"]["code"] == "PERMISSION_DENIED"
    assert parsed["error"]["exc_type"] == "PermissionError"


# ---------------------------------------------------------------------------
# UnicodeDecodeError → exit 22, stderr JSON, stdout empty
# ---------------------------------------------------------------------------


def test_json_errors_unicode_decode_error(tmp_path, capsys, monkeypatch):
    csv = _make_csv(tmp_path)

    def _raise(*a, **kw):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(cli_mod, "run_profile", _raise)
    rc = main(["--json-errors", "profile", csv])
    assert rc == 22
    captured = capsys.readouterr()
    assert captured.out == ""
    parsed = json.loads(captured.err)
    assert parsed["error"]["code"] == "DECODE_ERROR"
    assert parsed["error"]["exc_type"] == "UnicodeDecodeError"


# ---------------------------------------------------------------------------
# ValueError → exit 1, stderr JSON, stdout empty
# ---------------------------------------------------------------------------


def test_json_errors_value_error(tmp_path, capsys, monkeypatch):
    csv = _make_csv(tmp_path)

    def _raise(*a, **kw):
        raise ValueError("bad value in data")

    monkeypatch.setattr(cli_mod, "run_profile", _raise)
    rc = main(["--json-errors", "profile", csv])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    parsed = json.loads(captured.err)
    assert parsed["error"]["code"] == "VALUE_ERROR"
    assert "bad value in data" in parsed["error"]["message"]


# ---------------------------------------------------------------------------
# ParserError (ValueError subclass) → exit 1, JSON with hint
# ---------------------------------------------------------------------------


def test_json_errors_parser_error(tmp_path, capsys, monkeypatch):
    csv = _make_csv(tmp_path)

    def _raise(*a, **kw):
        raise _FakeParserError("Expected 3 fields, saw 4")

    monkeypatch.setattr(cli_mod, "run_profile", _raise)
    rc = main(["--json-errors", "profile", csv])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    parsed = json.loads(captured.err)
    assert parsed["error"]["code"] == "VALUE_ERROR"
    assert parsed["error"]["exc_type"] == "ParserError"
    assert "parsed" in parsed["error"]["message"].lower()
    assert "hint" in parsed["error"]
    assert "--sep" in parsed["error"]["hint"]


# ---------------------------------------------------------------------------
# Without --json-errors: text format preserved (regression guard)
# ---------------------------------------------------------------------------


def test_no_json_errors_flag_preserves_text_mode(tmp_path, capsys):
    missing = str(tmp_path / "does_not_exist.csv")
    rc = main(["profile", missing])
    assert rc == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Error:" in captured.err
    with pytest.raises(json.JSONDecodeError):
        json.loads(captured.err)


# ---------------------------------------------------------------------------
# JSON shape: top-level "error" key with required fields
# ---------------------------------------------------------------------------


def test_json_errors_shape_has_required_keys(tmp_path, capsys):
    missing = str(tmp_path / "does_not_exist.csv")
    main(["--json-errors", "profile", missing])
    captured = capsys.readouterr()
    parsed = json.loads(captured.err)
    error = parsed["error"]
    assert "code" in error
    assert "message" in error
    assert "exc_type" in error


# ---------------------------------------------------------------------------
# stdout stays empty even with --json-errors on error
# ---------------------------------------------------------------------------


def test_json_errors_stdout_empty_on_error(tmp_path, capsys, monkeypatch):
    csv = _make_csv(tmp_path)

    def _raise(*a, **kw):
        raise PermissionError("denied")

    monkeypatch.setattr(cli_mod, "run_profile", _raise)
    main(["--json-errors", "profile", csv])
    assert capsys.readouterr().out == ""
