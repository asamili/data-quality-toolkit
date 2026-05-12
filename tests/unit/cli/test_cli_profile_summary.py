"""Tests for cmd_profile stderr summary."""

from __future__ import annotations

import argparse
import json

import data_quality_toolkit.cli.main as cli


def _ns(**kwargs):
    d = dict(sep=None, encoding=None, no_header=False, na_values=None, sample_size=None)
    d.update(kwargs)
    return argparse.Namespace(**d)


def _profile_out(rows=100, cols=3, memory_mb=1.5):
    return {
        "profile": {
            "rows": rows,
            "cols": cols,
            "memory_mb": memory_mb,
            "columns": [],
        },
    }


def test_cmd_profile_stderr_contains_header(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_profile", lambda *a, **k: _profile_out())
    cli.cmd_profile(_ns(csv="data.csv"))
    err = capsys.readouterr().err
    assert "Profile complete" in err


def test_cmd_profile_stderr_filename(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_profile", lambda *a, **k: _profile_out())
    cli.cmd_profile(_ns(csv="path/to/orders.csv"))
    err = capsys.readouterr().err
    assert "orders.csv" in err


def test_cmd_profile_stderr_rows_and_cols(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_profile", lambda *a, **k: _profile_out(rows=42, cols=7))
    cli.cmd_profile(_ns(csv="data.csv"))
    err = capsys.readouterr().err
    assert "Rows: 42" in err
    assert "Columns: 7" in err


def test_cmd_profile_stderr_memory(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_profile", lambda *a, **k: _profile_out(memory_mb=2.75))
    cli.cmd_profile(_ns(csv="data.csv"))
    err = capsys.readouterr().err
    assert "Memory: 2.75 MB" in err


def test_cmd_profile_stdout_is_still_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_profile", lambda *a, **k: _profile_out())
    rc = cli.cmd_profile(_ns(csv="data.csv"))
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "profile" in parsed


def test_cmd_profile_no_profile_key_does_not_crash(monkeypatch, capsys):
    """Output without profile key must not raise."""
    monkeypatch.setattr(cli, "run_profile", lambda *a, **k: {"status": "ok"})
    rc = cli.cmd_profile(_ns(csv="data.csv"))
    assert rc == 0
