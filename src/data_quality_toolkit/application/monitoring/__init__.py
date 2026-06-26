"""Shared monitoring view-model package (v2.6.0).

Presentation-agnostic value objects and builders that normalize drift-monitoring
data read through the root ``data_quality_toolkit.api`` seam, so the static HTML
dashboard and (later) the Streamlit Drift Explorer render the same numbers.
"""

from __future__ import annotations

from data_quality_toolkit.application.monitoring.view_model import (
    ColumnDrift,
    DistributionBin,
    MonitoringOverview,
    RunDetail,
    RunRow,
    TrendSummary,
    build_column_drift,
    build_distribution_series,
    build_monitoring_overview,
    build_run_detail,
    list_run_rows,
)

__all__ = [
    "ColumnDrift",
    "DistributionBin",
    "MonitoringOverview",
    "RunDetail",
    "RunRow",
    "TrendSummary",
    "build_column_drift",
    "build_distribution_series",
    "build_monitoring_overview",
    "build_run_detail",
    "list_run_rows",
]
