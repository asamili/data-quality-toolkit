# CLI Reference

## Basic Usage
```bash
# Profile a dataset
dqt profile data/orders.csv

# Generate a terminal distribution chart for a column (Visibility)
dqt chart data/orders.csv --column order_amount

# Assess data quality (Trust)
dqt assess data/orders.csv --fail-under 0.90

# Export star-schema artifacts
dqt export data/orders.csv --outdir dist/

# Create a lineage manifest for an export run (Traceability)
dqt manifest create --run-id RUN_ID --sessions-root dist/star/

# Compare the latest two runs for the same dataset
# Requires at least two prior export runs written to the same --outdir
dqt compare data/orders.csv --outdir dist/

# Generate per-column preprocessing recommendations (impute / encode / scale / drop guidance)
dqt plan data/orders.csv

# Launch the Streamlit dashboard (requires: pip install data-quality-toolkit[ui])
dqt dashboard
```

## Pipeline Quality Gate (ETL/ELT)
DQT is a lightweight data-quality toolkit. It can act as a **quality-gate step in CSV-based ETL/ELT pipelines**: after a pipeline extracts or produces a CSV file, run `dqt assess <file> --fail-under <score>` to enforce a minimum quality score. When the dataset falls short, the command exits with code `2`, allowing your pipeline or CI system to halt and alert.

```bash
# Gate fails (exit 2) when quality score < 0.9
dqt assess extracted.csv --fail-under 0.9

# Gate passes (exit 0) — score meets or exceeds threshold
dqt assess extracted.csv --fail-under 0.0
```

Exit codes:
- `0`: Dataset meets threshold
- `1`: Error (file not found, invalid input)
- `2`: Dataset scored below `--fail-under` threshold

## Project Configuration (`dqt.yaml`)
DQT runs entirely from CLI flags by default. Optionally, place a `dqt.yaml` file in your project directory to set default values.

### Basic Configuration (v1)
| Key | CLI equivalent | Purpose |
|---|---|---|
| `null_threshold` | `--null-threshold` | Null-rate threshold for column quality checks |
| `fail_under` | `--fail-under` | Minimum quality score for the pipeline gate |
| `outdir` | `--outdir` | Default output directory for export artifacts |

### Rule Contract Configuration (v2)
For advanced rules, use the structured `dataset` and `columns` sections:

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
