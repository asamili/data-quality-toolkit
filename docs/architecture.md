# Architecture & Design

```
data-quality-toolkit/
├── src/data_quality_toolkit/
│   ├── domain/                # Business rules: profiling, assessment, semantics/KPI, statistics/drift
│   ├── application/
│   │   ├── workflow/          # Orchestration: pipeline, compare, preprocessing, kpi, elt
│   │   ├── monitoring/        # Drift view-model, threshold evaluators, notifications (pure)
│   │   └── ports.py           # Port seam (Option B layering)
│   ├── adapters/
│   │   ├── cli/               # Command-line interface (dqt entrypoint)
│   │   ├── ui/                # Streamlit dashboard UI — 11-step product spine (optional [ui] extra)
│   │   ├── loaders/           # CSV loading and validation
│   │   ├── exporters/         # Star-schema CSV, Power BI, dim_time, xlsx/duckdb/plots
│   │   ├── reports/           # Static drift dashboard + drift-history report
│   │   ├── storage/           # SQLite-backed run / drift history
│   │   └── notifications/     # Outbound webhook transport (SSRF-guarded)
│   ├── lineage/               # Export lineage manifests (top-level; see MODULES.md caveat)
│   ├── api.py                 # Public Python API
│   ├── shared/                # Cross-cutting kernel: models, settings, config, exceptions, guards
│   └── utils/                 # Helpers, logging, validators
├── tests/                     # Test suites (unit/, integration/, fixtures/, golden/)
├── docs/                      # Documentation
├── examples/                  # Demo packages
└── scripts/                   # Automation scripts
```

> Module-by-module detail lives in `MODULES.md` (the primary architecture map).
> `lineage/` currently sits outside the `domain/application/adapters` import-linter
> contracts — a known boundary review item deferred to gate DQT-ARCH-G5.

## CLI Structure

The `dqt` command-line interface is a small package so the public surface stays
stable while command code is modular:

- `adapters/cli/main.py` remains the public CLI entrypoint (`main`, `build_parser`); command names, flags, and behavior are unchanged.
- `adapters/cli/commands/` owns the per-command handlers and their parser registration (one module per command group, e.g. `profile`, `drift`, `drift_history`, `dashboard`, `ui`).
- `adapters/cli/utils/` owns shared parser pieces (`parser.py`) and the Streamlit launcher (`streamlit_launcher.py`).
- `dqt dashboard` and `dqt ui` share a single Streamlit launcher (`launch_streamlit_app`). The launcher keeps `import streamlit` behind a runtime guard, so importing the CLI never requires Streamlit.

## Unified Monitoring (v2.6.0)

Drift monitoring follows a single, layered data flow shared by every presentation surface:

```
SQLite monitoring DB
   → API / query seam (data_quality_toolkit.api: summarize/read drift *_sqlite)
      → shared monitoring view-model (application/monitoring/view_model.py)
         ├── static HTML Dashboard 2.0   (adapters/reports/drift_dashboard.py)
         └── Streamlit Drift Monitoring page  (adapters/ui/pages/drift_explorer.py
                                                via adapters/ui/services/monitoring.py)
```

- The **view-model** is presentation-agnostic, imports no Streamlit, and never touches storage adapters directly — it reads only through the public `api` seam. Both downstream surfaces consume the same `MonitoringOverview`/`RunDetail` values, so they cannot disagree.
- The **Dashboard** is a static, self-contained HTML artifact (no server, no JavaScript). The **UI** (`dqt ui`) is an optional local Streamlit app behind the `[ui]` extra; base, view-model, static-dashboard, and CLI imports never require Streamlit.
- **DuckDB-backed monitoring remains deferred.** The monitoring store is SQLite today. A read-only DuckDB *export/mirror* exists (`dqt drift-history export-duckdb`, v2.7.0) but is never a live backend — see "DuckDB Export/Mirror (v2.7.0)" below.

## Drift Threshold Evaluators (v2.6.1)

