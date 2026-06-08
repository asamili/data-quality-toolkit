# DQT Performance & Memory Baseline

Measurement-only baseline for the DQT Hardening Release. Captures wall-clock
time and peak memory for the load → profile → preprocess path **as it ships
today**. No library behavior is modified by this harness.

## Run

```bash
python benchmarks/baseline.py            # all shapes -> benchmarks/baseline_results.json
python benchmarks/baseline.py --skip-1m  # skip the 1,000,000-row shape
python benchmarks/baseline.py --out other.json
python benchmarks/baseline.py --check    # performance regression guard (CI)
```

Requires `numpy`, `pandas`, `psutil` (all already in the dev environment).

## Metrics

Per stage (`load`, `profile`, `preprocess`):

- `wall_s` — wall-clock seconds (`time.perf_counter`)
- `py_peak_mb` — `tracemalloc` peak (Python-level allocations only)
- `rss_delta_mb` — process RSS after − before (captures pandas/numpy C buffers)

`tracemalloc` misses C-level buffers, so `rss_delta_mb` is the more faithful
DataFrame-memory signal; RSS deltas are approximate (process-global, GC forced
between stages). Synthetic frames: numeric-majority + 2 string columns (one
low-cardinality, one high-cardinality id-like), ~5% nulls.

## Baseline results

Captured 2026-05-22 (numpy 1.26.4, pandas 2.3.3, psutil 7.2.2). Raw data in
[`baseline_results.json`](baseline_results.json).

| shape | csv_mb | load wall_s | load py_peak | load rss | profile wall_s | preprocess wall_s |
|------:|-------:|------------:|-------------:|---------:|---------------:|------------------:|
| 10k × 5    | 0.53   | 0.07 | 1.2 MB   | 1.7 MB  | 0.17  | 0.02 |
| 100k × 5   | 5.34   | 0.26 | 10.7 MB  | 3.4 MB  | 1.35  | 0.10 |
| 100k × 100 | 109.53 | 3.57 | 156.9 MB | 76.5 MB | 2.16  | 2.24 |
| 1M × 5     | 54.36  | 2.86 | 120.8 MB | 85.1 MB | 13.31 | 1.09 |

## Interpretation Rules & Cautions

- **Internal Baseline Only:** These benchmarks are used to detect relative regressions during development. They are not absolute performance guarantees.
- **Machine Dependent:** Results vary significantly based on CPU, RAM speed, and Disk I/O. Always include system metadata when sharing results.
- **Single-Threaded:** DQT profiling is currently single-threaded (pandas-based). Multi-core systems will not see linear speedups without architectural changes.
- **Memory Boundaries:** Default `MAX_ROWS_IN_MEMORY` is 1,000,000. Datasets exceeding this require `SAMPLE_SIZE` env to enable I/O-layer sampling (`nrows`).

## Available Harnesses

### 1. Data Pipeline Baseline (`baseline.py`)

Captures wall-clock time and memory for the core pipeline:
`load` → `profile` → `assess` → `preprocess` → `export` (Star Schema).

### 2. KPI Semantic Scaling (`kpi_bench.py`)

Measures validation and emission (DAX/TMSL) latency for KPI catalogs.
Generates synthetic catalogs with configurable depth to test DAG cycle detection and emission order performance.

```bash
python benchmarks/kpi_bench.py --sizes 10 50 100 250 500
```

### 3. Storage Aging (`storage_bench.py`)

Measures read latency for historical run records as the database grows.
Tests how the SQLite-backed audit trail handles thousands of entries for a single dataset.

```bash
python benchmarks/storage_bench.py --runs 100 1000 10000
```
