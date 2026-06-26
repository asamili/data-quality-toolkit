"""G8C2B: typed public result contracts for evaluators and stable small-return functions.

Proves each new TypedDict is importable from both the package root and the api seam,
present in __all__, and that runtime return shapes are unchanged (still plain dicts).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_RESULT_TYPES = [
    "DriftRateThresholdResult",
    "PsiOffender",
    "PsiThresholdResult",
    "ColumnPlan",
    "PlanCsvResult",
    "DimTimeResult",
    "KpiEmitResult",
    "KpiGraphResult",
    "SummarizeDriftTrendsResult",
]


@pytest.mark.parametrize("name", _RESULT_TYPES)
def test_result_type_importable_from_root(name: str) -> None:
    root = importlib.import_module("data_quality_toolkit")
    assert hasattr(root, name), f"{name} missing from data_quality_toolkit"
    assert name in root.__all__, f"{name} missing from data_quality_toolkit.__all__"


@pytest.mark.parametrize("name", _RESULT_TYPES)
def test_result_type_importable_from_api_seam(name: str) -> None:
    api = importlib.import_module("data_quality_toolkit.api")
    assert hasattr(api, name), f"{name} missing from data_quality_toolkit.api"
    assert name in api.__all__, f"{name} missing from data_quality_toolkit.api.__all__"


@pytest.mark.parametrize("name", _RESULT_TYPES)
def test_result_type_importable_from_shared(name: str) -> None:
    mod = importlib.import_module("data_quality_toolkit.shared.result_types")
    assert hasattr(mod, name), f"{name} missing from shared.result_types"
    assert name in mod.__all__, f"{name} missing from shared.result_types.__all__"


def test_evaluate_drift_rate_threshold_returns_dict_with_required_keys() -> None:
    from data_quality_toolkit import evaluate_drift_rate_threshold

    result = evaluate_drift_rate_threshold({"drift_rate": 0.4}, max_drift_rate=0.3)
    assert isinstance(result, dict)
    assert "breached" in result
    assert "drift_rate" in result
    assert "threshold" in result
    assert result["breached"] is True
    assert result["drift_rate"] == 0.4
    assert result["threshold"] == 0.3


def test_evaluate_drift_rate_threshold_not_breached() -> None:
    from data_quality_toolkit import evaluate_drift_rate_threshold

    result = evaluate_drift_rate_threshold({"drift_rate": 0.3}, max_drift_rate=0.3)
    assert result["breached"] is False


def test_evaluate_psi_threshold_returns_dict_with_required_keys() -> None:
    from data_quality_toolkit import evaluate_psi_threshold

    columns = [{"column_name": "amount", "psi": 0.27}, {"column_name": "price", "psi": 0.1}]
    result = evaluate_psi_threshold(columns, max_psi=0.2)
    assert isinstance(result, dict)
    assert "breached" in result
    assert "threshold" in result
    assert "offenders" in result
    assert result["breached"] is True
    assert result["threshold"] == 0.2
    assert result["offenders"] == [{"column_name": "amount", "psi": 0.27}]


def test_evaluate_psi_threshold_offender_keys() -> None:
    from data_quality_toolkit import evaluate_psi_threshold

    result = evaluate_psi_threshold([{"column_name": "x", "psi": 0.5}], max_psi=0.1)
    offender = result["offenders"][0]
    assert "column_name" in offender
    assert "psi" in offender


def test_evaluate_psi_threshold_empty_offenders() -> None:
    from data_quality_toolkit import evaluate_psi_threshold

    result = evaluate_psi_threshold([{"column_name": "x", "psi": 0.05}], max_psi=0.1)
    assert result["breached"] is False
    assert result["offenders"] == []


def test_plan_csv_shape(tmp_path: Path) -> None:
    from data_quality_toolkit import plan_csv

    csv = Path(tmp_path) / "t.csv"
    csv.write_text("a,b\n1,x\n2,y\n", encoding="utf-8")
    result = plan_csv(csv)
    assert isinstance(result, dict)
    assert "dataset_id" in result
    assert "columns" in result
    assert isinstance(result["columns"], list)
    col = result["columns"][0]
    assert "column" in col
    assert "dtype" in col
    assert "issues" in col
    assert "recommendations" in col


def test_generate_dim_time_shape_no_output() -> None:
    from data_quality_toolkit import generate_dim_time

    result = generate_dim_time(start_date="2024-01-01", end_date="2024-01-03")
    assert isinstance(result, dict)
    assert result["rows"] == 3
    assert result["start_date"] == "2024-01-01"
    assert result["end_date"] == "2024-01-03"
    assert "week_start" in result
    assert "path" not in result
    assert "fiscal_year_start" not in result


def test_generate_dim_time_optional_keys(tmp_path: Path) -> None:
    from data_quality_toolkit import generate_dim_time

    result = generate_dim_time(
        start_date="2024-01-01",
        end_date="2024-01-02",
        fiscal_year_start=4,
        output_dir=Path(tmp_path),
    )
    assert "fiscal_year_start" in result
    assert result["fiscal_year_start"] == 4
    assert "path" in result


def test_kpi_emit_shape(tmp_path: Path) -> None:
    from data_quality_toolkit import kpi_emit

    result = kpi_emit(
        "config/kpi_catalog.yaml",
        Path(tmp_path) / "measures.dax",
        Path(tmp_path) / "model.tmsl.json",
    )
    assert isinstance(result, dict)
    assert result["status"] == "success"
    assert "kpis" in result
    assert "dax" in result
    assert "tmsl" in result


def test_kpi_graph_shape(tmp_path: Path) -> None:
    from data_quality_toolkit import kpi_graph

    result = kpi_graph("config/kpi_catalog.yaml", Path(tmp_path) / "graph.mmd")
    assert isinstance(result, dict)
    assert result["status"] == "success"
    assert "graph" in result
    assert "format" in result
    assert "nodes" in result


def test_summarize_drift_trends_sqlite_stable_zero_shape(tmp_path: Path) -> None:
    from data_quality_toolkit import summarize_drift_trends_sqlite

    result = summarize_drift_trends_sqlite(Path(tmp_path) / "nonexistent.db")
    assert isinstance(result, dict)
    expected_keys = {
        "total_runs",
        "drifted_runs",
        "non_drifted_runs",
        "drift_rate",
        "latest_run_id",
        "latest_created_at",
        "latest_drift_detected",
        "columns_tested_total",
        "columns_tested_average",
        "columns_drifted_total",
        "columns_drifted_average",
    }
    assert expected_keys <= result.keys()
    assert result["total_runs"] == 0
    assert result["drift_rate"] == 0.0


def test_result_types_are_plain_dicts_at_runtime() -> None:
    from data_quality_toolkit import evaluate_drift_rate_threshold, evaluate_psi_threshold

    rate_result = evaluate_drift_rate_threshold({"drift_rate": 0.1}, max_drift_rate=0.5)
    psi_result = evaluate_psi_threshold([], max_psi=0.2)
    assert type(rate_result) is dict
    assert type(psi_result) is dict
