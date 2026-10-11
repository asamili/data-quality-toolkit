from __future__ import annotations

from pathlib import Path

from data_quality_toolkit.domain.semantics import (
    build_builtin_quality_catalog,
    emit_dax,
    validate_semantics,
)
from data_quality_toolkit.domain.semantics.schema import KPI, Catalog

EXPECTED_MEASURES = {
    "completeness_rate": "Completeness Rate",
    "null_rate": "Null Rate",
    "avg_distinct_count": "Avg Distinct Count",
    "run_count": "Run Count",
    "dataset_count": "Dataset Count",
    "column_count": "Column Count",
    "total_rows_profiled": "Total Rows Profiled",
    "issue_count": "Issue Count",
    "critical_issue_count": "Critical Issue Count",
    "warning_issue_count": "Warning Issue Count",
    "quality_score_proxy": "Quality Score (proxy)",
}

EXCLUDED_MEASURE_IDS = {
    "quality_score",
    "average_quality_score",
    "latest_quality_score",
    "quality_score_trend",
    "failed_quality_gate_count",
    "duplicate_rate",
    "drift_rate",
    "drifted_column_count",
    "max_psi",
    "average_psi",
    "last_run_date",
}


def test_builtin_quality_catalog_returns_catalog_and_validates() -> None:
    catalog = build_builtin_quality_catalog()

    assert isinstance(catalog, Catalog)
    validate_semantics(catalog)


def test_builtin_quality_catalog_has_expected_now_measure_ids_and_titles() -> None:
    catalog = build_builtin_quality_catalog()

    assert catalog.kpi_ids == set(EXPECTED_MEASURES)
    assert {kpi.id: kpi.title for kpi in catalog.kpis} == EXPECTED_MEASURES


def test_builtin_quality_catalog_excludes_deferred_and_true_score_measures() -> None:
    catalog = build_builtin_quality_catalog()

    assert catalog.kpi_ids.isdisjoint(EXCLUDED_MEASURE_IDS)
    assert "Quality Score" not in {kpi.title for kpi in catalog.kpis}


def test_quality_score_proxy_is_labeled_as_proxy() -> None:
    catalog = build_builtin_quality_catalog()
    proxy = catalog.get_kpi("quality_score_proxy")

    assert proxy is not None
    assert proxy.title == "Quality Score (proxy)"
    assert proxy.description is not None
    assert "BI proxy" in proxy.description
    assert "not the true assessment quality_score" in proxy.description
    assert proxy.support_status == "proxy-current-star"


def test_builtin_quality_catalog_populates_provenance_and_support_status() -> None:
    catalog = build_builtin_quality_catalog()

    completeness = catalog.get_kpi("completeness_rate")
    issue_count = catalog.get_kpi("issue_count")
    warning_count = catalog.get_kpi("warning_issue_count")

    assert completeness is not None
    assert completeness.source_table == "fact_quality_metrics"
    assert completeness.source_columns == ["completeness"]
    assert completeness.aggregation_rule == "average"
    assert completeness.support_status == "current-star"

    assert issue_count is not None
    assert issue_count.source_table == "fact_issues"
    assert issue_count.support_status == "current-star/fact_issues-contract-validated"

    assert warning_count is not None
    assert warning_count.source_columns == ["severity"]
    assert warning_count.support_status == "current-star/fact_issues-contract-validated"


def test_builtin_quality_catalog_emits_expected_golden_dax() -> None:
    catalog = build_builtin_quality_catalog()

    generated = emit_dax(catalog)
    expected = Path("tests/golden/dqt_quality_measures_expected.dax").read_text(encoding="utf-8")

    assert generated == expected


def test_user_supplied_catalog_remains_compatible_without_provenance_fields() -> None:
    kpi = KPI(
        id="user_count",
        title="User Count",
        expression="COUNTROWS('dim_dataset')",
        grain="global",
        unit="count",
    )
    catalog = Catalog(kpis=[kpi])

    validate_semantics(catalog)
    assert catalog.get_kpi("user_count") == kpi
    assert kpi.source_table is None
    assert kpi.source_columns is None
    assert kpi.aggregation_rule is None
    assert kpi.support_status is None
