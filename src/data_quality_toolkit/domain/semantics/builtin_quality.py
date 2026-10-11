"""Built-in semantic catalog for DQT quality facts."""

from __future__ import annotations

from .schema import KPI, Catalog

CURRENT_STAR = "current-star"
_FACT_ISSUES_CONTRACT_VALIDATED = "current-star/fact_issues-contract-validated"
PROXY_CURRENT_STAR = "proxy-current-star"


def build_builtin_quality_catalog() -> Catalog:
    """Return DQT's deterministic built-in quality semantic catalog."""
    return Catalog(
        version="2.9.5",
        description="Built-in DQT quality semantic catalog using current-star NOW measures.",
        kpis=[
            KPI(
                id="completeness_rate",
                title="Completeness Rate",
                expression="AVERAGE('fact_quality_metrics'[completeness])",
                grain="global",
                unit="percent",
                description="Average column completeness from fact_quality_metrics; 1 means no nulls.",
                format_string="0.00%",
                source_table="fact_quality_metrics",
                source_columns=["completeness"],
                aggregation_rule="average",
                support_status=CURRENT_STAR,
            ),
            KPI(
                id="null_rate",
                title="Null Rate",
                expression="AVERAGE('fact_quality_metrics'[null_pct])",
                grain="global",
                unit="percent",
                description="Average column null rate from fact_quality_metrics.",
                format_string="0.00%",
                source_table="fact_quality_metrics",
                source_columns=["null_pct"],
                aggregation_rule="average",
                support_status=CURRENT_STAR,
            ),
            KPI(
                id="avg_distinct_count",
                title="Avg Distinct Count",
                expression="AVERAGE('fact_quality_metrics'[distinct_count])",
                grain="global",
                unit="count",
                description="Average profiled distinct value count across columns.",
                format_string="#,##0",
                source_table="fact_quality_metrics",
                source_columns=["distinct_count"],
                aggregation_rule="average",
                support_status=CURRENT_STAR,
            ),
            KPI(
                id="run_count",
                title="Run Count",
                expression="DISTINCTCOUNT('fact_profile_runs'[run_id])",
                grain="global",
                unit="count",
                description="Distinct profiled run count from fact_profile_runs.",
                format_string="#,##0",
                source_table="fact_profile_runs",
                source_columns=["run_id"],
                aggregation_rule="distinct_count",
                support_status=CURRENT_STAR,
            ),
            KPI(
                id="dataset_count",
                title="Dataset Count",
                expression="COUNTROWS('dim_dataset')",
                grain="global",
                unit="count",
                description="Dataset dimension row count from dim_dataset.",
                format_string="#,##0",
                source_table="dim_dataset",
                aggregation_rule="count_rows",
                support_status=CURRENT_STAR,
            ),
            KPI(
                id="column_count",
                title="Column Count",
                expression="COUNTROWS('dim_column')",
                grain="global",
                unit="count",
                description="Column dimension row count from dim_column.",
                format_string="#,##0",
                source_table="dim_column",
                aggregation_rule="count_rows",
                support_status=CURRENT_STAR,
            ),
            KPI(
                id="total_rows_profiled",
                title="Total Rows Profiled",
                expression="SUM('fact_profile_runs'[rows])",
                grain="global",
                unit="count",
                description="Total source rows profiled across profile runs.",
                format_string="#,##0",
                source_table="fact_profile_runs",
                source_columns=["rows"],
                aggregation_rule="sum",
                support_status=CURRENT_STAR,
            ),
            KPI(
                id="issue_count",
                title="Issue Count",
                expression="COUNTROWS('fact_issues')",
                grain="global",
                unit="count",
                format_string="#,##0",
                source_table="fact_issues",
                aggregation_rule="count_rows",
                description="Contract-validated current-star fact_issues row count.",
                support_status=_FACT_ISSUES_CONTRACT_VALIDATED,
            ),
            KPI(
                id="critical_issue_count",
                title="Critical Issue Count",
                expression=(
                    "CALCULATE(COUNTROWS('fact_issues'), " "'fact_issues'[severity] = \"critical\")"
                ),
                grain="global",
                unit="count",
                description="Contract-validated current-star fact_issues critical severity count.",
                format_string="#,##0",
                source_table="fact_issues",
                source_columns=["severity"],
                aggregation_rule="count_rows_where_severity_equals_critical",
                support_status=_FACT_ISSUES_CONTRACT_VALIDATED,
            ),
            KPI(
                id="warning_issue_count",
                title="Warning Issue Count",
                expression=(
                    "CALCULATE(COUNTROWS('fact_issues'), " "'fact_issues'[severity] = \"warning\")"
                ),
                grain="global",
                unit="count",
                description="Contract-validated current-star fact_issues warning severity count.",
                format_string="#,##0",
                source_table="fact_issues",
                source_columns=["severity"],
                aggregation_rule="count_rows_where_severity_equals_warning",
                support_status=_FACT_ISSUES_CONTRACT_VALIDATED,
            ),
            KPI(
                id="quality_score_proxy",
                title="Quality Score (proxy)",
                expression=(
                    "(( [Completeness Rate] * 0.5 ) + " "( ( 1 - [Null Rate] ) * 0.5 )) * 100"
                ),
                grain="global",
                unit="score",
                depends_on=["completeness_rate", "null_rate"],
                description=(
                    "BI proxy derived from completeness and null rate; not the true assessment "
                    "quality_score."
                ),
                format_string="0.0",
                source_columns=[
                    "fact_quality_metrics.completeness",
                    "fact_quality_metrics.null_pct",
                ],
                aggregation_rule="weighted_proxy_from_bi_measures",
                support_status=PROXY_CURRENT_STAR,
            ),
        ],
    )


def get_builtin_quality_catalog() -> Catalog:
    """Alias for callers that prefer get-style catalog construction."""
    return build_builtin_quality_catalog()
