from __future__ import annotations

import json
from pathlib import Path

# ---------------- generate_dim_time.py ---------------- #


def test_generate_dim_time_json(monkeypatch, capsys, tmp_path: Path):
    # Patch write_dim_time to avoid real work
    import data_quality_toolkit.adapters.exporters.time.dim_time_generator as gen

    fake_out = tmp_path / "time" / "dim_time.csv"
    fake_out.parent.mkdir(parents=True, exist_ok=True)
    fake_out.write_text("time_id,date\n20240101,2024-01-01\n", encoding="utf-8")

    monkeypatch.setattr(
        gen,
        "write_dim_time",
        lambda output_dir, start_date, end_date, week_start=1, fiscal_year_start=None: str(
            fake_out
        ),
    )

    # Import the canonical package CLI (not scripts.*)
    from data_quality_toolkit.adapters.cli import main as dqt_main

    rc = dqt_main.main(
        [
            "gen-dim-time",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-02",
            "--week-start",
            "7",
            "--fiscal",
            "7",
            "--out",
            str(tmp_path / "time"),
            "--json",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["dim_time_path"] == str(fake_out)
    assert payload["week_start"] == 7
    assert payload["fiscal"] == 7


def test_generate_dim_time_error(monkeypatch, capsys):
    import data_quality_toolkit.adapters.exporters.time.dim_time_generator as gen

    monkeypatch.setattr(
        gen, "write_dim_time", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom"))
    )

    # Import the canonical package CLI (not scripts.*)
    from data_quality_toolkit.adapters.cli import main as dqt_main

    rc = dqt_main.main(["gen-dim-time", "--json"])
    assert rc == 1
    assert "Error: boom" in capsys.readouterr().err


# ---------------- build_powerbi_template.py ---------------- #


def test_build_powerbi_template_json(monkeypatch, capsys, tmp_path: Path):
    # Patch orchestrator
    import data_quality_toolkit.adapters.exporters.bi.powerbi_exporter as exp

    def _fake_export(**kw):
        outdir = kw["output_dir"]
        (Path(outdir) / "model.pbit").parent.mkdir(parents=True, exist_ok=True)
        return {
            "package_dir": str(outdir),
            "files": {"model.pbit": str(Path(outdir) / "model.pbit")},
            "validation": {"valid": True, "errors": [], "warnings": []},
            "time_range": f"{kw['time_start']} to {kw['time_end']}",
            "base_folder": kw["base_folder"],
            "dim_time_path": str(Path(outdir) / "time" / "dim_time.csv"),
        }

    monkeypatch.setattr(exp, "export_powerbi_package", _fake_export)

    # ✅ call the canonical CLI
    from data_quality_toolkit.adapters.cli import main as dqt_main

    outdir = tmp_path / "pkg"
    rc = dqt_main.main(
        [
            "build-pbi",
            "--star",
            str(tmp_path / "star"),
            "--out",
            str(outdir),
            "--time-start",
            "2024-01-01",
            "--time-end",
            "2024-12-31",
            "--base-folder",
            "./dist",
            "--fiscal",
            "7",
        ]
    )
    assert rc == 0
    # main() prints human-friendly info to stderr and JSON to stdout in cmd_build_pbi
    payload = json.loads(capsys.readouterr().out)
    assert payload["package_dir"] == str(outdir)
    assert payload["validation"]["valid"] is True


def test_build_powerbi_template_human(monkeypatch, capsys, tmp_path: Path):
    import data_quality_toolkit.adapters.exporters.bi.powerbi_exporter as exp

    monkeypatch.setattr(
        exp,
        "export_powerbi_package",
        lambda **kw: {
            "package_dir": str(kw["output_dir"]),
            "files": {},
            "validation": {"valid": True, "errors": [], "warnings": []},
            "time_range": f"{kw.get('time_start')} to {kw.get('time_end')}",
            "base_folder": kw.get("base_folder"),
        },
    )

    # ✅ call the canonical CLI
    from data_quality_toolkit.adapters.cli import main as dqt_main

    outdir = tmp_path / "pkg"
    rc = dqt_main.main(["build-pbi", "--star", str(tmp_path / "star"), "--out", str(outdir)])
    assert rc == 0
    out = capsys.readouterr().err  # human summary goes to stderr
    assert "Package:" in out or "Package created:" in out
    assert "Star schema exported" not in out  # sanity (different subcommand)


def test_build_powerbi_template_error(monkeypatch, capsys):
    import data_quality_toolkit.adapters.exporters.bi.powerbi_exporter as exp

    monkeypatch.setattr(
        exp, "export_powerbi_package", lambda **kw: (_ for _ in ()).throw(RuntimeError("kaboom"))
    )

    # ✅ call the canonical CLI
    from data_quality_toolkit.adapters.cli import main as dqt_main

    rc = dqt_main.main(["build-pbi"])
    assert rc == 1
    assert "Error: kaboom" in capsys.readouterr().err
