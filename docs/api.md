# Python API

Install once (`pip install -e .`), then import directly — no CLI required.

```python
from data_quality_toolkit import (
    profile_csv, assess_csv, export_csv, compare_runs, plan_csv,
    kpi_validate, kpi_emit, kpi_graph, generate_dim_time,
    create_manifest, create_elt_pipeline,
)

# Profile: returns shape and per-column stats. No disk writes.
result = profile_csv("data/orders.csv")
print(result["profile"]["rows"], result["profile"]["cols"])

# Assess: profile + quality score + detected issues. No disk writes.
result = assess_csv("data/orders.csv")
print(result["assessment"]["score"])          # e.g. 0.87
print(result["assessment"]["quality_score"])  # penalty-weighted score
for issue in result["assessment"]["issues"]:
    print(issue["type"], issue["column"], issue["severity"])

# Assess with quality gate — raise your own exception on failure:
result = assess_csv("data/orders.csv")
if result["assessment"]["quality_score"] < 0.9:
    raise ValueError("Quality gate failed")

# Export: full pipeline — profile → assess → star-schema CSVs + quality_report.json + SQLite history.
result = export_csv("data/orders.csv", output_dir="dist/")
print(result["export_paths"])

# Compare: trend analysis from the last two export runs.
result = compare_runs("data/orders.csv", output_dir="dist/")
print(result["score_delta"])

# Plan: per-column preprocessing recommendations (impute/scale/encode/drop). No disk writes.
result = plan_csv("data/orders.csv")
for col in result["columns"]:
    print(col["column"], col["issues"], col["recommendations"])

# KPI catalog validation (schema, semantics, cycles). No disk writes.
result = kpi_validate("config/kpi_catalog.yaml")
print(result["status"], result["kpis"])       # "valid", 8

# KPI emit: generate DAX measures + TMSL model JSON from catalog.
result = kpi_emit(
    "config/kpi_catalog.yaml",
    dax_out="dist/powerbi_package/dax/quality_measures.dax",
    tmsl_out="dist/powerbi_package/dax/model.tmsl.json",
)
print(result["dax"], result["tmsl"])

# KPI graph: export dependency graph as Mermaid (.mmd) or Graphviz (.dot).
result = kpi_graph("config/kpi_catalog.yaml", out="dist/semantics/kpi_graph", graph_format="mermaid")
print(result["graph"])                        # path to written .mmd file

# Time dimension: generate dim_time.csv (optional output_dir writes to disk).
result = generate_dim_time("2018-01-01", "2030-12-31", output_dir="dist/time")
print(result["rows"], result["path"])

# Power BI package: build the package from a star-schema directory. Writes files.
result = build_powerbi_package("dist/star", "dist/powerbi_package")
print(result["package_dir"], result["files"])

# Manifest: build a lineage manifest (artifacts, gates, sessions) for a specific run.
manifest = create_manifest(run_id="20240101-123456", sessions_root="dist/sessions/")
print(manifest["run_id"], len(manifest["artifacts"]))

# ELT Pipeline: create an orchestration object for complex extract/transform/load workflows.
pipeline = create_elt_pipeline(run_id="manual-run-001", sessions_root="dist/sessions/")
pipeline.extract("data/raw.csv")
pipeline.load("data/silver.csv")
pipeline.assess()
result = pipeline.run()
print(result.status)
```

Optional CSV-parsing kwargs (`sep`, `encoding`, `na_values`, `sample_size`) are accepted by all CSV functions.

> **Note:** `dqt.yaml` is not loaded by the Python API — pass options explicitly as keyword arguments.

## Shared Monitoring View-Model (v2.6.0)

`data_quality_toolkit.application.monitoring.view_model` is the single, presentation-agnostic source of truth for the *shape* of drift-monitoring data handed to presentation layers (the static HTML Dashboard 2.0 and the optional Streamlit Drift Explorer). It performs no rendering and owns no storage: it reaches the SQLite monitoring database **only** through the root `data_quality_toolkit.api` query seam (`summarize_drift_trends_sqlite`, `read_drift_runs_sqlite`, `read_drift_columns_sqlite`, `read_drift_distributions_sqlite`) and normalizes their JSON-ready dicts into frozen, typed value objects. It imports nothing from Streamlit and nothing from the storage adapters directly.

