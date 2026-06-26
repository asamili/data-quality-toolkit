"""Unit tests for the shared monitoring view-model (v2.6.0).

These tests exercise the presentation-agnostic value objects and builders in
``data_quality_toolkit.application.monitoring.view_model`` by monkeypatching the
root ``data_quality_toolkit.api`` seam the builders read through, so they need no
real database and never touch Streamlit or storage adapters directly.
"""

from __future__ import annotations

import ast
import inspect

import data_quality_toolkit.api as api_module
from data_quality_toolkit.application.monitoring import view_model as vm


def _imported_modules(module) -> set[str]:
    """Return the set of module names referenced by import statements (AST-based)."""
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


# --- Sample API-shaped payloads (mirror the storage/API reader dict shapes). ---

_SUMMARY = {
    "total_runs": 3,
    "drifted_runs": 2,
    "non_drifted_runs": 1,
    "drift_rate": 2 / 3,
    "latest_run_id": "r3",
    "latest_created_at": "2026-06-13T00:00:03+00:00",
    "latest_drift_detected": 1,
    "columns_tested_total": 12,
    "columns_tested_average": 4.0,
    "columns_drifted_total": 5,
    "columns_drifted_average": 1.6666,
}

_RUNS = [
    {
        "run_id": "r3",
        "created_at": "2026-06-13T00:00:03+00:00",
        "current_dataset_id": "cd1",
        "status": "ok",
        "drift_detected": 1,
        "columns_tested": 4,
        "columns_drifted": 2,
        "columns_skipped": 0,
    },
    {
        "run_id": "r2",
        "created_at": "2026-06-13T00:00:02+00:00",
        "current_dataset_id": "cd1",
        "status": "ok",
        "drift_detected": 0,
        "columns_tested": 4,
        "columns_drifted": 0,
        "columns_skipped": 0,
    },
]

_COLUMNS = [
    {
        "run_id": "r3",
        "column_name": "amount",
        "kind": "numeric",
        "test": "ks",
        "statistic": 0.4,
        "p_value": 0.01,
        "drift_detected": 1,
        "reference_n": 100,
        "current_n": 120,
        "status": "ok",
        "skip_reason": None,
        "psi": 0.27,
        "js_distance": 0.18,
        "wasserstein": 3.5,
    }
]

_DISTRIBUTIONS = [
    {
        "run_id": "r3",
        "column_name": "amount",
        "kind": "numeric",
        "bin_index": 0,
        "bin_label": "[0, 10)",
        "reference_prob": 0.5,
        "current_prob": 0.3,
    },
    {
        "run_id": "r3",
        "column_name": "amount",
        "kind": "numeric",
        "bin_index": 1,
        "bin_label": "[10, inf)",
        "reference_prob": 0.5,
        "current_prob": 0.7,
    },
]


def _patch_api(monkeypatch, *, summary=None, runs=None, columns=None, distributions=None):
    """Monkeypatch the four api reader seams the view-model builders call lazily."""
    s = _SUMMARY if summary is None else summary
    r = _RUNS if runs is None else runs
    c = _COLUMNS if columns is None else columns
    d = _DISTRIBUTIONS if distributions is None else distributions
    monkeypatch.setattr(api_module, "summarize_drift_trends_sqlite", lambda *a, **k: s)
    monkeypatch.setattr(api_module, "read_drift_runs_sqlite", lambda *a, **k: list(r))
    monkeypatch.setattr(api_module, "read_drift_columns_sqlite", lambda *a, **k: list(c))
    monkeypatch.setattr(api_module, "read_drift_distributions_sqlite", lambda *a, **k: list(d))


# --- Dataclass to_dict + normalization ---------------------------------------


def test_run_row_normalizes_drift_detected_int_to_bool():
    row = vm.RunRow.from_row(_RUNS[0])
    assert row.drift_detected is True
    assert vm.RunRow.from_row(_RUNS[1]).drift_detected is False


def test_run_row_preserves_none_drift_detected():
    row = vm.RunRow.from_row({"run_id": "r", "drift_detected": None})
    assert row.drift_detected is None


def test_run_row_projects_alpha_when_present():
    row = vm.RunRow.from_row({"run_id": "r", "alpha": 0.05})
    assert row.alpha == 0.05
    assert row.to_dict()["alpha"] == 0.05


def test_run_row_alpha_none_when_missing():
    # Existing sample rows carry no alpha key.
    row = vm.RunRow.from_row(_RUNS[0])
    assert row.alpha is None
    assert row.to_dict()["alpha"] is None


def test_run_row_alpha_none_when_invalid():
    row = vm.RunRow.from_row({"run_id": "r", "alpha": "not-a-number"})
    assert row.alpha is None


