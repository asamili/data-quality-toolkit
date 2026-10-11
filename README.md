# Data Quality Toolkit (DQT)

[![Python](https://img.shields.io/badge/Python-3.12-green)]()
[![License](https://img.shields.io/badge/License-Apache%202.0-blue)]()
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-blue)]()

**A CLI-first toolkit for CSV data quality: profile datasets, enforce quality gates, detect statistical drift, and export BI-ready artifacts.**

DQT runs from the command line with no service to stand up. Point it at a CSV and it profiles columns, scores quality, and fails your pipeline when data falls below threshold. It also detects statistical drift between datasets and turns drift history into SQLite-backed monitoring reports and dashboards.

## Why DQT

DQT is a **governed data quality system** that connects validation, monitoring, and BI-ready insight in one CLI-first, server-less tool:

- **Quality gates for pipelines** — `dqt assess --fail-under` exits `2` to halt CI/ETL the moment data drops below a quality threshold. The same gate is `assess_csv` in the Python API.
- **Drift monitoring and operational visibility** — KS + chi-square drift detection, an append-only history promoted into a SQLite monitoring store, and static, self-contained HTML dashboards and Markdown reports.
- **BI-ready exports and Power BI readiness** — star-schema CSVs, a zero-config Power BI package, semantic KPI / DAX emission, and a fiscal-aware time dimension, plus Excel / DuckDB / PNG monitoring exports.
- **One shared monitoring view-model** — the static dashboard and the optional Streamlit UI read identical values, so surfaces never disagree on run counts, drift rates, or column metrics.
- **Governed, default-off AI** — the optional StoryLens narrator stays off unless explicitly enabled; a deterministic fallback always applies; AI internals are kept out of the public API and CLI by a machine-checked import-linter contract.
- **Server-less and dependency-light** — no service to stand up; every optional capability is isolated behind an install extra so the base install stays lean.

> **Since v2.9.0.** DQT 2.10.0 adds a built-in DQT quality semantic catalog over current-star / proxy measures, public API helpers (`get_builtin_quality_catalog`, `emit_builtin_quality_dax`, `validate_builtin_quality_semantic_contract`), the additive `dqt kpi-builtin` CLI family, exporter semantic-contract validation, and statistics/API/CLI/EDA/Statistics Lab surfaces (`dqt stats`, `stats_profile_csv`, `select_statistical_test`, `run_statistical_test`, `compare_ab`). Statistics Lab also includes UI wiring for Distributions, Power & Sample Size, and lightweight result downloads / workspace saves. Package metadata reports v2.10.0; this does not claim the full canonical BI semantic model is complete — see the [Changelog](CHANGELOG.md).

> **Release status — v2.10.0.** The whole-repository technical audit for v2.10.0 is complete and accepted: technical audit **PASS**, technical release readiness **PASS**, architecture **B — SOUND: TARGETED HARDENING ONLY**, and no known current technical release blockers. Broader product, infrastructure, deployment, and operational readiness is a separate phase that is still active and not complete.

## First 5 minutes

New to DQT? Follow the **[Golden Path guide](docs/guides/golden_path.md)** — one dataset from load to BI-ready outputs — then see the **[BI worked example](docs/guides/bi_worked_example.md)** for connecting those outputs to Power BI.

## Install

```bash
git clone https://github.com/asamili/data-quality-toolkit
cd data-quality-toolkit
python -m venv .venv
.venv\Scripts\activate
pip install -e .

# Optional extras
pip install "data-quality-toolkit[stats]"   # drift detection + statistical tests (scipy)
pip install "data-quality-toolkit[ui]"      # Streamlit dashboard
```

## Core Workflow

```bash
# Profile a dataset
dqt profile data/orders.csv

# Score quality and fail the pipeline below a threshold (exit code 2)
dqt assess data/orders.csv --fail-under 0.90

# Export star-schema artifacts for BI
dqt export data/orders.csv --outdir dist/

# Detect statistical drift between two datasets
dqt drift data/baseline.csv data/current.csv --alpha 0.05
```

`dqt assess --fail-under <score>` is the pipeline gate: it exits `2` when the quality score is below the threshold, so CI/ETL steps can halt and alert. See the [CLI Reference](docs/cli.md) for the full command set.

## Statistical Drift Detection

Compare two CSV datasets for statistical drift using KS tests (numerical) and Chi-square tests (categorical). Requires the `[stats]` extra.

```bash
# Basic usage
dqt drift baseline.csv current.csv

# Advanced tuning
dqt drift baseline.csv current.csv --alpha 0.01 --min-samples 100 --max-categories 10

# Fail on drift (exit code 2)
dqt drift baseline.csv current.csv --fail-on-drift

# Persist a JSON evidence report (opt-in; written even with --fail-on-drift)
dqt drift baseline.csv current.csv --output drift_report.json

# Append a compact run record to an append-only drift history (opt-in)
dqt drift baseline.csv current.csv --output drift_report.json --history drift_history.jsonl
```

- **Output:** machine-readable JSON goes to `stdout` (suppress with `--no-json`); a human-readable summary goes to `stderr`.
- **Evidence report:** `--output <path>` writes the drift result wrapped in a versioned envelope (`schema_version`, `kind`, `run_id`, `created_at`, `baseline_path`, `current_path`, `result`). Written before the `--fail-on-drift` exit check, so CI keeps the evidence even on failure.
- **Drift history:** `--history <path>` appends one compact JSONL record per run (`run_id`, `created_at`, dataset ids, `status`, `alpha`, summary counts, `report_path`). When `--output` is also given, the record's `run_id` matches the evidence report's, so history lines trace back to full reports. This file is the input to the `dqt drift-history` analytics commands below.
- **Exit codes:** `0` success (no drift, or drift without `--fail-on-drift`); `1` unavailable (missing `scipy`); `2` drift detected with `--fail-on-drift`.

## Statistics and A/B Workflows

DQT 2.10.0 adds a DQT-native statistics surface. It includes public API helpers (`stats_profile_csv`, `select_statistical_test`, `run_statistical_test`, `compare_ab`), typed result contracts, the additive `dqt stats` CLI family, and Statistics Lab tabs for descriptive statistics, statistical tests, theoretical Distributions, and Power & Sample Size planning:

```bash
dqt stats profile data/orders.csv
dqt stats select-test --variable-type numeric --group-structure two_independent --sigma-known false --equal-variance-assumed false
dqt stats test data/orders.csv --test-key ONE_T --value-column order_amount --null-mean 0
dqt stats ab data/orders.csv --group-column variant --metric-column order_amount --group-a A --group-b B
```

Scipy remains optional behind `[stats]`; unsupported or missing-scipy paths return structured statuses instead of importing or failing at module load. Statistics Lab result tables use lightweight browser downloads, with opt-in workspace saves where a Workspace Root is configured. Notebook/ipwidgets workflows, generated PDF reports, statsmodels-dependent advanced branches, Bayesian branches, and DB/SQL utilities remain deferred to later releases.

## Drift History Analytics (v2.5.0)

> These commands ship in **v2.5.0**.

Promote an append-only drift history (`dqt drift --history drift_history.jsonl`) into a SQLite monitoring store, then query trends, inspect column metrics, and render reports and dashboards.

```bash
# Import a JSONL drift history into a SQLite monitoring DB
dqt drift-history import history.jsonl --db monitoring.db

# List imported runs
dqt drift-history list --db monitoring.db

# Trend summary across runs
dqt drift-history trend --db monitoring.db

# Per-column drift metrics
dqt drift-history columns --db monitoring.db

# Markdown/HTML report (opt-in column metrics + distribution plots)
dqt drift-history report --db monitoring.db --output drift-report.md --include-columns --include-plots

# Static, self-contained HTML dashboard
dqt drift-history dashboard --db monitoring.db --output drift-dashboard.html --include-plots
```

- **Dependency-free artifacts:** reports and the dashboard render with inline CSS only — **no JavaScript, no CDN, no images, and no matplotlib required**.
- **Advanced per-column metrics:** PSI (Population Stability Index), Jensen-Shannon distance, and Wasserstein distance.
- **SQLite-backed artifacts:** import populates the `drift_runs`, `drift_columns`, and `drift_column_distributions` tables.
- **Opt-in detail:** `--include-columns` appends column-level metrics to the report; `--include-plots` adds distribution plots to the report and dashboard. Both default off, leaving base output unchanged.
- A missing or empty database still produces valid output and exits `0`.

## Drift Threshold Gating (v2.7.1)

Opt-in CLI flags that exit `2` when a monitored metric exceeds a threshold — reusing the existing `--fail-on-drift` exit-code convention. No new dependencies. No network. No schema changes.

```bash
# Fail if the historical drift rate exceeds 30 %
dqt drift-history trend --db monitoring.db --fail-on-drift-rate 0.30

# Fail if any column's PSI exceeds 0.20
dqt drift-history columns --db monitoring.db --fail-on-psi 0.20
```

- **Breach semantics:** strictly greater than (`>`). Exactly equal to the threshold is **not** a breach.
- **Exit codes:** `0` within threshold (or flag absent); `1` invalid threshold value (out of `[0.0, 1.0]`); `2` threshold breached.
- **Empty/missing DB:** always exits `0` — zero drift rate / no columns = no breach.
- Both evaluators (`evaluate_drift_rate_threshold`, `evaluate_psi_threshold`) are also available in the Python API (see [docs/api.md](docs/api.md)).

## Excel Export (v2.7.1)

Export drift-history monitoring data to a local multi-sheet `.xlsx` workbook. Opt-in feature behind the `[powerbi]` extra (`pip install data-quality-toolkit[powerbi]`). Local-only — no network, no cloud, no `.pbix`.

```bash
dqt drift-history export-xlsx --db monitoring.db --out drift_monitoring.xlsx
```

- **Sheets:** `runs`, `trend_summary`, `columns` (default on; disable with `--no-include-columns`), `distributions` (opt-in via `--include-distributions`), `metadata`.
- **No overwrite by default:** an existing file is refused unless you pass `--force`.
- **Security:** every string cell is escaped against spreadsheet formula injection (values starting `=`, `+`, `-`, `@`, or a leading tab/CR are quoted); no formulas, macros, or external links are written.
- **Exit codes:** `0` written; `1` export failure (missing `[powerbi]` dep, unsafe `.xlsx` path, refused overwrite, write error); `2` argparse error.
- Available in the Python API as `export_drift_history_xlsx` (see [docs/api.md](docs/api.md)).

## DuckDB Export/Mirror (v2.7.1)

Mirror the drift-history monitoring tables (`drift_runs`, `drift_columns`, `drift_column_distributions`) into a standalone **DuckDB** file. Opt-in feature behind the `[duckdb]` extra (`pip install data-quality-toolkit[duckdb]`). **Export/mirror only — not a live backend; the monitoring store stays SQLite.**

```bash
dqt drift-history export-duckdb --db monitoring.db --out monitoring.duckdb
```

- **Read-only source:** the SQLite DB is opened `mode=ro` and never mutated — no schema change, no writes, no migrate.
- **No overwrite by default:** an existing output file is refused unless you pass `--overwrite`.
- **Exit codes:** `0` written; `1` export failure (missing `[duckdb]` dep, missing source DB, unsafe `.duckdb` path, refused overwrite, write error); `2` argparse error.
- Available in the Python API as `export_monitoring_duckdb` (see [docs/api.md](docs/api.md)).

## Drift Plots (v2.7.1)

Render drift-history monitoring data to local **PNG** chart files. Opt-in feature behind the `[viz]` extra (`pip install data-quality-toolkit[viz]`). Local-only — no network, no GUI backend, no remote image fetching (matplotlib runs on the non-interactive `Agg` backend).

```bash
dqt drift-history plot --db monitoring.db --out plots/ --chart all
```

- **Chart catalog:**
  - `drift-rate` (`drift_rate.png`) — per-run drift fraction (`columns_drifted / columns_tested`) over time, with the overall drift rate as a reference line.
  - `psi-by-column` (`psi_by_column.png`) — mean PSI per column across runs, descending.
  - `top-drifted` (`top_drifted.png`) — top-15 columns by number of runs in which they drifted.
- **Selector:** `--chart all` (default) writes the full set into the output directory; `--chart drift-rate|psi-by-column|top-drifted` writes a single PNG.
- **No overwrite by default:** an existing PNG is refused unless you pass `--force`.
- **Path safety:** the output directory is validated (no `..` traversal, no symlink escape) and created if needed; chart file names are fixed constants.
- **Zero-state:** a missing or empty database still produces valid "No data available" PNGs.
- **Exit codes:** `0` written; `1` plot failure (missing `[viz]` dep, unsafe path, refused overwrite, write error); `2` argparse error.
- The `distribution` (reference-vs-current) chart is **deferred** to a later release.
- Available in the Python API as `export_drift_plots` (see [docs/api.md](docs/api.md)).

## Drift Webhook Notifications (v2.7.1)

Build (and optionally POST) a one-shot drift-threshold notification from a SQLite monitoring DB. **Dry-run by default** — the JSON payload is printed and nothing is sent. Standard-library only — no new dependency, no scheduler, no retries.

```bash
# Dry-run (default): print payload, send nothing
dqt drift-history notify --db monitoring.db --webhook-url https://hooks.example.com/dqt

# Actually POST (requires DQT_ALLOW_NETWORK=true)
DQT_ALLOW_NETWORK=true dqt drift-history notify --db monitoring.db \
    --webhook-url https://hooks.example.com/dqt --send --fail-on-drift-rate 0.20
```

- **Fail-safe:** a real POST needs `--send` **and** `DQT_ALLOW_NETWORK=true`; otherwise it stays a dry-run.
- **HTTPS-only by default** (`--allow-http` opt-in for trusted local endpoints).
- **SSRF guard:** the host is resolved and every resolved IP must be public — loopback, private, link-local, multicast, reserved, unspecified, and cloud-metadata addresses are rejected (`--allow-insecure-host` bypasses for local testing only).
- **Redacted logging:** only `scheme://host[:port]/path` is shown; userinfo, query, and fragment are stripped. ⚠️ **Do not put tokens in the URL query string.**
- Redirects refused, proxies disabled, mandatory `--timeout`, single attempt (no retries), 64 KB payload cap. The payload carries no secrets, env values, webhook URL, or full DB path.
- **Exit codes:** `0` no breach; `1` validation/send/security failure; `2` threshold breached (even on a successful dry-run/send) or argparse error.
- Available in the Python API as `send_drift_notification` (see [docs/api.md](docs/api.md)).

## Unified Monitoring (v2.6.0)

> Part of the **v2.6.0** Unified Monitoring Experience.

The same SQLite monitoring database now feeds two complementary presentation surfaces through a single shared, presentation-agnostic **monitoring view-model**:

- **Dashboard 2.0** — a *static, self-contained HTML artifact* (`dqt drift-history dashboard`). No web server, no JavaScript, no external assets. Ideal for CI artifacts, email, and archival.
- **Drift Monitoring** — the *Drift Monitoring* page of the optional, interactive local Streamlit dashboard (`dqt ui`) for browsing runs, per-column drift (PSI / Jensen-Shannon / Wasserstein), and distribution bins with live filters.

Both read the identical view-model values, so the static dashboard and the interactive UI never disagree on run counts, drift rates, or column metrics.

The Streamlit UI is **optional** and lives behind the `[ui]` extra. CLI-first automation (profiling, drift, history import, static dashboard) never requires Streamlit:

```bash
pip install "data-quality-toolkit[ui]"      # only needed for `dqt ui`
```

Example end-to-end monitoring workflow:

```bash
# 1. Detect drift and append a history record
dqt drift data/baseline.csv data/current.csv --output drift_report.json --history drift_history.jsonl

# 2. Promote the JSONL history into a SQLite monitoring DB
dqt drift-history import drift_history.jsonl --db monitoring.db

# 3. Render the static HTML dashboard artifact (no Streamlit required)
dqt drift-history dashboard --db monitoring.db --output dashboard.html --include-plots

# 4. (Optional) Explore interactively in the local Streamlit UI
dqt ui --db monitoring.db
```

**Mental model:** *Dashboard = static artifact you ship; UI = optional local app you click through.* DuckDB-backed monitoring remains deferred; the monitoring store is SQLite today.

## Capabilities

DQT is built around three flagship value pillars:

1. **Pipeline-grade quality gating** — `dqt assess --fail-under <score>` exits `2` to halt CI/ETL when a dataset falls below a quality threshold. The same gate is available as `assess_csv` in the Python API.
2. **Statistical drift monitoring and BI-ready exports** — detect distribution shift (KS + chi-square), persist drift history in an append-only JSONL → SQLite store, render static HTML dashboards and Markdown reports, and export to Excel, DuckDB, PNG charts, or a zero-config Power BI package — all without a server.
3. **Governed optional AI via default-off StoryLens** — an optional local-AI narrator that produces plain-language data summaries. Disabled by default; the deterministic fallback always applies; AI internals are kept out of the public API and CLI by a machine-checked import-linter contract.

### CLI / API / UI parity

| Capability | CLI | Public API | UI |
| --- | --- | --- | --- |
| Profile + assess | `dqt profile` / `dqt assess` | `profile_csv`, `assess_csv` | Data Overview, EDA Explorer, Statistics Lab, Quality Score |
| Statistics + A/B | `dqt stats profile/select-test/test/ab` | `stats_profile_csv`, `select_statistical_test`, `run_statistical_test`, `compare_ab` | Statistics Lab, including Distributions, Power & Sample Size, CSV downloads, and opt-in workspace saves |
| Drift detection + history | `dqt drift`, `dqt drift-history` | `detect_drift`, `read_drift_*_sqlite`, `summarize_drift_*` | Drift Monitoring, Quality History |
| BI export | `dqt build-pbi`, `dqt drift-history export-xlsx/export-duckdb/plot` | `build_powerbi_package`, `export_drift_history_xlsx`, `export_monitoring_duckdb`, `export_drift_plots` | Artifact Center, Export |
| KPI + time dimension | `dqt kpi-emit`, `dqt kpi-graph`, `dqt gen-dim-time` | `kpi_emit`, `kpi_graph`, `generate_dim_time` | KPI Catalog, Dim Time |

See [docs/capability_matrix.md](docs/capability_matrix.md) for the full capability matrix, intentional asymmetries, governance notes, and portfolio value summary.

### Streamlit UI product surface

The optional `[ui]` Streamlit app (`dqt ui` / `dqt dashboard`) presents a **16-page product journey** that walks one dataset from load to delivery:

1. **Start / Load Dataset** — select and validate a local CSV once; later pages reuse it.
2. **Data Overview** — shape, quality score, issue count, and column health.
3. **EDA Explorer** — charts and visual exploration, including missingness, configurable histograms, categorical top-N with optional missing bucket, correlation heatmap, bounded scatter sampling, numeric-by-category summaries, datetime trends, and outlier summaries.
4. **Statistics Lab** — profile, descriptive statistics, hypothesis-test selection, statistical test runner, numeric A/B comparison, theoretical Distributions, Power & Sample Size planning, and the existing scipy-guarded inferential tier: normality checks, Welch t-test and Mann-Whitney, ANOVA and Kruskal-Wallis. Result tables can be downloaded as CSV and, where offered, saved to Workspace. When scipy is unavailable the inferential tests degrade gracefully with cautious wording.
5. **Quality Score** — explains the score: completeness, capped rule penalties, exclusions, and a per-rule breakdown.
6. **Preprocess Studio** — a dependency-free, in-memory recipe workflow with before/after validation and JSON/CSV recipe export; source data is not mutated.
7. **Pipeline Runner** — a dry-run and evidence workflow with a CLI-equivalent preview; legacy write-capable execution stays behind explicit confirmation.
8. **Drift Monitoring** — read-only drift evidence from a local monitoring database.
9. **Export** — CLI/API guidance plus optional confirmed server-side star-schema export; the resulting `dqt.db` is the handoff to Quality History.
10. **Quality History** — quality-score trend, latest-run issues, and run comparison from an Export-created `dqt.db`.
11. **Artifact Center** — a standalone surface to review generated outputs and downloads (basenames only).
12. **KPI Catalog** — validate a KPI catalog YAML and download or save DAX, TMSL, and graph artifacts.
13. **Dim Time** — generate a time dimension table and download it as CSV.
14. **Manifest Viewer** — inspect lineage manifest summaries, datasets, artifacts, and gate failures with safe path display.
15. **Settings / Governance** — truthful runtime, capability, and threshold diagnostics.
16. **Help / About** — orientation and the deterministic-by-default posture.

The UI is deterministic by default; optional local AI stays off unless explicitly enabled, and CLI-first automation never requires Streamlit.

## Documentation

- [Capability Matrix](docs/capability_matrix.md)
- [UI/UX Redesign Plan](docs/uiux_redesign_plan.md)
- [StoryLens Governance](docs/storylens_governance.md)
- [Public Safety Boundary](docs/public_safety_boundary.md)
- [ADR 0001: System Fitness and Redesign Decision](docs/adr/0001-system-fitness-and-redesign-decision.md)
- [Product Brief](docs/product.md)
- [CLI Reference](docs/cli.md)
- [Python API](docs/api.md)
- [Architecture & Design](docs/architecture.md)
- [Demo Story](docs/demo_story.md)

---
**Version**: 2.10.0 · **Technical audit**: complete and accepted — PASS, no known current technical release blockers · **Release programme**: product, infrastructure, deployment, and operational readiness still in progress
