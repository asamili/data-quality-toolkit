"""Unit tests for the ``dqt ui`` launcher (v2.6.0).

Mirrors the existing ``test_cli_dashboard`` patterns: Streamlit and subprocess
are mocked, so no real Streamlit server is launched. The command is the preferred
entrypoint to the Drift Explorer and seeds ``DQT_UI_DB`` from ``--db``.
"""

from __future__ import annotations

import argparse
import os
import sys
from unittest.mock import MagicMock, patch

from data_quality_toolkit.adapters.cli import main as cli


def test_cmd_ui_missing_streamlit_returns_1(capsys):
    with patch.dict(sys.modules, {"streamlit": None}):
        rc = cli.cmd_ui(argparse.Namespace(db=None))
    assert rc == 1
    err = capsys.readouterr().err
    assert 'pip install "data-quality-toolkit[ui]"' in err


def test_cmd_ui_sets_dqt_ui_db_env(monkeypatch):
    # Isolate os.environ so the direct mutation in cmd_ui is auto-restored.
    monkeypatch.setattr(os, "environ", os.environ.copy())

    fake_result = MagicMock()
    fake_result.returncode = 0
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: fake_result)

    with patch.dict(sys.modules, {"streamlit": MagicMock()}):
        rc = cli.cmd_ui(argparse.Namespace(db="monitoring.db"))

    assert rc == 0
    assert os.environ["DQT_UI_DB"] == "monitoring.db"


def test_cmd_ui_without_db_does_not_set_env(monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    os.environ.pop("DQT_UI_DB", None)

    fake_result = MagicMock()
    fake_result.returncode = 0
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: fake_result)

    with patch.dict(sys.modules, {"streamlit": MagicMock()}):
        rc = cli.cmd_ui(argparse.Namespace(db=None))

    assert rc == 0
    assert "DQT_UI_DB" not in os.environ


def test_cmd_ui_invokes_streamlit_run_with_app_file(monkeypatch):
    captured: list[object] = []

    def fake_run(cmd, **_):
        captured.extend(cmd)
        result = MagicMock()
        result.returncode = 0
        return result

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    with patch.dict(sys.modules, {"streamlit": MagicMock()}):
        rc = cli.cmd_ui(argparse.Namespace(db=None))

    assert rc == 0
    assert captured[0] == sys.executable
    assert captured[1:4] == ["-m", "streamlit", "run"]
    assert str(captured[4]).endswith("app.py")


def test_cmd_ui_propagates_return_code(monkeypatch):
    fake_result = MagicMock()
    fake_result.returncode = 7
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: fake_result)

    with patch.dict(sys.modules, {"streamlit": MagicMock()}):
        rc = cli.cmd_ui(argparse.Namespace(db=None))

    assert rc == 7


def test_cmd_ui_keyboard_interrupt_returns_130(monkeypatch):
    def raise_kbi(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.subprocess, "run", raise_kbi)

    with patch.dict(sys.modules, {"streamlit": MagicMock()}):
        rc = cli.cmd_ui(argparse.Namespace(db=None))

    assert rc == 130


def test_cli_main_importable_without_streamlit():
    # The parser (and the registered `ui` command) must build with no Streamlit.
    with patch.dict(sys.modules, {"streamlit": None}):
        parser = cli.build_parser()
    ns = parser.parse_args(["ui", "--db", "monitoring.db"])
    assert ns.func is cli.cmd_ui
    assert ns.db == "monitoring.db"


def test_cli_ui_db_optional():
    parser = cli.build_parser()
    ns = parser.parse_args(["ui"])
    assert ns.func is cli.cmd_ui
    assert getattr(ns, "db", None) is None