Pure evaluator functions in `application/monitoring/thresholds.py` sit alongside the view-model as a read-only analysis layer:

```
SQLite monitoring DB
   → API / query seam (summarize_drift_trends_sqlite, read_drift_columns_sqlite)
      → pure threshold evaluators (application/monitoring/thresholds.py)
         evaluate_drift_rate_threshold(summary, max_drift_rate=…)  → JSON-ready dict
         evaluate_psi_threshold(columns, max_psi=…)                → JSON-ready dict
      → CLI handlers (adapters/cli/commands/drift_history.py)
         set exit code 2 on breach, 0 otherwise
```

- **No I/O, no network, no DB writeback, no new dependencies.** The evaluators are pure functions over already-fetched API dicts.
- **No schema change.** Threshold evaluation is a post-query memory operation only.
- **Exit codes set in CLI layer only**, following the existing `--fail-on-drift` precedent.
- Re-exported via `data_quality_toolkit.api` so programmers can call evaluators directly without touching the CLI.

## Excel Export (v2.6.1)

The `.xlsx` exporter is an output adapter that reuses the existing monitoring read seams; it adds no new query or storage code and changes no schema:

```
SQLite monitoring DB
   → API / query seam (read_drift_runs_sqlite, summarize_drift_trends_sqlite,
                        read_drift_columns_sqlite, read_drift_distributions_sqlite)
      → api.export_drift_history_xlsx  (lazy seam, re-exported at package root)
         → adapters/exporters/bi/xlsx_drift_exporter.py
              build_workbook_model(...)   pure, openpyxl-free (sheets/headers/rows + formula-injection escaping)
              export_drift_history_xlsx() path-guard + openpyxl write-only writer
                 ↑ requires the optional [powerbi] extra (openpyxl)
      → CLI handler (adapters/cli/commands/drift_history.py: export-xlsx)
```

- **Optional-dependency boundary:** openpyxl is imported lazily inside the exporter; absence raises `XlsxExportError` with a `[powerbi]` install hint. The base CLI/API stay import-light.
- **Pure/impure split:** `build_workbook_model` (escaping, sheet selection, headers, row counts) is pure and unit-tested without openpyxl; only the thin writer needs the extra.
- **Security at the boundary:** formula-injection escaping on every string cell; `.xlsx`-extension + `path_guard` output validation; no-overwrite unless `force`. No formulas, macros, external links, or embedded objects are emitted.
- **No schema change, no network/cloud, no `.pbix`.** Local file output only.

## Drift Plots (v2.6.1)

The PNG plot exporter follows the same output-adapter shape as the `.xlsx`
exporter: an API seam → a pure model builder → a lazy matplotlib renderer. It adds
no query or storage code and changes no schema:

```
SQLite monitoring DB
   → API / query seam (read_drift_runs_sqlite, summarize_drift_trends_sqlite,
                        read_drift_columns_sqlite)   ← only the seams a chart needs
      → api.export_drift_plots  (lazy seam, re-exported at package root)
         → adapters/exporters/viz/drift_plots.py
              build_plot_model(...)    pure, matplotlib-free (per-chart series/labels/title)
              export_drift_plots()     path-guard + lazy Agg matplotlib renderer (one PNG per chart)
                 ↑ requires the optional [viz] extra (matplotlib)
      → CLI handler (adapters/cli/commands/drift_history.py: plot)
```

- **Optional-dependency boundary:** matplotlib is imported lazily inside the
  exporter and forced onto the non-interactive `Agg` backend *before* `pyplot` is
  imported; absence raises `PlotExportError` with a `[viz]` install hint. The base
  CLI/API stay import-light (matplotlib is never imported on the base path).
- **Pure/impure split:** `build_plot_model` (drift-fraction series, mean-PSI
  aggregation, drift-count ranking) is pure and unit-tested without matplotlib;
  only the thin renderer needs the extra.
- **Security at the boundary:** `path_guard` output-directory validation (no
  `..`/symlink-escape), fixed chart file names (no user input in a filename),
  no-overwrite unless `force`. Figures are closed after each save to bound memory.
