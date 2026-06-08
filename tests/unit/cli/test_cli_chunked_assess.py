from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

import data_quality_toolkit.adapters.cli.main as cli


def _ns(**kwargs: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "sep": None,
        "encoding": None,
        "no_header": False,
        "na_values": None,
        "sample_size": None,
        "no_json": False,
        "null_threshold": None,
        "fail_under": None,
        "score_field": "score",
        "db": None,
        "chunksize": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _chunked_assess_out(rows: int = 4, cols: int = 3) -> dict[str, Any]:
    return {
        "run_id": "r1",
        "dataset_id": "sha1:abc",
        "ts": "2024-01-01T00:00:00Z",
        "duration_secs": 0.01,
        "meta": {"chunksize": 2},
        "profile": {"rows": rows, "cols": cols, "memory_mb": None, "columns": []},
        "approximate": True,
        "assessment": {
            "run_id": "r1",
            "dataset_id": "sha1:abc",
            "ts": "2024-01-01T00:00:00Z",
            "score": 0.9,
            "completeness_score": 0.9,
            "issues": [],
            "assessment_mode": "chunked",
            "approximate": True,
            "unsupported_rules": [
                "constant_column",
                "high_cardinality",
                "numeric_outliers",
                "accepted_values_violation",
                "uniqueness_violation",
            ],
        },
    }


# --- parser ---


def test_assess_parser_has_chunksize() -> None:
    p = cli.build_parser()
    args = p.parse_args(["assess", "data.csv", "--chunksize", "100"])
    assert args.chunksize == 100


def test_assess_parser_chunksize_default_is_none() -> None:
    p = cli.build_parser()
    args = p.parse_args(["assess", "data.csv"])
    assert args.chunksize is None


# --- cmd_assess unit (monkeypatch) ---


def test_cmd_assess_chunked_routes_to_run_assessment_chunked(monkeypatch, capsys) -> None:
    called: dict[str, Any] = {}

    def fake_chunked(csv: str, chunksize: int, **kw: Any) -> dict[str, Any]:
        called["csv"] = csv
        called["chunksize"] = chunksize
        return _chunked_assess_out()

    monkeypatch.setattr(cli, "run_assessment_chunked", fake_chunked)
    rc = cli.cmd_assess(_ns(csv="data.csv", chunksize=2))
    assert rc == 0
    assert called["chunksize"] == 2


def test_cmd_assess_chunked_stdout_has_assessment_mode(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "run_assessment_chunked", lambda *a, **k: _chunked_assess_out())
    cli.cmd_assess(_ns(csv="data.csv", chunksize=2))
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["assessment"]["assessment_mode"] == "chunked"


def test_cmd_assess_chunked_stderr_mentions_partial_or_chunked(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "run_assessment_chunked", lambda *a, **k: _chunked_assess_out())
    cli.cmd_assess(_ns(csv="data.csv", chunksize=2))
    err = capsys.readouterr().err
    assert "partial" in err.lower() or "chunked" in err.lower()


def test_cmd_assess_no_chunksize_uses_full_load(monkeypatch, capsys) -> None:
    called: dict[str, bool] = {}

    def fake_run(csv: str, sample_size: Any = None, **kw: Any) -> dict[str, Any]:
        called["used"] = True
        return {
            "run_id": "r1",
            "dataset_id": "sha1:abc",
            "ts": "2024-01-01T00:00:00Z",
            "duration_secs": 0.01,
            "meta": {},
            "profile": {"rows": 4, "cols": 3, "memory_mb": 0.1, "columns": []},
            "assessment": {
                "run_id": "r1",
                "dataset_id": "sha1:abc",
                "ts": "2024-01-01T00:00:00Z",
                "score": 0.9,
                "completeness_score": 0.9,
                "quality_score": 0.85,
                "issues": [],
            },
        }

    monkeypatch.setattr(cli, "run_assessment", fake_run)
    cli.cmd_assess(_ns(csv="data.csv", chunksize=None))
    assert called.get("used") is True


# --- integration smoke (real CSV) ---


@pytest.fixture
def tiny_csv(tmp_path: Path) -> Path:
    p = tmp_path / "t.csv"
    p.write_text("x,y\n1,10\n2,20\n3,30\n", encoding="utf-8")
    return p


def test_main_assess_chunked_exits_zero(tiny_csv: Path, capsys) -> None:
    rc = cli.main(["assess", str(tiny_csv), "--chunksize", "2"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["assessment"]["assessment_mode"] == "chunked"
    assert payload["approximate"] is True
    assert payload["profile"]["rows"] == 3
