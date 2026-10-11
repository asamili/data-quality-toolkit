# Product Brief

### Vision
DQT is a **governed data quality system** that connects validation, monitoring, and BI-ready insight in one CLI-first, server-less tool. What makes it distinct is the combination of: a pipeline-grade quality gate (`assess --fail-under`, exit code 2); drift monitoring built on a *single shared view-model* that keeps the static dashboard and the optional UI in agreement; BI-ready exports (star schema, zero-config Power BI package, semantic KPI / DAX, fiscal-aware time dimension); a 16-page local UI journey; and governed, default-off optional AI that never compromises determinism. DQT 2.10.0 sharpens this positioning and onboarding. DQT now ships a **built-in current-star quality semantic catalog** — a `quality_score_proxy` measure with built-in DAX emission and semantic-contract validation, reachable via `dqt kpi-builtin`. The *full* canonical BI semantic model (a true Quality Score, plus drift/PSI, duplicate-rate, failed-quality-gate-count, and Last Run Date measures) remains **held** for a later release.

New to DQT? The [Golden Path guide](guides/golden_path.md) walks one dataset from load to BI-ready outputs.

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
- Ships a built-in current-star quality semantic catalog — a proxy quality score (`quality_score_proxy`), DAX emission, and semantic-contract validation via `dqt kpi-builtin` (full canonical BI semantic measures remain held)
- Tracks run-to-run quality trends from SQLite-backed run history
- Provides an optional local Streamlit dashboard organized as a 16-page product journey: Start / Load Dataset, Data Overview, EDA Explorer, Statistics Lab, Quality Score, Preprocess Studio, Pipeline Runner, Drift Monitoring, Export, Quality History, Artifact Center, KPI Catalog, Dim Time, Manifest Viewer, Settings / Governance, and Help / About
- Gives Statistics Lab a focused numbers workspace: descriptive statistics, statistical tests, theoretical Distributions, Power & Sample Size planning, lightweight result downloads, and opt-in workspace saves where a Workspace Root is configured
- Hands Export-created `dqt.db` files to Quality History for score trends, latest-run issues, and run comparison
- Hands a successful confirmed UI Export to Artifact Center through a session-only Latest Export context — no manual path or ID re-entry — and writes an `artifacts.json` lineage manifest inside the confirmed export output directory (disclosed before confirmation; the public API default stays `emit_manifest=False` and the CLI stays opt-in via `--manifest`, so manifest-less exports remain fully usable)
- Loads existing lineage manifests read-only in Artifact Center and Manifest Viewer (shared reader, basename-first display, manifest-relative artifact resolution); rebuilding `artifacts.json` is a separately confirmed write action limited to an existing session directory, and manifests remain private/local evidence

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
