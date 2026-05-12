# tests/unit/workflow/test_pipeline_quality_report.py
"""Focused tests for quality_report.json written by run_export_star."""

from __future__ import annotations

import json
from pathlib import Path


def test_quality_report_written(tmp_path: Path, monkeypatch: object) -> None:
    """run_export_star writes quality_report.json with expected top-level keys."""

    from data_quality_toolkit.workflow.pipeline import run_export_star

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("id,val\n1,a\n2,\n3,c\n", encoding="utf-8")

    out = run_export_star(str(csv_file), output_dir=str(tmp_path))

    report_path = Path(out["export_paths"]["quality_report"])
    assert report_path.exists(), "quality_report.json should be written"

    report = json.loads(report_path.read_text(encoding="utf-8"))

    required_keys = {
        "run_id",
        "dataset_id",
        "ts",
        "score",
        "rows",
        "cols",
        "issues_total",
        "issues_by_severity",
        "issues_by_category",
        "artifacts",
    }
    assert required_keys <= report.keys(), f"Missing keys: {required_keys - report.keys()}"


def test_quality_report_score_range(tmp_path: Path) -> None:
    """Score in quality_report is between 0 and 1."""
    from data_quality_toolkit.workflow.pipeline import run_export_star

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    out = run_export_star(str(csv_file), output_dir=str(tmp_path))
    report_path = Path(out["export_paths"]["quality_report"])
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert 0.0 <= report["score"] <= 1.0


def test_quality_report_issues_counted(tmp_path: Path) -> None:
    """issues_total matches the sum of issues_by_severity values."""
    from data_quality_toolkit.workflow.pipeline import run_export_star

    # Column with 50 % nulls → should flag at least one issue
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("id,val\n1,\n2,\n3,x\n4,y\n", encoding="utf-8")

    out = run_export_star(str(csv_file), output_dir=str(tmp_path))
    report_path = Path(out["export_paths"]["quality_report"])
    report = json.loads(report_path.read_text(encoding="utf-8"))

    total_from_severity = sum(report["issues_by_severity"].values())
    assert report["issues_total"] == total_from_severity


def test_quality_report_duration_secs(tmp_path: Path) -> None:
    """duration_secs is a non-negative float in quality_report and the return dict."""
    from data_quality_toolkit.workflow.pipeline import run_export_star

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    out = run_export_star(str(csv_file), output_dir=str(tmp_path))

    # Present in the return value
    assert "duration_secs" in out, "duration_secs missing from run_export_star return"
    assert isinstance(out["duration_secs"], float)
    assert out["duration_secs"] >= 0.0

    # Also written into quality_report.json
    report = json.loads(Path(out["export_paths"]["quality_report"]).read_text(encoding="utf-8"))
    assert "duration_secs" in report, "duration_secs missing from quality_report.json"
    assert isinstance(report["duration_secs"], float)
    assert report["duration_secs"] >= 0.0


def test_quality_report_artifacts_subset(tmp_path: Path) -> None:
    """artifacts dict contains star CSV keys but not 'relationships'."""
    from data_quality_toolkit.workflow.pipeline import run_export_star

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("x,y\n1,2\n", encoding="utf-8")

    out = run_export_star(str(csv_file), output_dir=str(tmp_path))
    report_path = Path(out["export_paths"]["quality_report"])
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert "relationships" not in report["artifacts"]
    assert "dim_dataset" in report["artifacts"]
    assert "fact_issues" in report["artifacts"]


def test_history_record_includes_breakdown_fields(tmp_path: Path) -> None:
    """quality_history.jsonl records must include issues_by_severity and issues_by_category."""
    from data_quality_toolkit.workflow.pipeline import run_export_star

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("id,val\n1,a\n2,\n3,c\n", encoding="utf-8")

    out = run_export_star(str(csv_file), output_dir=str(tmp_path))
    history_path = Path(out["export_paths"]["quality_history"])
    assert history_path.exists(), "quality_history.jsonl should exist"

    records = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) >= 1
    last = records[-1]

    assert "issues_by_severity" in last, "history record missing issues_by_severity"
    assert "issues_by_category" in last, "history record missing issues_by_category"
    assert isinstance(last["issues_by_severity"], dict)
    assert isinstance(last["issues_by_category"], dict)
