# DQT Pipeline Quality Gate — Runnable Example

This example shows how to use DQT as a **quality-gate step in a CSV-based
ETL/ELT pipeline**. After a pipeline extracts or produces a CSV file, run
`dqt assess` with `--fail-under` to enforce a minimum quality score. If the
dataset falls short, the command exits with code `2`, allowing your pipeline
or CI system to halt and alert.

**DQT is not an ETL/ELT engine.** It does not transform data, load data into
targets, or connect to warehouses. It validates CSV input and emits quality
artifacts; pipeline execution and scheduling remain your responsibility.

---

## Scenario

A pipeline has produced `sample_pipeline_output.csv`. Before passing it to the
next stage, run a DQT quality gate.

The sample file contains deliberate quality issues:
- `notes` column: entirely null (all 10 rows)
- `product`, `quantity`, `price`: partial nulls

Quality score: **0.66** (66%).

---

## Commands

> **Windows note:** If `dqt` is not on your PATH, replace `dqt` with your
> full interpreter path — for example:
> `<path-to-python> -m data_quality_toolkit.cli.main assess ...`
> See [Windows-safe invocation](../../README.md#windows-safe-invocation).

### 1. Strict gate — expected to fail (exit 2)

Score 0.66 is below threshold 0.9, so the gate rejects the dataset.

```bash
dqt assess sample_pipeline_output.csv --fail-under 0.9
echo "Exit code: $?"
# Expected: Exit code: 2
```

### 2. Permissive gate — expected to pass (exit 0)

Score 0.66 meets threshold 0.0, so the gate accepts the dataset.

```bash
dqt assess sample_pipeline_output.csv --fail-under 0.0
echo "Exit code: $?"
# Expected: Exit code: 0
```

### 3. Export quality artifacts

Export star-schema CSVs and a machine-readable `quality_report.json` summary.

```bash
dqt export sample_pipeline_output.csv --outdir dist/
# Produces: dist/star/quality_report.json, dist/star/fact_issues.csv, etc.
```

### 4. View results in the dashboard

`dqt export` also writes a dashboard-readable SQLite database at `dist/dqt.db`.
To view the run visually:

```bash
dqt dashboard
```

In the dashboard, enter `dist/dqt.db` as the database path and the `dataset_id`
from `dist/star/quality_report.json` as the dataset ID.

`dqt assess` does not populate this database — only `dqt export` does. See
[examples/dashboard/](../dashboard/README.md) for a full walkthrough.

---

## Exit codes

| Code | Meaning |
|------|---------|
| `0`  | Dataset met the quality threshold (or no threshold was set) |
| `1`  | Error (file not found, invalid input, etc.) |
| `2`  | Dataset scored below the `--fail-under` threshold |

These exit codes are scriptable in any CI system or shell script.
See `run_gate.sh` in this directory for a minimal shell example.

---

## CI integration sketch

```bash
# In a CI step, Airflow pre-task hook, or Makefile target:
dqt assess sample_pipeline_output.csv --fail-under 0.9
if [ $? -ne 0 ]; then
  echo "Data quality gate failed. Halting pipeline."
  exit 1
fi
echo "Quality gate passed. Proceeding to next stage."
```

---

## Notes

- `dist/` is runtime output — do not commit it.
- Replace `sample_pipeline_output.csv` with your own pipeline output CSV.
- DQT is CSV-first. Parquet, Excel, and warehouse connectors are not currently
  supported.
- For repeated runs, use `dqt compare` to track quality trends over time.
