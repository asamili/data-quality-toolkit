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

# Launch the interactive dashboard, pre-pointing the Drift Monitoring page at a monitoring DB (preferred)
dqt ui --db monitoring.db
```

`dqt ui` is the preferred launcher for the interactive **Streamlit dashboard**. `--db` is optional; when given it seeds `DQT_UI_DB` so the **Drift Monitoring** page opens pre-pointed at that monitoring database. The UI is optional — if Streamlit is not installed, the command exits `1` and prints an install hint: `pip install "data-quality-toolkit[ui]"`. CLI-first automation (profiling, drift, history import, static dashboard) never requires Streamlit.

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

## Drift History Analytics (v2.5.0)
Promote append-only drift history (written by `dqt drift --history drift_history.jsonl`) into a SQLite
monitoring database, then query, report, and visualize drift over time. These commands ship in v2.5.0
(prepared in the private repository; not yet tagged or public-synced).

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

- **Subcommands:** `read`, `import`, `list`, `trend`, `columns`, `report`, `dashboard`.
- **Dependency-free artifacts:** reports and dashboard use inline CSS only — no JavaScript, no CDN, no images, no matplotlib required.
- **Advanced per-column metrics:** PSI, Jensen-Shannon distance, Wasserstein distance.
- **SQLite-backed tables:** `drift_runs`, `drift_columns`, `drift_column_distributions`.
- **Opt-in flags:** `--include-columns` adds column-level metrics to the report; `--include-plots` adds dependency-free distribution plots to report and dashboard. Both default off.
- A missing or empty database produces valid output and exits `0`.

## Drift Threshold Gating (v2.6.1)

Opt-in flags on the existing `trend` and `columns` subcommands that exit `2` when a metric exceeds a threshold.

```bash
# Exit 2 if the historical drift rate exceeds 30 %
dqt drift-history trend --db monitoring.db --fail-on-drift-rate 0.30

# Combine with existing filters
dqt drift-history trend --db monitoring.db --current-dataset-id orders --limit 10 --fail-on-drift-rate 0.20

# Exit 2 if any column PSI exceeds 0.20
dqt drift-history columns --db monitoring.db --fail-on-psi 0.20

# Combine with run filter
dqt drift-history columns --db monitoring.db --run-id <run_id> --fail-on-psi 0.15
```

**Flags:**

| Subcommand | Flag | Type | Effect |
| --- | --- | --- | --- |
| `trend` | `--fail-on-drift-rate FLOAT` | 0.0–1.0 | Exit 2 if `drift_rate > FLOAT` |
| `columns` | `--fail-on-psi FLOAT` | 0.0–1.0 | Exit 2 if any column `psi > FLOAT` |

**Exit codes:**

| Code | Meaning |
| --- | --- |
| `0` | Within threshold, or flag absent |
| `1` | Invalid threshold value (out of 0.0–1.0) |
| `2` | Threshold breached |

**Behavior notes:**

- Breach is **strictly greater than** (`>`). Exactly equal to the threshold is not a breach.
- `None` PSI values (scipy unavailable or column skipped) are silently skipped.
- A missing or empty database produces zero drift rate / no columns → no breach → exits `0`.
- The breach message is printed to `stderr`; JSON output to `stdout` is unaffected by the flag.

## Excel Export (v2.6.1)

Export drift-history monitoring data from a SQLite monitoring DB to a local,
multi-sheet `.xlsx` workbook. Optional feature — install the `[powerbi]` extra
(`pip install data-quality-toolkit[powerbi]`).

```bash
# Minimal export (runs, trend_summary, columns, metadata sheets)
dqt drift-history export-xlsx --db monitoring.db --out drift_monitoring.xlsx

# Add the (potentially large) per-column distribution-bins sheet
dqt drift-history export-xlsx --db monitoring.db --out drift_monitoring.xlsx --include-distributions

# Narrow with the same filters as report/dashboard, omit the columns sheet, overwrite
dqt drift-history export-xlsx --db monitoring.db --out out.xlsx \
    --current-dataset-id orders --limit 10 --no-include-columns --force
