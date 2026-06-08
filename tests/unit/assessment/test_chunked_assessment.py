from __future__ import annotations

import os
from pathlib import Path

import pytest

from data_quality_toolkit.application.workflow.pipeline import (
    run_assessment,
    run_assessment_chunked,
)


@pytest.fixture
def simple_csv(tmp_path: Path) -> Path:
    p = tmp_path / "simple.csv"
    p.write_text("id,val,name\n1,10,Alice\n2,20,\n3,30,Bob\n4,40,Carol\n", encoding="utf-8")
    return p


def test_chunked_assess_assessment_mode_is_chunked(simple_csv: Path) -> None:
    out = run_assessment_chunked(str(simple_csv), chunksize=2)
    assert out["assessment"]["assessment_mode"] == "chunked"


def test_chunked_assess_approximate_true(simple_csv: Path) -> None:
    out = run_assessment_chunked(str(simple_csv), chunksize=2)
    assert out["approximate"] is True
    assert out["assessment"]["approximate"] is True


def test_chunked_assess_has_unsupported_rules(simple_csv: Path) -> None:
    out = run_assessment_chunked(str(simple_csv), chunksize=2)
    ur = out["assessment"]["unsupported_rules"]
    for rule in (
        "constant_column",
        "high_cardinality",
        "numeric_outliers",
        "accepted_values_violation",
        "uniqueness_violation",
    ):
        assert rule in ur


def test_chunked_assess_has_completeness_score(simple_csv: Path) -> None:
    out = run_assessment_chunked(str(simple_csv), chunksize=2)
    assert "completeness_score" in out["assessment"]
    assert isinstance(out["assessment"]["completeness_score"], float)


def test_chunked_assess_no_quality_score(simple_csv: Path) -> None:
    out = run_assessment_chunked(str(simple_csv), chunksize=2)
    assert "quality_score" not in out["assessment"]


def test_chunked_assess_completeness_score_matches_full(simple_csv: Path) -> None:
    full = run_assessment(str(simple_csv))
    chunked = run_assessment_chunked(str(simple_csv), chunksize=2)
    assert chunked["assessment"]["completeness_score"] == full["assessment"]["completeness_score"]


def test_chunked_assess_has_issues_list(simple_csv: Path) -> None:
    out = run_assessment_chunked(str(simple_csv), chunksize=2)
    assert isinstance(out["assessment"]["issues"], list)


def test_chunked_assess_detects_missing_values(tmp_path: Path) -> None:
    """completeness/missing rule works in chunked mode."""
    p = tmp_path / "nulls.csv"
    rows_str = "\n".join([f"{i}," for i in range(8)])
    p.write_text(f"id,name\n{rows_str}\n8,Alice\n9,Bob\n", encoding="utf-8")
    out = run_assessment_chunked(str(p), chunksize=3)
    issue_types = [i["type"] for i in out["assessment"]["issues"]]
    assert "missing" in issue_types


def test_chunked_assess_detects_all_null_column(tmp_path: Path) -> None:
    p = tmp_path / "allnull.csv"
    p.write_text("a,b\n,1\n,2\n,3\n", encoding="utf-8")
    out = run_assessment_chunked(str(p), chunksize=2)
    issue_types = [i["type"] for i in out["assessment"]["issues"]]
    assert "all_null_column" in issue_types


def test_chunked_assess_detects_dtype_mismatch(tmp_path: Path) -> None:
    """dtype_mismatch fires when inferred dtype disagrees with config."""
    import yaml

    p = tmp_path / "data.csv"
    p.write_text("id,val\n1,foo\n2,bar\n", encoding="utf-8")
    cfg = {"columns": {"val": {"dtype": "int64"}}}
    (tmp_path / "dqt.yaml").write_text(yaml.dump(cfg), encoding="utf-8")
    orig_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        out = run_assessment_chunked(str(p), chunksize=2)
        issue_types = [i["type"] for i in out["assessment"]["issues"]]
        assert "dtype_mismatch" in issue_types
    finally:
        os.chdir(orig_cwd)


def test_chunked_assess_has_profile(simple_csv: Path) -> None:
    out = run_assessment_chunked(str(simple_csv), chunksize=2)
    assert "profile" in out
    assert out["profile"]["rows"] == 4


def test_chunked_assess_has_meta_chunksize(simple_csv: Path) -> None:
    out = run_assessment_chunked(str(simple_csv), chunksize=2)
    assert out["meta"]["chunksize"] == 2


def test_chunked_assess_has_duration_secs(simple_csv: Path) -> None:
    out = run_assessment_chunked(str(simple_csv), chunksize=2)
    assert isinstance(out["duration_secs"], float)
    assert out["duration_secs"] >= 0


def test_chunked_assess_has_run_id_and_dataset_id(simple_csv: Path) -> None:
    out = run_assessment_chunked(str(simple_csv), chunksize=2)
    assert "run_id" in out
    assert "dataset_id" in out


def test_full_assess_unchanged_no_chunked_fields(simple_csv: Path) -> None:
    """Full-load assess must NOT gain assessment_mode or approximate."""
    out = run_assessment(str(simple_csv))
    assessment = out.get("assessment", {})
    assert "assessment_mode" not in assessment
    assert "approximate" not in assessment
    assert "quality_score" in assessment
