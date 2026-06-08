from __future__ import annotations

from pathlib import Path

import pytest

from data_quality_toolkit.api import assess_csv


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    p = tmp_path / "data.csv"
    p.write_text("id,val,name\n1,10,Alice\n2,20,\n3,30,Bob\n4,40,Carol\n", encoding="utf-8")
    return p


def test_chunked_assess_api_assessment_mode(csv_file: Path) -> None:
    out = assess_csv(csv_file, chunksize=2)
    assert out["assessment"]["assessment_mode"] == "chunked"


def test_chunked_assess_api_approximate_flag(csv_file: Path) -> None:
    out = assess_csv(csv_file, chunksize=2)
    assert out["approximate"] is True


def test_chunked_assess_api_has_completeness_score(csv_file: Path) -> None:
    out = assess_csv(csv_file, chunksize=2)
    assert "completeness_score" in out["assessment"]
    assert isinstance(out["assessment"]["completeness_score"], float)


def test_chunked_assess_api_no_quality_score(csv_file: Path) -> None:
    out = assess_csv(csv_file, chunksize=2)
    assert "quality_score" not in out["assessment"]


def test_chunked_assess_api_unsupported_rules_present(csv_file: Path) -> None:
    out = assess_csv(csv_file, chunksize=2)
    ur = out["assessment"]["unsupported_rules"]
    assert "constant_column" in ur
    assert "numeric_outliers" in ur


def test_chunked_assess_api_completeness_matches_full(csv_file: Path) -> None:
    full = assess_csv(csv_file)
    chunked = assess_csv(csv_file, chunksize=2)
    assert chunked["assessment"]["completeness_score"] == full["assessment"]["completeness_score"]


def test_chunked_assess_api_has_profile(csv_file: Path) -> None:
    out = assess_csv(csv_file, chunksize=2)
    assert out["profile"]["rows"] == 4
    assert out["profile"]["cols"] == 3


def test_full_assess_api_unchanged(csv_file: Path) -> None:
    """chunksize=None keeps full-load behavior — must have quality_score, no assessment_mode."""
    out = assess_csv(csv_file)
    assert "quality_score" in out["assessment"]
    assert "assessment_mode" not in out["assessment"]
    assert "approximate" not in out


def test_chunked_assess_api_null_threshold_forwarded(tmp_path: Path) -> None:
    """null_threshold is forwarded to the chunked path."""
    p = tmp_path / "d.csv"
    # col b: 1/4 null (25%) — above default 0.2 threshold but below 0.5 custom threshold
    p.write_text("a,b\n1,x\n2,\n3,y\n4,z\n", encoding="utf-8")
    # With default threshold (0.2): issue expected
    out_default = assess_csv(p, chunksize=2)
    issue_types_default = [i["type"] for i in out_default["assessment"]["issues"]]
    # With raised threshold (0.5): no issue
    out_high = assess_csv(p, chunksize=2, null_threshold=0.5)
    issue_types_high = [i["type"] for i in out_high["assessment"]["issues"]]
    assert "missing" in issue_types_default
    assert "missing" not in issue_types_high
