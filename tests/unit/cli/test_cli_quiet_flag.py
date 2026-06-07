"""Tests for --quiet flag (DQT-PATCH-003-A): log suppression shorthand."""

from __future__ import annotations

import argparse
import json

import data_quality_toolkit.adapters.cli.main as cli

# ---------------------------------------------------------------------------
# Parser acceptance
# ---------------------------------------------------------------------------


def test_quiet_flag_accepted_by_parser():
    parser = cli.build_parser()
    args = parser.parse_args(["--quiet", "version"])
    assert args.quiet is True


def test_quiet_flag_default_is_false():
    parser = cli.build_parser()
    args = parser.parse_args(["version"])
    assert args.quiet is False


# ---------------------------------------------------------------------------
# Log-level override logic in main()
# ---------------------------------------------------------------------------


def test_quiet_sets_log_level_to_warning_when_no_explicit_log_level(monkeypatch):
    """--quiet alone must raise effective log level to WARNING."""
    captured: list[str] = []
    monkeypatch.setattr(
        cli,
        "setup_logging",
        lambda level=None, fmt=None: captured.append(level or ""),
    )
    monkeypatch.setattr("sys.argv", ["dqt", "--quiet", "version"])
    cli.main(["--quiet", "version"])
    assert captured and captured[0] == "WARNING"


def test_explicit_log_level_wins_over_quiet(monkeypatch):
    """Explicit --log-level must not be overridden by --quiet."""
    captured: list[str] = []
    monkeypatch.setattr(
        cli,
        "setup_logging",
        lambda level=None, fmt=None: captured.append(level or ""),
    )
    cli.main(["--quiet", "--log-level", "DEBUG", "version"])
    assert captured and captured[0] == "DEBUG"


def test_explicit_log_level_info_wins_over_quiet(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(
        cli,
        "setup_logging",
        lambda level=None, fmt=None: captured.append(level or ""),
    )
    cli.main(["--quiet", "--log-level", "INFO", "version"])
    assert captured and captured[0] == "INFO"


def test_no_quiet_no_explicit_log_level_passes_none(monkeypatch):
    """Without --quiet or --log-level, setup_logging receives level=None."""
    captured: list[str | None] = []
    monkeypatch.setattr(
        cli,
        "setup_logging",
        lambda level=None, fmt=None: captured.append(level),
    )
    cli.main(["version"])
    assert captured and captured[0] is None


# ---------------------------------------------------------------------------
# Output contract: stdout JSON and stderr human summary unaffected
# ---------------------------------------------------------------------------


def _profile_out():
    return {"profile": {"rows": 10, "cols": 3, "memory_mb": 0.5, "columns": []}}


def test_quiet_does_not_suppress_stdout_json(monkeypatch, capsys):
    """--quiet must not remove machine JSON from stdout."""
    monkeypatch.setattr(cli, "run_profile", lambda *a, **k: _profile_out())
    args = argparse.Namespace(
        csv="data.csv",
        sep=None,
        encoding=None,
        no_header=False,
        na_values=None,
        sample_size=None,
    )
    rc = cli.cmd_profile(args)
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "profile" in parsed


def test_quiet_does_not_suppress_stderr_human_summary(monkeypatch, capsys):
    """--quiet must not remove human-readable summary from stderr."""
    monkeypatch.setattr(cli, "run_profile", lambda *a, **k: _profile_out())
    args = argparse.Namespace(
        csv="data.csv",
        sep=None,
        encoding=None,
        no_header=False,
        na_values=None,
        sample_size=None,
    )
    cli.cmd_profile(args)
    err = capsys.readouterr().err
    assert "Profile complete" in err