**Value objects** (all frozen dataclasses with a `to_dict()` for JSON/CLI parity):

- `TrendSummary` — aggregate trend (`total_runs`, `drifted_runs`, `drift_rate`, latest-run fields, columns tested/drifted totals and averages).
- `RunRow` — one run-level row (`run_id`, `created_at`, `current_dataset_id`, `status`, `drift_detected`, `columns_tested/drifted/skipped`).
- `ColumnDrift` — one per-column result (`column_name`, `kind`, `test`, `drift_detected`, `psi`, `js_distance`, `wasserstein`, …).
- `DistributionBin` — one distribution bin (`bin_index`, `bin_label`, `reference_prob`, `current_prob`).
- `RunDetail` — a run plus its `columns` and `distributions`.
- `MonitoringOverview` — `summary` (a `TrendSummary`) plus the recent `runs`.

**Builders:**

```python
from data_quality_toolkit.application.monitoring.view_model import (
    build_monitoring_overview, list_run_rows, build_column_drift,
    build_distribution_series, build_run_detail,
)

overview = build_monitoring_overview("monitoring.db", current_dataset_id="cd1", limit=20)
print(overview.summary.total_runs, len(overview.runs))

detail = build_run_detail("monitoring.db", "run-123")
print(len(detail.columns), len(detail.distributions))
```

Normalization happens once here: integer `drift_detected` flags become `bool` (`None` preserved), missing numerics stay `None`, and a missing or empty database yields a zeroed summary and empty lists rather than raising. The builders are consumed by both presentation surfaces, so the static dashboard and the Streamlit UI always agree on the same derived values.

## Drift Threshold Evaluators (v2.6.1)

Pure evaluation functions — no I/O, no network, no new dependencies. Both accept already-fetched API dicts and return JSON-ready plain dicts.

### `evaluate_drift_rate_threshold`

```python
from data_quality_toolkit.api import evaluate_drift_rate_threshold, summarize_drift_trends_sqlite

summary = summarize_drift_trends_sqlite("monitoring.db")
result = evaluate_drift_rate_threshold(summary, max_drift_rate=0.30)
# {"breached": True, "drift_rate": 0.4, "threshold": 0.3}
```

**Return shape:**

```python
{
    "breached": bool,      # True only when drift_rate > max_drift_rate (strictly greater)
    "drift_rate": float,   # Value read from summary; missing/None treated as 0.0
    "threshold": float,    # The max_drift_rate argument
}
```

### `evaluate_psi_threshold`

```python
from data_quality_toolkit.api import evaluate_psi_threshold, read_drift_columns_sqlite

columns = read_drift_columns_sqlite("monitoring.db")
result = evaluate_psi_threshold(columns, max_psi=0.20)
# {"breached": True, "threshold": 0.2, "offenders": [{"column_name": "amount", "psi": 0.27}]}
```

**Return shape:**

```python
{
    "breached": bool,        # True only when any psi > max_psi (strictly greater)
    "threshold": float,      # The max_psi argument
    "offenders": [           # Columns whose psi breached the threshold (input order)
        {"column_name": str, "psi": float},
        ...
    ],
}
```

**Notes:**
- `None` PSI values (scipy unavailable or column skipped) are silently skipped.
- An empty column list or all-`None` PSI values → `breached=False`, `offenders=[]`.
- A missing or empty database → `read_drift_columns_sqlite` returns `[]` → no breach.

## Excel Export (v2.6.1)

Export drift-history monitoring data to a local multi-sheet `.xlsx` workbook.
Requires the optional `[powerbi]` extra (openpyxl) — `pip install
data-quality-toolkit[powerbi]`.

### `export_drift_history_xlsx`

