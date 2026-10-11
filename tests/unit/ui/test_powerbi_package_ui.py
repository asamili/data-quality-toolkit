"""Focused tests for the Power BI package UI service and relationship rows."""

from __future__ import annotations

from pathlib import Path

from data_quality_toolkit.adapters.ui.components.diagrams import relationships_to_rows
from data_quality_toolkit.adapters.ui.services.powerbi_package import (
    LIFECYCLE_GENERATED,
    LIFECYCLE_INVALID,
    LIFECYCLE_NOT_GENERATED,
    LIFECYCLE_VALID,
    generate_package,
    lifecycle_label,
    package_file_rows,
    validate_generated_package,
)

_STAR_FILES = {
    "dim_dataset.csv": "dataset_id\nds1\n",
    "dim_column.csv": "column_id,dataset_id\ncol1,ds1\n",
    "fact_profile_runs.csv": "dataset_id\nds1\n",
    "fact_quality_metrics.csv": "column_id\ncol1\n",
    "fact_issues.csv": (
        "run_id,dataset_id,column_id,issue_type,severity,category,message\n"
        "r1,ds1,col1,missing,high,completeness,msg\n"
    ),
}


def _write_star(tmp_path: Path) -> Path:
    star = tmp_path / "star"
    star.mkdir()
    for name, content in _STAR_FILES.items():
        (star / name).write_text(content, encoding="utf-8")
    return star


# ── lifecycle ────────────────────────────────────────────────────────────────


def test_lifecycle_labels() -> None:
    assert lifecycle_label(generated=False, valid=None) == LIFECYCLE_NOT_GENERATED
    assert lifecycle_label(generated=True, valid=None) == LIFECYCLE_GENERATED
    assert lifecycle_label(generated=True, valid=True) == LIFECYCLE_VALID
    assert lifecycle_label(generated=True, valid=False) == LIFECYCLE_INVALID


# ── generate / validate ──────────────────────────────────────────────────────


def test_generate_package_creates_files(tmp_path: Path) -> None:
    star = _write_star(tmp_path)
    result, err = generate_package(str(star), str(tmp_path / "pkg"), "./dist")

    assert err is None
    assert result is not None
    assert result["star_count"] == 5
    assert "parameters.json" in result["files"]
    assert "relationships.json" in result["files"]


def test_generate_package_missing_star_dir_errors(tmp_path: Path) -> None:
    result, err = generate_package(str(tmp_path / "nope"), str(tmp_path / "pkg"), "./dist")
    assert result is None
    assert err is not None
    # error must not leak an absolute path as primary text
    assert str(tmp_path) not in err


def test_package_file_rows_are_basename_only(tmp_path: Path) -> None:
    star = _write_star(tmp_path)
    result, _ = generate_package(str(star), str(tmp_path / "pkg"), "./dist")
    assert result is not None
    rows = package_file_rows({str(k): str(v) for k, v in result["files"].items()})

    text = " ".join(str(v) for row in rows for v in row.values())
    assert str(tmp_path) not in text
    files = {row["File"] for row in rows}
    assert "parameters.json" in files
    assert "relationships.json" in files


def test_validate_generated_package_returns_summary(tmp_path: Path) -> None:
    star = _write_star(tmp_path)
    result, _ = generate_package(str(star), str(tmp_path / "pkg"), "./dist")
    assert result is not None
    summary, err = validate_generated_package(str(result["output_dir"]))

    assert err is None
    assert summary is not None
    assert "valid" in summary
    assert isinstance(summary["valid"], bool)


def test_validate_missing_dir_errors(tmp_path: Path) -> None:
    summary, err = validate_generated_package(str(tmp_path / "missing"))
    assert summary is None
    assert err is not None


# ── relationships ────────────────────────────────────────────────────────────


def test_relationships_to_rows_flattens_valid_entries() -> None:
    spec = {
        "relationships": [
            {
                "from": ["dim_column", "dataset_id"],
                "to": ["dim_dataset", "dataset_id"],
                "type": "many-to-one",
                "crossFilter": "single",
            },
            {"from": ["bad"], "to": ["x", "y"]},  # malformed -> skipped
            "not-a-dict",
        ]
    }
    rows = relationships_to_rows(spec)
    assert rows == [
        {
            "From": "dim_column.dataset_id",
            "To": "dim_dataset.dataset_id",
            "Type": "many-to-one",
            "Cross-filter": "single",
        }
    ]


def test_relationships_to_rows_handles_missing_and_malformed() -> None:
    assert relationships_to_rows(None) == []
    assert relationships_to_rows({}) == []
    assert relationships_to_rows({"relationships": "nope"}) == []
