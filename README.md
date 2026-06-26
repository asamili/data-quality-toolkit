# Data Quality Toolkit (DQT)

[![Python](https://img.shields.io/badge/Python-3.12+-green)]()
[![License](https://img.shields.io/badge/License-Apache%202.0-blue)]()
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-blue)]()

**A CLI-first toolkit for CSV data quality: profile datasets, enforce quality gates, detect statistical drift, and export BI-ready artifacts.**

DQT runs from the command line with no service to stand up. Point it at a CSV and it profiles columns, scores quality, and fails your pipeline when data falls below threshold. It also detects statistical drift between datasets and turns drift history into SQLite-backed monitoring reports and dashboards.

## Install

```bash
git clone https://github.com/asamili/data-quality-toolkit
cd data-quality-toolkit
python -m venv .venv
.venv\Scripts\activate
pip install -e .

# Optional extras
pip install "data-quality-toolkit[stats]"   # drift detection (scipy)
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

## Drift History Analytics (v2.5.0)

> These commands ship in **v2.5.0**. The release is prepared in the private repository (version bumped, changelog promoted); it has not yet been tagged or public-synced.

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

> Prepared in the private repository as part of the **v2.6.0** Unified Monitoring Experience; not yet tagged or public-synced.

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
| Drift detection + history | `dqt drift`, `dqt drift-history` | `detect_drift`, `read_drift_*_sqlite`, `summarize_drift_*` | Drift Monitoring, Quality History |
| BI export | `dqt build-pbi`, `dqt drift-history export-xlsx/export-duckdb/plot` | `build_powerbi_package`, `export_drift_history_xlsx`, `export_monitoring_duckdb`, `export_drift_plots` | Artifact Center, Export |
| KPI + time dimension | `dqt kpi-emit`, `dqt kpi-graph`, `dqt gen-dim-time` | `kpi_emit`, `kpi_graph`, `generate_dim_time` | KPI Catalog, Dim Time |

See [docs/capability_matrix.md](docs/capability_matrix.md) for the full capability matrix, intentional asymmetries, governance notes, and portfolio value summary.

### Streamlit UI product surface

The optional `[ui]` Streamlit app (`dqt ui` / `dqt dashboard`) presents an **11-step product spine** that walks one dataset from load to delivery:

1. **Start / Load Dataset** — select and validate a local CSV once; later pages reuse it.
2. **Data Overview** — shape, quality score, issue count, and column health.
3. **EDA Explorer** — charts and visual exploration.
4. **Statistics Lab** — descriptive statistics plus a scipy-guarded inferential tier: normality checks, Welch t-test and Mann-Whitney, ANOVA and Kruskal-Wallis, and A/B comparison. When scipy is unavailable the inferential tests degrade gracefully with cautious wording.
5. **Quality Score** — explains the score: completeness, capped rule penalties, exclusions, and a per-rule breakdown.
6. **Preprocess Studio** — a dependency-free, in-memory recipe workflow with before/after validation and JSON/CSV recipe export; source data is not mutated.
7. **Pipeline Runner** — a dry-run and evidence workflow with a CLI-equivalent preview; legacy write-capable execution stays behind explicit confirmation.
8. **Drift Monitoring** — read-only drift evidence from a local monitoring database.
9. **Artifact Center** — a standalone surface to review generated outputs and downloads (basenames only).
10. **Settings / Governance** — truthful runtime, capability, and threshold diagnostics.
11. **Help / About** — orientation and the deterministic-by-default posture.

Utility pages (Quality History, Export, KPI Catalog, Dim Time, Manifest Viewer) remain available alongside the spine. The UI is deterministic by default; optional local AI stays off unless explicitly enabled, and CLI-first automation never requires Streamlit.

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
**Version**: v2.8.0 | **Status**: Active development
