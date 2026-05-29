"""Performance & memory baseline harness for the DQT Hardening Release.

Measurement only. This script does NOT change library behavior — it calls the
public load / profile / preprocess paths exactly as they ship today and records
wall-clock time and peak memory for representative CSV shapes.

Run:
    python benchmarks/baseline.py                 # default shapes -> JSON + table
    python benchmarks/baseline.py --out path.json # custom output location

Metrics per stage (load, profile, preprocess):
    - wall_s        : time.perf_counter seconds
    - py_peak_mb    : tracemalloc peak (Python-level allocations only)
    - rss_delta_mb  : psutil RSS after - before (captures pandas C buffers)

Caveats:
    - tracemalloc misses pandas/numpy C-level buffers; rss_delta_mb is the more
      faithful memory signal for DataFrame work. Both are reported.
    - RSS is process-global; GC is forced between stages to reduce cross-talk,
      but absolute RSS deltas remain approximate.
"""

# mypy: warn_unused_ignores=False
from __future__ import annotations

import argparse
import gc
import json
import os
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil  # type: ignore[import-untyped]

from data_quality_toolkit.loaders.file.csv_loader import load_csv
from data_quality_toolkit.profiling.profiling_orchestrator import run_profiling
from data_quality_toolkit.shared.settings import load_settings
from data_quality_toolkit.workflow.preprocessing import plan_preprocessing

# (rows, cols, label) — last entry is optional/heavy
DEFAULT_SHAPES: list[tuple[int, int]] = [
    (10_000, 5),
    (100_000, 5),
    (100_000, 100),
    (1_000_000, 5),
]

_PROC = psutil.Process(os.getpid())
_NULL_FRACTION = 0.05


def _rss_mb() -> float:
    return float(_PROC.memory_info().rss) / (1024 * 1024)


def make_dataframe(rows: int, cols: int, seed: int = 1234) -> pd.DataFrame:
    """Build a mixed-dtype frame: numeric majority + a few string columns, ~5% nulls."""
    rng = np.random.default_rng(seed)
    data: dict[str, Any] = {}
    # First two columns are object/string to exercise nunique / dropna on strings:
    #   one low-cardinality categorical, one high-cardinality id-like column.
    n_string = min(2, cols)
    for c in range(cols):
        if c == 0 and n_string >= 1:
            cats = np.array(["alpha", "beta", "gamma", "delta", "epsilon"])
            col = cats[rng.integers(0, len(cats), size=rows)].astype(object)
        elif c == 1 and n_string >= 2:
            col = np.array([f"id_{v}" for v in rng.integers(0, rows, size=rows)], dtype=object)
        elif c % 2 == 0:
            col = rng.normal(100.0, 25.0, size=rows)
        else:
            col = rng.integers(0, 1_000, size=rows).astype(float)
        # inject nulls
        mask = rng.random(rows) < _NULL_FRACTION
        if col.dtype == object:
            col[mask] = None
        else:
            col[mask] = np.nan
        data[f"col_{c}"] = col
    return pd.DataFrame(data)


def _measure(fn: Any) -> tuple[Any, dict[str, float]]:
    """Run fn(), return (result, metrics)."""
    gc.collect()
    rss_before = _rss_mb()
    tracemalloc.start()
    t0 = time.perf_counter()
    result = fn()
    wall = time.perf_counter() - t0
    _, py_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_after = _rss_mb()
    return result, {
        "wall_s": round(wall, 4),
        "py_peak_mb": round(py_peak / (1024 * 1024), 2),
        "rss_delta_mb": round(rss_after - rss_before, 2),
    }


def bench_shape(rows: int, cols: int, tmp_dir: Path) -> dict[str, Any]:
    csv_path = tmp_dir / f"bench_{rows}x{cols}.csv"
    df_gen = make_dataframe(rows, cols)
    df_gen.to_csv(csv_path, index=False)
    file_mb = round(csv_path.stat().st_size / (1024 * 1024), 2)
    del df_gen
    gc.collect()

    # Stage 1: load (SAMPLE_SIZE unset -> full read, current default behavior)
    loaded, load_m = _measure(lambda: load_csv(str(csv_path)))
    df, meta = loaded
    dataset_id = str(meta["dataset_id"])
    # Stage 2: profile
    _, profile_m = _measure(lambda d=df, ds=dataset_id: run_profiling(d, ds))
    # Stage 3: preprocess plan
    _, plan_m = _measure(lambda d=df: plan_preprocessing(d))

    result = {
        "rows": rows,
        "cols": cols,
        "csv_file_mb": file_mb,
        "loaded_rows": int(meta["rows"]),
        "sample_applied_on_load": bool(meta["sample_applied"]),
        "load": load_m,
        "profile": profile_m,
        "preprocess": plan_m,
    }
    del df
    gc.collect()
    csv_path.unlink(missing_ok=True)
    return result


