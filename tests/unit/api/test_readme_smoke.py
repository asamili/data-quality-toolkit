"""Smoke tests for README-documented CLI invocations.

Ensures the module paths shown in README can be imported and the version
command returns the expected output. Guards against re-introducing broken paths.
"""

from __future__ import annotations

import subprocess
import sys


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "data_quality_toolkit.adapters.cli.main", *args],
        capture_output=True,
        text=True,
    )


def test_readme_module_path_help() -> None:
    proc = _run("--help")
    assert proc.returncode == 0
    assert "Data Quality Toolkit CLI" in proc.stdout


def test_readme_module_path_version() -> None:
    proc = _run("version")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "2.0.0"


def test_readme_module_path_profile(tmp_path) -> None:
    csv = tmp_path / "smoke.csv"
    csv.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    proc = _run("--no-json", "profile", str(csv))
    assert proc.returncode == 0
