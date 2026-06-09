# tests/integration/adapters/cli/test_manifest.py
"""Integration tests for `dqt manifest create`."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


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
    return subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603


def _make_session(tmp_path: Path, run_id: str) -> Path:
    session_dir = tmp_path / run_id
    meta = session_dir / "meta"
    meta.mkdir(parents=True)
    (meta / "lineage.jsonl").write_text("", encoding="utf-8")
    return session_dir


class TestManifestCreate:
    def test_creates_artifacts_json(self, tmp_path: Path) -> None:
        run_id = "run-001"
        _make_session(tmp_path, run_id)
        result = _run_cli(
            "manifest",
            "create",
            "--run-id",
            run_id,
            "--sessions-root",
            str(tmp_path),
        )
        assert result.returncode == 0, result.stderr
        assert (tmp_path / run_id / "artifacts.json").exists()

    def test_stdout_is_valid_manifest_json(self, tmp_path: Path) -> None:
        run_id = "run-json"
        _make_session(tmp_path, run_id)
        result = _run_cli(
            "manifest",
            "create",
            "--run-id",
            run_id,
            "--sessions-root",
            str(tmp_path),
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["run_id"] == run_id
        assert "schema_version" in data
        assert "datasets" in data
        assert "artifacts" in data
        assert "summary" in data
        assert "gates" in data

    def test_no_json_flag_suppresses_stdout(self, tmp_path: Path) -> None:
        run_id = "run-nojson"
        _make_session(tmp_path, run_id)
        result = _run_cli(
            "--no-json",
            "manifest",
            "create",
            "--run-id",
            run_id,
            "--sessions-root",
            str(tmp_path),
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == ""

    def test_missing_run_id_exits_nonzero(self, tmp_path: Path) -> None:
        result = _run_cli("manifest", "create", "--sessions-root", str(tmp_path))
        assert result.returncode != 0

    def test_missing_sessions_root_exits_nonzero(self) -> None:
        result = _run_cli("manifest", "create", "--run-id", "run-x")
        assert result.returncode != 0

    def test_empty_session_produces_empty_datasets_and_artifacts(self, tmp_path: Path) -> None:
        run_id = "run-empty"
        _make_session(tmp_path, run_id)
        result = _run_cli(
            "manifest",
            "create",
            "--run-id",
            run_id,
            "--sessions-root",
            str(tmp_path),
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["datasets"] == []
        assert data["artifacts"] == []
        assert data["gates"]["status"] == "skipped"
