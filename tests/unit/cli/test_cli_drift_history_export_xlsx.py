# tests/unit/cli/test_cli_drift_history_export_xlsx.py
"""Unit tests for the `dqt drift-history export-xlsx` command.

The CLI handler is tested with the lazy ``cli.export_drift_history_xlsx`` proxy
monkeypatched, so these run without the optional [powerbi] extra.
"""

from __future__ import annotations

import pytest

import data_quality_toolkit.adapters.cli.main as cli
from data_quality_toolkit.adapters.exporters.bi.xlsx_drift_exporter import XlsxExportError

_RESULT = {
    "output_path": "/tmp/drift_monitoring.xlsx",
    "sheets": ["runs", "trend_summary", "columns", "metadata"],
    "row_counts": {"runs": 2, "trend_summary": 5, "columns": 3, "metadata": 8},
}


def _patch_ok(monkeypatch):
    """Patch the proxy to succeed; record forwarded (args, kwargs)."""
    calls: list[tuple[tuple, dict]] = []

    def fake_export(db_path, output_path, **kwargs):
        calls.append(((db_path, output_path), kwargs))
        return dict(_RESULT)

    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "export_drift_history_xlsx", fake_export)
    return calls


def test_export_xlsx_success_exit0(monkeypatch, tmp_path, capsys):
    _patch_ok(monkeypatch)
    out = tmp_path / "drift.xlsx"
    rc = cli.main(["drift-history", "export-xlsx", "--db", "m.db", "--out", str(out)])
    assert rc == 0


def test_export_xlsx_summary_to_stderr(monkeypatch, tmp_path, capsys):
    _patch_ok(monkeypatch)
    out = tmp_path / "drift.xlsx"
    cli.main(["drift-history", "export-xlsx", "--db", "m.db", "--out", str(out)])
    err = capsys.readouterr().err
    assert "Drift workbook written" in err
    assert "Sheets: runs, trend_summary, columns, metadata" in err
    assert "runs rows: 2" in err


def test_export_xlsx_no_stdout_pollution(monkeypatch, tmp_path, capsys):
    _patch_ok(monkeypatch)
    out = tmp_path / "drift.xlsx"
    cli.main(["drift-history", "export-xlsx", "--db", "m.db", "--out", str(out)])
    assert capsys.readouterr().out == ""


def test_export_xlsx_forwards_flags(monkeypatch, tmp_path, capsys):
    calls = _patch_ok(monkeypatch)
    out = tmp_path / "drift.xlsx"
    cli.main(
        [
            "drift-history",
            "export-xlsx",
            "--db",
            "m.db",
            "--out",
            str(out),
            "--limit",
            "5",
            "--current-dataset-id",
            "cd1",
            "--include-distributions",
            "--force",
        ]
    )
    (_, _), kwargs = calls[0]
    assert kwargs["limit"] == 5
    assert kwargs["current_dataset_id"] == "cd1"
    assert kwargs["include_columns"] is True  # default on
    assert kwargs["include_distributions"] is True
    assert kwargs["force"] is True


def test_export_xlsx_no_include_columns_flag(monkeypatch, tmp_path, capsys):
    calls = _patch_ok(monkeypatch)
    out = tmp_path / "drift.xlsx"
    cli.main(
        ["drift-history", "export-xlsx", "--db", "m.db", "--out", str(out), "--no-include-columns"]
    )
    (_, _), kwargs = calls[0]
    assert kwargs["include_columns"] is False


def test_export_xlsx_missing_db_exits_2(monkeypatch, tmp_path):
    _patch_ok(monkeypatch)
    out = tmp_path / "drift.xlsx"
    with pytest.raises(SystemExit) as ei:
        cli.main(["drift-history", "export-xlsx", "--out", str(out)])
    assert ei.value.code == 2


def test_export_xlsx_missing_out_exits_2(monkeypatch):
    _patch_ok(monkeypatch)
    with pytest.raises(SystemExit) as ei:
        cli.main(["drift-history", "export-xlsx", "--db", "m.db"])
    assert ei.value.code == 2


def test_export_xlsx_invalid_path_exits_1(monkeypatch, capsys):
    """Exporter path-safety failure surfaces as exit 1 with a message."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)

    def boom(*_a, **_k):
        raise XlsxExportError("Output path must end with .xlsx, got: out.csv")

    monkeypatch.setattr(cli, "export_drift_history_xlsx", boom)
    rc = cli.main(["drift-history", "export-xlsx", "--db", "m.db", "--out", "out.csv"])
    assert rc == 1
    assert "Error:" in capsys.readouterr().err


def test_export_xlsx_missing_dependency_exits_1_with_hint(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)

    def boom(*_a, **_k):
        raise XlsxExportError(
            "openpyxl is not installed; install the powerbi extra: "
            "pip install data-quality-toolkit[powerbi]"
        )

    monkeypatch.setattr(cli, "export_drift_history_xlsx", boom)
    out = tmp_path / "drift.xlsx"
    rc = cli.main(["drift-history", "export-xlsx", "--db", "m.db", "--out", str(out)])
    assert rc == 1
    assert "powerbi" in capsys.readouterr().err


def test_export_xlsx_no_overwrite_without_force_exits_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)

    def boom(*_a, **_k):
        raise XlsxExportError("Output file already exists; pass --force to overwrite: x")

    monkeypatch.setattr(cli, "export_drift_history_xlsx", boom)
    out = tmp_path / "drift.xlsx"
    rc = cli.main(["drift-history", "export-xlsx", "--db", "m.db", "--out", str(out)])
    assert rc == 1
    assert "already exists" in capsys.readouterr().err
