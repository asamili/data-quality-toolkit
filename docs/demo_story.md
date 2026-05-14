# Demo Story — From Raw CSV to Quality-Verified BI Artifacts

This document explains the product value of one complete DQT success path,
using the bundled synthetic orders dataset as the worked example.

---

## Demo flow at a glance

1.  **Export:** Run `dqt export` on a raw CSV.
2.  **Review:** Examine `quality_report.json` for summary, `fact_issues.csv` for details.
3.  **Compare:** Run `dqt export` a second time, then `dqt compare` to see trends.

### Show these artifacts

-   `quality_report.json` (summary, score, issue counts)
-   `fact_issues.csv` (detailed issue log — 3 rows on sample_orders run)
-   `fact_quality_metrics.csv` (column completeness)
-   `quality_history.jsonl` (after `compare`)

For exact commands and reusable demo paths, see the
[happy-path demo package](../examples/demo/README.md) and
[issue-showcase demo package](../examples/demo/issue_showcase/README.md).

---

## The problem this demo solves

A data team receives a CSV export from an upstream system.
They need to know, before it reaches a dashboard or report:

- Are any columns missing data, and how much?
- Are there structural problems (duplicate names, blank headers, placeholders)?
- What is the overall quality score?
- Where are the artifacts needed for BI review or pipeline sign-off?

Without a tool like DQT, answering these questions requires manual inspection in Excel or ad-hoc scripts — slow, inconsistent, and not repeatable.

---

## The input

`examples/demo/sample_orders.csv`

Synthetic business orders dataset — multi-region, mixed statuses, nullable fields.
170 rows, 14 columns.

No pre-processing is required. DQT takes the raw file directly.

---

## The single command

```bash
# Using the dqt CLI
dqt export examples/demo/sample_orders.csv --outdir dist/demo

# Using python -m
python -m data_quality_toolkit.cli.main export examples/demo/sample_orders.csv --outdir dist/demo
```

This runs the full pipeline in one step:

1. Load and validate the CSV
2. Profile every column (null rate, distinct count, dtype, min/max for numerics)
3. Compute a quality score (0–1, completeness-weighted across all columns)
4. Detect issues: missing data above threshold, schema problems, and fully-null columns (`all_null_column` — flags columns where every value is missing)
5. Build a star schema (dimension + fact tables) ready for BI
6. Write `fact_issues.csv` — one row per detected issue with severity and category
7. Write `quality_report.json` — a single-file summary of the run

The verified run produced the following results:

- Rows: 170
- Columns: 14
- Quality score: 95.71%
- Issues flagged: 3 (`discount_pct` missing, `notes` missing, `currency` constant)

Artifacts written to `dist/demo/`:

```text
dim_dataset.csv
dim_column.csv
fact_profile_runs.csv
fact_quality_metrics.csv
fact_issues.csv
quality_report.json
```

---

## The output artifacts and their business purpose

### `quality_report.json`

The top-level run summary. The report uses a nested structure with these top-level sections:

```json
{
  "meta":         { "run_id": "...", "dataset_id": "sha1:...", "ts": "..." },
  "profile":      { "rows": 170, "cols": 14, ... },
  "assessment":   { "score": 0.9571, "issues": [ { "type": "missing", "column": "discount_pct", "severity": "high", "category": "Completeness" }, { "..." } ] },
  "star":         { ... },
  "export_paths": { ... }
}
```

**Who cares:** data engineers running pipeline gates, analysts sharing run results,
managers wanting a one-number answer to "is this data good enough?"

**How to use it:** attach it to a pull request, check `score >= threshold` in CI,
or paste it into a Slack message as run evidence.

---

### `fact_issues.csv`

One row per detected problem. On this demo run the file contains 3 rows — `discount_pct` (missing data), `notes` (missing data), and `currency` (constant column).

Schema: `run_id | dataset_id | column_id | issue_type | severity | category | message`

**Who cares:** data engineers triaging problems, BI developers building issue dashboards.

**How to use it:** load into Power BI alongside `dim_column` to filter and prioritize issues.
Filter `severity = critical` to find the worst problems first.

---

### `fact_quality_metrics.csv`

One row per column, per run. Example structure:

| run_id | column_id | null_pct | distinct_count | completeness |
| --- | --- | --- | --- | --- |
| `...` | `...:discount_pct` | `0.2471` | `...` | `0.7529` |
| `...` | `...:notes` | `0.3529` | `...` | `0.6471` |

**Who cares:** analysts and BI developers tracking completeness by column over time.

**How to use it:** sort by `null_pct` descending to prioritize remediation effort.
Join to `dim_column` to get human-readable column names.

---

### Star schema tables (`dim_dataset`, `dim_column`, `fact_profile_runs`)

Standard dimension and fact tables wired by `relationships.json`.
These feed directly into Power BI via `dqt build-pbi` or any BI tool that reads CSV.

---

## What the demo proves about the product

| Claim | Evidence from demo run |
| --- | --- |
| Works on raw CSV, no prep required | `sample_orders.csv` (170 rows, 14 columns) loaded and profiled without modification |
| Produces a correct quality score | 95.71% — verified against actual run output |
| Detects real quality issues | 3 issues flagged: missing data on `discount_pct` and `notes`, constant-column on `currency` |
| Produces structured, queryable output | `fact_issues.csv` and `fact_quality_metrics.csv` are BI-ready |
| Produces a single-file summary | `quality_report.json` (nested: meta/profile/assessment/star/export_paths) is self-contained and CI-friendly |
| Fast | Full run on 170-row dataset completes in under a second |
| One command | No config files, no setup steps beyond `pip install -e .` |

---

## What this demo does not cover

- Power BI package assembly (`dqt build-pbi`) — see `docs/powerbi/`
- KPI/DAX generation (`dqt kpi-emit`) — requires a `kpi_catalog.yaml`

---

## Comparing runs

`compare` is the first small monitoring-style capability in DQT.
It shows how quality metrics shifted between the latest two export runs for the same dataset.

```bash
# Run export twice, then compare
dqt export examples/demo/sample_orders.csv --outdir dist/demo
dqt export examples/demo/sample_orders.csv --outdir dist/demo
dqt compare examples/demo/sample_orders.csv --outdir dist/demo
```

History is stored in `dist/demo/star/quality_history.jsonl`.
If fewer than two runs exist, compare returns `not_enough_runs` — run `export` at least twice first.

---

## Next steps after the demo

1. Replace `sample_orders.csv` with your own dataset and re-run
2. Check `quality_report.json` — is the score acceptable? Are issues expected?
3. Load `fact_issues.csv` and `fact_quality_metrics.csv` into your BI tool
4. Run `export` a second time and use `compare` to see quality trends
5. Integrate `dqt export` into your data pipeline as a pre-publish quality gate
