# tests/unit/reports/test_drift_history_report.py
"""Unit tests for the pure drift-history report renderer."""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.reports.drift_history import (
    render_drift_history_report,
)

_SUMMARY: dict[str, Any] = {
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

_ZERO: dict[str, Any] = {
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

_RUNS: list[dict[str, Any]] = [
    {
        "run_id": "r3",
        "created_at": "2026-06-13T00:00:03+00:00",
        "current_dataset_id": "cd1",
        "status": "ok",
        "columns_tested": 4,
        "columns_drifted": 2,
        "drift_detected": 1,
    },
    {
        "run_id": "r2",
        "created_at": "2026-06-13T00:00:02+00:00",
        "current_dataset_id": "cd1",
        "status": "ok",
        "columns_tested": 4,
        "columns_drifted": 0,
        "drift_detected": 0,
    },
]


def test_markdown_includes_required_fields() -> None:
    md = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        generated_at="2026-06-13T12:00:00+00:00",
    )
    assert md.startswith("# Drift History Monitoring Report")
    assert "generated_at:** 2026-06-13T12:00:00+00:00" in md
    assert "database:** drift.db" in md
    for field in (
        "total_runs:** 3",
        "drifted_runs:** 2",
        "non_drifted_runs:** 1",
        "drift_rate:** 0.666",
        "latest_run_id:** r3",
        "latest_created_at:** 2026-06-13T00:00:03+00:00",
        "latest_drift_detected:** True",
        "columns_tested_total:** 12",
        "columns_tested_average:** 4.0",
        "columns_drifted_total:** 4",
        "columns_drifted_average:** 1.333",
    ):
        assert field in md, field


def test_markdown_recent_runs_table_rows() -> None:
    md = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        generated_at="t",
    )
    assert "| run_id | created_at | current_dataset_id | status |" in md
    assert "| r3 | 2026-06-13T00:00:03+00:00 | cd1 | ok | 4 | 2 | 1 |" in md
    assert "| r2 | 2026-06-13T00:00:02+00:00 | cd1 | ok | 4 | 0 | 0 |" in md


def test_filter_and_limit_echoed_in_header() -> None:
    md = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        current_dataset_id="cd1",
        limit=5,
        generated_at="t",
    )
    assert "current_dataset_id filter:** cd1" in md
    assert "limit:** 5" in md


def test_filter_and_limit_default_none() -> None:
    md = render_drift_history_report(
        summary=_ZERO,
        runs=[],
        db_path="drift.db",
        generated_at="t",
    )
    assert "current_dataset_id filter:** (none)" in md
    assert "limit:** (none)" in md


def test_zero_summary_empty_renders_valid_report() -> None:
    md = render_drift_history_report(
        summary=_ZERO,
        runs=[],
        db_path="missing.db",
        generated_at="t",
    )
    assert "# Drift History Monitoring Report" in md
    assert "total_runs:** 0" in md
    assert "_(no runs)_" in md


def test_generated_at_defaults_when_omitted() -> None:
    md = render_drift_history_report(summary=_ZERO, runs=[], db_path="d.db")
    assert "generated_at:** (none)" not in md
    assert "generated_at:**" in md


def test_html_format_produces_escaped_table() -> None:
    runs = [
        {
            "run_id": "<r&1>",
            "created_at": "t",
            "current_dataset_id": "cd1",
            "status": "ok",
            "columns_tested": 2,
            "columns_drifted": 0,
            "drift_detected": 0,
        }
    ]
    html = render_drift_history_report(
        summary=_SUMMARY,
        runs=runs,
        db_path="drift.db",
        generated_at="t",
        fmt="html",
    )
    assert html.startswith("<!DOCTYPE html>")
    assert "<table>" in html
    assert "<th>run_id</th>" in html
    # value escaped, raw angle brackets/ampersand not present in cell
    assert "&lt;r&amp;1&gt;" in html
    assert "<r&1>" not in html


def test_html_zero_runs_no_table() -> None:
    html = render_drift_history_report(
        summary=_ZERO,
        runs=[],
        db_path="d.db",
        generated_at="t",
        fmt="html",
    )
    assert "<h1>Drift History Monitoring Report</h1>" in html
    assert "(no runs)" in html
    assert "<table>" not in html


_COLUMNS: list[dict[str, Any]] = [
    {
        "run_id": "r3",
        "column_name": "age",
        "kind": "numeric",
        "drift_detected": 1,
        "psi": 0.31,
        "js_distance": 0.22,
        "wasserstein": 1.5,
        "status": "tested",
    }
]


def test_markdown_columns_none_omits_section() -> None:
    md = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        generated_at="t",
    )
    assert "## Column-level drift metrics" not in md


