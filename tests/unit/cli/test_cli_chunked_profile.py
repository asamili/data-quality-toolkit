from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

import data_quality_toolkit.adapters.cli.main as cli


def _ns(**kwargs):
    defaults = {
        "sep": None,
        "encoding": None,
        "no_header": False,
        "na_values": None,
        "sample_size": None,
        "no_json": False,
        "chunksize": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _chunked_out(rows=8, cols=2):
    return {
        "run_id": "r1",
        "dataset_id": "sha1:abc",
        "ts": "2024-01-01T00:00:00Z",
        "meta": {"chunksize": 2},
        "profile": {"rows": rows, "cols": cols, "memory_mb": None, "columns": []},
        "approximate": True,
        "unsupported_metrics": ["unique", "memory_mb"],
    }


# --- cmd_profile unit (monkeypatch) ---


def test_cmd_profile_chunked_calls_run_profile_chunked(monkeypatch, capsys):
    called = {}

    def fake_chunked(csv, chunksize, **kw):
        called["csv"] = csv
        called["chunksize"] = chunksize
        return _chunked_out()

    monkeypatch.setattr(cli, "run_profile_chunked", fake_chunked)
    rc = cli.cmd_profile(_ns(csv="data.csv", chunksize=2))
    assert rc == 0
    assert called["chunksize"] == 2


def test_cmd_profile_chunked_stdout_json_has_approximate(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_profile_chunked", lambda *a, **k: _chunked_out())
    cli.cmd_profile(_ns(csv="data.csv", chunksize=2))
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["approximate"] is True
    assert "memory_mb" in payload["unsupported_metrics"]


def test_cmd_profile_chunked_stderr_note(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_profile_chunked", lambda *a, **k: _chunked_out())
    cli.cmd_profile(_ns(csv="data.csv", chunksize=2))
    err = capsys.readouterr().err
    assert "chunked" in err.lower()


def test_cmd_profile_chunked_memory_mb_none_not_printed(monkeypatch, capsys):
    """memory_mb=None must not crash with %.2f formatting."""
    monkeypatch.setattr(cli, "run_profile_chunked", lambda *a, **k: _chunked_out())
    rc = cli.cmd_profile(_ns(csv="data.csv", chunksize=2))
    assert rc == 0
    err = capsys.readouterr().err
    assert "Memory:" not in err


def test_cmd_profile_no_chunksize_still_calls_run_profile(monkeypatch, capsys):
    """chunksize=None must route to original run_profile."""
    called: dict[str, bool] = {}

    def fake_run_profile(*a: Any, **k: Any) -> dict[str, Any]:
        called["used"] = True
        return {"profile": {"rows": 1, "cols": 1, "memory_mb": 0.1, "columns": []}}

    monkeypatch.setattr(cli, "run_profile", fake_run_profile)
    cli.cmd_profile(_ns(csv="data.csv", chunksize=None))
    assert called.get("used") is True


# --- parser smoke ---


def test_profile_parser_accepts_chunksize():
    p = cli.build_parser()
    args = p.parse_args(["profile", "data.csv", "--chunksize", "1000"])
    assert args.chunksize == 1000


def test_profile_parser_chunksize_default_is_none():
    p = cli.build_parser()
    args = p.parse_args(["profile", "data.csv"])
    assert args.chunksize is None


# --- integration smoke (real CSV) ---


@pytest.fixture
def tiny_csv(tmp_path: Path) -> Path:
    p = tmp_path / "t.csv"
    p.write_text("x,y\n1,10\n2,20\n3,30\n", encoding="utf-8")
    return p


def test_main_profile_chunked_exits_zero(tiny_csv: Path, capsys) -> None:
    rc = cli.main(["profile", str(tiny_csv), "--chunksize", "2"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["approximate"] is True
    assert payload["profile"]["rows"] == 3
