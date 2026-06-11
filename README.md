# Data Quality Toolkit (DQT)

[![Python](https://img.shields.io/badge/Python-3.12+-green)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue)](LICENSE)
[![CI](https://github.com/asamili/data-quality-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/asamili/data-quality-toolkit/actions/workflows/ci.yml)

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

> Not published on public PyPI. Install from source (below) or download wheel/sdist from the [latest release](https://github.com/asamili/data-quality-toolkit/releases/latest).

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
```

## Documentation
- [Product Brief](docs/product.md)
- [CLI Reference](docs/cli.md)
- [Python API](docs/api.md)
- [Architecture & Design](docs/architecture.md)
- [Demo Story](docs/demo_story.md)

---
**Version**: v2.2.1 | **Status**: Active development | [Latest release](https://github.com/asamili/data-quality-toolkit/releases/latest)
