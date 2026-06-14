# tests/unit/cli/test_cli_drift_history_report.py
"""Unit tests for the `dqt drift-history report` command."""

from __future__ import annotations

import data_quality_toolkit.adapters.cli.main as cli
from data_quality_toolkit.adapters.storage.connection import connect
from data_quality_toolkit.adapters.storage.schema import ensure_db

_SUMMARY = {
    "total_runs": 2,
    "drifted_runs": 1,
    "non_drifted_runs": 1,
    "drift_rate": 0.5,
    "latest_run_id": "r2",
    "latest_created_at": "2026-06-13T00:00:02+00:00",
    "latest_drift_detected": False,
    "columns_tested_total": 4,
    "columns_tested_average": 2.0,
    "columns_drifted_total": 1,
    "columns_drifted_average": 0.5,
}

_RUNS = [
    {
        "run_id": "r2",
        "created_at": "2026-06-13T00:00:02+00:00",
        "current_dataset_id": "cd1",
        "status": "ok",
        "columns_tested": 2,
        "columns_drifted": 0,
        "drift_detected": 0,
    },
    {
        "run_id": "r1",
        "created_at": "2026-06-13T00:00:01+00:00",
        "current_dataset_id": "cd1",
        "status": "ok",
        "columns_tested": 2,
        "columns_drifted": 1,
        "drift_detected": 1,
    },
]


def _patch(monkeypatch, summary=None, runs=None):
    """Monkeypatch the lazy summarizer + reader; record forwarded args."""
    summary_calls: list[tuple[str, dict]] = []
    runs_calls: list[tuple[str, dict]] = []
    s_result = dict(_SUMMARY) if summary is None else summary
    r_result = list(_RUNS) if runs is None else runs

    def fake_summarize(db_path, **filters):
        summary_calls.append((db_path, filters))
        return s_result

    def fake_read(db_path, **filters):
        runs_calls.append((db_path, filters))
        return r_result

    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "summarize_drift_trends_sqlite", fake_summarize)
    monkeypatch.setattr(cli, "read_drift_runs_sqlite", fake_read)
    return summary_calls, runs_calls


def test_report_writes_markdown_file(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch)
    out = tmp_path / "report.md"
    rc = cli.main(["drift-history", "report", "--db", "drift.db", "--output", str(out)])
    assert rc == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Drift History Monitoring Report")
    assert "total_runs:** 2" in text
    assert "| r2 |" in text


def test_report_stderr_summary(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch)
    out = tmp_path / "report.md"
    cli.main(["drift-history", "report", "--db", "drift.db", "--output", str(out)])
    err = capsys.readouterr().err
    assert "Drift report written" in err
    assert str(out) in err
    assert "Total runs: 2" in err


def test_report_no_stdout_json(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch)
    out = tmp_path / "report.md"
    cli.main(["drift-history", "report", "--db", "drift.db", "--output", str(out)])
    assert capsys.readouterr().out == ""


def test_report_forwards_filters(monkeypatch, tmp_path, capsys):
    summary_calls, runs_calls = _patch(monkeypatch)
    out = tmp_path / "report.md"
    cli.main(
        [
            "drift-history",
            "report",
            "--db",
            "drift.db",
            "--output",
            str(out),
            "--limit",
            "1",
            "--current-dataset-id",
            "cd1",
        ]
    )
    assert summary_calls[0][1]["limit"] == 1
    assert summary_calls[0][1]["current_dataset_id"] == "cd1"
    assert runs_calls[0][1]["limit"] == 1
    assert runs_calls[0][1]["current_dataset_id"] == "cd1"