```

**Sheets:** `runs`, `trend_summary`, `columns` (default on), `distributions`
(opt-in), `metadata` (provenance: tool version, UTC timestamp, db/output paths,
filters — no secrets).

**Flags:**

| Flag | Effect |
| --- | --- |
| `--db PATH` (required) | SQLite monitoring database |
| `--out PATH` (required) | Output workbook; must end in `.xlsx` |
| `--current-dataset-id VALUE` | Filter runs by `current_dataset_id` |
| `--limit N` | Cap number of runs |
| `--include-columns` / `--no-include-columns` | Per-column metrics sheet (default: on) |
| `--include-distributions` | Add distribution-bins sheet (default: off) |
| `--force` | Overwrite an existing output file |

**Exit codes:**

| Code | Meaning |
| --- | --- |
| `0` | Workbook written |
| `1` | Export failure: missing `[powerbi]` dep, invalid/unsafe output path, refused overwrite (no `--force`), or write error |
| `2` | Argparse error (missing `--db`/`--out`) |

**Behavior notes:**

- **Security:** every string cell (headers, data, metadata) is escaped against
  spreadsheet formula injection — values leading with `=`, `+`, `-`, `@` (or a
  leading tab/CR) are prefixed with a single quote. No formulas, macros, external
  links, or embedded objects are emitted.
- **No overwrite by default:** an existing output file is refused unless `--force`.
- A missing or empty database yields a valid zero-state workbook (exit `0`).
- Success summary goes to `stderr`; `stdout` stays clean.

## DuckDB Export/Mirror (v2.7.0)

One-shot mirror of the drift-history monitoring tables from a SQLite monitoring
DB into a standalone **DuckDB** database file. Optional feature — install the
`[duckdb]` extra (`pip install data-quality-toolkit[duckdb]`).

DuckDB is **export/mirror only** — never a live monitoring backend. The source
SQLite database is opened **read-only** and is never mutated; the monitoring
store stays SQLite. Only the drift-history tables `drift_runs`, `drift_columns`,
and `drift_column_distributions` are mirrored.

```bash
# Mirror to a new DuckDB file
dqt drift-history export-duckdb --db monitoring.db --out monitoring.duckdb

# Replace an existing output file
dqt drift-history export-duckdb --db monitoring.db --out monitoring.duckdb --overwrite
```

**Flags:**

| Flag | Effect |
| --- | --- |
| `--db PATH` (required) | Source SQLite monitoring database (read-only) |
| `--out PATH` (required) | Output DuckDB file; must end in `.duckdb` |
| `--overwrite` | Replace the output file if it already exists |

**Exit codes:**

| Code | Meaning |
| --- | --- |
| `0` | Mirror written |
| `1` | Export failure: missing `[duckdb]` dep, missing source DB, invalid/unsafe output path, refused overwrite (no `--overwrite`), or write error |
| `2` | Argparse error (missing `--db`/`--out`) |

**Behavior notes:**

- **Read-only source:** the SQLite DB is opened with the `mode=ro` URI flag — no
  schema changes, no writes, no WAL side files.
- **No overwrite by default:** an existing output file is refused unless `--overwrite`.
- Drift-history tables absent from the source are mirrored as empty tables (stable schema).
- Success summary goes to `stderr`; `stdout` stays clean.

## Drift Plots (v2.6.1)

Render drift-history monitoring data from a SQLite monitoring DB to local **PNG**
chart files. Optional feature — install the `[viz]` extra
(`pip install data-quality-toolkit[viz]`). Local-only: matplotlib runs on the
non-interactive `Agg` backend; no GUI, no network, no remote image fetching.

```bash
# Render all charts into a directory
dqt drift-history plot --db monitoring.db --out plots/ --chart all

# Render a single chart
dqt drift-history plot --db monitoring.db --out plots/ --chart psi-by-column

# Narrow runs, overwrite existing PNGs
dqt drift-history plot --db monitoring.db --out plots/ \
    --current-dataset-id orders --limit 10 --force
