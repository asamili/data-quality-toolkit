from __future__ import annotations

import pandas as pd

from data_quality_toolkit.adapters.exporters.filesystem.csv_exporter import write_star_csvs


def test_write_star_csvs_creates_files(tmp_path):
    tables = {
        "dim_dataset": pd.DataFrame([{"dataset_id": "sha1:x", "source_path": ""}]),
        "dim_column": pd.DataFrame(
            [
                {
                    "column_id": "sha1:x:a",
                    "dataset_id": "sha1:x",
                    "column_name": "a",
                    "dtype": "int64",
                }
            ]
        ),
        "fact_profile_runs": pd.DataFrame(
            [
                {
                    "run_id": "run-1",
                    "dataset_id": "sha1:x",
                    "ts": "1970-01-01T00:00:00Z",
                    "rows": 1,
                    "cols": 1,
                    "memory_mb": 0.0,
                }
            ]
        ),
        "fact_quality_metrics": pd.DataFrame(
            [
                {
                    "run_id": "run-1",
                    "column_id": "sha1:x:a",
                    "null_pct": 0.0,
                    "distinct_count": 1,
                    "completeness": 1.0,
                }
            ]
        ),
    }
    paths = write_star_csvs(tables, output_dir=str(tmp_path))
    for name, p in paths.items():
        assert name in tables
        fp = tmp_path / "star" / f"{name}.csv"
        assert p == str(fp)
        assert fp.exists()
        assert fp.read_text(encoding="utf-8").splitlines()[0]  # header present
        assert p == str(fp)
        assert fp.exists()
        assert fp.read_text(encoding="utf-8").splitlines()[0]  # header present
