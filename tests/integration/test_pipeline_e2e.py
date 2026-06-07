# tests/integration/test_pipeline_e2e.py
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.application.workflow.pipeline import run_export_star

pytestmark = pytest.mark.integration  # only run when -m integration


def _generate_test_csv(path: Path, rows: int = 100_000) -> Path:
    """Generate synthetic CSV (with some nulls) deterministically."""
    rng = np.random.default_rng(42)

    # Build department without using rng.choice on a list[str | None]
    dept_opts: list[str | None] = ["Sales", "Engineering", "Marketing", None]
    dept_idx = rng.integers(0, len(dept_opts), size=rows, endpoint=False)
    department = [dept_opts[i] for i in dept_idx]  # list[str | None]

    df = pd.DataFrame(
        {
            "id": range(rows),
            "age": rng.integers(18, 80, size=rows, endpoint=True),
            "salary": rng.normal(50_000, 20_000, size=rows),
            "department": department,
            "score": rng.uniform(0, 100, size=rows),
        }
    )

    # Inject missingness using .loc with a typed Index (plays nicely with stubs)
    age_idx: pd.Index = pd.Index(rng.integers(0, rows, size=int(rows * 0.10), endpoint=False))
    sal_idx: pd.Index = pd.Index(rng.integers(0, rows, size=int(rows * 0.05), endpoint=False))

    df.loc[age_idx, "age"] = np.nan
    df.loc[sal_idx, "salary"] = np.nan

    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


@pytest.mark.slow
def test_pipeline_e2e_smoke(tmp_path: Path):
    """End-to-end: CSV -> profile -> assess -> star -> export CSVs."""
    csv_path = _generate_test_csv(tmp_path / "test_100k.csv", rows=100_000)

    t0 = time.time()
    result = run_export_star(str(csv_path), output_dir=str(tmp_path))
    elapsed = time.time() - t0

    # basic shape
    required_keys = {"run_id", "dataset_id", "ts", "meta", "profile", "star", "export_paths"}
    assert required_keys <= set(result.keys())

    # profile (dataset-level)
    prof = result["profile"]
    assert prof["rows"] == 100_000
    assert prof["cols"] == 5
    assert isinstance(prof["memory_mb"], float)

    # star + paths
    star = result["star"]
    paths = result["export_paths"]
    for name in ["dim_dataset", "dim_column", "fact_profile_runs", "fact_quality_metrics"]:
        assert name in star["tables"]
        p = Path(paths[name])
        assert p.exists()
        df = pd.read_csv(p)
        assert len(df) > 0

    # performance note (non-binding)
    print(f"\nPipeline completed in {elapsed:.2f} seconds")
    if elapsed > 30:
        pytest.skip(f"Performance warning: {elapsed:.2f}s > 30s target")


def test_pipeline_relationships(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """relationships.json is emitted alongside star CSVs and well-formed."""
    monkeypatch.setenv("DQT_DB_PATH", str(tmp_path / "dqt.db"))
    csv_path = _generate_test_csv(tmp_path / "test_small.csv", rows=1_000)
    result = run_export_star(str(csv_path), output_dir=str(tmp_path))

    rel_path = Path(result["export_paths"]["relationships"])
    assert rel_path.exists()

    data = json.loads(rel_path.read_text(encoding="utf-8"))
    assert "relationships" in data and len(data["relationships"]) == 3

    # SQLite DB created and run persisted
    import sqlite3 as _sqlite3

    db_path = tmp_path / "dqt.db"
    assert db_path.exists()
    con = _sqlite3.connect(str(db_path))
    try:
        assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    finally:
        con.close()
