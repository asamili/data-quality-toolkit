"""Unit tests for dqt dashboard CLI subcommand."""

from __future__ import annotations

import argparse
import sys
from unittest.mock import MagicMock, patch

import data_quality_toolkit.cli.main as cli


def test_build_parser_wires_dashboard() -> None:
    p = cli.build_parser()
    a = p.parse_args(["dashboard"])
    assert a.func is cli.cmd_dashboard


def test_cmd_dashboard_missing_streamlit_returns_1(capsys: object) -> None:
    with patch.dict(sys.modules, {"streamlit": None}):
        rc = cli.cmd_dashboard(argparse.Namespace())
    assert rc == 1
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "pip install data-quality-toolkit[ui]" in captured.err


def test_cmd_dashboard_calls_subprocess_with_app_file(monkeypatch: object) -> None:
    fake_result = MagicMock()
    fake_result.returncode = 0

    captured_args: list[object] = []

    def fake_run(cmd: list[str], **_: object) -> MagicMock:
        captured_args.extend(cmd)
        return fake_result

    monkeypatch.setattr(cli.subprocess, "run", fake_run)  # type: ignore[attr-defined]

    rc = cli.cmd_dashboard(argparse.Namespace())

    assert rc == 0
    assert captured_args[0] == sys.executable
    assert captured_args[1] == "-m"
    assert captured_args[2] == "streamlit"
    assert captured_args[3] == "run"
    assert str(captured_args[4]).endswith("app.py")


def test_cmd_dashboard_propagates_exit_code(monkeypatch: object) -> None:
    fake_result = MagicMock()
    fake_result.returncode = 42
    monkeypatch.setattr(cli.subprocess, "run", lambda *_a, **_k: fake_result)  # type: ignore[attr-defined]

    rc = cli.cmd_dashboard(argparse.Namespace())
    assert rc == 42
