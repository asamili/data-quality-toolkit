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

## Findings confirmed (baseline, not yet optimized)

1. **Full-file read; sampling does not cut read memory.** Load `py_peak`/`rss`
   track file size (100k×100 → 157 MB peak for a 110 MB file). The probe is
   decisive: with `SAMPLE_SIZE=2000` the frame downsamples to 2000 rows but load
   `py_peak` stays **10.7 MB — identical to the full read**. Sampling happens
   *after* the full `pd.read_csv`, so peak memory is unaffected.
2. **Profiling time dominated by full-frame `nunique` on high-cardinality data.**
   1M×5 profile = **13.3 s**, far above 100k×100 = 2.2 s. The high-cardinality
   string id column drives near-`O(n)` hashing per column. `nulls`/`unique` are
   computed on the full frame regardless of `sample_size`; only min/max extras
   use the sample.
3. **Preprocessing scales with rows × cols × passes.** 100k×100 = 2.24 s from
   ~4–6 full-column passes (isna.mean, nunique, dropna, 2 quantiles, mask) per
   column.
4. **`max_rows_in_memory` is configured but never enforced.** Default 1,000,000;
   no code path reads it. The 1M×5 shape loads fully with no guard.

## Behavior reference (current, unchanged)

- Loader samples **only** when `SAMPLE_SIZE` env is explicitly set; default load
  is full-file.
- Profiling samples "column extras" (min/max) to `settings.sample_size`
  (default 1000); full frame still scanned for nulls/unique.
- `max_rows_in_memory` = 1,000,000, unenforced.

Optimization is out of scope for this gate — see the recommended optimization
gates in the hardening release plan.

---

## After refactor (Complexity/Profiler Hotspot gate)

Vectorized `df.isna().sum()` / `df.nunique()` in `column_profiler.py` and
combined `series.quantile([0.25, 0.75])` in `preprocessing.py`. No behavior
changes; all 19 targeted tests pass.

| shape | stage | baseline wall_s | after wall_s | Δ |
|------:|------:|----------------:|-------------:|--:|
| 100k × 5   | profile    | 1.348 | 0.968 | −28% |
| 100k × 100 | profile    | 2.156 | 1.541 | −29% |
| 1M × 5     | profile    | 13.307 | 10.476 | −21% |
| 100k × 5   | preprocess | 0.105 | 0.079 | −24% |
| 100k × 100 | preprocess | 2.240 | 1.472 | −34% |
| 1M × 5     | preprocess | 1.087 | 0.860 | −21% |

Memory (`py_peak_mb`) unchanged across all shapes. Load times unaffected.

---

## After memory hardening (Memory/Loader gate)

`csv_loader.py` changes:
- `SAMPLE_SIZE` env now injects `nrows` into `pd.read_csv` — full file is never
  materialized before sampling (first-N rows instead of random post-read sample).
- `max_rows_in_memory` is now enforced: raises `ValueError` if loaded rows exceed
  the configured limit (default 1,000,000).

All 53 targeted loader + shared tests pass. Behavior probe (100k × 5 file,
`SAMPLE_SIZE=2000` vs no env):

| case | loaded_rows | py_peak_mb | rss_delta_mb |
|------|------------:|-----------:|-------------:|
| default (no SAMPLE_SIZE) | 100,000 | 10.72 | 1.55 |
| SAMPLE_SIZE=2000 (nrows) | 2,000   | 10.72 | 0.01 |

`py_peak_mb` is unchanged across both cases — `tracemalloc` does not capture
pandas/numpy C-level buffer allocations (see caveats above). The RSS delta
confirms near-zero new allocation for the sampled load. The architectural
improvement is that pandas never reads the remaining 98,000 rows from disk.

`max_rows_in_memory` is now active. The 1M x 5 shape (1,000,000 rows) loads
without error against the default limit of 1,000,000 (`len > limit`, not `>=`).