```python
from data_quality_toolkit import export_drift_history_xlsx

result = export_drift_history_xlsx(
    "monitoring.db",
    "drift_monitoring.xlsx",
    current_dataset_id=None,     # optional run filter
    limit=None,                  # optional cap on runs
    include_columns=True,        # per-column metrics sheet (default on)
    include_distributions=False, # distribution-bins sheet (default off; can be large)
    force=False,                 # refuse to overwrite an existing file unless True
)
# {"output_path": ".../drift_monitoring.xlsx",
#  "sheets": ["runs", "trend_summary", "columns", "metadata"],
#  "row_counts": {"runs": 2, "trend_summary": 11, "columns": 4, "metadata": 8}}
```

**Workbook sheets:** `runs`, `trend_summary` (key/value), `columns` (when
`include_columns`), `distributions` (when `include_distributions`), `metadata`
(tool version, UTC timestamp, db/output paths, filters — no secrets). Sheet data
is sourced via the existing `read_drift_runs_sqlite`,
`summarize_drift_trends_sqlite`, `read_drift_columns_sqlite`, and
`read_drift_distributions_sqlite` seams (no schema changes).

**Return shape:**

```python
{
    "output_path": str,           # resolved absolute path written
    "sheets": list[str],          # sheet names in workbook order
    "row_counts": dict[str, int], # data-row count per sheet (excludes header)
}
```

**Behavior & safety:**

- Raises `XlsxExportError` (a `DQTError`) with a `pip install
  data-quality-toolkit[powerbi]` hint when openpyxl is not installed.
- Enforces the `.xlsx` extension, rejects empty paths and `..`/symlink-escape
  (reuses `path_guard`), and refuses to overwrite an existing file unless
  `force=True`.
- Every string cell — headers, data, and metadata — is escaped against
  spreadsheet formula injection (leading `=`, `+`, `-`, `@`, or tab/CR → quoted).
- A missing or empty database yields a valid zero-state workbook rather than
  raising.

## DuckDB Export/Mirror (v2.7.0)

Mirror the drift-history monitoring tables from a SQLite monitoring DB into a
standalone DuckDB database file. Requires the optional `[duckdb]` extra —
`pip install data-quality-toolkit[duckdb]`. DuckDB is **export/mirror only**, not
a live monitoring backend; the source SQLite DB is opened **read-only** and never
mutated.

### `export_monitoring_duckdb`

```python
from data_quality_toolkit import export_monitoring_duckdb

result = export_monitoring_duckdb(
    "monitoring.db",
    "monitoring.duckdb",
    overwrite=False,   # refuse to overwrite an existing output unless True
)
# {"input_db_path": "monitoring.db",
#  "output_path": ".../monitoring.duckdb",
#  "tables": ["drift_runs", "drift_columns", "drift_column_distributions"],
#  "row_counts": {"drift_runs": 2, "drift_columns": 6, "drift_column_distributions": 24},
#  "overwritten": False}
```

**Mirrored tables:** `drift_runs`, `drift_columns`, `drift_column_distributions`
(stable schema). Tables absent from the source are mirrored as empty tables.

**Return shape:**

```python
{
    "input_db_path": str,         # source SQLite path (as supplied)
    "output_path": str,           # resolved absolute DuckDB path written
    "tables": list[str],          # mirrored table names
    "row_counts": dict[str, int], # row count per mirrored table
    "overwritten": bool,          # whether an existing output was replaced
}
```

**Behavior & safety:**

- Raises `DuckdbExportError` (a `DQTError`) with a `pip install
  data-quality-toolkit[duckdb]` hint when duckdb is not installed.
- Opens the source SQLite DB **read-only** (`mode=ro` URI) — no schema changes,
  no writes, no migrate, no network, no `.env` reads.
- Enforces the `.duckdb` extension, rejects empty paths and `..`/symlink-escape
  (reuses `path_guard`), and refuses to overwrite an existing file unless
  `overwrite=True` (which recreates the output deterministically).
- A missing source database raises rather than producing an empty mirror.

## Drift Plots (v2.6.1)

Render drift-history monitoring data to local PNG chart files. Requires the
optional `[viz]` extra (matplotlib) — `pip install data-quality-toolkit[viz]`.

### `export_drift_plots`

