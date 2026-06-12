# Data Quality Toolkit (DQT)

[![Python](https://img.shields.io/badge/Python-3.12+-green)]()
[![License](https://img.shields.io/badge/License-Apache%202.0-blue)]()
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-blue)]()

**CLI-first data quality toolkit for CSV validation, issue detection, and BI-ready export artifacts.**

## Quality Position
DQT is a portfolio-grade Python CLI project designed for practical, automated data-quality workflows.

## Core Business Value
- **Trust:** Catch data issues before they break reporting or analytics workflows with automated quality gates.
- **Visibility:** Faster profiling with terminal-based distribution charts and dashboard EDA.
- **Traceability:** Improve confidence in downstream reporting with structured lineage manifests for impact analysis.

## Portfolio Differentiation
- Python package design
- CLI product thinking
- Rigorous testing and release discipline
- Data-quality automation
- Analytics reliability

## Quick Start
```bash
# Clone and install
git clone https://github.com/asamili/data-quality-toolkit
cd data-quality-toolkit
python -m venv .venv
.venv\Scripts\activate
pip install -e .

# Basic Usage
dqt profile data/orders.csv
dqt assess data/orders.csv --fail-under 0.90
dqt export data/orders.csv --outdir dist/

# Detect statistical drift between two datasets
dqt drift data/baseline.csv data/current.csv --alpha 0.05
```

### Statistical Drift Detection
Compare two CSV datasets for statistical drift using KS (numerical) and Chi-square (categorical) tests.

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

- **Output:** Machine-readable JSON is written to `stdout` (suppress with `--no-json`), while a human-readable summary is written to `stderr`.
- **Evidence report:** `--output <path>` writes the drift result to a file, wrapped in a versioned envelope (`schema_version`, `kind`, `run_id`, `created_at`, `baseline_path`, `current_path`, `result`). Without the flag, nothing is written to disk. The report is written before the `--fail-on-drift` exit-code check, so CI keeps the evidence even on failure.
- **Drift history:** `--history <path>` appends one compact JSONL record per run (`schema_version`, `kind: drift_history_record`, `run_id`, `created_at`, dataset ids, `status`, `alpha`, summary counts, `report_path`). When `--output` is also given, the record's `run_id` matches the evidence report's, so history lines can be traced back to full reports. The file is append-only and intended as the trend source for future dashboard/reporting work; a SQLite importer may follow once dashboard requirements are settled (mirroring how `quality_history.jsonl` is imported today).
- **Dependency:** Requires `scipy`. Install via: `pip install "data-quality-toolkit[stats]"`
- **V1 Behavior:** Drift detected exits `0`; unavailable `scipy` exits `1`.
- **Exit Codes:**
  - `0`: Success (no drift, or drift detected without `--fail-on-drift`).
  - `1`: Unavailable (missing `scipy`).
  - `2`: Fail (drift detected with `--fail-on-drift`).

## Documentation
- [Product Brief](docs/product.md)
- [CLI Reference](docs/cli.md)
- [Python API](docs/api.md)
- [Architecture & Design](docs/architecture.md)
- [Demo Story](docs/demo_story.md)

---
**Version**: v2.4.0 | **Status**: Active development