def sample_behavior_probe(tmp_dir: Path) -> dict[str, Any]:
    """Demonstrate current sample_size handling without changing it."""
    rows, cols = 100_000, 5
    csv_path = tmp_dir / "sample_probe.csv"
    make_dataframe(rows, cols).to_csv(csv_path, index=False)

    # default: no env SAMPLE_SIZE -> loader does full read
    os.environ.pop("SAMPLE_SIZE", None)
    loaded_default, m_default = _measure(lambda: load_csv(str(csv_path)))
    df_default, meta_default = loaded_default
    default_loaded = int(meta_default["rows"])
    default_sampled = bool(meta_default["sample_applied"])
    del df_default

    # explicit env SAMPLE_SIZE -> loader samples at read path
    os.environ["SAMPLE_SIZE"] = "2000"
    loaded_env, m_env = _measure(lambda: load_csv(str(csv_path)))
    df_env, meta_env = loaded_env
    env_loaded = int(meta_env["rows"])
    env_sampled = bool(meta_env["sample_applied"])
    del df_env
    os.environ.pop("SAMPLE_SIZE", None)

    csv_path.unlink(missing_ok=True)
    settings = load_settings()
    return {
        "default_no_env": {
            "loaded_rows": default_loaded,
            "sample_applied": default_sampled,
            "load": m_default,
        },
        "env_sample_size_2000": {
            "loaded_rows": env_loaded,
            "sample_applied": env_sampled,
            "load": m_env,
        },
        "settings_sample_size_default": settings.sample_size,
        "settings_max_rows_in_memory": settings.max_rows_in_memory,
        "max_rows_in_memory_enforced": True,
        "notes": (
            "Loader samples at read time (nrows) when SAMPLE_SIZE env is explicitly set, "
            "yielding first-N rows and avoiding full-file materialization. Default load is "
            "full-file. Profiling samples 'column extras' (min/max) to settings.sample_size "
            "by default, but nulls/unique are computed on the full frame. "
            "max_rows_in_memory is enforced: loader raises ValueError if loaded rows exceed the limit."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="DQT performance/memory baseline")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).parent / "baseline_results.json"),
        help="Output JSON path",
    )
    parser.add_argument(
        "--skip-1m",
        action="store_true",
        help="Skip the 1,000,000-row shape",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check runtime against baseline_results.json",
    )
    args = parser.parse_args()

    if args.check:
        baseline_path = Path(args.out)
        if not baseline_path.exists():
            print(f"Baseline file {baseline_path} not found.")
            return 1
        with open(baseline_path, encoding="utf-8") as f:
            baseline_data = json.load(f)

        # Check 100k x 5
        rows, cols = 100_000, 5
        print(f"[check] testing {rows} rows x {cols} cols ...", flush=True)
        with tempfile.TemporaryDirectory(prefix="dqt_bench_") as td:
            actual = bench_shape(rows, cols, Path(td))

        baseline_entry = next(
            s for s in baseline_data["shapes"] if s["rows"] == rows and s["cols"] == cols
        )

        threshold = 2.0
        baseline_load = baseline_entry["load"]["wall_s"]
        actual_load = actual["load"]["wall_s"]

        if actual_load > baseline_load * threshold:
            print(f"Regression detected in load: {actual_load}s > {baseline_load}s * {threshold}")
            return 1
        print(f"Check passed: {actual_load}s <= {baseline_load}s * {threshold}")
        return 0

    shapes = [s for s in DEFAULT_SHAPES if not (args.skip_1m and s[0] >= 1_000_000)]

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="dqt_bench_") as td:
        tmp_dir = Path(td)
        for rows, cols in shapes:
            print(f"[bench] {rows} rows x {cols} cols ...", flush=True)
            results.append(bench_shape(rows, cols, tmp_dir))
        print("[bench] sample_size / max_rows_in_memory behavior probe ...", flush=True)
        probe = sample_behavior_probe(tmp_dir)

    payload = {
        "generated_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "env": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "psutil": psutil.__version__,
        },
        "null_fraction": _NULL_FRACTION,
        "shapes": results,
        "behavior_probe": probe,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Console table
    print("\n=== Baseline (wall_s | py_peak_mb | rss_delta_mb) ===")
    header = f"{'shape':>14} {'file_mb':>8} | {'load':>26} | {'profile':>26} | {'preprocess':>26}"
    print(header)
    for r in results:
        shape = f"{r['rows']}x{r['cols']}"

        def fmt(stage: dict[str, float]) -> str:
            return f"{stage['wall_s']:>7}s {stage['py_peak_mb']:>7}py {stage['rss_delta_mb']:>7}rss"

        print(
            f"{shape:>14} {r['csv_file_mb']:>8} | {fmt(r['load'])} | "
            f"{fmt(r['profile'])} | {fmt(r['preprocess'])}"
        )
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
