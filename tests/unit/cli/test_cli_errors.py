from types import SimpleNamespace

import pytest

import data_quality_toolkit.adapters.cli.main as cli


def _make_fake_parser(exc_to_raise, log_level="INFO", log_format="json"):
    """Return a fake parser object that yields a namespace with a func that raises."""

    class _FakeParser:
        def parse_args(self, argv=None):  # noqa: ARG002
            def _raiser(_args):  # noqa: ANN001
                raise exc_to_raise

            return SimpleNamespace(
                func=_raiser,
                log_level=log_level,
                log_format=log_format,
            )

    return _FakeParser()


@pytest.mark.parametrize(
    "exc, code",
    [
        (FileNotFoundError("nope.csv"), 2),
        (PermissionError("blocked"), 13),
        (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "reason"), 22),
        (ValueError("bad value"), 1),
    ],
)
def test_main_exception_mappings(monkeypatch, exc, code, capsys):
    # prevent real logging configuration noise
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    # replace the parser with our fake one
    monkeypatch.setattr(cli, "build_parser", lambda: _make_fake_parser(exc))
    rc = cli.main([])
    stderr = capsys.readouterr().err
    assert rc == code
    assert "Error:" in stderr


def test__safe_text_ascii_fallback(monkeypatch):
    # Force an ASCII-only stdout so '✓' is not encodable
    class _Dummy:
        encoding = "ascii"

    monkeypatch.setattr(cli.sys, "stdout", _Dummy())
    out = cli._safe_text("✓", "[OK]")
    assert out == "[OK]"
