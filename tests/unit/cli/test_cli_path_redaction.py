"""Tests that human-facing CLI error output redacts absolute local paths.

The absolute paths used here (Windows ``C:\\Users\\example_user\\...`` and POSIX
``/home/...``) are *fixtures*: each test asserts the private directory/username is
stripped from stderr, proving the caller-side redaction. The ``--json-errors``
(machine) surface is asserted to keep raw paths, since it is the programmatic
output. No real private path is emitted by the toolkit.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import data_quality_toolkit.adapters.cli.main as cli


def _make_parser_raising(exc, csv: str):
    """Fake parser whose handler raises *exc*; ``csv`` feeds path validation."""

    class _FakeParser:
        def parse_args(self, argv=None):  # noqa: ARG002
            def _raiser(_args):  # noqa: ANN001
                raise exc

            return SimpleNamespace(
                func=_raiser,
                log_level="INFO",
                log_format="json",
                csv=csv,
            )

    return _FakeParser()


# --- human error output redaction -----------------------------------------


def test_windows_absolute_path_redacted_in_human_output(monkeypatch, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    path = r"C:\Users\example_user\private\customers.csv"
    exc = FileNotFoundError(2, "No such file or directory", path)
    monkeypatch.setattr(cli, "build_parser", lambda: _make_parser_raising(exc, path))

    rc = cli.main([])
    stderr = capsys.readouterr().err

    assert rc == 2
    assert "<path:customers.csv>" in stderr  # basename preserved
    assert "example_user" not in stderr
    assert "Users" not in stderr
    assert "private" not in stderr
    assert "C:\\" not in stderr


def test_posix_absolute_path_redacted_in_human_output(monkeypatch, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    path = "/home/user/data/customers.csv"
    exc = FileNotFoundError(2, "No such file or directory", path)
    monkeypatch.setattr(cli, "build_parser", lambda: _make_parser_raising(exc, path))

    cli.main([])
    stderr = capsys.readouterr().err

    assert "<path:customers.csv>" in stderr  # basename preserved
    assert "/home" not in stderr
    assert "user" not in stderr


def test_non_path_message_not_mangled(monkeypatch, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    exc = ValueError("bad value in data")
    monkeypatch.setattr(cli, "build_parser", lambda: _make_parser_raising(exc, "data.csv"))

    rc = cli.main([])
    stderr = capsys.readouterr().err

    assert rc == 1
    assert "bad value in data" in stderr
    assert "<path" not in stderr


# --- programmatic (--json-errors) output stays raw ------------------------


def test_json_errors_mode_preserves_raw_path(tmp_path, capsys):
    missing = str(tmp_path / "secret_dir" / "data.csv")
    rc = cli.main(["--json-errors", "profile", missing])
    captured = capsys.readouterr()

    assert rc == 2
    parsed = json.loads(captured.err)
    # JSON is the programmatic surface: the raw path is intentionally preserved.
    assert "secret_dir" in parsed["error"]["message"]
    assert "<path:" not in parsed["error"]["message"]


def test_human_mode_redacts_same_real_missing_path(tmp_path, capsys):
    missing = str(tmp_path / "secret_dir" / "data.csv")
    rc = cli.main(["profile", missing])
    captured = capsys.readouterr()

    assert rc == 2
    assert "<path:data.csv>" in captured.err
    assert "secret_dir" not in captured.err
