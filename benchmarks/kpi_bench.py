"""KPI Semantic Scaling Benchmark.

Measures validation and emission time for synthetic KPI catalogs of varying sizes.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil
import yaml

from data_quality_toolkit.application.workflow.kpi import emit_kpi_artifacts, validate_kpi_catalog


def _get_env_metadata() -> dict[str, Any]:
    mem = psutil.virtual_memory()
    return {
        "timestamp": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "os": platform.system(),
        "os_version": platform.version(),
        "python_version": sys.version,
        "cpu_count": psutil.cpu_count(),
        "total_ram_gb": round(mem.total / (1024**3), 2),
    }


def generate_catalog(count: int, depth: int) -> dict[str, Any]:
    """Generate a synthetic KPI catalog with a controlled dependency structure."""
    kpis = []
    for i in range(count):
        kpi_id = f"kpi_{i:04d}"
        depends_on = []
        # Create a tree-like structure: each KPI depends on a parent in the previous layer
        if i > 0 and depth > 0:
            layer_size = max(1, count // depth)
            parent_idx = max(0, i - layer_size)
            if parent_idx < i:
                depends_on.append(f"kpi_{parent_idx:04d}")

        kpis.append(
            {
                "id": kpi_id,
                "title": f"KPI {i}",
                "expression": (
                    f"SUM(Fact[Value_{i}])" if not depends_on else f"[{depends_on[0]}] * 1.05"
                ),
                "grain": "time",
                "unit": "score",
                "depends_on": depends_on,
            }
        )
    return {"kpis": kpis}


def bench_kpis(count: int, depth: int) -> dict[str, Any]:
    catalog_dict = generate_catalog(count, depth)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(catalog_dict, f)
        temp_path = Path(f.name)

    try:
        # Measure validation
        t0 = time.perf_counter()
        val_res = validate_kpi_catalog(temp_path)
        val_time = time.perf_counter() - t0

        # Measure emission
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            t0 = time.perf_counter()
            emit_kpi_artifacts(
                temp_path,
                out_dir / "measures.dax",
                out_dir / "model.tmsl.json",
            )
            emit_time = time.perf_counter() - t0

        return {
            "count": count,
            "depth": depth,
            "validate_s": round(val_time, 4),
            "emit_s": round(emit_time, 4),
            "status": val_res.get("status"),
        }
    finally:
        temp_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="DQT KPI scaling benchmark")
    parser.add_argument("--out", help="Output JSON path")
    parser.add_argument("--sizes", nargs="+", type=int, default=[10, 50, 100, 250, 500])
    args = parser.parse_args()

    print(f"=== KPI Scaling Benchmark ({datetime.now(tz=UTC).isoformat()}) ===")
    results = []
    for size in args.sizes:
        print(f"Benchmarking {size} KPIs ...", flush=True)
        results.append(bench_kpis(size, depth=min(size // 2, 10)))

    payload = {
        "env": _get_env_metadata(),
        "results": results,
    }

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {out_path}")

    print("\nKPI Count | Validate (s) | Emit (s)")
    print("-" * 35)
    for r in results:
        print(f"{r['count']:>9} | {r['validate_s']:>12} | {r['emit_s']:>8}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