```python
from data_quality_toolkit import export_drift_plots

result = export_drift_plots(
    "monitoring.db",
    "plots/",                  # output directory (created if needed)
    chart="all",               # "all" | "drift-rate" | "psi-by-column" | "top-drifted"
    current_dataset_id=None,   # optional run filter
    limit=None,                # optional cap on runs
    force=False,               # refuse to overwrite existing PNGs unless True
)
# {"output_dir": ".../plots",
#  "charts": {"drift-rate": ".../plots/drift_rate.png",
#             "psi-by-column": ".../plots/psi_by_column.png",
#             "top-drifted": ".../plots/top_drifted.png"},
#  "row_counts": {"drift-rate": 2, "psi-by-column": 4, "top-drifted": 1}}
```

**Charts:** `drift-rate` (per-run drift fraction over time), `psi-by-column`
(mean PSI per column, descending), `top-drifted` (top-15 columns by drift count).
Chart data is sourced via the existing `read_drift_runs_sqlite`,
`summarize_drift_trends_sqlite`, and `read_drift_columns_sqlite` seams (no schema
changes); only the seams a requested chart needs are queried. The `distribution`
chart is **deferred** to a later release.

**Return shape:**

```python
{
    "output_dir": str,            # resolved output directory
    "charts": dict[str, str],     # chart name -> written PNG path
    "row_counts": dict[str, int], # data-point count per rendered chart
}
```

**Behavior & safety:**

- Raises `PlotExportError` (a `DQTError`) with a `pip install
  data-quality-toolkit[viz]` hint when matplotlib is not installed.
- Matplotlib is imported lazily and forced onto the non-interactive `Agg`
  backend before `pyplot` is imported — no GUI/display backend is required.
- The output directory is validated against `..`/symlink-escape (reuses
  `path_guard`) and created if needed; an existing PNG is not overwritten unless
  `force=True`.
- A missing or empty database yields valid zero-state ("No data available") PNGs
  rather than raising.
- Local file writes only — no network, no cloud, no remote image fetching.

## Drift Webhook Notifications (v2.7.0)

Build (and optionally POST) a one-shot drift-threshold notification. Standard-library
only — no new dependency, no scheduler, no retries.

### `send_drift_notification`

```python
from data_quality_toolkit import send_drift_notification

result = send_drift_notification(
    "monitoring.db",
    "https://hooks.example.com/dqt",
    max_drift_rate=0.20,        # optional: set to evaluate a drift-rate breach
    max_psi=0.20,               # optional: set to evaluate a per-column PSI breach
    dry_run=True,               # default: build payload, send nothing
    send=False,                 # set True (with dry_run=False) to actually POST
    timeout=10.0,               # connect/read timeout for a real send
    allow_http=False,           # permit a plain-http URL (unsafe)
    allow_insecure_host=False,  # skip the SSRF host check (unsafe; local testing)
)
# {"payload": {...}, "sent": False, "status": None,
#  "breached": True, "redacted_url": "https://hooks.example.com/dqt"}
```

Reads a drift trend summary (and per-column PSI when `max_psi` is set) via the
existing `summarize_drift_trends_sqlite` / `read_drift_columns_sqlite` /
`evaluate_drift_rate_threshold` / `evaluate_psi_threshold` seams (no schema
changes) and builds the payload with the pure
`application.monitoring.notifications.build_drift_notification_payload`.

**Payload shape (minimal):**

```python
{
    "tool": "data-quality-toolkit",
    "version": "<package version>",
    "event": "drift_threshold_check",
    "generated_at": "<UTC ISO8601>",
    "status": "ok" | "breach",
    "breached": bool,
    "drift_summary": {"total_runs", "drifted_runs", "drift_rate",
                      "latest_run_id", "latest_created_at"},
    "thresholds": {"max_drift_rate", "max_psi"},
    "columns_breached": [{"column_name", "psi"}],  # capped at 50
}
```

No secrets, environment values, webhook URL, or full local DB path appear in the payload.

**Return shape:**

```python
{
    "payload": dict,          # the JSON-ready payload above
    "sent": bool,             # True only on a real POST
    "status": int | None,     # HTTP status when sent, else None
    "breached": bool,         # any requested threshold breached
    "redacted_url": str,      # scheme://host[:port]/path (no userinfo/query/fragment)
}
```