- **No schema change, no network/cloud, no GUI backend, no remote image fetching.**
  Local PNG output only. The `distribution` chart is deferred to a later release.

## DuckDB Export/Mirror (v2.7.0)

The DuckDB exporter is a one-shot output adapter that mirrors the drift-history
monitoring tables into a standalone DuckDB file. **DuckDB is export/mirror only —
it is not a live monitoring backend; the monitoring store remains SQLite.** Unlike
the other exporters, it reads the source **directly and read-only** (not via the
mutating `ensure_db` seams) so the SQLite database is provably never changed:

```
SQLite monitoring DB (opened read-only: file:...?mode=ro)
   → api.export_monitoring_duckdb  (lazy seam, re-exported at package root)
      → adapters/exporters/bi/duckdb_exporter.py
           _TABLE_COLUMNS            stable schema for drift_runs / drift_columns /
                                     drift_column_distributions (column order + DuckDB types)
           export_monitoring_duckdb() path-guard + read-only SQLite copy → DuckDB writer
              ↑ requires the optional [duckdb] extra (duckdb)
   → CLI handler (adapters/cli/commands/drift_history.py: export-duckdb)
```

- **Export/mirror only, not a backend:** runtime monitoring writes never touch
  DuckDB; this is an explicit, manual, one-shot export. DuckDB-backed *monitoring*
  remains deferred.
- **Read-only source:** the SQLite DB is opened with `mode=ro`; only `SELECT`/`PRAGMA`
  run against it. No schema changes, no writes, no WAL side files, no migrate command.
- **Optional-dependency boundary:** duckdb is imported lazily inside the exporter;
  absence raises `DuckdbExportError` with a `[duckdb]` install hint. The base CLI/API
  stay import-light (duckdb is never imported on the base path).
- **Security at the boundary:** `.duckdb`-extension + `path_guard` output validation
  (no `..`/symlink-escape), no-overwrite unless `--overwrite` (deterministic recreate).
- **No backend replacement, no storage-port refactor, no network, no `.env` reads.**

## Drift Webhook Notifications (v2.7.0)

The notifier reuses the output-adapter shape — an API seam → a pure payload builder
→ a thin transport — and adds the project's first **outbound network** boundary. It
adds no query or storage code and changes no schema:

```
SQLite monitoring DB
   → API / query seam (summarize_drift_trends_sqlite, read_drift_columns_sqlite,
                        evaluate_drift_rate_threshold, evaluate_psi_threshold)
      → api.send_drift_notification  (lazy seam, re-exported at package root)
         → application/monitoring/notifications.py
              build_drift_notification_payload(...)   pure, no I/O, no network
         → adapters/notifications/webhook.py
              validate_webhook_url(...)   SSRF guard (every resolved IP must be public)
              redact_url(...)             strips userinfo/query/fragment for logs
              post_json(...)              single-attempt stdlib urllib POST, no redirects
      → CLI handler (adapters/cli/commands/drift_history.py: notify)
```

- **Pure/impure split:** the payload builder is pure and unit-tested with no network;
  only the thin transport touches `urllib`. Both DNS resolution and the URL opener are
  injectable so tests never hit the network.
- **Network gate:** a real POST requires `--send` (CLI) / `send=True, dry_run=False`
  (API) **and** the existing `DQT_ALLOW_NETWORK` setting; the default is a dry-run.
- **Security at the boundary:** https-only by default; SSRF host-blocklist
  (loopback/private/link-local/multicast/reserved/unspecified/cloud-metadata),
  refused redirects, disabled proxies, mandatory timeout, single attempt (no retries),
  64 KB payload cap, redacted logging. `NotificationError` / `WebhookSecurityError`
  extend `DQTError`.
- **Standard-library only** — no requests/httpx/aiohttp, no scheduler, no daemon, no
  background worker, no secret persistence. The base CLI/API path imports no HTTP code.

## Testing
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=data_quality_toolkit --cov-report=html

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
```