def test_report_html_format(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch)
    out = tmp_path / "report.html"
    rc = cli.main(
        [
            "drift-history",
            "report",
            "--db",
            "drift.db",
            "--output",
            str(out),
            "--format",
            "html",
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>")
    assert "<table>" in text


def test_report_requires_db_flag(monkeypatch, tmp_path):
    _patch(monkeypatch)
    out = tmp_path / "report.md"
    try:
        cli.main(["drift-history", "report", "--output", str(out)])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - defensive
        raise AssertionError("expected SystemExit for missing --db")


def test_report_requires_output_flag(monkeypatch):
    _patch(monkeypatch)
    try:
        cli.main(["drift-history", "report", "--db", "drift.db"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - defensive
        raise AssertionError("expected SystemExit for missing --output")


def test_report_missing_db_zero_report(monkeypatch, tmp_path, capsys):
    """Real API: missing DB yields a valid zero report, exit 0."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    out = tmp_path / "report.md"
    missing = tmp_path / "nope.db"
    rc = cli.main(["drift-history", "report", "--db", str(missing), "--output", str(out)])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "total_runs:** 0" in text
    assert "_(no runs)_" in text


def test_report_empty_db_zero_report(monkeypatch, tmp_path, capsys):
    """Real API: empty DB (schema only) yields a valid zero report, exit 0."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = tmp_path / "drift.db"
    ensure_db(db)
    out = tmp_path / "report.md"
    rc = cli.main(["drift-history", "report", "--db", str(db), "--output", str(out)])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "total_runs:** 0" in text
    assert "_(no runs)_" in text


def test_report_real_db_aggregates(monkeypatch, tmp_path, capsys):
    """End-to-end with a real SQLite DB and inserted drift runs."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = tmp_path / "drift.db"
    ensure_db(db)
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

    out = tmp_path / "report.md"
    rc = cli.main(["drift-history", "report", "--db", str(db), "--output", str(out)])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "total_runs:** 2" in text
    assert "| r2 |" in text
    assert "| r1 |" in text


_COLUMNS = [
    {
        "run_id": "r1",
        "column_name": "age",
        "kind": "numeric",
        "drift_detected": 1,
        "psi": 0.31,
        "js_distance": 0.22,
        "wasserstein": 1.5,
        "status": "tested",
    }
]


def _patch_columns(monkeypatch, rows=None):
    """Monkeypatch the lazy column reader; record forwarded args."""
    calls: list[tuple[str, dict]] = []
    result = list(_COLUMNS) if rows is None else rows

    def fake_read(db_path, **filters):
        calls.append((db_path, filters))
        return result

    monkeypatch.setattr(cli, "read_drift_columns_sqlite", fake_read)
    return calls


def test_report_include_columns_adds_section(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch)
    _patch_columns(monkeypatch)
    out = tmp_path / "report.md"
    rc = cli.main(
        ["drift-history", "report", "--db", "drift.db", "--output", str(out), "--include-columns"]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "## Column-level drift metrics" in text
    assert "| age |" in text


def test_report_without_flag_omits_columns_section(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch)
    _patch_columns(monkeypatch)
    out = tmp_path / "report.md"
    cli.main(["drift-history", "report", "--db", "drift.db", "--output", str(out)])
    text = out.read_text(encoding="utf-8")
    assert "## Column-level drift metrics" not in text


def test_report_include_columns_empty_placeholder(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch)
    _patch_columns(monkeypatch, rows=[])
    out = tmp_path / "report.md"
    cli.main(
        ["drift-history", "report", "--db", "drift.db", "--output", str(out), "--include-columns"]
    )
    text = out.read_text(encoding="utf-8")
    assert "## Column-level drift metrics" in text
    assert "No column-level drift rows available." in text


_DISTRIBUTIONS = [
    {
        "run_id": "r1",
        "column_name": "age",
        "kind": "numeric",
        "bin_index": 0,
        "bin_label": "[-inf, 1.5)",
        "reference_prob": 0.6,
        "current_prob": 0.4,
    },
    {
        "run_id": "r1",
        "column_name": "age",
        "kind": "numeric",
        "bin_index": 1,
        "bin_label": "[1.5, inf)",
        "reference_prob": 0.4,
        "current_prob": 0.6,
    },
]


def _patch_distributions(monkeypatch, rows=None):
    """Monkeypatch the lazy distribution reader; record forwarded args."""
    calls: list[tuple[str, dict]] = []
    result = list(_DISTRIBUTIONS) if rows is None else rows

    def fake_read(db_path, **filters):
        calls.append((db_path, filters))
        return result

    monkeypatch.setattr(cli, "read_drift_distributions_sqlite", fake_read)
    return calls


def test_report_include_plots_adds_section_and_fetches(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch)
    calls = _patch_distributions(monkeypatch)
    out = tmp_path / "report.md"
    rc = cli.main(
        ["drift-history", "report", "--db", "drift.db", "--output", str(out), "--include-plots"]
    )
    assert rc == 0
    assert len(calls) == 1  # distributions were fetched
    text = out.read_text(encoding="utf-8")
    assert "## Distribution plots" in text
    assert "[-inf, 1.5)" in text
    err = capsys.readouterr().err
    assert "Distribution rows: 2" in err


def test_report_without_flag_does_not_fetch_distributions(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch)
    calls = _patch_distributions(monkeypatch)
    out = tmp_path / "report.md"
    cli.main(["drift-history", "report", "--db", "drift.db", "--output", str(out)])
    assert calls == []  # not fetched when flag omitted
    text = out.read_text(encoding="utf-8")
    assert "## Distribution plots" not in text
    err = capsys.readouterr().err
    assert "Distribution rows:" not in err


def test_report_include_plots_html_bars(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch)
    _patch_distributions(monkeypatch)
    out = tmp_path / "report.html"
    cli.main(
        [
            "drift-history",
            "report",
            "--db",
            "drift.db",
            "--output",
            str(out),
            "--format",
            "html",
            "--include-plots",
        ]
    )
    text = out.read_text(encoding="utf-8")
    assert "<h2>Distribution plots</h2>" in text
    assert "60.0%" in text
    assert "<script" not in text


def test_report_include_plots_empty_db(monkeypatch, tmp_path, capsys):
    """Real API path: empty DB with --include-plots exits 0 with empty-state."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = tmp_path / "drift.db"
    ensure_db(db)
    out = tmp_path / "report.md"
    rc = cli.main(
        ["drift-history", "report", "--db", str(db), "--output", str(out), "--include-plots"]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "## Distribution plots" in text
    assert "_No distribution rows available._" in text
    err = capsys.readouterr().err
    assert "Distribution rows: 0" in err