```

**Chart catalog:**

| `--chart` | File | Content |
| --- | --- | --- |
| `drift-rate` | `drift_rate.png` | Per-run drift fraction (`columns_drifted / columns_tested`) over time, with the overall drift rate as a reference line |
| `psi-by-column` | `psi_by_column.png` | Mean PSI per column across runs, descending (None PSI skipped) |
| `top-drifted` | `top_drifted.png` | Top-15 columns by number of runs in which they drifted |
| `all` (default) | all of the above | Writes the full set into `--out` |

The `distribution` (reference-vs-current) chart is **deferred** to a later release.

**Flags:**

| Flag | Effect |
| --- | --- |
| `--db PATH` (required) | SQLite monitoring database |
| `--out DIR` (required) | Output directory for PNG files (created if needed) |
| `--chart {drift-rate,psi-by-column,top-drifted,all}` | Which chart(s) to render (default: `all`) |
| `--current-dataset-id VALUE` | Filter runs by `current_dataset_id` |
| `--limit N` | Cap number of runs |
| `--force` | Overwrite existing PNG files |

**Exit codes:**

| Code | Meaning |
| --- | --- |
| `0` | PNG(s) written |
| `1` | Plot failure: missing `[viz]` dep, invalid/unsafe output path, refused overwrite (no `--force`), or write error |
| `2` | Argparse error (missing `--db`/`--out`, invalid `--chart`) |

**Behavior notes:**

- **Path safety:** the output directory is validated (no `..` traversal, no
  symlink escape) and created if needed; chart file names are fixed constants, so
  no user input flows into a written filename.
- **No overwrite by default:** an existing PNG is refused unless `--force`.
- A missing or empty database yields valid zero-state ("No data available") PNGs
  (exit `0`).
- Success summary goes to `stderr`; `stdout` stays clean.

## Drift Webhook Notifications (v2.7.0)

Build (and optionally POST) a one-shot drift-threshold notification from a SQLite
monitoring DB. **Dry-run by default** — the payload is printed to `stdout` and
nothing is sent. Standard-library only; no new dependency, no scheduler, no retries.

```bash
# Dry-run (default): print the JSON payload, send nothing
dqt drift-history notify --db monitoring.db --webhook-url https://hooks.example.com/dqt

# Flag a breach in the payload, still dry-run
dqt drift-history notify --db monitoring.db --webhook-url https://hooks.example.com/dqt \
    --fail-on-drift-rate 0.20 --fail-on-psi 0.20

# Actually POST (requires DQT_ALLOW_NETWORK=true)
DQT_ALLOW_NETWORK=true dqt drift-history notify --db monitoring.db \
    --webhook-url https://hooks.example.com/dqt --send --timeout 10
```

**Flags:**

| Flag | Effect |
| --- | --- |
| `--db PATH` (required) | SQLite monitoring database |
| `--webhook-url URL` (required) | Destination URL (https only by default) |
| `--fail-on-drift-rate FLOAT` | Mark breach (exit 2) if `drift_rate > FLOAT` (0.0–1.0) |
| `--fail-on-psi FLOAT` | Mark breach (exit 2) if any column `psi > FLOAT` (0.0–1.0) |
| `--dry-run` | Build/print payload only (default; mutually exclusive with `--send`) |
| `--send` | Actually POST (also needs `DQT_ALLOW_NETWORK=true`) |
| `--timeout SECONDS` | Connect/read timeout for a real send (default 10.0) |
| `--allow-http` | Permit a plain-http URL (unsafe; https is the default) |
| `--allow-insecure-host` | Skip the SSRF host check (unsafe; local testing only) |

**Exit codes:**

| Code | Meaning |
| --- | --- |
| `0` | Payload built/sent, no breach |
| `1` | Validation, send, or security failure (incl. `--send` without `DQT_ALLOW_NETWORK=true`) |
| `2` | Threshold breached (even when the dry-run/send itself succeeded), or argparse error |

**Security & behavior notes:**

- **HTTPS-only by default.** `--allow-http` is an explicit opt-in for trusted local endpoints.
- **SSRF guard:** the host is resolved and **every** resolved IP must be public —
  loopback, private, link-local, multicast, reserved, unspecified, and cloud-metadata
  addresses (`169.254.169.254`, `fd00:ec2::254`) are rejected. `--allow-insecure-host`
  bypasses this for local testing only and is unsafe.
- **Redirects are refused** and proxy environment variables are disabled (no SSRF bypass).
- **Redacted logging:** `stderr`/error messages show only `scheme://host[:port]/path`;
  userinfo, query string, and fragment are stripped. ⚠️ **Do not put tokens or secrets in
  the webhook URL query string** — prefer a path-embedded secret on a trusted endpoint.
- The payload carries no secrets, no environment values, no webhook URL, and no full
  local DB path. Single attempt, no retries; payload capped at 64 KB.
- A missing or empty database yields a valid zero-state payload (no breach → exit `0`).

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

## Internal Structure (maintainers)

Public command names, flags, and behavior described above are stable. Internally
the CLI is modularized: per-command handlers live under `adapters/cli/commands/`,
shared parser/launcher helpers under `adapters/cli/utils/`, and
`adapters/cli/main.py` remains the public entrypoint. `dqt dashboard` and
`dqt ui` share one Streamlit launcher. This is an internal refactor only — no
public command behavior changed.
