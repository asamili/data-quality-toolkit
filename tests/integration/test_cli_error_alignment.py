"""Integration tests: CLI exit codes and error output use the shared error contract."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_SRC = str(Path(__file__).resolve().parents[2] / "src")
_SUBPROCESS_ENV = {**os.environ, "PYTHONPATH": _SRC + os.pathsep + os.environ.get("PYTHONPATH", "")}


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        "-m",
        "data_quality_toolkit.adapters.cli.main",
        "--log-level",
        "ERROR",
        "--log-format",
        "json",
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, env=_SUBPROCESS_ENV)  # noqa: S603


# ── FileNotFoundError → exit 2 ────────────────────────────────────────────────


def test_missing_csv_exit_2_and_error_prefix(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.csv"
    r = _run_cli("profile", str(missing))
    assert r.returncode == 2
    assert "Error:" in r.stderr


def test_missing_csv_stderr_contains_filename(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.csv"
    r = _run_cli("profile", str(missing))
    assert r.returncode == 2
    assert "does_not_exist.csv" in r.stderr


# ── UnicodeDecodeError → exit 22 ─────────────────────────────────────────────


def test_bad_encoding_exit_22_and_error_prefix(tmp_path: Path) -> None:
    csv = tmp_path / "latin.csv"
    # Write latin-1 bytes that are invalid UTF-8
    csv.write_bytes(b"id,name\n1,Caf\xe9\n")
    r = _run_cli("profile", str(csv))
    assert r.returncode == 22
    assert "Error:" in r.stderr


# ── ValueError → exit 1 ──────────────────────────────────────────────────────


def test_malformed_csv_value_error_exit_1(tmp_path: Path) -> None:
    csv = tmp_path / "bad.csv"
    # Inconsistent column count triggers pd ParserError (ValueError subclass)
    csv.write_text("a,b,c\n1,2\n3,4,5,6\n", encoding="utf-8")
    r = _run_cli("profile", str(csv))
    assert r.returncode == 1
    assert "Error:" in r.stderr


# ── Stdout stays clean on error ───────────────────────────────────────────────


def test_error_output_goes_to_stderr_not_stdout(tmp_path: Path) -> None:
    missing = tmp_path / "gone.csv"
    r = _run_cli("profile", str(missing))
    assert r.returncode == 2
    assert r.stdout.strip() == ""
    assert "Error:" in r.stderr
