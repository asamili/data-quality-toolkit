# cspell:ignore José Café
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

# Ensure subprocess picks up our src/ rather than any other editable install
_SRC = str(Path(__file__).resolve().parents[2] / "src")
_SUBPROCESS_ENV = {**os.environ, "PYTHONPATH": _SRC + os.pathsep + os.environ.get("PYTHONPATH", "")}

pytestmark = pytest.mark.integration  # only runs when you include -m integration


def _csv(tmp: Path) -> Path:
    p = tmp / "cli_small.csv"
    p.write_text(
        (
            "id,name,age,score\n"
            "1,Alice,25,95.5\n"
            "2,Bob,30,87.2\n"
            "3,Charlie,,76.8\n"
            "4,Diana,28,92.1\n"
            "5,Eve,35,88.9\n"
        ),
        encoding="utf-8",
    )
    return p


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """
    Run the CLI via module entry so it works reliably in editable installs & on Windows.
    Returns CompletedProcess with text output.

    Safety: validate subcommand/flags before invoking subprocess to avoid untrusted input (Ruff S603).
    """
    # --- minimal allowlist for test invocations ---
    allowed_cmds = {
        "profile",
        "assess",
        "export-star",
        "export",
        "settings",
        "version",
        "log-demo",
        "build-pbi",
        "plan",
        "pipeline",
    }
    allowed_flags = {
        "--outdir",
        "--sep",
        "--encoding",
        "--na-values",
        "--no-header",
        "--sample-size",
        "--raise-error",
        "--time-start",
        "--time-end",
        "--base-folder",
        "--star",
        "--out",
        "--fiscal",
        "--score-field",
        "--run-id",
        "--sessions-root",
        "--extract",
        "--transform",
        "--load",
        "--assess",
        "--manifest",
    }

    if args:
        assert args[0] in allowed_cmds, f"unsupported subcommand: {args[0]}"

    i = 1
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            assert a in allowed_flags, f"unsupported flag: {a}"
            if a in {
                "--outdir",
                "--sep",
                "--encoding",
                "--na-values",
                "--sample-size",
                "--time-start",
                "--time-end",
                "--base-folder",
                "--star",
                "--out",
                "--fiscal",
                "--run-id",
                "--sessions-root",
                "--extract",
                "--transform",
                "--load",
            }:
                i += 1  # skip the value
        i += 1

    cmd = [
        sys.executable,
        "-m",
        "data_quality_toolkit.adapters.cli.main",
        "--log-level",
        "ERROR",  # suppress INFO logs so stdout is pure JSON
        "--log-format",
        "json",
        *args,
    ]
    # Args are validated above; shell=False; executable is sys.executable (trusted).
    return subprocess.run(cmd, capture_output=True, text=True, env=_SUBPROCESS_ENV)  # noqa: S603


def test_cli_profile_assess_export_star(tmp_path: Path):
    csv = _csv(tmp_path)

    # profile
    r1 = _run_cli("profile", str(csv))
    assert r1.returncode == 0, r1.stderr
    prof_out = json.loads(r1.stdout)
    assert {"run_id", "dataset_id", "ts", "meta", "profile"} <= set(prof_out)
    assert prof_out["profile"]["rows"] == 5
    assert prof_out["profile"]["cols"] == 4

    # assess
    r2 = _run_cli("assess", str(csv))
    assert r2.returncode == 0, r2.stderr
    assess_out = json.loads(r2.stdout)
    assert "assessment" in assess_out
    assert 0.0 <= assess_out["assessment"]["score"] <= 1.0
    assert isinstance(assess_out["assessment"]["issues"], list)

    # export-star (write into tmp_path so we don't touch repo dist/)
    outdir = tmp_path / "out"
    r3 = _run_cli("export-star", str(csv), "--outdir", str(outdir))
    assert r3.returncode == 0, r3.stderr
    star_out = json.loads(r3.stdout)
    assert {"export_paths", "star"} <= set(star_out)

    # verify star files exist and are non-empty
    paths = star_out["export_paths"]
    for name in ["dim_dataset", "dim_column", "fact_profile_runs", "fact_quality_metrics"]:
        fp = Path(paths[name])
        assert fp.exists(), f"missing {name} at {fp}"
        df = pd.read_csv(fp)
        assert len(df) > 0

    # relationships.json present & well-formed
    rel = Path(paths["relationships"])
    assert rel.exists()
    rel_json = json.loads(rel.read_text(encoding="utf-8"))
    assert "relationships" in rel_json and len(rel_json["relationships"]) == 3


def test_cli_missing_file_returns_code_2(tmp_path: Path):
    missing = tmp_path / "does_not_exist.csv"
    r = _run_cli("profile", str(missing))
    assert r.returncode == 2
    assert "Error:" in r.stderr


def test_cli_profile_with_sep_encoding_na_values(tmp_path: Path):
    """
    Ensure the CLI correctly honors --sep, --encoding, and --na-values.
    We write a Latin-1 encoded, semicolon-delimited CSV with an 'NA' token
    and verify that 'age' has exactly one null after parsing.
    """
    csv = tmp_path / "latin_semicolon.csv"
    csv.write_text(
        "id;name;age\n1;Café;30\n2;José;NA\n",  # merged into a single literal (no implicit concat)
        encoding="latin-1",
    )

    cp = _run_cli(
        "profile",
        str(csv),
        "--sep",
        ";",
        "--encoding",
        "latin-1",
        "--na-values",
        "NA",
    )
    assert cp.returncode == 0, cp.stderr

    out = json.loads(cp.stdout)
    assert out["profile"]["rows"] == 2
    assert out["profile"]["cols"] == 3

    # Find column profile for 'age' and validate that NA was parsed as missing
    age = next(c for c in out["profile"]["columns"] if c["name"] == "age")
    assert age["nulls"] == 1


def test_cli_pipeline_run_smoke(tmp_path: Path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    r = _run_cli(
        "pipeline",
        "run",
        "--run-id",
        "smoke",
        "--sessions-root",
        str(sessions),
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["run_id"] == "smoke"
    assert out["status"] == "success"
    assert out["steps_executed"] == []
    assert out["manifest"] is None
