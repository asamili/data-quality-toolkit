# tests/unit/cli/test_cli_drift_history_import.py
"""Unit tests for the `dqt drift-history import` command."""

from __future__ import annotations

import json

import data_quality_toolkit.adapters.cli.main as cli
from data_quality_toolkit.adapters.storage.schema import ensure_db

_RECORD_LINE = (
    '{"schema_version": "1", "kind": "drift_history_record", "run_id": "1", '
    '"created_at": "2026-06-13T00:00:00", "baseline_path": "a", "current_path": "b", '
    '"baseline_dataset_id": "1", "current_dataset_id": "2", "status": "detected", '
    '"alpha": 0.05, "columns_tested": 1, "columns_skipped": 0, "columns_drifted": 0, '
    '"drift_detected": false, "report_path": null}\n'
)


def _patch(monkeypatch, count: int = 3):
    calls: dict = {"ensure": [], "import": []}

    def fake_ensure(db_path: str):
        calls["ensure"].append(db_path)

    def fake_import(db_path: str, history_path: str) -> int:
        calls["import"].append((db_path, history_path))
        return count

    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "ensure_drift_db", fake_ensure)
    monkeypatch.setattr(cli, "import_drift_history_sqlite", fake_import)
    return calls


def test_import_stdout_is_json_with_required_fields(monkeypatch, capsys):
    _patch(monkeypatch, count=3)
    rc = cli.main(["drift-history", "import", "hist.jsonl", "--db", "drift.db"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["imported_count"] == 3
    assert parsed["history_path"] == "hist.jsonl"
    assert parsed["db_path"] == "drift.db"


def test_import_summary_on_stderr(monkeypatch, capsys):
    _patch(monkeypatch, count=2)
    cli.main(["drift-history", "import", "hist.jsonl", "--db", "drift.db"])
    err = capsys.readouterr().err
    assert "Drift history imported" in err
    assert "hist.jsonl" in err
    assert "Imported rows: 2" in err


def test_import_no_json_suppresses_stdout(monkeypatch, capsys):
    _patch(monkeypatch, count=2)
    rc = cli.main(["--no-json", "drift-history", "import", "hist.jsonl", "--db", "drift.db"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert "Drift history imported" in captured.err


def test_import_forwards_args_and_ensures_db_first(monkeypatch, capsys):
    calls = _patch(monkeypatch, count=1)
    cli.main(["drift-history", "import", "path/to/hist.jsonl", "--db", "path/to/drift.db"])
    assert calls["ensure"] == ["path/to/drift.db"]
    assert calls["import"] == [("path/to/drift.db", "path/to/hist.jsonl")]


def test_import_requires_db_flag(monkeypatch, capsys):
    _patch(monkeypatch)
    # argparse exits with code 2 when a required option is missing.
    try:
        cli.main(["drift-history", "import", "hist.jsonl"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - defensive
        raise AssertionError("expected SystemExit for missing --db")


def test_import_real_db_delta_count_and_idempotent(monkeypatch, tmp_path, capsys):
    """Fresh import returns 1; re-import returns 0; DB stays at 1 row."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    history = tmp_path / "history.jsonl"
    history.write_text(_RECORD_LINE, encoding="utf-8")
    db = tmp_path / "drift.db"

    rc = cli.main(["drift-history", "import", str(history), "--db", str(db)])
    assert rc == 0
    first = json.loads(capsys.readouterr().out)
    assert first["imported_count"] == 1

    rc = cli.main(["drift-history", "import", str(history), "--db", str(db)])
    assert rc == 0
    second = json.loads(capsys.readouterr().out)
    assert second["imported_count"] == 0

    from data_quality_toolkit.adapters.storage.connection import connect

    with connect(db) as con:
        rows = con.execute("SELECT COUNT(*) FROM drift_runs").fetchone()[0]
    assert rows == 1


def test_import_missing_history_returns_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = tmp_path / "drift.db"
    ensure_db(db)
    missing = tmp_path / "nope.jsonl"

    rc = cli.main(["drift-history", "import", str(missing), "--db", str(db)])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["imported_count"] == 0
