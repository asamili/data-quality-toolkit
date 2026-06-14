# Data Quality Toolkit (DQT)

[![Python](https://img.shields.io/badge/Python-3.12+-green)]()
[![License](https://img.shields.io/badge/License-Apache%202.0-blue)]()
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-blue)]()

**A CLI-first toolkit for CSV data quality: profile datasets, enforce quality gates, detect statistical drift, and export BI-ready artifacts.**

DQT runs from the command line with no service to stand up. Point it at a CSV and it profiles columns, scores quality, and fails your pipeline when data falls below threshold. It also detects statistical drift between datasets and turns drift history into SQLite-backed monitoring reports and dashboards.

## Install

```bash
git clone https://github.com/asamili/data-quality-toolkit
cd data-quality-toolkit
python -m venv .venv
.venv\Scripts\activate
pip install -e .

# Optional extras
pip install "data-quality-toolkit[stats]"   # drift detection (scipy)
pip install "data-quality-toolkit[ui]"      # Streamlit dashboard
```

## Core Workflow

```bash
# Profile a dataset
dqt profile data/orders.csv

# Score quality and fail the pipeline below a threshold (exit code 2)
dqt assess data/orders.csv --fail-under 0.90

# Export star-schema artifacts for BI
dqt export data/orders.csv --outdir dist/

# Detect statistical drift between two datasets
dqt drift data/baseline.csv data/current.csv --alpha 0.05
```

`dqt assess --fail-under <score>` is the pipeline gate: it exits `2` when the quality score is below the threshold, so CI/ETL steps can halt and alert. See the [CLI Reference](docs/cli.md) for the full command set.

## Statistical Drift Detection

Compare two CSV datasets for statistical drift using KS tests (numerical) and Chi-square tests (categorical). Requires the `[stats]` extra.

```bash
# Basic usage
dqt drift baseline.csv current.csv

# Advanced tuning
dqt drift baseline.csv current.csv --alpha 0.01 --min-samples 100 --max-categories 10

# Fail on drift (exit code 2)
dqt drift baseline.csv current.csv --fail-on-drift

# Persist a JSON evidence report (opt-in; written even with --fail-on-drift)
dqt drift baseline.csv current.csv --output drift_report.json

# Append a compact run record to an append-only drift history (opt-in)
dqt drift baseline.csv current.csv --output drift_report.json --history drift_history.jsonl
```

- **Output:** machine-readable JSON goes to `stdout` (suppress with `--no-json`); a human-readable summary goes to `stderr`.
- **Evidence report:** `--output <path>` writes the drift result wrapped in a versioned envelope (`schema_version`, `kind`, `run_id`, `created_at`, `baseline_path`, `current_path`, `result`). Written before the `--fail-on-drift` exit check, so CI keeps the evidence even on failure.
- **Drift history:** `--history <path>` appends one compact JSONL record per run (`run_id`, `created_at`, dataset ids, `status`, `alpha`, summary counts, `report_path`). When `--output` is also given, the record's `run_id` matches the evidence report's, so history lines trace back to full reports. This file is the input to the `dqt drift-history` analytics commands below.
- **Exit codes:** `0` success (no drift, or drift without `--fail-on-drift`); `1` unavailable (missing `scipy`); `2` drift detected with `--fail-on-drift`.

## Drift History Analytics (v2.5.0)

> These commands ship in **v2.5.0**.

Promote an append-only drift history (`dqt drift --history drift_history.jsonl`) into a SQLite monitoring store, then query trends, inspect column metrics, and render reports and dashboards.

```bash
# Import a JSONL drift history into a SQLite monitoring DB
dqt drift-history import history.jsonl --db monitoring.db

# List imported runs
dqt drift-history list --db monitoring.db

# Trend summary across runs
dqt drift-history trend --db monitoring.db

# Per-column drift metrics
dqt drift-history columns --db monitoring.db

# Markdown/HTML report (opt-in column metrics + distribution plots)
dqt drift-history report --db monitoring.db --output drift-report.md --include-columns --include-plots

# Static, self-contained HTML dashboard
dqt drift-history dashboard --db monitoring.db --output drift-dashboard.html --include-plots
```

- **Dependency-free artifacts:** reports and the dashboard render with inline CSS only — **no JavaScript, no CDN, no images, and no matplotlib required**.
- **Advanced per-column metrics:** PSI (Population Stability Index), Jensen-Shannon distance, and Wasserstein distance.
- **SQLite-backed artifacts:** import populates the `drift_runs`, `drift_columns`, and `drift_column_distributions` tables.
- **Opt-in detail:** `--include-columns` appends column-level metrics to the report; `--include-plots` adds distribution plots to the report and dashboard. Both default off, leaving base output unchanged.
- A missing or empty database still produces valid output and exits `0`.

## Documentation
- [Product Brief](docs/product.md)
- [CLI Reference](docs/cli.md)
- [Python API](docs/api.md)
- [Architecture & Design](docs/architecture.md)
- [Demo Story](docs/demo_story.md)

---
**Version**: v2.5.0 | **Status**: Active development
