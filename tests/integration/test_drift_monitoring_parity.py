"""Cross-surface parity tests for the v2.6.0 Unified Monitoring Experience.

Builds a small real SQLite monitoring database in ``tmp_path`` and asserts that
the shared monitoring view-model, the Streamlit-free UI service, and the static
dashboard renderer all derive consistent values from the same underlying
API/storage query surfaces. No Streamlit server is launched and no brittle
full-HTML snapshots are taken — only stable shared data structures and text
markers are compared.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import data_quality_toolkit.api as api
from data_quality_toolkit.adapters.storage.connection import connect
from data_quality_toolkit.adapters.storage.schema import ensure_db
from data_quality_toolkit.adapters.ui.services import monitoring as svc
from data_quality_toolkit.application.monitoring import view_model as vm

# --- Fixture data -------------------------------------------------------------

_RUNS = [
    # (run_id, created_at, current_dataset_id, status, drift_detected,
    #  columns_tested, columns_skipped, columns_drifted)
    ("r1", "2026-06-13T00:00:01+00:00", "cd1", "ok", 0, 4, 0, 0),
    ("r2", "2026-06-13T00:00:02+00:00", "cd1", "ok", 1, 4, 0, 2),
    ("r3", "2026-06-13T00:00:03+00:00", "cd1", "ok", 1, 4, 0, 1),
]

_COLUMNS = [
    # (run_id, column_name, kind, test, statistic, p_value, drift_detected,
    #  reference_n, current_n, status, skip_reason, psi, js_distance, wasserstein)
    ("r2", "amount", "numeric", "ks", 0.40, 0.01, 1, 100, 120, "ok", None, 0.27, 0.18, 3.5),
    ("r2", "country", "categorical", "chi2", 12.0, 0.02, 1, 100, 120, "ok", None, 0.31, 0.22, None),
]

_DISTRIBUTIONS = [
    # (run_id, column_name, kind, bin_index, bin_label, reference_prob, current_prob)
    ("r2", "amount", "numeric", 0, "[0, 10)", 0.5, 0.3),
    ("r2", "amount", "numeric", 1, "[10, inf)", 0.5, 0.7),
]


def _build_db(tmp_path: Path) -> Path:
    """Create and populate a real monitoring DB (storage is fair game in tests)."""
    db_path = tmp_path / "monitoring.db"
    ensure_db(db_path)
    with connect(db_path) as con:
        for run in _RUNS:
            con.execute(
                """
                INSERT INTO drift_runs(
                    run_id, created_at, baseline_path, current_path,
                    baseline_dataset_id, current_dataset_id, status, alpha,
                    columns_tested, columns_skipped, columns_drifted,
                    drift_detected, report_path, schema_version
                ) VALUES (?, ?, 'b.csv', 'c.csv', 'bd1', ?, ?, 0.05, ?, ?, ?, ?, NULL, '1')
                """,
                (run[0], run[1], run[2], run[3], run[5], run[6], run[7], run[4]),
            )
        for col in _COLUMNS:
            con.execute(
                """
                INSERT INTO drift_columns(
                    run_id, column_name, kind, test, statistic, p_value,
                    drift_detected, reference_n, current_n, status, skip_reason,
                    psi, js_distance, wasserstein
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                col,
            )
        for dist in _DISTRIBUTIONS:
            con.execute(
                """
                INSERT INTO drift_column_distributions(
                    run_id, column_name, kind, bin_index, bin_label,
                    reference_prob, current_prob
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                dist,
            )
        con.commit()
    return db_path


# --- Overview / trend parity --------------------------------------------------


def test_overview_matches_api_summary_and_runs(tmp_path):
    db = _build_db(tmp_path)
    overview = vm.build_monitoring_overview(db)
    api_summary = api.summarize_drift_trends_sqlite(db)
    api_runs = api.read_drift_runs_sqlite(db)

    # Trend summary parity.
    assert overview.summary.total_runs == api_summary["total_runs"] == 3
    assert overview.summary.drifted_runs == api_summary["drifted_runs"] == 2
    assert overview.summary.drift_rate == api_summary["drift_rate"]

    # Run-count and run-id parity.
    assert len(overview.runs) == len(api_runs) == 3
    assert {r.run_id for r in overview.runs} == {r["run_id"] for r in api_runs}


def test_ui_service_overview_equals_view_model(tmp_path):
    db = _build_db(tmp_path)
    data, err = svc.load_monitoring_overview(str(db))
    assert err is None and data is not None
    direct = vm.build_monitoring_overview(db)
    assert data.summary.to_dict() == direct.summary.to_dict()
    assert [r.run_id for r in data.runs] == [r.run_id for r in direct.runs]


# --- Column / distribution parity --------------------------------------------


def test_column_metrics_match_api(tmp_path):
    db = _build_db(tmp_path)
    detail = vm.build_run_detail(db, "r2")
    api_cols = api.read_drift_columns_sqlite(db, run_id="r2")
    assert len(detail.columns) == len(api_cols) == 2
    vm_by_name = {c.column_name: c for c in detail.columns}
    api_by_name = {c["column_name"]: c for c in api_cols}
    for name in api_by_name:
        assert vm_by_name[name].psi == api_by_name[name]["psi"]
        assert vm_by_name[name].js_distance == api_by_name[name]["js_distance"]
        assert vm_by_name[name].wasserstein == api_by_name[name]["wasserstein"]


def test_distribution_rows_match_api(tmp_path):
    db = _build_db(tmp_path)
    series = vm.build_distribution_series(db, "r2", "amount")
    api_dist = api.read_drift_distributions_sqlite(db, run_id="r2", column_name="amount")
    assert len(series) == len(api_dist) == 2
    assert [b.reference_prob for b in series] == [d["reference_prob"] for d in api_dist]
    assert [b.current_prob for b in series] == [d["current_prob"] for d in api_dist]


# --- Dashboard (static HTML) vs UI service share the same derived values ------


def test_static_dashboard_and_ui_service_agree_on_counts(tmp_path):
    db = _build_db(tmp_path)
    from data_quality_toolkit.adapters.reports.drift_dashboard import render_drift_dashboard

    summary = api.summarize_drift_trends_sqlite(db)
    runs = api.read_drift_runs_sqlite(db)
    columns = api.read_drift_columns_sqlite(db)
    distributions = api.read_drift_distributions_sqlite(db)
    html = render_drift_dashboard(
        summary=summary,
        runs=runs,
        columns=columns,
        db_path=str(db),
        current_dataset_id=None,
        limit=None,
        distributions=distributions,
    )

    ui_overview, err = svc.load_monitoring_overview(str(db))
    assert err is None and ui_overview is not None

    # Both surfaces derive from the same totals; the static dashboard text
    # carries the same run count the UI service exposes (stable marker, not a
    # byte-for-byte HTML snapshot).
    assert ui_overview.summary.total_runs == summary["total_runs"]
    assert str(summary["total_runs"]) in html
    assert "amount" in html  # column-level row rendered from the shared columns


# --- Empty-state and missing-DB consistency ----------------------------------


def test_empty_db_consistent_across_surfaces(tmp_path):
    db = tmp_path / "empty.db"
    ensure_db(db)  # schema only, no rows

    overview = vm.build_monitoring_overview(db)
    assert overview.summary.total_runs == 0
    assert overview.runs == []

    data, err = svc.load_monitoring_overview(str(db))
    assert err is None
    assert data is not None
    assert data.summary.total_runs == 0
    assert data.runs == []


def test_missing_db_view_model_does_not_raise_service_reports_error(tmp_path):
    missing = tmp_path / "does_not_exist.db"

    # View-model tolerates a missing DB (stable zero behavior, no raise).
    overview = vm.build_monitoring_overview(missing)
    assert overview.summary.total_runs == 0

    # UI service surfaces a clean error for the missing file (path guard).
    data, err = svc.load_monitoring_overview(str(missing))
    assert data is None
    assert err


# --- Threshold evaluator parity (v2.6.1) -------------------------------------


def test_drift_rate_threshold_api_matches_expected(tmp_path):
    db = _build_db(tmp_path)
    summary = api.summarize_drift_trends_sqlite(db)
    result = api.evaluate_drift_rate_threshold(summary, max_drift_rate=0.5)
    assert result["drift_rate"] == pytest.approx(summary["drift_rate"])
    assert result["threshold"] == pytest.approx(0.5)
    assert isinstance(result["breached"], bool)


def test_drift_rate_threshold_breach_above_actual_rate(tmp_path):
    db = _build_db(tmp_path)
    summary = api.summarize_drift_trends_sqlite(db)
    actual_rate = summary["drift_rate"]
    result_no_breach = api.evaluate_drift_rate_threshold(summary, max_drift_rate=actual_rate)
    result_breach = api.evaluate_drift_rate_threshold(summary, max_drift_rate=actual_rate - 0.01)
    assert result_no_breach["breached"] is False
    assert result_breach["breached"] is True


def test_psi_threshold_api_matches_expected(tmp_path):
    db = _build_db(tmp_path)
    columns = api.read_drift_columns_sqlite(db)
    result = api.evaluate_psi_threshold(columns, max_psi=0.5)
    assert isinstance(result["breached"], bool)
    assert isinstance(result["offenders"], list)
    assert result["threshold"] == pytest.approx(0.5)


def test_psi_threshold_breach_below_max_psi(tmp_path):
    db = _build_db(tmp_path)
    columns = api.read_drift_columns_sqlite(db)
    psi_values = [c["psi"] for c in columns if c.get("psi") is not None]
    if psi_values:
        max_psi_in_data = max(psi_values)
        result_no_breach = api.evaluate_psi_threshold(columns, max_psi=max_psi_in_data)
        result_breach = api.evaluate_psi_threshold(columns, max_psi=max_psi_in_data - 0.01)
        assert result_no_breach["breached"] is False
        assert result_breach["breached"] is True


def test_drift_rate_threshold_empty_db_exits_no_breach(tmp_path):
    db = tmp_path / "empty.db"
    ensure_db(db)
    summary = api.summarize_drift_trends_sqlite(db)
    result = api.evaluate_drift_rate_threshold(summary, max_drift_rate=0.3)
    assert result["breached"] is False
    assert result["drift_rate"] == pytest.approx(0.0)


def test_psi_threshold_missing_db_empty_columns_no_breach(tmp_path):
    missing = tmp_path / "does_not_exist.db"
    columns = api.read_drift_columns_sqlite(missing)
    result = api.evaluate_psi_threshold(columns, max_psi=0.2)
    assert result["breached"] is False
    assert result["offenders"] == []
