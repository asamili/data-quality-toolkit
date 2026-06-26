# tests/unit/cli/test_cli_drift_history_plot.py
"""Unit tests for the `dqt drift-history plot` command.

The CLI handler is tested with the lazy ``cli.export_drift_plots`` proxy
monkeypatched, so these run without the optional [viz] extra.
"""

from __future__ import annotations

import pytest

import data_quality_toolkit.adapters.cli.main as cli
from data_quality_toolkit.adapters.exporters.viz.drift_plots import PlotExportError

_RESULT = {
    "output_dir": "/tmp/plots",
    "charts": {
        "drift-rate": "/tmp/plots/drift_rate.png",
        "psi-by-column": "/tmp/plots/psi_by_column.png",
        "top-drifted": "/tmp/plots/top_drifted.png",
    },
    "row_counts": {"drift-rate": 2, "psi-by-column": 3, "top-drifted": 1},
}


def _patch_ok(monkeypatch):
    """Patch the proxy to succeed; record forwarded (args, kwargs)."""
    calls: list[tuple[tuple, dict]] = []

    def fake_export(db_path, out, **kwargs):
        calls.append(((db_path, out), kwargs))
        return dict(_RESULT)

    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "export_drift_plots", fake_export)
    return calls


def test_plot_success_exit0(monkeypatch, tmp_path):
    _patch_ok(monkeypatch)
    out = tmp_path / "plots"
    rc = cli.main(["drift-history", "plot", "--db", "m.db", "--out", str(out)])
    assert rc == 0


def test_plot_summary_to_stderr(monkeypatch, tmp_path, capsys):
    _patch_ok(monkeypatch)
    out = tmp_path / "plots"
    cli.main(["drift-history", "plot", "--db", "m.db", "--out", str(out)])
    err = capsys.readouterr().err
    assert "Drift plots written" in err
    assert "Charts: drift-rate, psi-by-column, top-drifted" in err
    assert "drift-rate points: 2" in err


def test_plot_no_stdout_pollution(monkeypatch, tmp_path, capsys):
    _patch_ok(monkeypatch)
    out = tmp_path / "plots"
    cli.main(["drift-history", "plot", "--db", "m.db", "--out", str(out)])
    assert capsys.readouterr().out == ""


def test_plot_forwards_flags(monkeypatch, tmp_path):
    calls = _patch_ok(monkeypatch)
    out = tmp_path / "plots"
    cli.main(
        [
            "drift-history",
            "plot",
            "--db",
            "m.db",
            "--out",
            str(out),
            "--chart",
            "psi-by-column",
            "--limit",
            "5",
            "--current-dataset-id",
            "cd1",
            "--force",
        ]
    )
    (_, _), kwargs = calls[0]
    assert kwargs["chart"] == "psi-by-column"
    assert kwargs["limit"] == 5
    assert kwargs["current_dataset_id"] == "cd1"
    assert kwargs["force"] is True


def test_plot_default_chart_is_all(monkeypatch, tmp_path):
    calls = _patch_ok(monkeypatch)
    out = tmp_path / "plots"
    cli.main(["drift-history", "plot", "--db", "m.db", "--out", str(out)])
    (_, _), kwargs = calls[0]
    assert kwargs["chart"] == "all"


def test_plot_missing_db_exits_2(monkeypatch, tmp_path):
    _patch_ok(monkeypatch)
    out = tmp_path / "plots"
    with pytest.raises(SystemExit) as ei:
        cli.main(["drift-history", "plot", "--out", str(out)])
    assert ei.value.code == 2


def test_plot_missing_out_exits_2(monkeypatch):
    _patch_ok(monkeypatch)
    with pytest.raises(SystemExit) as ei:
        cli.main(["drift-history", "plot", "--db", "m.db"])
    assert ei.value.code == 2


def test_plot_invalid_chart_exits_2(monkeypatch, tmp_path):
    _patch_ok(monkeypatch)
    out = tmp_path / "plots"
    with pytest.raises(SystemExit) as ei:
        cli.main(["drift-history", "plot", "--db", "m.db", "--out", str(out), "--chart", "bogus"])
    assert ei.value.code == 2


def test_plot_missing_dependency_exits_1_with_hint(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)

    def boom(*_a, **_k):
        raise PlotExportError(
            "matplotlib is not installed; install the viz extra: "
            "pip install data-quality-toolkit[viz]"
        )

    monkeypatch.setattr(cli, "export_drift_plots", boom)
    out = tmp_path / "plots"
    rc = cli.main(["drift-history", "plot", "--db", "m.db", "--out", str(out)])
    assert rc == 1
    assert "viz" in capsys.readouterr().err


def test_plot_no_overwrite_without_force_exits_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)

    def boom(*_a, **_k):
        raise PlotExportError("Output file already exists; pass --force to overwrite: x.png")

    monkeypatch.setattr(cli, "export_drift_plots", boom)
    out = tmp_path / "plots"
    rc = cli.main(["drift-history", "plot", "--db", "m.db", "--out", str(out)])
    assert rc == 1
    assert "already exists" in capsys.readouterr().err
