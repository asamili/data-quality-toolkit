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
<path-to-python> -m data_quality_toolkit.cli.main --help
```

```powershell
# Export the bundled demo dataset — produces quality artifacts under dist/demo/
<path-to-python> -m data_quality_toolkit.cli.main export examples/demo/sample_orders.csv --outdir dist/demo
```
Open `dist/demo/star/quality_report.json` to confirm the run succeeded (score, issue counts, artifact paths). The bundled `sample_orders.csv` is a 170-row synthetic orders dataset; a successful first run produces a quality score around 0.96 with 3 intentional issues flagged.

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
```

> **Note on `compare`:** history is stored in `star/quality_history.jsonl` inside your `--outdir`.
> If fewer than two runs exist, compare returns `not_enough_runs` — run `export` at least twice first.

### Windows-safe invocation

If `dqt` is not on your PATH, invoke the CLI directly via the interpreter:

```bash
<path-to-python> -m data_quality_toolkit.cli.main export examples/demo/sample_orders.csv --outdir dist/demo
<path-to-python> -m data_quality_toolkit.cli.main compare examples/demo/sample_orders.csv --outdir dist/demo
```

## 📁 Project Structure

```
data-quality-toolkit/
├── src/data_quality_toolkit/   # Core library
│   ├── loaders/               # CSV loading and validation
│   ├── profiling/             # Column-level profiling
│   ├── assessment/            # Quality issue detection
│   ├── exporters/             # Star-schema CSV + quality_report export
│   ├── workflow/              # Pipeline orchestration and compare
│   └── cli/                   # Command-line interface
├── tests/                      # Test suites
├── docs/                       # Documentation and demo stories
├── examples/                   # Demo packages and sample data
└── scripts/                    # Automation scripts
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
pytest tests/e2e/
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

- **CLI-only:** no REST API or web UI in this release
- **CSV input only:** other file formats are not supported
- **No config file:** all options are passed as CLI flags (`--null-threshold`, `--outdir`)
- **No streaming / chunking:** large files are loaded fully into memory via pandas
- **No PII detection or masking**

## 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).

## 🏆 Acknowledgments

Built with pandas, typer, rich, pydantic, and other open-source libraries.

## 📞 Support

- **Issues**: [GitHub Issues](../../issues)
- **Discussions**: [GitHub Discussions](../../discussions)

---

**Version**: v1.2.0 | **Status**: MVP — CLI-first, CSV-first
