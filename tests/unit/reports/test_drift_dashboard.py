# tests/unit/reports/test_drift_dashboard.py
"""Unit tests for the pure ``render_drift_dashboard`` renderer (no I/O)."""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.reports.drift_dashboard import render_drift_dashboard

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

_RUNS = [
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

_COLUMNS = [
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


def _render(**overrides: Any) -> str:
    kwargs: dict[str, Any] = {
        "summary": _SUMMARY,
        "runs": _RUNS,
        "columns": _COLUMNS,
        "db_path": "drift.db",
        "generated_at": "2026-06-13T12:00:00+00:00",
    }
    kwargs.update(overrides)
    return render_drift_dashboard(**kwargs)


def test_self_contained_html_document() -> None:
    html = _render()
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html
    assert "<title>Drift Analytics Dashboard</title>" in html
    assert "<style>" in html


def test_no_external_assets_or_javascript() -> None:
    html = _render()
    assert "<script" not in html
    assert "http://" not in html
    assert "https://" not in html
    assert "cdn" not in html.lower()
    assert "<img" not in html


def test_title_and_meta_present() -> None:
    html = _render()
    assert "<h1>Drift Analytics Dashboard</h1>" in html
    assert "generated_at:</strong> 2026-06-13T12:00:00+00:00" in html
    assert "database:</strong> drift.db" in html


def test_summary_cards_present() -> None:
    html = _render()
    for label in (
        "total_runs",
        "drifted_runs",
        "non_drifted_runs",
        "drift_rate",
        "latest_run_id",
        "latest_created_at",
    ):
        assert f'<div class="label">{label}</div>' in html
    assert "r3" in html  # latest_run_id value


def test_run_table_rows_present() -> None:
    html = _render()
    assert "<th>run_id</th>" in html
    assert "<th>columns_tested</th>" in html
    assert "<td>r3</td>" in html
    assert "<td>r2</td>" in html


def test_column_table_rows_present() -> None:
    html = _render()
    assert "Column-level drift metrics" in html
    assert "<th>psi</th>" in html
    assert "<th>wasserstein</th>" in html
    assert "<td>age</td>" in html
    assert "<td>0.31</td>" in html


def test_current_dataset_id_and_limit_shown_when_provided() -> None:
    html = _render(current_dataset_id="cd1", limit=5)
    assert "current_dataset_id filter:</strong> cd1" in html
    assert "limit:</strong> 5" in html


def test_filters_omitted_when_absent() -> None:
    html = _render()
    assert "current_dataset_id filter" not in html
    assert "limit:</strong>" not in html


def test_html_escaping() -> None:
    runs = [
        {
            "run_id": "<r&1>",
            "created_at": "t",
            "current_dataset_id": "cd1",
            "status": "ok",
            "columns_tested": 1,
            "columns_drifted": 0,
            "drift_detected": 0,
        }
    ]
    html = _render(runs=runs)
    assert "&lt;r&amp;1&gt;" in html
    assert "<td><r&1></td>" not in html


def test_empty_runs_and_columns_show_empty_state() -> None:
    html = _render(summary=_ZERO, runs=[], columns=[])
    assert html.startswith("<!DOCTYPE html>")
    assert "No drift runs available." in html
    assert "No column-level drift rows available." in html


def test_zero_summary_renders_valid_dashboard() -> None:
    html = _render(summary=_ZERO, runs=[], columns=[])
    assert "<h1>Drift Analytics Dashboard</h1>" in html
    assert '<div class="value">0</div>' in html  # total_runs card
    assert "(none)" in html  # latest_run_id None display


def test_generated_at_defaults_when_omitted() -> None:
    html = render_drift_dashboard(
        summary=_ZERO,
        runs=[],
        columns=[],
        db_path="drift.db",
    )
    assert "generated_at:</strong>" in html
    assert "Drift Analytics Dashboard" in html


_DISTRIBUTIONS = [
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


def test_distributions_none_omits_section() -> None:
    html = _render()
    assert "Distribution plots" not in html


def test_distributions_section_renders_bars_and_values() -> None:
    html = _render(distributions=_DISTRIBUTIONS)
    assert "<h2>Distribution plots</h2>" in html
    assert "run_id=r3 · column_name=age (numeric)" in html
    assert "[-inf, 1.5)" in html
    # reference vs current percentages in the same group
    assert "60.0%" in html
    assert "40.0%" in html
    # inline-CSS bar widths present
    assert "width:60.0%" in html
    assert 'class="dist-fill"' in html


def test_distributions_section_self_contained() -> None:
    html = _render(distributions=_DISTRIBUTIONS)
    assert "<script" not in html
    assert "http://" not in html
    assert "https://" not in html
    assert "cdn" not in html.lower()
    assert "<img" not in html


def test_distributions_escaping() -> None:
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
    html = _render(distributions=distributions)
    assert "&lt;r&amp;1&gt;" in html
    assert "&lt;col&gt;" in html
    assert "&lt;bin&amp;lbl&gt;" in html
    assert "<bin&lbl>" not in html


def test_distributions_empty_state() -> None:
    html = _render(distributions=[])
    assert "<h2>Distribution plots</h2>" in html
    assert "No distribution rows available." in html
