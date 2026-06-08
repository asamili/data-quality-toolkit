"""Storage Aging Benchmark.

Measures read latency for historical run data as the database grows.
"""

from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from data_quality_toolkit.adapters.storage.connection import connect
from data_quality_toolkit.adapters.storage.reader import read_run_history
from data_quality_toolkit.adapters.storage.schema import ensure_db
from data_quality_toolkit.adapters.storage.writer import persist_export_run


def _get_env_metadata() -> dict[str, Any]:
    mem = psutil.virtual_memory()
    return {
        "timestamp": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "os": platform.system(),
        "python_version": sys.version,
        "total_ram_gb": round(mem.total / (1024**3), 2),
    }


def populate_db(
    con: sqlite3.Connection, dataset_id: str, count: int, start_offset: int = 0
) -> None:
    """Populate database with synthetic run records."""
    cols = [{"name": f"col_{i}", "dtype": "float64"} for i in range(10)]
    for i in range(count):
        run_idx = start_offset + i
        persist_export_run(
            con,
            run_id=f"run_{run_idx:06d}",
            dataset_id=dataset_id,
            source_path="bench.csv",
            ts=datetime.now(tz=UTC).isoformat(),
            score=0.95,
            completeness_score=0.98,
            quality_score=0.92,
            rows=1000,
            cols=10,
            memory_mb=1.5,
            null_threshold=0.05,
            issues_total=2,
            issues_by_severity={"high": 1, "low": 1},
            issues_by_category={"Schema": 1, "Completeness": 1},
            duration_secs=0.5,
            columns=cols,
            quality_metrics=[],
            issues=[
                {"column": "col_1", "severity": "high", "category": "Schema", "message": "error"},
                {
                    "column": "col_2",
                    "severity": "low",
                    "category": "Completeness",
                    "message": "warn",
                },
            ],
        )


def bench_storage(runs_list: list[int]) -> list[dict[str, Any]]:
    results = []
    dataset_id = "bench_dataset"

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "bench.db"
        ensure_db(db_path)
        con = connect(db_path)
        try:
            current_count = 0
            for target_count in sorted(runs_list):
                to_add = target_count - current_count
                if to_add > 0:
                    print(f"Populating database to {target_count} runs ...", flush=True)
                    populate_db(con, dataset_id, to_add, start_offset=current_count)
                    current_count = target_count

                # Measure read latency (average of 5 reads)
                latencies = []
                for _ in range(5):
                    t0 = time.perf_counter()
                    history = read_run_history(db_path, dataset_id)
                    latencies.append(time.perf_counter() - t0)
                    assert len(history) == target_count

                avg_latency = sum(latencies) / len(latencies)
                results.append(
                    {
                        "run_count": target_count,
                        "avg_read_s": round(avg_latency, 6),
                        "db_size_kb": round(db_path.stat().st_size / 1024, 2),
                    }
                )
        finally:
            con.close()

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="DQT storage aging benchmark")
    parser.add_argument("--out", help="Output JSON path")
    parser.add_argument("--runs", nargs="+", type=int, default=[100, 1000, 10000])
    args = parser.parse_args()

    print(f"=== Storage Aging Benchmark ({datetime.now(tz=UTC).isoformat()}) ===")
    results = bench_storage(args.runs)

    payload = {
        "env": _get_env_metadata(),
        "results": results,
    }

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {out_path}")

    print("\nRun Count | Avg Read (s) | DB Size (KB)")
    print("-" * 40)
    for r in results:
        print(f"{r['run_count']:>9} | {r['avg_read_s']:>12} | {r['db_size_kb']:>10}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
