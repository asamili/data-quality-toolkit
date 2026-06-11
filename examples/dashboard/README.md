# DQT Dashboard — User Guide

The DQT dashboard is a Streamlit app that surfaces the full data quality
toolkit through a browser UI. It covers profiling, assessment, EDA, run
history, pipeline execution, BI exports, KPI validation, and system
diagnostics — all backed by the same core layer used by the CLI and Python API.

---

## Prerequisites

Install the UI extra:

```bash
pip install data-quality-toolkit[ui]
```

Python 3.12+ required.

---

## Launching the Dashboard

```bash
dqt dashboard
```

This spawns `streamlit run` on the app and opens your browser at
`http://localhost:8501`. Press **Ctrl+C** in the terminal to stop.

If `streamlit` is not installed the command exits immediately with:

```text
Error: Streamlit is not installed.
Install it with: pip install data-quality-toolkit[ui]
```

> **Windows note:** if `dqt` is not on your PATH, invoke via the interpreter:
> `<path-to-python> -m data_quality_toolkit.adapters.cli.main dashboard`
> See [Windows-safe invocation](../../README.md#windows-safe-invocation).

---

## Navigation Overview

The dashboard is organised into five sections in the left sidebar:

| Section | Pages |
| ------- | ----- |
| Data Quality | Data Overview · EDA Explorer · Run History |
| Pipeline | Pipeline Runner |
| BI & Export | Export · KPI Catalog · Dim Time |
| Lineage | Manifest Viewer |
| System | Settings & Diagnostics |

**Data Overview** is the default landing page.

---

## Data Quality

### Data Overview

**Inputs:** CSV file path, Large-data mode checkbox.

**Full mode** (default) runs a complete profile and assessment:

- Quality Score metric and Issues Flagged count
- Column Analysis table — downloadable as CSV
- Null % by column bar chart
- Numeric Summary table
- Duplicate row count
- High-cardinality column warnings

**Large-data mode** streams the file in chunks and produces a profile only.
Assessment, EDA, outlier detection, unique counts, and correlation are
unavailable in this mode; a warning banner makes the limitation explicit.

---

### EDA Explorer

**Inputs:** CSV file path.

**Univariate Explorer** — select any column:

- Numeric: distribution bar chart + IQR outlier summary (fences and count)
- Categorical: top-values table (up to 20 values) + bar chart

**Bivariate Explorer** — select two columns:

- Numeric × Numeric: scatter plot + Pearson correlation
- Numeric × Categorical: grouped bar chart (mean by category)
- Categorical × Categorical: cross-tabulation (contingency table)

**Preprocessing Recommendations** — per-column issue table (impute / scale /
encode / drop guidance), downloadable as CSV.

---

### Run History

**Inputs:** Database path (`dqt.db`), Dataset ID.

Produces `dqt.db` only via `dqt export` — `dqt assess` alone does not write it.
The `dataset_id` is available in `star/quality_report.json` after an export run.

**Displays:**

- Score Trend line chart (requires 2 or more runs for the same dataset)
- Latest Run Issues Breakdown — by severity and by category

#### Run-to-Run Comparison

When two or more runs exist the page adds a comparison block:

- Score delta (current vs previous run)
- Issues count delta
- Issues delta by severity
- Issues delta by category

Run `dqt export` on the same CSV with the same `--outdir` a second time to
populate the comparison.

**Step-by-step:**

1. Export your CSV:

   ```bash
   dqt export data/orders.csv --outdir dist
   ```

   Windows:

   ```powershell
   dqt export data\orders.csv --outdir dist
   ```

2. Find the `dataset_id` in `dist/star/quality_report.json`:

   ```json
   {
     "run_id": "...",
     "dataset_id": "sha1:6f93a3412073e92bec4e09bcc6d7fd9d17aeb64c",
     "score": 0.991
   }
   ```

3. Launch the dashboard (`dqt dashboard`) and navigate to **Run History**.
4. Enter the database path (e.g. `dist/dqt.db`) and the `dataset_id`.

---

## Pipeline

### Pipeline Runner

**Inputs:** Run ID (required), Sessions Root (required), Pipeline YAML Config
Path (optional).

**Step selection checkboxes:** Extract · Transform · Load · Assess · Manifest.

Click **Run Pipeline** to execute the selected steps. The page displays the
JSON result and a CLI equivalence snippet showing the equivalent `dqt run`
command. The runner operates as a declarative scaffold — it records step
selections and reads existing session artifacts from the sessions root.

---

## BI & Export

### Export

Runs a full profile → assess → star-schema pipeline and writes artifacts to
disk. A confirmation checkbox is required before any server-side write.

**Inputs:** CSV file path, output directory (absolute path required).

**Artifacts written:**

| Artifact | Description |
| -------- | ----------- |
| `dqt.db` | SQLite run-history database |
| `star/dim_dataset.csv` | Dataset dimension |
| `star/dim_column.csv` | Column dimension |
| `star/fact_profile_runs.csv` | Per-run profile facts |
| `star/fact_quality_metrics.csv` | Per-column completeness metrics |
| `star/fact_issues.csv` | Detected issues fact table |
| `star/quality_report.json` | Run summary (meta / profile / assessment / star / export paths) |
| `star/quality_history.jsonl` | Full run history for trend tracking |

The page also shows the equivalent CLI and Python API calls:

```bash
dqt export data.csv --outdir ./dist
```

```python
from data_quality_toolkit import export_csv
result = export_csv("data.csv", output_dir="./dist")
```

---

### KPI Catalog

**Inputs:** KPI catalog YAML path (e.g. `config/kpi_catalog.yaml`).

**Displays:** Validation status banner (valid / invalid), KPI count, dependency
count, KPIs-by-grain breakdown, dependency graph preview (first 30 lines, shown
when the catalog has 20 or fewer KPIs).

**Downloads:**

- DAX measures (`measures.dax`)
- TMSL model JSON (`model.tmsl.json`)
- Mermaid dependency graph (`kpi_graph.mmd`)

The equivalent CLI commands are shown inline:

```bash
dqt kpi-emit --config config/kpi_catalog.yaml --dax-out measures.dax --tmsl-out model.tmsl.json
dqt kpi-graph --config config/kpi_catalog.yaml --out kpi_graph.mmd
```

---

### Dim Time

Generates a time-dimension table in memory and provides a browser download.
Nothing is written to disk.

**Inputs:**

| Field | Default | Notes |
| ----- | ------- | ----- |
| Start date | 2018-01-01 | YYYY-MM-DD |
| End date | 2030-12-31 | YYYY-MM-DD |
| Week start day | 1 (Monday) | 1 = Mon … 7 = Sun |
| Fiscal year start month | — | Optional; enables fiscal columns |

A success message confirms the row count and date range before the download
button appears. Output file: `dim_time.csv`.

---

## Lineage

### Manifest Viewer

**Inputs:** Run ID, Sessions Root (default `.`).

Click **Load Manifest** to fetch the lineage manifest for the specified run.

**Sections displayed:**

- **Manifest Summary** — collapsed JSON
- **Datasets** — tabular view of dataset entries
- **Artifacts** — tabular view of artifact entries
- **Gate Failures** — table of any gate failures, or "No gate failures" if the
  run passed all gates
- **Raw Manifest JSON** — full expanded JSON

---

## System

### Settings & Diagnostics

**Displays:**

- **Versions table** — DQT, Python, Streamlit, and key dependency versions
- **Settings Snapshot** — active configuration JSON
- **Project Config** — contents of `dqt.yaml` if present in the working
  directory
- **Import Diagnostics** — module availability and dependency resolution
- **Writable Directory Probe** — enter a directory path and click
  **Confirm Probe** to test filesystem write permissions; the result is shown
  inline

---

## Error Reference

| Symptom | Cause | Fix |
| ------- | ----- | --- |
| "No run history found for this dataset" | `dataset_id` does not match any run in the database | Re-copy `dataset_id` exactly from `quality_report.json`, including the `sha1:` prefix |
| "Storage error" / database cannot be opened | Wrong database path | Point to the actual `dqt.db` — by default `<outdir>/dqt.db`, e.g. `dist/dqt.db` |
| Dashboard shows nothing after entering values | Only `dqt assess` was run | `assess` does not write `dqt.db`. Run `dqt export <file> --outdir dist` first |
| Score trend absent, issues breakdown present | Fewer than two runs for the dataset | Run `dqt export` on the same CSV at least twice with the same `--outdir` |
| Run-to-Run Comparison absent | Fewer than two runs | Same as above |
| Windows path not accepted | Mixed forward/backward slashes | Use backslashes on Windows: `dist\dqt.db` |
| "Compare unavailable" info message | Not enough history for comparison | Add another export run to the same outdir |
| "Manifest load failed" | Invalid run ID or sessions root | Verify the run ID exists under the sessions root |
| KPI graph or DAX unavailable | Validation failure or catalog error | Check the error banner; fix the YAML and reload |
| Export confirmation not accepted | Confirmation checkbox unchecked | Check the confirmation box before clicking Export |
| "Streamlit is not installed" on `dqt dashboard` | UI extra not installed | `pip install data-quality-toolkit[ui]` |
| Large-data mode shows no assessment results | Large-data mode disables assessment | Uncheck Large-data mode or use `dqt assess` from the CLI |

---

## UI, CLI, and API Surfaces

The dashboard, CLI, and Python API all call the same underlying core layer.
Choose whichever surface fits your workflow — results are equivalent.

| Feature | CLI | Python API | UI Page |
| ------- | --- | ---------- | ------- |
| Profile + assess a CSV | `dqt profile` / `dqt assess` | `assess_csv()` | Data Overview |
| EDA charts + preprocessing plan | `dqt chart` / `dqt plan` | — | EDA Explorer |
| Run history trend | — | — | Run History |
| Run-to-run comparison | — | — | Run History |
| Full export + star schema | `dqt export` | `export_csv()` | Export |
| KPI catalog validation + emit | `dqt kpi-emit` / `dqt kpi-graph` | — | KPI Catalog |
| Time dimension generation | — | `generate_dim_time()` | Dim Time |
| Lineage manifest | `dqt manifest create` | — | Manifest Viewer |
| Pipeline scaffold | `dqt run` | — | Pipeline Runner |
| System diagnostics | — | — | Settings & Diagnostics |
