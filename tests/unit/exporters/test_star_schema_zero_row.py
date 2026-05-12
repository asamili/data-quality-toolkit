"""Tests for build_star and write_star_csvs with zero-row / zero-column profiles."""

from __future__ import annotations

import pandas as pd
import pytest

from data_quality_toolkit.exporters.bi_star_schema import build_star, validate_relationships
from data_quality_toolkit.exporters.filesystem.csv_exporter import write_star_csvs
from data_quality_toolkit.shared.models import ProfileResult

_REQUIRED_TABLES = {"dim_dataset", "dim_column", "fact_profile_runs", "fact_quality_metrics"}


def _base_profile(**overrides) -> ProfileResult:
    base: ProfileResult = {
        "run_id": "run-zero",
        "dataset_id": "sha1:zero",
        "ts": "2024-01-01T00:00:00Z",
        "rows": 0,
        "cols": 0,
        "memory_mb": 0.0,
        "columns": [],
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


# --- zero-column profile (profile["columns"] = []) ---


def test_zero_columns_returns_all_four_tables():
    tables = build_star(_base_profile(), pd.DataFrame())
    assert set(tables.keys()) == _REQUIRED_TABLES


def test_zero_columns_dim_column_has_correct_schema():
    tables = build_star(_base_profile(), pd.DataFrame())
    dim_col = tables["dim_column"]
    assert dim_col.shape[0] == 0
    assert {"column_id", "dataset_id", "column_name", "dtype"}.issubset(dim_col.columns)


def test_zero_columns_fact_quality_metrics_has_correct_schema():
    tables = build_star(_base_profile(), pd.DataFrame())
    fqm = tables["fact_quality_metrics"]
    assert fqm.shape[0] == 0
    assert {"run_id", "column_id", "null_pct", "distinct_count", "completeness"}.issubset(
        fqm.columns
    )


def test_zero_columns_passes_validate_relationships():
    tables = build_star(_base_profile(), pd.DataFrame())
    validate_relationships(tables)  # must not raise


# --- header-only profile (rows=0, N columns present) ---


def test_header_only_profile_builds_correctly():
    profile = _base_profile(
        rows=0,
        cols=2,
        columns=[
            {"name": "id", "dtype": "int64", "nulls": 0, "unique": 0},
            {"name": "val", "dtype": "object", "nulls": 0, "unique": 0},
        ],
    )
    df = pd.DataFrame(columns=["id", "val"])
    tables = build_star(profile, df)

    assert len(tables["dim_column"]) == 2
    assert len(tables["fact_quality_metrics"]) == 2
    assert len(tables["fact_profile_runs"]) == 1
    assert tables["fact_profile_runs"].iloc[0]["rows"] == 0


def test_header_only_completeness_is_one():
    """With 0 rows and 0 nulls, completeness should be 1.0."""
    profile = _base_profile(
        rows=0,
        cols=1,
        columns=[{"name": "x", "dtype": "float64", "nulls": 0, "unique": 0}],
    )
    tables = build_star(profile, pd.DataFrame(columns=["x"]))
    fqm = tables["fact_quality_metrics"]
    assert fqm.iloc[0]["completeness"] == pytest.approx(1.0)
    assert fqm.iloc[0]["null_pct"] == pytest.approx(0.0)


def test_header_only_passes_validate_relationships():
    profile = _base_profile(
        rows=0,
        cols=1,
        columns=[{"name": "id", "dtype": "int64", "nulls": 0, "unique": 0}],
    )
    tables = build_star(profile, pd.DataFrame(columns=["id"]))
    validate_relationships(tables)  # must not raise


# --- write_star_csvs with zero-row tables ---


def test_write_star_csvs_writes_header_only_files(tmp_path):
    profile = _base_profile(
        rows=0,
        cols=1,
        columns=[{"name": "id", "dtype": "int64", "nulls": 0, "unique": 0}],
    )
    tables = build_star(profile, pd.DataFrame(columns=["id"]))
    paths = write_star_csvs(dict(tables), str(tmp_path))

    for name, path in paths.items():
        from pathlib import Path

        written = Path(path)
        assert written.exists(), f"{name} CSV not written"
        lines = written.read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 1, f"{name} CSV has no header"
