# Product Brief

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

## Known Limitations
- **CLI-first:** no REST API in this release; an optional local Streamlit dashboard is available via `dqt dashboard` — install with `pip install data-quality-toolkit[ui]`. The dashboard is a local viewer, not a hosted/multi-user web product
- **CSV input only:** other file formats are not supported
- **Minimal config:** CLI flags drive all behavior; an optional `dqt.yaml` sets defaults for `null_threshold`, `fail_under`, and `outdir` only
- **Chunked/streaming support (partial):** `profile_csv(chunksize=N)` / `dqt profile --chunksize N` stream large files without a full in-memory load. `assess_csv(chunksize=N)` / `dqt assess --chunksize N` support *partial* chunked assessment — honest `completeness_score` and a subset of rules (null/completeness, all-null, required-column, dtype-mismatch, column-name hygiene); does not produce a full `quality_score` and skips rules that need unique counts or a full DataFrame (constant-column, high-cardinality, outliers, accepted-values, uniqueness). The UI dashboard has an opt-in large-data/profile-only mode that routes to chunked profiling and disables full-data EDA, full assessment, export, and preprocessing plan. Export/star-schema and compare still require full in-memory load. Unique/distinct counts, outlier detection, accepted-values and uniqueness checks, and full EDA remain unavailable in chunked mode
- **No PII detection or masking**
