# tests/unit/cli/test_cli_drift_history_export_duckdb.py
"""Unit tests for the `dqt drift-history export-duckdb` command.

The CLI handler is tested with the lazy ``cli.export_monitoring_duckdb`` proxy
monkeypatched, so these run without the optional [duckdb] extra.
"""

from __future__ import annotations

import pytest

import data_quality_toolkit.adapters.cli.main as cli
from data_quality_toolkit.adapters.exporters.bi.duckdb_exporter import DuckdbExportError

_RESULT = {
    "input_db_path": "m.db",
    "output_path": "/tmp/m.duckdb",
    "tables": ["drift_runs", "drift_columns", "drift_column_distributions"],
    "row_counts": {"drift_runs": 2, "drift_columns": 3, "drift_column_distributions": 4},
    "overwritten": False,
}


def _patch_ok(monkeypatch):
    """Patch the proxy to succeed; record forwarded (args, kwargs)."""
    calls: list[tuple[tuple, dict]] = []

    def fake_export(db_path, out_path, **kwargs):
        calls.append(((db_path, out_path), kwargs))
        return dict(_RESULT)

    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "export_monitoring_duckdb", fake_export)
    return calls


def test_export_duckdb_success_exit0(monkeypatch, tmp_path, capsys):
    _patch_ok(monkeypatch)
    out = tmp_path / "m.duckdb"
    rc = cli.main(["drift-history", "export-duckdb", "--db", "m.db", "--out", str(out)])
    assert rc == 0


def test_export_duckdb_summary_to_stderr(monkeypatch, tmp_path, capsys):
    _patch_ok(monkeypatch)
    out = tmp_path / "m.duckdb"
    cli.main(["drift-history", "export-duckdb", "--db", "m.db", "--out", str(out)])
    err = capsys.readouterr().err
    assert "DuckDB mirror written" in err
    assert "Tables: drift_runs, drift_columns, drift_column_distributions" in err
    assert "drift_runs rows: 2" in err


def test_export_duckdb_default_no_overwrite(monkeypatch, tmp_path, capsys):
    calls = _patch_ok(monkeypatch)
    out = tmp_path / "m.duckdb"
    cli.main(["drift-history", "export-duckdb", "--db", "m.db", "--out", str(out)])
    (_, _), kwargs = calls[0]
    assert kwargs["overwrite"] is False


def test_export_duckdb_forwards_overwrite_flag(monkeypatch, tmp_path, capsys):
    calls = _patch_ok(monkeypatch)
    out = tmp_path / "m.duckdb"
    cli.main(["drift-history", "export-duckdb", "--db", "m.db", "--out", str(out), "--overwrite"])
    (db, _out), kwargs = calls[0]
    assert db == "m.db"
    assert kwargs["overwrite"] is True


def test_export_duckdb_missing_db_exits_2(monkeypatch, tmp_path):
    _patch_ok(monkeypatch)
    out = tmp_path / "m.duckdb"
    with pytest.raises(SystemExit) as ei:
        cli.main(["drift-history", "export-duckdb", "--out", str(out)])
    assert ei.value.code == 2


def test_export_duckdb_missing_out_exits_2(monkeypatch):
    _patch_ok(monkeypatch)
    with pytest.raises(SystemExit) as ei:
        cli.main(["drift-history", "export-duckdb", "--db", "m.db"])
    assert ei.value.code == 2


def test_export_duckdb_no_overwrite_existing_exits_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)

    def boom(*_a, **_k):
        raise DuckdbExportError("Output file already exists; pass --overwrite to replace it: x")

    monkeypatch.setattr(cli, "export_monitoring_duckdb", boom)
    out = tmp_path / "m.duckdb"
    rc = cli.main(["drift-history", "export-duckdb", "--db", "m.db", "--out", str(out)])
    assert rc == 1
    assert "already exists" in capsys.readouterr().err


def test_export_duckdb_missing_dependency_exits_1_with_hint(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)

    def boom(*_a, **_k):
        raise DuckdbExportError(
            "duckdb is not installed; install the duckdb extra: "
            "pip install data-quality-toolkit[duckdb]"
        )

    monkeypatch.setattr(cli, "export_monitoring_duckdb", boom)
    out = tmp_path / "m.duckdb"
    rc = cli.main(["drift-history", "export-duckdb", "--db", "m.db", "--out", str(out)])
    assert rc == 1
    assert "duckdb" in capsys.readouterr().err
