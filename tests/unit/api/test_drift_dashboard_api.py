# tests/unit/api/test_drift_dashboard_api.py
"""Unit tests for the ``drift_dashboard`` public Python API wrapper."""

from __future__ import annotations

import data_quality_toolkit.api as api_module
from data_quality_toolkit import drift_dashboard
from data_quality_toolkit.adapters.storage.connection import connect
from data_quality_toolkit.adapters.storage.schema import ensure_db


def test_drift_dashboard_exported() -> None:
    import data_quality_toolkit as dqt

    assert "drift_dashboard" in dqt.__all__
    assert dqt.drift_dashboard is drift_dashboard


def test_missing_db_yields_zero_dashboard(tmp_path) -> None:
    html = drift_dashboard(tmp_path / "nope.db")
    assert html.startswith("<!DOCTYPE html>")
    assert "Drift Analytics Dashboard" in html
    assert "No drift runs available." in html
    assert "No column-level drift rows available." in html


def test_empty_db_yields_zero_dashboard(tmp_path) -> None:
    db = tmp_path / "drift.db"
    ensure_db(db)
    html = drift_dashboard(db)
    assert html.startswith("<!DOCTYPE html>")
    assert "No drift runs available." in html


def test_real_db_renders_runs(tmp_path) -> None:
    db = tmp_path / "drift.db"
    ensure_db(db)
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
                "2026-06-13T00:00:01+00:00",
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

    html = drift_dashboard(db)
    assert "<td>r1</td>" in html


def test_forwards_filters(monkeypatch, tmp_path) -> None:
    """The wrapper forwards current_dataset_id/limit to the readers."""
    summary_calls: list[dict] = []
    runs_calls: list[dict] = []

    def fake_summarize(db_path, **filters):
        summary_calls.append(filters)
        return {
            "total_runs": 0,
            "drifted_runs": 0,
            "non_drifted_runs": 0,
            "drift_rate": 0.0,
            "latest_run_id": None,
            "latest_created_at": None,
        }

    def fake_runs(db_path, **filters):
        runs_calls.append(filters)
        return []

    def fake_columns(db_path, **filters):
        return []

    monkeypatch.setattr(api_module, "summarize_drift_trends_sqlite", fake_summarize)
    monkeypatch.setattr(api_module, "read_drift_runs_sqlite", fake_runs)
    monkeypatch.setattr(api_module, "read_drift_columns_sqlite", fake_columns)

    drift_dashboard(tmp_path / "drift.db", current_dataset_id="cd1", limit=3)

    assert summary_calls[0]["current_dataset_id"] == "cd1"
    assert summary_calls[0]["limit"] == 3
    assert runs_calls[0]["current_dataset_id"] == "cd1"
    assert runs_calls[0]["limit"] == 3


def test_include_plots_default_omits_section(tmp_path) -> None:
    db = tmp_path / "drift.db"
    ensure_db(db)
    html = drift_dashboard(db)
    assert "Distribution plots" not in html


def test_include_plots_empty_db_renders_empty_state(tmp_path) -> None:
    db = tmp_path / "drift.db"
    ensure_db(db)
    html = drift_dashboard(db, include_plots=True)
    assert "<h2>Distribution plots</h2>" in html
    assert "No distribution rows available." in html


def test_include_plots_fetches_distributions(monkeypatch, tmp_path) -> None:
    """include_plots=True reads distributions via the public reader."""
    dist_calls: list[str] = []

    def fake_distributions(db_path, **_filters):
        dist_calls.append(str(db_path))
        return [
            {
                "run_id": "r1",
                "column_name": "age",
                "kind": "numeric",
                "bin_index": 0,
                "bin_label": "[-inf, 1.5)",
                "reference_prob": 0.6,
                "current_prob": 0.4,
            }
        ]

    monkeypatch.setattr(api_module, "read_drift_distributions_sqlite", fake_distributions)

    db = tmp_path / "drift.db"
    ensure_db(db)
    html = drift_dashboard(db, include_plots=True)
    assert len(dist_calls) == 1
    assert "<h2>Distribution plots</h2>" in html
    assert "[-inf, 1.5)" in html
    assert "60.0%" in html