**Behavior & safety:**

- **Fail-safe default.** A real POST happens only when `send=True` **and**
  `dry_run=False` **and** `DQT_ALLOW_NETWORK=true`; otherwise it is a dry-run.
  Sending with the network gate off raises `NotificationError`.
- **HTTPS-only by default** (`allow_http=True` to permit http on trusted endpoints).
- **SSRF guard:** the host is resolved and every resolved IP must be public;
  loopback/private/link-local/multicast/reserved/unspecified and cloud-metadata
  addresses are rejected (raises `WebhookSecurityError`). `allow_insecure_host=True`
  bypasses this for local testing only.
- Redirects refused; proxies disabled; single attempt, no retries; mandatory timeout;
  64 KB payload cap. Non-2xx, timeout, or transport errors raise `NotificationError`
  with a redacted message.
- `NotificationError` and `WebhookSecurityError` are part of the `DQTError` family.

## Public API Boundary and Typed Result Contracts

### Canonical API seam

`data_quality_toolkit.api` is the canonical programmatic surface. The root
`data_quality_toolkit` package re-exports all supported public symbols for
convenience — consumers may import from either path.

Internal modules (adapters, application layer, storage) are implementation
details and are not part of the public API unless their symbols are explicitly
re-exported through `data_quality_toolkit.api`.

### Stable TypedDict contracts

Return shapes for stable API functions are documented through `TypedDict`
classes in `data_quality_toolkit.shared.result_types`, all of which are
re-exported from `data_quality_toolkit.api` and the root package. These
contracts are plain dicts at runtime — no runtime enforcement overhead, fully
backward-compatible.

| Contract | Function |
| --- | --- |
| `DriftRateThresholdResult` | `evaluate_drift_rate_threshold` |
| `PsiThresholdResult` | `evaluate_psi_threshold` |
| `PsiOffender` | nested in `PsiThresholdResult.offenders` |
| `PlanCsvResult` | `plan_csv` |
| `ColumnPlan` | nested in `PlanCsvResult.columns` |
| `DimTimeResult` | `generate_dim_time` |
| `KpiEmitResult` | `kpi_emit` |
| `KpiGraphResult` | `kpi_graph` |
| `SummarizeDriftTrendsResult` | `summarize_drift_trends_sqlite` |
| `DriftHistoryXlsxExportResult` | `export_drift_history_xlsx` |
| `MonitoringDuckdbExportResult` | `export_monitoring_duckdb` |
| `DriftPlotsExportResult` | `export_drift_plots` |
| `DriftNotificationSendResult` | `send_drift_notification` |
| `PowerBIPackageResult` | `build_powerbi_package` |

### Drift-history row contracts

`DriftRunRow`, `DriftColumnRow`, and `DriftDistributionRow` describe the key
sets returned by the SQLite drift-history read helpers:

| Contract | Function | Table |
| --- | --- | --- |
| `DriftRunRow` | `read_drift_runs_sqlite` | `drift_runs` |
| `DriftColumnRow` | `read_drift_columns_sqlite` | `drift_columns` |
| `DriftDistributionRow` | `read_drift_distributions_sqlite` | `drift_column_distributions` |

All keys in each row are always present. `drift_detected` is `int | None` at
the DB row contract level — the database stores 0/1 integers. View-model layers
(e.g. `RunRow`, `ColumnDrift`) normalize this to `bool` for presentation; the
DB row contracts preserve the storage shape.

`read_drift_runs_sqlite`, `read_drift_columns_sqlite`, and
`read_drift_distributions_sqlite` currently keep wide runtime return annotations
(`list[dict[str, Any]]`). The row TypedDicts are consumer-facing shape
references — they do not change runtime behavior.

```python
from data_quality_toolkit import DriftRunRow, DriftColumnRow, DriftDistributionRow
from data_quality_toolkit import read_drift_runs_sqlite

rows = read_drift_runs_sqlite("monitoring.db")  # list[dict[str, Any]] at runtime
for row in rows:
    # Keys match DriftRunRow; drift_detected is int | None, not bool
    print(row["run_id"], row["drift_detected"])
```
