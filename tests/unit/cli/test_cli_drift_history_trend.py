# tests/unit/cli/test_cli_drift_history_trend.py
"""Unit tests for the `dqt drift-history trend` command."""

from __future__ import annotations

import json

import data_quality_toolkit.adapters.cli.main as cli
from data_quality_toolkit.adapters.storage.schema import ensure_db

_SUMMARY = {
    "total_runs": 3,
    "drifted_runs": 2,
    "non_drifted_runs": 1,
    "drift_rate": 0.6666666666666666,
    "latest_run_id": "r3",
    "latest_created_at": "2026-06-13T00:00:03+00:00",
    "latest_drift_detected": True,
    "columns_tested_total": 12,
    "columns_tested_average": 4.0,
    "columns_drifted_total": 4,
    "columns_drifted_average": 1.3333333333333333,
}

_ZERO = {
    "total_runs": 0,
    "drifted_runs": 0,
    "non_drifted_runs": 0,
    "drift_rate": 0.0,
    "latest_run_id": None,
    "latest_created_at": None,
    "latest_drift_detected": None,
    "columns_tested_total": 0,
    "columns_tested_average": 0.0,
    "columns_drifted_total": 0,
    "columns_drifted_average": 0.0,
}


def _patch(monkeypatch, summary=None):
    """Monkeypatch the lazy trend summarizer; record forwarded args."""
    calls: list[tuple[str, dict]] = []
    result = dict(_SUMMARY) if summary is None else summary

    def fake_summarize(db_path: str, **filters):
        calls.append((db_path, filters))
        return result

    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "summarize_drift_trends_sqlite", fake_summarize)
    return calls


def test_trend_stdout_is_summary_dict(monkeypatch, capsys):
    _patch(monkeypatch)
    rc = cli.main(["drift-history", "trend", "--db", "drift.db"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed == _SUMMARY


def test_trend_summary_on_stderr(monkeypatch, capsys):
    _patch(monkeypatch)
    cli.main(["drift-history", "trend", "--db", "drift.db"])
    err = capsys.readouterr().err
    assert "Drift trend summarized" in err
    assert "drift.db" in err
    assert "Total runs: 3" in err
    assert "Drifted runs: 2" in err
    assert "Drift rate:" in err


def test_trend_no_json_suppresses_stdout(monkeypatch, capsys):
    _patch(monkeypatch)
    rc = cli.main(["--no-json", "drift-history", "trend", "--db", "drift.db"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert "Drift trend summarized" in captured.err
    assert "Total runs: 3" in captured.err


def test_trend_forwards_db_path(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(["drift-history", "trend", "--db", "path/to/drift.db"])
    assert calls[0][0] == "path/to/drift.db"


def test_trend_forwards_filters_typed(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(
        [
            "drift-history",
            "trend",
            "--db",
            "drift.db",
            "--limit",
            "5",
            "--current-dataset-id",
            "cd1",
        ]
    )
    filters = calls[0][1]
    assert filters["limit"] == 5
    assert filters["current_dataset_id"] == "cd1"


def test_trend_defaults_filters_none(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(["drift-history", "trend", "--db", "drift.db"])
    filters = calls[0][1]
    assert filters["limit"] is None
    assert filters["current_dataset_id"] is None


def test_trend_bad_limit_value_exits_2(monkeypatch, capsys):
    _patch(monkeypatch)
    try:
        cli.main(["drift-history", "trend", "--db", "drift.db", "--limit", "abc"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - defensive
        raise AssertionError("expected SystemExit for invalid --limit")


def test_trend_requires_db_flag(monkeypatch, capsys):
    _patch(monkeypatch)
    try:
        cli.main(["drift-history", "trend"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - defensive
        raise AssertionError("expected SystemExit for missing --db")


def test_trend_missing_db_returns_zero_summary(monkeypatch, tmp_path, capsys):
    """Missing DB file follows API behavior: zero-summary with exit 0 (real API)."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    missing = tmp_path / "nope.db"

    rc = cli.main(["drift-history", "trend", "--db", str(missing)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == _ZERO


def test_trend_empty_db_returns_zero_summary(monkeypatch, tmp_path, capsys):
    """Empty DB (schema only, no rows) returns the stable zero-summary, exit 0."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = tmp_path / "drift.db"
    ensure_db(db)

    rc = cli.main(["drift-history", "trend", "--db", str(db)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == _ZERO


def test_trend_real_db_aggregates_inserted_runs(monkeypatch, tmp_path, capsys):
    """End-to-end with a real SQLite DB and inserted drift runs."""
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

    rc = cli.main(["drift-history", "trend", "--db", str(db)])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["total_runs"] == 2
    assert parsed["drifted_runs"] == 1
    assert parsed["drift_rate"] == 0.5


def test_trend_real_db_current_dataset_id_filter(monkeypatch, tmp_path, capsys):
    """--current-dataset-id narrows real rows aggregated."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = tmp_path / "drift.db"
    ensure_db(db)

    from data_quality_toolkit.adapters.storage.connection import connect

    rows = [
        ("r1", "2026-06-13T00:00:01+00:00", "cd1", 1),
        ("r2", "2026-06-13T00:00:02+00:00", "cd2", 0),
    ]
    with connect(db) as con:
        for run_id, created_at, current_dataset_id, drift in rows:
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
                    current_dataset_id,
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

    rc = cli.main(["drift-history", "trend", "--db", str(db), "--current-dataset-id", "cd1"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["total_runs"] == 1
    assert parsed["drifted_runs"] == 1
    assert parsed["latest_run_id"] == "r1"
