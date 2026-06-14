# tests/unit/cli/test_cli_drift_history_list.py
"""Unit tests for the `dqt drift-history list` command."""

from __future__ import annotations

import json

import data_quality_toolkit.adapters.cli.main as cli
from data_quality_toolkit.adapters.storage.schema import ensure_db

_RUN = {
    "run_id": "r1",
    "created_at": "2026-06-13T00:00:00+00:00",
    "baseline_path": "b.csv",
    "current_path": "c.csv",
    "baseline_dataset_id": "bd1",
    "current_dataset_id": "cd1",
    "status": "ok",
    "alpha": 0.05,
    "columns_tested": 2,
    "columns_skipped": 0,
    "columns_drifted": 1,
    "drift_detected": 0,
    "report_path": None,
    "schema_version": "1",
}


def _patch(monkeypatch, runs=None):
    """Monkeypatch the lazy reader; record forwarded args."""
    calls: list[tuple[str, dict]] = []
    rows = [dict(_RUN)] if runs is None else runs

    def fake_read(db_path: str, **filters):
        calls.append((db_path, filters))
        return rows

    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "read_drift_runs_sqlite", fake_read)
    return calls


def test_list_stdout_is_json_list(monkeypatch, capsys):
    _patch(monkeypatch)
    rc = cli.main(["drift-history", "list", "--db", "drift.db"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["run_id"] == "r1"


def test_list_summary_on_stderr(monkeypatch, capsys):
    _patch(monkeypatch)
    cli.main(["drift-history", "list", "--db", "drift.db"])
    err = capsys.readouterr().err
    assert "Drift runs listed" in err
    assert "drift.db" in err
    assert "Runs: 1" in err


def test_list_no_json_suppresses_stdout(monkeypatch, capsys):
    _patch(monkeypatch)
    rc = cli.main(["--no-json", "drift-history", "list", "--db", "drift.db"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert "Drift runs listed" in captured.err
    assert "Runs: 1" in captured.err


def test_list_empty_result_is_empty_json_list(monkeypatch, capsys):
    _patch(monkeypatch, runs=[])
    rc = cli.main(["drift-history", "list", "--db", "drift.db"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_list_forwards_db_path(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(["drift-history", "list", "--db", "path/to/drift.db"])
    assert calls[0][0] == "path/to/drift.db"


def test_list_forwards_filters_typed(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(
        [
            "drift-history",
            "list",
            "--db",
            "drift.db",
            "--limit",
            "5",
            "--current-dataset-id",
            "cd1",
            "--drift-detected",
            "true",
            "--status",
            "ok",
        ]
    )
    filters = calls[0][1]
    assert filters["limit"] == 5
    assert filters["current_dataset_id"] == "cd1"
    assert filters["drift_detected"] is True
    assert filters["status"] == "ok"


def test_list_drift_detected_false_forwarded_as_false(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(["drift-history", "list", "--db", "drift.db", "--drift-detected", "false"])
    assert calls[0][1]["drift_detected"] is False


def test_list_defaults_filters_none(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(["drift-history", "list", "--db", "drift.db"])
    filters = calls[0][1]
    assert filters["limit"] is None
    assert filters["current_dataset_id"] is None
    assert filters["drift_detected"] is None
    assert filters["status"] is None


def test_list_bad_drift_detected_value_exits_2(monkeypatch, capsys):
    _patch(monkeypatch)
    try:
        cli.main(["drift-history", "list", "--db", "drift.db", "--drift-detected", "maybe"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - defensive
        raise AssertionError("expected SystemExit for invalid --drift-detected")


def test_list_requires_db_flag(monkeypatch, capsys):
    _patch(monkeypatch)
    try:
        cli.main(["drift-history", "list"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - defensive
        raise AssertionError("expected SystemExit for missing --db")


def test_list_missing_db_returns_empty_list(monkeypatch, tmp_path, capsys):
    """Missing DB file follows API behavior: [] with exit 0 (real reader)."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    missing = tmp_path / "nope.db"

    rc = cli.main(["drift-history", "list", "--db", str(missing)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_list_real_db_returns_inserted_run(monkeypatch, tmp_path, capsys):
    """End-to-end with a real SQLite DB and one inserted drift run."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = tmp_path / "drift.db"
    ensure_db(db)

    from data_quality_toolkit.adapters.storage.connection import connect

    with connect(db) as con:
        con.execute(
            """
            INSERT INTO drift_runs(
                run_id, created_at, baseline_path, current_path,
                baseline_dataset_id, current_dataset_id, status, alpha,
                columns_tested, columns_skipped, columns_drifted,
                drift_detected, report_path, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "r1",
                "2026-06-13T00:00:00+00:00",
                "b.csv",
                "c.csv",
                "bd1",
                "cd1",
                "ok",
                0.05,
                2,
                0,
                1,
                1,
                None,
                "1",
            ),
        )
        con.commit()

    rc = cli.main(["drift-history", "list", "--db", str(db)])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert len(parsed) == 1
    assert parsed[0]["run_id"] == "r1"
    assert parsed[0]["drift_detected"] == 1


def test_list_real_db_drift_detected_filter(monkeypatch, tmp_path, capsys):
    """--drift-detected true narrows real rows to drifted runs only."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = tmp_path / "drift.db"
    ensure_db(db)

    from data_quality_toolkit.adapters.storage.connection import connect

    rows = [
        ("r1", "2026-06-13T00:00:01+00:00", 1),
        ("r2", "2026-06-13T00:00:02+00:00", 0),
    ]
    with connect(db) as con:
        for run_id, created_at, drift in rows:
            con.execute(
                """
                INSERT INTO drift_runs(
                    run_id, created_at, baseline_path, current_path,
                    baseline_dataset_id, current_dataset_id, status, alpha,
                    columns_tested, columns_skipped, columns_drifted,
                    drift_detected, report_path, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    created_at,
                    "b.csv",
                    "c.csv",
                    "bd1",
                    "cd1",
                    "ok",
                    0.05,
                    2,
                    0,
                    1,
                    drift,
                    None,
                    "1",
                ),
            )
        con.commit()

    rc = cli.main(["drift-history", "list", "--db", str(db), "--drift-detected", "true"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert [r["run_id"] for r in parsed] == ["r1"]
