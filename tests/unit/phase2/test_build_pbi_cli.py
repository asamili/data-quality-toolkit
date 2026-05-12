from __future__ import annotations

import json
from pathlib import Path

from data_quality_toolkit.cli.main import main


def _fake_export_ok(**kwargs):
    # Minimal realistic return structure from export_powerbi_package
    pkg_dir = kwargs["output_dir"]
    return {
        "package_dir": str(pkg_dir),
        "files": {"model": str(Path(pkg_dir) / "model.pbit")},
        "validation": {"valid": True, "errors": [], "warnings": []},
        "time_range": f"{kwargs['time_start']} to {kwargs['time_end']}",
        "base_folder": kwargs["base_folder"],
        "dim_time_path": str(Path(pkg_dir) / "time" / "dim_time.csv"),
    }


def test_cli_build_pbi_success(monkeypatch, tmp_path, capsys):
    # Monkeypatch the orchestrator inside the CLI module namespace
    import data_quality_toolkit.exporters.bi.powerbi_exporter as exporter

    monkeypatch.setattr(exporter, "export_powerbi_package", lambda **kw: _fake_export_ok(**kw))

    # Build args and run
    star = tmp_path / "star"
    star.mkdir()
    out = tmp_path / "pkg"
    argv = [
        "build-pbi",
        "--star",
        str(star),
        "--out",
        str(out),
        "--time-start",
        "2024-01-01",
        "--time-end",
        "2024-01-31",
        "--base-folder",
        "./dist",
        "--fiscal",
        "7",
    ]
    rc = main(argv)
    assert rc == 0

    captured = capsys.readouterr()
    # STDOUT should be JSON
    payload = json.loads(captured.out)
    assert payload["package_dir"] == str(out)
    assert payload["validation"]["valid"] is True
    # STDERR should have the pretty lines
    assert "Package:" in captured.err


def test_cli_build_pbi_failure(monkeypatch, tmp_path, capsys):
    # Force orchestrator to raise
    import data_quality_toolkit.exporters.bi.powerbi_exporter as exporter

    def _boom(**kw):
        raise ValueError("simulated failure")

    monkeypatch.setattr(exporter, "export_powerbi_package", _boom)

    argv = ["build-pbi", "--star", str(tmp_path / "star"), "--out", str(tmp_path / "pkg")]
    rc = main(argv)
    assert rc == 1

    captured = capsys.readouterr()
    assert "Error: simulated failure" in captured.err
    # no JSON emitted on stdout in failure path
    assert captured.out.strip() == ""
