# Data Quality Toolkit (DQT)

[![Python](https://img.shields.io/badge/Python-3.12+-green)]()
[![License](https://img.shields.io/badge/License-Apache%202.0-blue)]()
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-blue)]()

**CLI-first data quality toolkit for CSV validation, issue detection, and BI-ready export artifacts.**

## Product Brief

### What it is
Data Quality Toolkit (DQT) is a lightweight, CLI-first product for validating CSV datasets, profiling columns, detecting quality issues, and exporting structured artifacts for reporting, BI, and automation workflows.

### Who it is for
- Data engineers
- Analytics engineers
- BI developers
- Technical analysts
- Internal data platform or reporting teams

### Problem it solves
CSV-based workflows often fail late. Data issues are discovered only after manual inspection, broken dashboards, or downstream pipeline errors. DQT moves that detection earlier by turning raw files into structured quality outputs that can be reviewed, exported, and consumed by BI tools or CI workflows.

### What it does today
- Loads and validates CSV inputs
- Profiles dataset and column-level structure
- Detects quality and schema issues
- Produces structured issue outputs
- Exports BI-ready artifacts including star-schema outputs
- Produces a per-run `quality_report.json` summary for automation and review
- Supports semantic KPI / DAX generation for BI-oriented workflows
- Tracks run-to-run quality trends from SQLite-backed run history
- Provides an optional local Streamlit dashboard for run-history trends, data overview, exploratory data analysis (EDA) charts, and per-column preprocessing recommendations

### Current product positioning
DQT is best positioned today as:
- a CLI tool
- an internal data platform component
- a lightweight data quality control layer for CSV-to-BI workflows

It is not yet positioned as:
- a SaaS platform
- a web UI product
- a full monitoring platform
- a multi-tenant enterprise governance system

### Core business value
- Catch data issues before they break reporting or analytics workflows
- Reduce manual CSV quality checking
- Standardize issue reporting across datasets
- Produce reusable artifacts for BI, governance, and CI-style validation
- Improve confidence in downstream reporting and decision-making

## KPI Table

| KPI | Why it matters | Available now | Source |
|---|---|---:|---|
| Quality score per run | Gives a simple summary of dataset health | Yes | assessment output / export artifacts |
| Total issues per run | Shows immediate quality burden | Yes | `fact_issues.csv`, `quality_report.json` |
| Issues by severity | Helps prioritize remediation | Yes | `fact_issues.csv`, `quality_report.json` |
| Issues by category | Shows whether problems are schema-related or data-related | Yes | `fact_issues.csv`, `quality_report.json` |
| Columns affected | Highlights concentration of quality problems | Yes | `fact_issues.csv` |
| Column completeness | Measures null exposure by column | Yes | `fact_quality_metrics.csv` |
| Artifact completeness | Confirms export outputs were produced successfully | Yes | export paths / output folder |
| Successful export rate | Measures workflow reliability | Yes | CLI/export run outcomes |
| Time to export | Measures operational efficiency | Yes | `duration_secs` in `quality_report.json` |
| Quality trend by dataset | Shows whether repeated runs are improving | Yes | `compare` output / `quality_history.jsonl` |
| Issue resolution rate | Measures quality improvement over time | Not yet | requires repeated-run tracking |
| Pipeline gate pass rate | Shows how often datasets meet expected thresholds | Not yet | enabled by `quality_report.json` + threshold policy |

## Current Scope Notes

The next productization steps are expected to focus on:
- clearer configuration
- stronger business-facing summaries
- additional quality rules
- richer trend visualization and alerting on top of the existing compare/history foundation

## 🚀 Quick Start

> **Windows note:** If `python`, `pip`, or `pytest` are not found in PowerShell,
> use your virtual environment's full interpreter path directly (see
> [Windows-safe invocation](#windows-safe-invocation) below).


### Installation

```bash
# Clone the repository
git clone <repo-url>
cd data-quality-toolkit

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install the toolkit
pip install -e .
```

### First successful run on Windows

Use the full interpreter path — works immediately after `pip install -e .` with no shell configuration required. Replace `<path-to-python>` with your `dqt` env interpreter (default: `C:\Users\<you>\micromamba\envs\dqt\python.exe`). Verify the install first:
```powershell
<path-to-python> -m data_quality_toolkit.adapters.cli.main --help
```

```powershell
# Export the bundled demo dataset — produces quality artifacts under dist/demo/
<path-to-python> -m data_quality_toolkit.adapters.cli.main export examples/demo/sample_orders.csv --outdir dist/demo
```
Open `dist/demo/star/quality_report.json` to confirm the run succeeded (score, issue counts, artifact paths).

### Demo

#### Happy path

- [Demo story](docs/demo_story.md)
- [Runnable demo package](examples/demo/README.md)

#### Issue showcase

- [Issue-focused demo package](examples/demo/issue_showcase/README.md)

### Basic Usage

The commands below require `dqt` to be on your PATH — this means the active environment's `Scripts\` directory (Windows) or `bin/` directory (Unix/macOS) must be in PATH. If `dqt` is not found, use the [Windows-safe invocation](#windows-safe-invocation) block below instead.

```bash
# Profile a dataset
dqt profile data/orders.csv

# Assess data quality
dqt assess data/orders.csv

# Export star-schema artifacts
dqt export data/orders.csv --outdir dist/

# Compare the latest two runs for the same dataset
# Requires at least two prior export runs written to the same --outdir
dqt compare data/orders.csv --outdir dist/

# Generate per-column preprocessing recommendations (impute / encode / scale / drop guidance)
dqt plan data/orders.csv

# Launch the Streamlit dashboard (requires: pip install data-quality-toolkit[ui])
dqt dashboard
```

> **Note on `compare`:** history is stored in `star/quality_history.jsonl` inside your `--outdir`.
> If fewer than two runs exist, compare returns `not_enough_runs` — run `export` at least twice first.

### View results in the dashboard

The dashboard does not open a raw CSV directly — it reads a dashboard-readable
SQLite database plus a `dataset_id`. Produce that database by exporting your
CSV first:

```bash
# 1. Export the CSV — writes dist/dqt.db and dist/star/quality_report.json
dqt export data/orders.csv --outdir dist

# 2. Launch the dashboard (requires: pip install data-quality-toolkit[ui])
dqt dashboard
```

In the dashboard, enter:
- **Database path:** `dist/dqt.db` (Windows: `dist\dqt.db`)
- **Dataset ID:** the `dataset_id` value from `dist/star/quality_report.json`

The dashboard provides:
- **Run History** — past export runs, score-over-time trend, and latest-run issues breakdown
- **Data Overview** — per-column dtype/null/unique/min/max table, numeric summary, duplicate-row count, and high-cardinality warnings (from a CSV path)
- **EDA Explorer** — univariate distributions and bivariate relationships (numeric↔numeric scatter with Pearson r, numeric↔categorical grouped stats, categorical↔categorical crosstab)
- **Preprocessing Recommendations** — per-column impute/scale/encode/outlier/drop guidance derived from dtype, null rate, cardinality, and IQR statistics (advisory only; no transformation is applied)

`dqt assess` prints a quick quality summary but does not populate the dashboard
database — use `dqt export` for the dashboard. See
[examples/dashboard/](examples/dashboard/README.md) for a full walkthrough and
troubleshooting.

### Windows-safe invocation

If `dqt` is not on your PATH, invoke the CLI directly via the interpreter:

```bash
<path-to-python> -m data_quality_toolkit.adapters.cli.main export examples/demo/sample_orders.csv --outdir dist/demo
<path-to-python> -m data_quality_toolkit.adapters.cli.main compare examples/demo/sample_orders.csv --outdir dist/demo
```

## Python API

Install once (`pip install -e .`), then import directly — no CLI required.

```python
from data_quality_toolkit import (
    profile_csv, assess_csv, export_csv, compare_runs, plan_csv,
    kpi_validate, kpi_emit, kpi_graph, generate_dim_time,
)

# Profile: returns shape and per-column stats. No disk writes.
result = profile_csv("data/orders.csv")
print(result["profile"]["rows"], result["profile"]["cols"])

# Assess: profile + quality score + detected issues. No disk writes.
result = assess_csv("data/orders.csv")
print(result["assessment"]["score"])          # e.g. 0.87
print(result["assessment"]["quality_score"])  # penalty-weighted score
for issue in result["assessment"]["issues"]:
    print(issue["type"], issue["column"], issue["severity"])

# Assess with quality gate — raise your own exception on failure:
result = assess_csv("data/orders.csv")
if result["assessment"]["quality_score"] < 0.9:
    raise ValueError("Quality gate failed")

# Export: full pipeline — profile → assess → star-schema CSVs + quality_report.json + SQLite history.
result = export_csv("data/orders.csv", output_dir="dist/")
print(result["export_paths"])

# Compare: trend analysis from the last two export runs.
result = compare_runs("data/orders.csv", output_dir="dist/")
print(result["score_delta"])

# Plan: per-column preprocessing recommendations (impute/scale/encode/drop). No disk writes.
result = plan_csv("data/orders.csv")
for col in result["columns"]:
    print(col["column"], col["issues"], col["recommendations"])

# KPI catalog validation (schema, semantics, cycles). No disk writes.
result = kpi_validate("config/kpi_catalog.yaml")
print(result["status"], result["kpis"])       # "valid", 8

# KPI emit: generate DAX measures + TMSL model JSON from catalog.
result = kpi_emit(
    "config/kpi_catalog.yaml",
    dax_out="dist/powerbi_package/dax/quality_measures.dax",
    tmsl_out="dist/powerbi_package/dax/model.tmsl.json",
)
print(result["dax"], result["tmsl"])

# KPI graph: export dependency graph as Mermaid (.mmd) or Graphviz (.dot).
result = kpi_graph("config/kpi_catalog.yaml", out="dist/semantics/kpi_graph", graph_format="mermaid")
print(result["graph"])                        # path to written .mmd file

# Time dimension: generate dim_time.csv (optional output_dir writes to disk).
result = generate_dim_time("2018-01-01", "2030-12-31", output_dir="dist/time")
print(result["rows"], result["path"])
```

Optional CSV-parsing kwargs (`sep`, `encoding`, `na_values`, `sample_size`) are accepted by all CSV functions.

> **Note:** `dqt.yaml` is not loaded by the Python API — pass options explicitly as keyword arguments.

## Advanced CLI Commands

The following commands complement the core workflow documented above.

### Preprocessing plan

```bash
# Per-column preprocessing recommendations (advisory only — no transformation applied)
dqt plan data/orders.csv
```

### Persist assessment to dashboard database

```bash
# Run assessment and write the result to a SQLite database for dashboard viewing
dqt assess data/orders.csv --db dist/dqt.db
```

### Power BI package (star schema → .pbit)

```bash
# Generate a Power BI zero-config package from an existing star-schema export
dqt build-pbi --star dist/star --out dist/powerbi_package
```

### Dimension time table

```bash
# Generate a standalone dim_time.csv for use in BI models
dqt gen-dim-time --start 2018-01-01 --end 2030-12-31 --out dist/time
```

### KPI catalog (DAX / TMSL generation)

```bash
# Validate a KPI catalog YAML for schema, semantic, and cycle errors
dqt kpi-validate --config config/kpi_catalog.yaml

# Generate DAX measures and TMSL from the KPI catalog
dqt kpi-emit --config config/kpi_catalog.yaml

# Export the KPI dependency graph (Mermaid or Graphviz)
dqt kpi-graph --config config/kpi_catalog.yaml --format mermaid
```

---

## Pipeline Quality Gate (ETL/ELT)

DQT is a lightweight data-quality toolkit. It can act as a **quality-gate step in CSV-based ETL/ELT pipelines**: after a pipeline extracts or produces a CSV file, run `dqt assess <file> --fail-under <score>` to enforce a minimum quality score. When the dataset falls short, the command exits with code `2`, allowing your pipeline or CI system to halt and alert.

```bash
# Gate fails (exit 2) when quality score < 0.9
dqt assess extracted.csv --fail-under 0.9

# Gate passes (exit 0) — score meets or exceeds threshold
dqt assess extracted.csv --fail-under 0.0
```

Exit codes are scriptable:

| Code | Meaning |
|------|---------|
| `0`  | Dataset meets the quality threshold (or no threshold set) |
| `1`  | Error (file not found, invalid input, etc.) |
| `2`  | Dataset scored below `--fail-under` threshold |

This makes DQT usable for **CI-style data quality gates** and **pipeline quality enforcement**.

### Quality score fields

DQT tracks three score fields per assessment run:

| Score field | Description |
|---|---|
| `score` | Legacy completeness score — fraction of non-null values across all columns (default) |
| `completeness_score` | Explicit alias for `score` — same value, clearer name |
| `quality_score` | Penalty-weighted score — starts from `completeness_score`, then deducts for structural and distribution issues (schema problems, outlier concentration, high cardinality); capped at `[0.0, 1.0]` |

Use `--score-field` to choose which score controls `--fail-under`:

```bash
# Default — uses legacy score (backward compatible)
dqt assess data.csv --fail-under 0.90

# Gate on penalty-weighted quality score
dqt assess data.csv --fail-under 0.90 --score-field quality_score

# Gate on explicit completeness score
dqt assess data.csv --fail-under 0.90 --score-field completeness_score
```

`--score-field` accepts `score`, `completeness_score`, or `quality_score`. Default is `score`. Omitting `--score-field` preserves existing exit-code behavior exactly.

**DQT is not an ETL/ELT engine.** It does not transform data, load data into targets, connect to warehouses, or orchestrate pipelines. It validates CSV input and emits quality artifacts; transformation, loading, and scheduling remain the responsibility of your pipeline.

See [examples/pipeline_gate/](examples/pipeline_gate/README.md) for a runnable example.

---

## Project Configuration (`dqt.yaml`)

DQT runs entirely from CLI flags by default — no configuration file is required. Optionally, you can place a `dqt.yaml` file in your project directory to set default values.

Supported keys (all optional):

### Basic Configuration (v1)
| Key | CLI equivalent | Purpose |
|---|---|---|
| `null_threshold` | `--null-threshold` | Null-rate threshold for column quality checks |
| `fail_under` | `--fail-under` | Minimum quality score for the pipeline gate |
| `outdir` | `--outdir` | Default output directory for export artifacts |

### Rule Contract Configuration (v2)
For advanced rules, use the structured `dataset` and `columns` sections:

| Key | Purpose |
|---|---|
| `dataset.fail_under` | Minimum quality score for the pipeline gate |
| `dataset.score_field` | Choose which score controls the gate (`score`, `completeness_score`, `quality_score`) |
| `columns.<name>.*` | Per-column thresholds (e.g., `required`, `critical`, `null_threshold`, `weight`, `outlier_threshold`) |

```yaml
# dqt.yaml example
dataset:
  fail_under: 0.85
  score_field: quality_score

columns:
  customer_id:
    required: true
    critical: true
  order_amount:
    null_threshold: 0.05
    weight: 2.0
```

**Notes:**
- A config value applies only when the matching CLI flag is omitted; an explicit CLI flag always takes precedence.
- Unknown rule keys fail loudly.
- If `dqt.yaml` is absent, behavior is unchanged — every option still works as a CLI flag.


---

## 📁 Project Structure

```
data-quality-toolkit/
├── src/data_quality_toolkit/
│   ├── domain/                # Business rules: profiling, assessment, semantics/KPI
│   ├── application/           # Workflow orchestration: pipeline, compare, preprocessing
│   ├── adapters/
│   │   ├── cli/               # Command-line interface (dqt entrypoint)
│   │   ├── ui/                # Streamlit dashboard (run history, data overview, EDA, preprocessing)
│   │   ├── loaders/           # CSV loading and validation
│   │   ├── exporters/         # Star-schema CSV, quality_report, Power BI, dim_time
│   │   └── storage/           # SQLite-backed run history
│   ├── api.py                 # Public Python API (profile_csv, assess_csv, export_csv, compare_runs, plan_csv)
│   └── shared/                # Cross-cutting constants, settings, exceptions
├── tests/                     # Test suites (unit/, integration/)
├── docs/                      # Documentation and demo stories
├── examples/                  # Demo packages and sample data
└── scripts/                   # Automation scripts
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=data_quality_toolkit --cov-report=html

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
```

## 📚 Documentation

- [Power BI integration — date table](docs/powerbi/date_table.md)
- [Power BI integration — incremental refresh](docs/powerbi/incremental_refresh.md)
- [Power BI integration — RLS testing](docs/powerbi/rls_testing.md)

## 🤝 Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Setup

```bash
# Install development dependencies
pip install -e ".[dev]"

# Setup pre-commit hooks
pre-commit install

# Run code quality checks
make lint
make type
make test
```

## ⚠️ Known Limitations

- **CLI-first:** no REST API in this release; an optional local Streamlit dashboard is available via `dqt dashboard` — install with `pip install data-quality-toolkit[ui]`. The dashboard is a local viewer, not a hosted/multi-user web product
- **CSV input only:** other file formats are not supported
- **Minimal config:** CLI flags drive all behavior; an optional `dqt.yaml` sets defaults for `null_threshold`, `fail_under`, and `outdir` only
- **Chunked/streaming support (partial):** `profile_csv(chunksize=N)` / `dqt profile --chunksize N` stream large files without a full in-memory load. `assess_csv(chunksize=N)` / `dqt assess --chunksize N` support *partial* chunked assessment — honest `completeness_score` and a subset of rules (null/completeness, all-null, required-column, dtype-mismatch, column-name hygiene); does not produce a full `quality_score` and skips rules that need unique counts or a full DataFrame (constant-column, high-cardinality, outliers, accepted-values, uniqueness). The UI dashboard has an opt-in large-data/profile-only mode that routes to chunked profiling and disables full-data EDA, full assessment, export, and preprocessing plan. Export/star-schema and compare still require full in-memory load. Unique/distinct counts, outlier detection, accepted-values and uniqueness checks, and full EDA remain unavailable in chunked mode
- **No PII detection or masking**

## 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).

## 🏆 Acknowledgments

Built with pandas, rich, pydantic, and other open-source libraries.

## 📞 Support

- **Issues**: [GitHub Issues](../../issues)
- **Discussions**: [GitHub Discussions](../../discussions)

---

**Version**: v2.0.0 | **Status**: Active development — CLI-first, CSV-first, SQLite-backed run history, pipeline quality gate (`--fail-under`), optional project config (`dqt.yaml`), and an optional local Streamlit dashboard (run history, data overview, EDA, preprocessing recommendations)
