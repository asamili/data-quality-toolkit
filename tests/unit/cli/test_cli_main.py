# tests/unit/cli/test_cli_main.py
from __future__ import annotations

import argparse
import json
import os

import data_quality_toolkit.adapters.cli.main as cli


def _ns(**kwargs):
    # Minimal argparse.Namespace builder with defaults used by helpers
    d = dict(sep=None, encoding=None, no_header=False, na_values=None, sample_size=None)
    d.update(kwargs)
    return argparse.Namespace(**d)


# ---------- helpers ----------


def test__csv_kwargs_from_args_basic():
    args = _ns(sep=";", encoding="latin-1", no_header=True, na_values="NA, NaN , null")
    out = cli._csv_kwargs_from_args(args)
    assert out == {
        "sep": ";",
        "encoding": "latin-1",
        "header": None,
        "na_values": ["NA", "NaN", "null"],
    }


def test__json_dump_prefers_model_dump_json_and_falls_back(monkeypatch, capsys):
    class HasModelDumpJson:
        def model_dump_json(self, indent=2):
            return '{"a": 1}'

    class HasDict:
        def dict(self):
            return {"b": 2}

    print(cli._json_dump(HasModelDumpJson()))
    print(cli._json_dump(HasDict()))
    print(cli._json_dump({"c": 3}))

    out = capsys.readouterr().out
    # Exact console output including newlines
    assert out == ('{"a": 1}\n' '{\n  "b": 2\n}\n' '{\n  "c": 3\n}\n')


# ---------- simple commands ----------


def test_cmd_settings_show_prints_json(monkeypatch, capsys):
    # Avoid hitting real Settings; return a tiny object with dict()
    class Dummy:
        def dict(self):  # pydantic v1 style
            return {"ok": True}

    monkeypatch.setattr(cli, "load_settings", lambda: Dummy())
    rc = cli.cmd_settings_show(argparse.Namespace())
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True


def test_cmd_version_prints(monkeypatch, capsys):
    monkeypatch.setattr(cli, "VERSION", "9.9.9")
    rc = cli.cmd_version(argparse.Namespace())
    assert rc == 0
    assert capsys.readouterr().out.strip() == "9.9.9"


def test_cmd_log_demo_with_exception(monkeypatch):
    # just ensure it returns 0 even when emitting an exception log
    rc = cli.cmd_log_demo(argparse.Namespace(raise_error=True))
    assert rc == 0


# ---------- commands that call pipeline ----------


def test_cmd_profile_passes_sample_size_explicit_no_env_mutation(monkeypatch, capsys):
    recorded = {}

    def fake_run_profile(csv, sample_size=None, **kw):
        recorded["csv"] = csv
        recorded["sample_size"] = sample_size
        recorded["kw"] = kw
        return {"ok": True}

    monkeypatch.setattr(cli, "run_profile", fake_run_profile)
    monkeypatch.delenv("SAMPLE_SIZE", raising=False)
    args = _ns(sep=",", encoding="utf-8", no_header=True, na_values="NA,NaN", sample_size=123)
    args.csv = "data.csv"
    rc = cli.cmd_profile(args)
    assert rc == 0

    # stdout is JSON
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True

    # sample_size passed as explicit named param (not via env)
    assert recorded["csv"] == "data.csv"
    assert recorded["sample_size"] == 123

    # CSV kwargs exclude sample_size (it travels as a named param)
    assert recorded["kw"] == {
        "sep": ",",
        "encoding": "utf-8",
        "header": None,
        "na_values": ["NA", "NaN"],
    }

    # env NOT mutated
    assert os.environ.get("SAMPLE_SIZE") is None


def test_cmd_assess(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **k: {"status": "ok"})
    args = _ns()
    args.csv = "x.csv"
    rc = cli.cmd_assess(args)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ok"


def test_cmd_export_star(monkeypatch, capsys, tmp_path):
    outpaths = {"dim_dataset": str(tmp_path / "star" / "dim_dataset.csv")}
    monkeypatch.setattr(cli, "run_export_star", lambda *a, **k: {"export_paths": outpaths})
    args = _ns()
    args.csv = "x.csv"
    args.outdir = str(tmp_path)
    rc = cli.cmd_export_star(args)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["export_paths"] == outpaths


# ---------- parser + main() ----------


def test_build_parser_wires_subcommands():
    p = cli.build_parser()

    a = p.parse_args(["version"])
    assert a.func is cli.cmd_version

    a = p.parse_args(["settings", "show"])
    assert a.func is cli.cmd_settings_show

    a = p.parse_args(["profile", "file.csv"])
    assert a.func is cli.cmd_profile and a.csv == "file.csv"

    a = p.parse_args(["assess", "file.csv"])
    assert a.func is cli.cmd_assess and a.csv == "file.csv"

    a = p.parse_args(["export-star", "file.csv", "--outdir", "dist"])
    assert a.func is cli.cmd_export_star and a.outdir == "dist"


def test_build_parser_export_alias():
    p = cli.build_parser()

    a = p.parse_args(["export", "file.csv", "--outdir", "dist"])
    assert a.func is cli.cmd_export_star
    assert a.csv == "file.csv"
    assert a.outdir == "dist"


def test_main_success(monkeypatch, capsys):
    # record setup_logging args
    called = {}
    monkeypatch.setattr(cli, "setup_logging", lambda **kw: called.update(kw))
    monkeypatch.setattr(cli, "run_profile", lambda *a, **k: {"ok": True})

    rc = cli.main(["--log-level", "DEBUG", "--log-format", "json", "profile", "x.csv"])
    assert rc == 0
    assert called == {"level": "DEBUG", "fmt": "json"}
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_main_file_not_found(monkeypatch, capsys):
    def boom(*a, **k):
        raise FileNotFoundError("nope.csv")

    monkeypatch.setattr(cli, "run_profile", boom)
    rc = cli.main(["profile", "x.csv"])
    assert rc == 2
    assert "Error:" in capsys.readouterr().err