def test_markdown_columns_section_table_rows() -> None:
    md = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        generated_at="t",
        columns=_COLUMNS,
    )
    assert "## Column-level drift metrics" in md
    assert (
        "| run_id | column_name | kind | drift_detected | psi | js_distance | wasserstein | status |"
        in md
    )
    assert "| r3 | age | numeric | 1 | 0.31 | 0.22 | 1.5 | tested |" in md


def test_markdown_columns_empty_placeholder() -> None:
    md = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        generated_at="t",
        columns=[],
    )
    assert "## Column-level drift metrics" in md
    assert "_No column-level drift rows available._" in md


def test_markdown_columns_section_renders_when_no_runs() -> None:
    md = render_drift_history_report(
        summary=_ZERO,
        runs=[],
        db_path="drift.db",
        generated_at="t",
        columns=_COLUMNS,
    )
    assert "_(no runs)_" in md
    assert "## Column-level drift metrics" in md
    assert "| r3 | age |" in md


def test_html_columns_section_escaped_table() -> None:
    columns = [
        {
            "run_id": "<r&1>",
            "column_name": "age",
            "kind": "numeric",
            "drift_detected": 1,
            "psi": 0.31,
            "js_distance": 0.22,
            "wasserstein": 1.5,
            "status": "tested",
        }
    ]
    html = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        generated_at="t",
        fmt="html",
        columns=columns,
    )
    assert "<h2>Column-level drift metrics</h2>" in html
    assert "<th>column_name</th>" in html
    assert "&lt;r&amp;1&gt;" in html


def test_html_columns_none_omits_section() -> None:
    html = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        generated_at="t",
        fmt="html",
    )
    assert "Column-level drift metrics" not in html


def test_html_columns_empty_placeholder() -> None:
    html = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        generated_at="t",
        fmt="html",
        columns=[],
    )
    assert "<h2>Column-level drift metrics</h2>" in html
    assert "No column-level drift rows available." in html


_DISTRIBUTIONS: list[dict[str, Any]] = [
    {
        "run_id": "r3",
        "column_name": "age",
        "kind": "numeric",
        "bin_index": 0,
        "bin_label": "[-inf, 1.5)",
        "reference_prob": 0.6,
        "current_prob": 0.4,
    },
    {
        "run_id": "r3",
        "column_name": "age",
        "kind": "numeric",
        "bin_index": 1,
        "bin_label": "[1.5, inf)",
        "reference_prob": 0.4,
        "current_prob": 0.6,
    },
]


def test_markdown_distributions_none_omits_section() -> None:
    md = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        generated_at="t",
    )
    assert "## Distribution plots" not in md


def test_markdown_distributions_section_renders_rows() -> None:
    md = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        generated_at="t",
        distributions=_DISTRIBUTIONS,
    )
    assert "## Distribution plots" in md
    assert "### run_id=r3 · column_name=age (numeric)" in md
    assert "[-inf, 1.5)" in md
    assert "60.0%" in md
    assert "40.0%" in md
    # compact unicode block bar present
    assert "█" in md


def test_markdown_distributions_empty_placeholder() -> None:
    md = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        generated_at="t",
        distributions=[],
    )
    assert "## Distribution plots" in md
    assert "_No distribution rows available._" in md


def test_html_distributions_none_omits_section() -> None:
    html = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        generated_at="t",
        fmt="html",
    )
    assert "Distribution plots" not in html


def test_html_distributions_section_bars_and_values() -> None:
    html = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        generated_at="t",
        fmt="html",
        distributions=_DISTRIBUTIONS,
    )
    assert "<h2>Distribution plots</h2>" in html
    assert "run_id=r3 · column_name=age (numeric)" in html
    # reference / current percentages rendered
    assert "60.0%" in html
    assert "40.0%" in html
    # inline-CSS bar widths present, dependency-free
    assert "width:60.0%" in html
    assert "<script" not in html
    assert "http://" not in html
    assert "https://" not in html
    assert "<img" not in html


def test_html_distributions_escapes_labels_and_names() -> None:
    distributions = [
        {
            "run_id": "<r&1>",
            "column_name": "<col>",
            "kind": "numeric",
            "bin_index": 0,
            "bin_label": "<bin&lbl>",
            "reference_prob": 0.5,
            "current_prob": 0.5,
        }
    ]
    html = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        generated_at="t",
        fmt="html",
        distributions=distributions,
    )
    assert "&lt;r&amp;1&gt;" in html
    assert "&lt;col&gt;" in html
    assert "&lt;bin&amp;lbl&gt;" in html
    assert "<bin&lbl>" not in html


def test_html_distributions_empty_placeholder() -> None:
    html = render_drift_history_report(
        summary=_SUMMARY,
        runs=_RUNS,
        db_path="drift.db",
        generated_at="t",
        fmt="html",
        distributions=[],
    )
    assert "<h2>Distribution plots</h2>" in html
    assert "No distribution rows available." in html