def test_run_row_to_dict_excludes_path_fields():
    # Path fields must never appear, even if present on the source row.
    row = vm.RunRow.from_row(
        {
            "run_id": "r",
            "alpha": 0.01,
            "baseline_path": "/secret/baseline.csv",
            "current_path": "/secret/current.csv",
            "report_path": "/secret/report.html",
        }
    )
    d = row.to_dict()
    assert "baseline_path" not in d
    assert "current_path" not in d
    assert "report_path" not in d
    assert "alpha" in d


def test_run_rows_preserve_newest_first_ordering(monkeypatch):
    _patch_api(monkeypatch)
    rows = vm.list_run_rows("any.db")
    assert [r.run_id for r in rows] == ["r3", "r2"]


def test_column_drift_to_dict_roundtrips_metrics():
    col = vm.ColumnDrift.from_row(_COLUMNS[0])
    d = col.to_dict()
    assert d["psi"] == 0.27
    assert d["js_distance"] == 0.18
    assert d["wasserstein"] == 3.5
    assert d["drift_detected"] is True
    assert set(d) == {
        "column_name",
        "kind",
        "test",
        "drift_detected",
        "statistic",
        "p_value",
        "psi",
        "js_distance",
        "wasserstein",
        "reference_n",
        "current_n",
        "status",
        "skip_reason",
    }


def test_distribution_bin_to_dict():
    b = vm.DistributionBin.from_row(_DISTRIBUTIONS[0])
    # DistributionBin is a per-column projection and carries no run_id.
    expected = {k: v for k, v in _DISTRIBUTIONS[0].items() if k != "run_id"}
    assert b.to_dict() == expected


def test_trend_summary_to_dict_keys():
    s = vm.TrendSummary.from_summary(_SUMMARY)
    d = s.to_dict()
    assert d["total_runs"] == 3
    assert d["drifted_runs"] == 2
    assert d["latest_drift_detected"] is True


# --- Builders -----------------------------------------------------------------


def test_list_run_rows_returns_run_row_objects(monkeypatch):
    _patch_api(monkeypatch)
    rows = vm.list_run_rows("any.db")
    assert all(isinstance(r, vm.RunRow) for r in rows)
    assert [r.run_id for r in rows] == ["r3", "r2"]


def test_build_monitoring_overview_returns_summary_and_runs(monkeypatch):
    _patch_api(monkeypatch)
    overview = vm.build_monitoring_overview("any.db", current_dataset_id="cd1", limit=5)
    assert isinstance(overview, vm.MonitoringOverview)
    assert overview.summary.total_runs == 3
    assert len(overview.runs) == 2
    assert overview.db_path == "any.db"
    assert overview.current_dataset_id == "cd1"
    assert overview.limit == 5
    assert overview.generated_at  # non-empty ISO timestamp


def test_build_run_detail_returns_run_columns_distributions(monkeypatch):
    _patch_api(monkeypatch)
    detail = vm.build_run_detail("any.db", "r3")
    assert isinstance(detail, vm.RunDetail)
    assert detail.run.run_id == "r3"
    assert len(detail.columns) == 1
    assert detail.columns[0].column_name == "amount"
    assert len(detail.distributions) == 2


def test_build_run_detail_without_distributions(monkeypatch):
    _patch_api(monkeypatch)
    detail = vm.build_run_detail("any.db", "r3", include_distributions=False)
    assert detail.distributions == []


def test_build_run_detail_unknown_run_id_minimal_row(monkeypatch):
    _patch_api(monkeypatch, columns=[], distributions=[])
    detail = vm.build_run_detail("any.db", "does-not-exist")
    assert detail.run.run_id == "does-not-exist"
    assert detail.run.status is None
    assert detail.columns == []


def test_build_distribution_series(monkeypatch):
    _patch_api(monkeypatch)
    bins = vm.build_distribution_series("any.db", "r3", "amount")
    assert [b.bin_index for b in bins] == [0, 1]
    assert all(isinstance(b, vm.DistributionBin) for b in bins)


# --- Empty / missing DB stability --------------------------------------------


def test_empty_db_yields_zeroed_overview(monkeypatch):
    empty_summary = {
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
    _patch_api(monkeypatch, summary=empty_summary, runs=[], columns=[], distributions=[])
    overview = vm.build_monitoring_overview("missing.db")
    assert overview.summary.total_runs == 0
    assert overview.runs == []


# --- Optional-dependency / layering boundary (static source inspection) -------


def test_view_model_does_not_import_streamlit():
    assert not any(m.split(".")[0] == "streamlit" for m in _imported_modules(vm))


def test_view_model_does_not_import_storage_adapters_directly():
    assert not any("adapters.storage" in m for m in _imported_modules(vm))
