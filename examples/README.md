# Data Quality Toolkit Examples

This directory contains small datasets and runnable demo assets for the Data Quality Toolkit (DQT).

Use these examples when you want to:

- try the CLI on known CSV inputs
- demonstrate profiling, assessment, and export flows
- compare clean-data and issue-focused scenarios
- produce sample quality artifacts for review

## Recommended starting point

Start with the full demo package:

- [Demo package — sample orders dataset](demo/README.md)

That guide shows the standard happy-path workflow and links to the issue-showcase demo.

## Current structure

```text
examples/
  README.md
  demo.csv
  tiny.csv
  01_quickstart.ipynb
  demo/
    README.md
    sample_orders.csv
    issue_showcase/
      README.md
      issue_demo.csv
    dist/
      star/
        dim_column.csv
        dim_dataset.csv
        fact_issues.csv
        fact_profile_runs.csv
        fact_quality_metrics.csv
        quality_history.jsonl
        quality_report.json
```

## Available datasets

| File | Description | Best for |
|---|---|---|
| `examples/demo/sample_orders.csv` | Synthetic business orders dataset — multi-region, mixed statuses, nullable fields | Primary demo, business-domain quality checks |
| `examples/demo/issue_showcase/issue_demo.csv` | Tiny crafted dataset designed to trigger quality rules | Demonstrating issue detection |
| `examples/tiny.csv` | Minimal three-row CSV | Fast smoke checks |
| `examples/demo.csv` | Small simple CSV with a missing value | Basic CLI testing |

## Basic CLI commands

Run these commands from the repository root.

### Profile a dataset

```bash
python -m data_quality_toolkit.adapters.cli.main profile examples/demo/sample_orders.csv
```

### Assess quality

```bash
python -m data_quality_toolkit.adapters.cli.main assess examples/demo/sample_orders.csv
```

### Export quality artifacts

```bash
python -m data_quality_toolkit.adapters.cli.main export examples/demo/sample_orders.csv --outdir dist/demo
```

The export command writes star-schema quality artifacts under `dist/demo/`.

## More demo guides

- [Main demo package](demo/README.md)
- [Issue-showcase demo](demo/issue_showcase/README.md)
- [Demo story and product walkthrough](../docs/demo_story.md)

## Notes

These examples are for local development, demonstrations, and documentation. Do not use production or sensitive data in this directory.
