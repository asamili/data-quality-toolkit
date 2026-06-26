# Changelog

All notable changes to the Data Quality Toolkit project are documented in this file.

The format is inspired by Keep a Changelog and adapted for this project.

## [Unreleased]

## [2.9.0] - 2026-06-21

### Added

- Added optional local AI adapter for StoryLens (`storylens-ai` extra); disabled by default via `DQT_STORYLENS_AI_ENABLED` flag. No model download or inference occurs unless explicitly enabled.
- Added `StoryLensFacts` builder for the Data Overview panel; wired to deterministic fallback when local AI is unavailable or disabled.
- Added import-linter AI isolation contract enforcing that AI adapter code cannot be imported by core data quality logic.

### Changed

- Hardened UI seams: all StoryLens surface calls now route through the public API boundary rather than internal modules.
- Tightened validator rules for scientific notation values, revision hash leakage, and severity contradiction patterns.

### Fixed

- Ensured deterministic fallback behavior when the optional local AI backend is absent, unreachable, or produces no output.
- Resolved severity contradiction edge cases in the validation pipeline.

### Notes

- First public release of v2.9.0: the sanitized public snapshot, the `v2.9.0` tag, and the GitHub Release (created by the release workflow on tag push) are published to the public repository.
- Optional local AI (StoryLens) is **off by default**: no model is bundled, no model download or inference occurs on install or at runtime, and the AI path is not exposed through the CLI or public API.
- The public snapshot applies the project's public/private boundary exclusions; it contains no internal coordination/governance files, secrets, or model artifacts.
- Optional `storylens-ai` dependency (`transformers>=5.0.0,<6.0.0`, `torch>=2.12.0`) remains opt-in; not added to the default install.

## [2.8.0] - 2026-06-18

### Added

- Added stable typed contracts for public API returns, including public API typed result contracts, row contracts, nested/flat envelope wrapper annotations/contracts, and Power BI package public API wrapper.
- Exposed monitoring API boundary (builders/value objects) and the complete `DQTError` exception family (along with `StorageError`) directly from the canonical `data_quality_toolkit.api` boundary.
- Added package lineage marker (`py.typed`) and import-linter boundary.

### Changed

- Routed the `gen-dim-time` CLI command through the public API (`generate_dim_time`) while preserving the CLI JSON payload representation.

### Fixed

- Stabilized settings environment-dependent defaults and resolved environment-loading variance using `cast(Any)` to silence `_env_file` stub variance.
- Resolved UI service return typing errors in the Streamlit monitoring UI service.

### Tests

- Added CLI help and optional dependency packaging smoke tests.
- Added direct unit tests for the manifest package lineage tools.
- Pinned `gen-dim-time` CLI/API parity gap tests.

### Documentation

- Documented public API boundary and typed result contracts.
- Refreshed DQT module inventory in architecture documentation.
- Aligned README release references with v2.7.1.

## [2.7.1] - 2026-06-17

### Fixed

- Fixed CI mypy validation for optional DuckDB imports by extending the existing optional-dependency ignore-missing-imports configuration to `duckdb` and `duckdb.*`.

## [2.7.0] - 2026-06-16

### Added

- Added one-shot drift webhook notifications (v2.7.0 slice). New CLI command `dqt drift-history notify --db monitoring.db --webhook-url URL [--fail-on-drift-rate FLOAT] [--fail-on-psi FLOAT] [--dry-run|--send] [--timeout SECONDS] [--allow-http] [--allow-insecure-host]` and public API seam `send_drift_notification(db_path, webhook_url, *, max_drift_rate=None, max_psi=None, dry_run=True, send=False, timeout=10.0, allow_http=False, allow_insecure_host=False)` (re-exported at the package root; lazy `cli/main.py` proxy). Builds a minimal JSON payload from the existing `summarize_drift_trends_sqlite` / `read_drift_columns_sqlite` / `evaluate_drift_rate_threshold` / `evaluate_psi_threshold` seams — no schema or query changes. **Dry-run is the default**: the payload is printed to stdout and nothing is sent. A real POST happens only when `--send` is given **and** `DQT_ALLOW_NETWORK=true`. Returns `{"payload", "sent", "status", "breached", "redacted_url"}`.
- Security model for the notifier: HTTPS-only by default (`--allow-http` opt-in for trusted local endpoints); SSRF guard rejecting loopback/private/link-local/multicast/reserved/unspecified and cloud-metadata (`169.254.169.254`, `fd00:ec2::254`) addresses, validating **every** resolved IP (`--allow-insecure-host` opt-in for local testing only); redirects refused; proxies disabled so `*_proxy` env vars cannot bypass the guard; mandatory timeout; single attempt, no retries; 64 KB payload cap with offender-list truncation; all logs/errors use a redacted URL (userinfo, query, and fragment stripped). No secrets, environment values, webhook URL, or full local DB path appear in the payload. Standard-library `urllib` only — **no new dependency** (no requests/httpx/aiohttp), no scheduler, no daemon, no background worker, no secret persistence.
- Added pure payload builder `build_drift_notification_payload(...)` in `application/monitoring/notifications.py` (no I/O, no network) and the webhook transport `adapters/notifications/webhook.py` (`validate_webhook_url`, `redact_url`, `post_json`; injectable resolver/opener for tests). Added `NotificationError` and `WebhookSecurityError` to the `DQTError` family in `shared/exceptions.py`.
- Exit codes for `notify`: `0` success (no breach), `1` validation/send/security failure, `2` threshold breach (applies even when the dry-run/send itself succeeds), `2` argparse error (e.g. missing `--webhook-url`, or `--dry-run` and `--send` together).
- Added drift-history SQLite → DuckDB export/mirror (v2.7.0 slice). New CLI command `dqt drift-history export-duckdb --db monitoring.db --out monitoring.duckdb [--overwrite]` and public API seam `export_monitoring_duckdb(db_path, out_path, *, overwrite=False) -> dict` (re-exported at the package root; lazy `cli/main.py` proxy). One-shot mirror of the drift-history tables `drift_runs`, `drift_columns`, and `drift_column_distributions` into a standalone DuckDB database file, returning `{"input_db_path", "output_path", "tables", "row_counts", "overwritten"}`. **DuckDB is export/mirror only — never a live monitoring backend; the monitoring store remains SQLite (no backend replacement, no storage-port refactor, no migrate command).** The source SQLite DB is opened **read-only** (`file:…?mode=ro` URI) and is provably never mutated (only `SELECT`/`PRAGMA` run; no schema changes, no writes, no WAL side files); tables absent from the source are mirrored as empty tables with a stable schema. Implemented in `adapters/exporters/bi/duckdb_exporter.py` with a single-source-of-truth `_TABLE_COLUMNS` mapping (column order + DuckDB types). Optional behind a new `[duckdb]` extra (`duckdb>=1.0.0`): duckdb is imported lazily inside the exporter and its absence raises `DuckdbExportError` with a `pip install data-quality-toolkit[duckdb]` hint — duckdb is never imported on the base path. Safety: `.duckdb` extension + `path_guard` output validation (no `..`/symlink-escape); refuses to overwrite an existing file unless `--overwrite` / `overwrite=True` (which removes the existing file for a deterministic recreate); a missing source database raises rather than producing an empty mirror. No network, no cloud, no `.env` reads, no scheduler/daemon/retry, no secret persistence. CLI exits `0` on success, `1` on export/dependency/path/missing-source failure, `2` on argparse error; success summary to stderr.

### Tests

- Added `tests/unit/notifications/test_webhook.py`: URL redaction, https-only/scheme validation, `--allow-http`, the full SSRF blocklist (loopback/private/link-local/metadata/unspecified, IPv4 + IPv6), multi-IP rejection, `--allow-insecure-host` bypass, redacted error messages, POST success/timeout/non-2xx/URL-error/oversized-payload, and redirect refusal — all with injected resolver/opener (no real network).
- Added `tests/unit/api/test_drift_notifications_api.py`: dry-run builds payload with no network, breach sets `breached`/offenders, send refused when `DQT_ALLOW_NETWORK` is unset, send succeeds with mocked transport (timeout forwarded), and `send=False` stays a dry-run even with network enabled.
- Added `tests/unit/cli/test_cli_drift_history_notify.py`: dry-run default prints payload JSON, stderr carries no secret (only redacted URL), `--no-json` suppresses stdout, breach exit `2`, `--send`/`--timeout` flag forwarding, send-failure exit `1`, missing-required-arg exit `2`, and `--dry-run`/`--send` mutual-exclusion exit `2`.
- Extended `tests/integration/test_api_parity.py` (dry-run delegation, no network) and `tests/integration/test_seam_parity.py` (dual-interface seam presence) for `send_drift_notification`.
- Added `tests/unit/exporters/test_duckdb_exporter.py`: path-safety (`.duckdb` extension, empty path, `..` traversal, directory target, overwrite refusal/allow), missing-`duckdb` install-hint guard (no extra needed), missing-source-DB error, and on-disk mirror tests (`importorskip("duckdb")`) covering mirrored tables + row counts, value round-trip, **SQLite-input-not-mutated** (byte hash + mtime, no WAL/SHM side files), deterministic overwrite, and empty-mirror when drift tables are absent.
- Added `tests/unit/cli/test_cli_drift_history_export_duckdb.py`: command exists, success exit `0`, stderr summary, default no-overwrite, `--overwrite` forwarding, missing `--db`/`--out` exit `2`, refused-overwrite exit `1`, and clean missing-dependency handling (exit `1` with `[duckdb]` hint) — all via the monkeypatched proxy (no extra needed).
- Added `tests/unit/api/test_duckdb_export_api.py`: seam present/callable, re-exported from the package root and in `__all__`, delegates to the exporter impl, returns the expected dict shape, and respects the `overwrite` default.
- Extended `tests/integration/test_api_parity.py` (delegation) and `tests/integration/test_seam_parity.py` (dual-interface seam presence) for `export_monitoring_duckdb`; added `tests/integration/test_duckdb_export_e2e.py` (build/populate a real monitoring SQLite DB, export, verify DuckDB tables + row counts; `importorskip("duckdb")`).

### Docs

- Added "Drift Webhook Notifications (v2.7.0)" sections to `README.md`, `docs/cli.md` (flag/exit-code tables, SSRF/redaction/timeout notes, token-in-query warning), `docs/api.md` (`send_drift_notification` signature, return shape, network-gate behavior), and `docs/architecture.md` (API seam → pure payload builder → SSRF-guarded stdlib transport data flow).
- Added "DuckDB Export/Mirror (v2.7.0)" sections to `README.md`, `docs/cli.md` (flag/exit-code tables, read-only-source notes), and `docs/api.md` (`export_monitoring_duckdb` signature + return shape), plus a "DuckDB Export/Mirror (v2.7.0)" data-flow section in `docs/architecture.md` clarifying that DuckDB is export/mirror only (read-only SQLite source, not a live backend) and updating the "DuckDB-backed monitoring remains deferred" note accordingly.

## [2.6.1] - 2026-06-15

### Added

- Added core drift threshold flagging (v2.6.1 slice). Two opt-in CLI flags on existing `drift-history` subcommands exit `2` when a monitored metric exceeds a threshold, following the `--fail-on-drift` exit-code convention: `dqt drift-history trend --fail-on-drift-rate <float>` exits `2` when the historical drift rate exceeds the threshold; `dqt drift-history columns --fail-on-psi <float>` exits `2` when any column's PSI exceeds the threshold. Breach is strictly greater than (`>`); exactly equal is not a breach. Exit `1` on invalid threshold value (out of `[0.0, 1.0]`); exit `0` when no flag is provided or when the threshold is not breached. A missing or empty database produces zero drift rate / no columns → no breach → exit `0`. `None` PSI values (scipy unavailable or column skipped) are silently skipped. No new dependencies, no network, no DB writeback, no schema change.
- Added pure threshold evaluator functions `evaluate_drift_rate_threshold(summary, *, max_drift_rate)` and `evaluate_psi_threshold(columns, *, max_psi)` in `application/monitoring/thresholds.py`, re-exported via the root `data_quality_toolkit.api` seam. Both return JSON-ready plain dicts (`breached`, metric value, `threshold`; PSI adds `offenders` list). No I/O, no Streamlit, no storage imports.
- Added drift-history Excel (`.xlsx`) export (v2.6.1 slice). New CLI command `dqt drift-history export-xlsx --db monitoring.db --out drift_monitoring.xlsx` and public API seam `export_drift_history_xlsx(db_path, output_path, *, current_dataset_id=None, limit=None, include_columns=True, include_distributions=False, force=False)` (re-exported at the package root; lazy `cli/main.py` proxy). Writes a multi-sheet workbook (`runs`, `trend_summary`, `columns` default-on, `distributions` opt-in, `metadata`) by reusing the existing `read_drift_runs_sqlite` / `summarize_drift_trends_sqlite` / `read_drift_columns_sqlite` / `read_drift_distributions_sqlite` seams — no schema or query changes. Implemented in `adapters/exporters/bi/xlsx_drift_exporter.py` with a pure, openpyxl-free `build_workbook_model` plus an openpyxl write-only (streaming) writer. Optional behind the existing `[powerbi]` extra: openpyxl is imported lazily and its absence raises `XlsxExportError` with a `pip install data-quality-toolkit[powerbi]` hint. Security: every string cell (headers/data/metadata) is escaped against spreadsheet formula injection (leading `=` `+` `-` `@` or tab/CR → single-quote prefix); `.xlsx` extension and `path_guard` output validation; refuses to overwrite an existing file unless `--force`. No formulas, macros, external links, embedded objects, network, cloud, or `.pbix`. CLI exits `0` on success, `1` on export/dependency/path failure, `2` on argparse error; success summary to stderr, no stdout pollution. A missing or empty database yields a valid zero-state workbook.
- Cleaned up the `[powerbi]` extra comments in `pyproject.toml` (`openpyxl` now wired to the `.xlsx` export; `xlsxwriter` noted as reserved for future rich formatting). No dependency additions; no Excel dependency moved into the base install.
- Added drift-history Matplotlib PNG plot export (v2.6.1 slice). New CLI command `dqt drift-history plot --db monitoring.db --out plots/ [--chart drift-rate|psi-by-column|top-drifted|all] [--current-dataset-id ID] [--limit N] [--force]` and public API seam `export_drift_plots(db_path, out, *, chart="all", current_dataset_id=None, limit=None, force=False)` (re-exported at the package root; lazy `cli/main.py` proxy). Renders local PNG charts — `drift-rate` (per-run drift fraction over time with overall-rate reference line), `psi-by-column` (mean PSI per column, descending), `top-drifted` (top-15 columns by drift count) — by reusing the existing `read_drift_runs_sqlite` / `summarize_drift_trends_sqlite` / `read_drift_columns_sqlite` seams (only the seams a requested chart needs are queried; no schema or query changes). Implemented in `adapters/exporters/viz/drift_plots.py` with a pure, matplotlib-free `build_plot_model` plus a lazy renderer that forces the non-interactive `Agg` backend **before** importing `pyplot`. Optional behind the existing `[viz]` extra: matplotlib is imported lazily and its absence raises `PlotExportError` with a `pip install data-quality-toolkit[viz]` hint. Safety: `path_guard` output-directory validation (no `..`/symlink-escape), fixed chart file names (no user input in a filename), refuses to overwrite an existing PNG unless `--force`, figures closed after each save. No network, no cloud, no GUI backend, no remote image fetching. CLI exits `0` on success, `1` on plot/dependency/path failure, `2` on argparse error; success summary to stderr, no stdout pollution. A missing or empty database yields valid zero-state ("No data available") PNGs. The `distribution` (reference-vs-current) chart is deferred to a later release.
- Updated the `[viz]` extra comment in `pyproject.toml` (`matplotlib` now wired to `dqt drift-history plot`, replacing the "future" placeholder note). No dependency additions; matplotlib remains an optional extra and is not moved into the base install.

### Tests

- Added `tests/unit/exporters/test_drift_plots_exporter.py` covering the pure plot model (drift-fraction ordering, mean-PSI aggregation, drift-count ranking, zero-state, `None`-PSI skip), chart selector, output-path safety, the missing-matplotlib `[viz]` hint, Agg-backend enforcement, valid-PNG writes, single-vs-all chart selection, and no-overwrite/`--force` behavior (matplotlib-requiring tests gated by `importorskip`).
- Added `tests/unit/cli/test_cli_drift_history_plot.py` for the `plot` command: success exit `0`, stderr summary, clean stdout, flag forwarding, default `--chart all`, missing `--db`/`--out` and invalid `--chart` exit `2`, missing-`[viz]` exit `1` with hint, no-overwrite exit `1`.
- Added `tests/unit/api/test_drift_plots_api.py` for `export_drift_plots` API-seam import and delegation to the exporter impl.
- Added `tests/integration/test_drift_plots_e2e.py` (gated by `importorskip("matplotlib")`): seeds a real SQLite monitoring DB and asserts valid PNG output, correct `row_counts`, and API/CLI parity.
- Added `tests/unit/monitoring/test_thresholds.py` with boundary, equality, above-threshold, `None`-skip, empty-input, ordering, and JSON-readiness coverage for both evaluators.
- Extended `tests/unit/cli/test_cli_drift_history.py` with threshold flag tests: flag absent, below/equal/above threshold exit codes, breach stderr message, invalid threshold exit `1`, empty/missing DB exit `0`, `None` PSI skip — for both `trend` and `columns` subcommands.
- Added `tests/unit/api/test_drift_thresholds_api.py` for evaluator API-seam import, breach, no-breach, `None`-skip, and empty-columns coverage.
- Extended `tests/integration/test_drift_monitoring_parity.py` with threshold parity tests: direct API evaluator result matches CLI exit behavior for drift-rate and PSI thresholds; empty/missing DB exits no breach.
- Extended `tests/integration/test_api_parity.py` and `tests/integration/test_seam_parity.py` with `export_drift_plots` delegation and dual-interface seam-presence checks.

### Docs

- Added "Drift Plots (v2.6.1)" section to `README.md` (chart catalog, example command, `[viz]` install note, no-overwrite/`--force`, exit codes).
- Added "Drift Plots (v2.6.1)" section to `docs/cli.md` (chart-catalog table, flag reference, exit-code table, path-safety/zero-state notes).
- Added "Drift Plots (v2.6.1)" section to `docs/api.md` (`export_drift_plots` signature, return shape, lazy-Agg/safety behavior).
- Added "Drift Plots (v2.6.1)" section to `docs/architecture.md` (API seam → pure plot model → lazy Agg renderer data flow).
- Added "Drift Threshold Gating (v2.6.1)" section to `README.md` with example commands, breach semantics, and exit-code table.
- Added "Drift Threshold Gating (v2.6.1)" section to `docs/cli.md` with flag reference table, exit-code table, and behavior notes.
- Added "Drift Threshold Evaluators (v2.6.1)" section to `docs/api.md` documenting both functions, return shapes, and empty/None behavior.
- Added "Drift Threshold Evaluators (v2.6.1)" section to `docs/architecture.md` showing the pure-evaluator seam in the monitoring data flow.

## [2.6.0] - 2026-06-15

### Added

- Added the v2.6.0 Unified Monitoring Experience: a single, presentation-agnostic shared monitoring view-model (`data_quality_toolkit.application.monitoring.view_model`) that normalizes the existing SQLite/API drift query surfaces (`summarize_drift_trends_sqlite`, `read_drift_runs_sqlite`, `read_drift_columns_sqlite`, `read_drift_distributions_sqlite`) into frozen, typed value objects (`TrendSummary`, `RunRow`, `ColumnDrift`, `DistributionBin`, `RunDetail`, `MonitoringOverview`, each with `to_dict()`) via builders (`build_monitoring_overview`, `list_run_rows`, `build_column_drift`, `build_distribution_series`, `build_run_detail`). The view-model reaches storage **only** through the root `data_quality_toolkit.api` seam, imports nothing from Streamlit or the storage adapters directly, normalizes integer `drift_detected` flags to `bool` (preserving `None`), preserves missing numerics as `None`, and returns a zeroed summary / empty lists for a missing or empty database rather than raising.
- Added the optional interactive **DQT Drift Explorer** Streamlit page (`adapters/ui/pages/drift_explorer.py`) and its Streamlit-free `(data, err)` UI service (`adapters/ui/services/monitoring.py`), both consuming the shared view-model. The Explorer reads its initial DB path from `DQT_UI_DB`, shows trend-summary metrics, a drift-runs table, a run selector, a per-column drift table with column / `drift_detected` / metric (PSI / Jensen-Shannon / Wasserstein) filters, and reference-vs-current distribution bars, with empty-state guidance for no runs / no columns / no distributions. The page is registered under the existing dashboard navigation.
- Added the preferred `dqt ui --db monitoring.db` CLI launcher (`cmd_ui`). `--db` is optional and, when given, seeds `DQT_UI_DB` for the Drift Explorer; the command launches `python -m streamlit run <app>`, propagates the subprocess return code, returns 130 on `KeyboardInterrupt`, and on missing Streamlit prints `pip install "data-quality-toolkit[ui]"` to stderr and exits 1. No `[streamlit]` extra and no `pyproject.toml` change.

### Changed

- Promoted the static drift dashboard to **Dashboard 2.0**, rendered from the shared monitoring view-model so the static HTML artifact and the interactive Streamlit UI derive identical run counts, drift rates, and column metrics. Still a dependency-free, self-contained HTML artifact (no server, no JavaScript, no external assets).
- Modularized the `dqt` CLI internals: per-command handlers moved to `adapters/cli/commands/` and shared parser/launcher helpers to `adapters/cli/utils/`, while `adapters/cli/main.py` remains the public entrypoint. Public command names, flags, exit codes, and behavior are unchanged. Deduplicated the `dqt dashboard` and `dqt ui` Streamlit launch paths into a single shared launcher (`launch_streamlit_app`), keeping the `import streamlit` guard at call time so the base CLI stays Streamlit-free. Internal refactor only — no version bump, tag, or release.

### Tests

- Added unit tests for the shared monitoring view-model (`to_dict` parity, `drift_detected` int-to-bool normalization, builders, empty/missing-DB stability, and AST-based assertions that it imports neither Streamlit nor storage adapters), the Streamlit-free UI service (blank/missing-DB clean errors, monkeypatched success/error paths, converter helpers, and import-boundary checks), and the `dqt ui` launcher (missing-Streamlit exit 1 with install hint, `DQT_UI_DB` seeding, mocked `streamlit run` invocation, return-code propagation, `KeyboardInterrupt` → 130, Streamlit-free parser build). Added an integration parity suite (`tests/integration/test_drift_monitoring_parity.py`) that builds a real SQLite monitoring DB and asserts the view-model, UI service, and static dashboard agree on run/drifted counts, trend summary, column metrics, distribution rows, and empty-state behavior without launching a real Streamlit server or taking brittle full-HTML snapshots.

### Docs

- Documented the Unified Monitoring Experience: a README "Unified Monitoring (v2.6.0)" section (static dashboard vs Streamlit UI, the `[ui]` install, the `dqt drift` → `drift-history import` → `drift-history dashboard` → `dqt ui` workflow, and the dashboard-vs-UI mental model), the `dqt ui --db` command and its missing-Streamlit hint in the CLI reference, the shared monitoring view-model module/dataclasses/builders in the API reference, and the `SQLite → API/query seam → shared view-model → static dashboard + Streamlit UI` relationship in the architecture doc (noting Dashboard is a static artifact, the UI is an optional local app, and DuckDB remains deferred). Docs only — no version bump, tag, or release.

## [2.5.0] - 2026-06-13

### Added

- Added README and CLI-reference usage documentation for the v2.5.0 drift-history analytics workflow (import / list / trend / columns / report / dashboard, `--include-columns`, `--include-plots`), including the dependency-free report/dashboard note, the PSI / Jensen-Shannon / Wasserstein advanced metrics, and the `drift_runs` / `drift_columns` / `drift_column_distributions` SQLite artifacts. Docs only — no source, schema, version, or behavior change.
- Added dependency-free distribution-plot rendering to the drift-history report and dashboard, behind a new opt-in `--include-plots` flag (`dqt drift-history report ... --include-plots`, `dqt drift-history dashboard ... --include-plots`) and `include_plots=True` on the `drift_history_report` / `drift_dashboard` public Python APIs (and the `build_drift_*` builders / `render_drift_*` renderers via a `distributions` parameter). When requested, the renderers consume the persisted `drift_column_distributions` rows via the accepted `read_drift_distributions_sqlite` reader and render a "Distribution plots" section grouped by `run_id` + `column_name`, showing per-bin `bin_label` with paired reference-vs-current probabilities as percentages and overlaid horizontal bars (HTML: inline-CSS bars with all dynamic text escaped via `html.escape`; Markdown: a compact table with unicode block bars). `distributions=None` (default / flag omitted) omits the section entirely so existing report/dashboard output is byte-for-byte unchanged; `distributions=[]` (flag set, no persisted rows) renders the section with a clear "No distribution rows available." empty-state. The CLI fetches distribution rows only when the flag is set and appends a "Distribution rows" count to its stderr summary; a missing or empty database still exits 0 with valid output. Rendering only — reuses the existing persisted bins; no SQLite/`drift_column_distributions` schema change, no importer/`drift.py`/metric behavior change, no new CLI plot command, no JSONL widening, no matplotlib/DuckDB/Parquet/Arrow/Streamlit, no JavaScript/CDN/external CSS/image assets, no new dependencies, no version bump.
- Added column-level distribution capture for drift detection (data backbone for future static plots; no rendering in this slice). Tested numeric and categorical columns now carry a nullable `distribution` field on each `detect_drift` / `detect_drift_frames` result entry — `{"kind": "numeric"|"categorical", "bins": [{"label", "reference", "current"}, ...]}` — reusing the same reference-quantile / category-bucketing probability vectors already computed for PSI/JS (no change to PSI/JS/Wasserstein scalar values). Numeric labels are deterministic half-open `[lo, hi)` ranges (outer edges `±inf`); categorical labels reuse the existing `__other__` bucketing. Skipped/unavailable/degenerate/all-null columns keep `distribution = None`. `DRIFT_REPORT_SCHEMA_VERSION` bumped from `"2"` to `"3"` (the evidence report serializes the full result, so it now includes `distribution`); `DRIFT_HISTORY_SCHEMA_VERSION` and the summary-only JSONL history record are unchanged. Added the SQLite `drift_column_distributions` table (one row per bin: `run_id`, `column_name`, `kind`, `bin_index`, `bin_label`, `reference_prob`, `current_prob`) with index `idx_drift_col_dist_run`; `import_drift_history_sqlite` now also populates it from each imported `drift_runs.report_path` evidence report's `result.columns[].distribution.bins` (delete-then-insert per `run_id` for idempotency, gracefully skipping null/missing/unreadable reports, columns without a usable distribution, and non-list bins — the run-level import return value is unchanged). A v2 report without a `distribution` key imports cleanly with zero distribution rows (backward compatible). `drift_schema_version` bumped from `"2"` to `"3"` via the existing guarded, idempotent upgrade (fresh DBs get `"3"`; legacy v1/v2 DBs upgrade on next `ensure_db`; `drift_runs` and `drift_columns` unchanged). Added the `read_drift_distributions_sqlite(db_path, *, run_id, column_name)` public Python API (over the `read_drift_distributions` storage query) returning JSON-ready bin dicts ordered by `run_id`, `column_name`, then `bin_index`; a missing DB or empty table returns `[]`. Data backbone only — no plot rendering, no SVG/HTML sparkbars, no dashboard/report `--include-plots`, no matplotlib, no new dependencies, no version bump.
- Added a static, dependency-free drift analytics dashboard surface. New `dqt drift-history dashboard --db PATH --output dashboard.html` CLI command and `drift_dashboard(db_path, *, current_dataset_id, limit)` public Python API render a single self-contained HTML file (inline minimal CSS only — no web server, no JavaScript, no external CDN, no image assets, no new dependencies) summarizing both run-level and column-level drift. Consumes the accepted `summarize_drift_trends_sqlite`, `read_drift_runs_sqlite`, and `read_drift_columns_sqlite` APIs only. The dashboard includes the title "Drift Analytics Dashboard", `generated_at`, the database path, the optional `current_dataset_id`/`limit` filters when provided, summary cards (`total_runs`, `drifted_runs`, `non_drifted_runs`, `drift_rate`, `latest_run_id`, `latest_created_at`), a run-level table (`run_id`, `created_at`, `current_dataset_id`, `status`, `drift_detected`, `columns_tested`, `columns_drifted`), and a column-level metrics table (`run_id`, `column_name`, `kind`, `drift_detected`, `psi`, `js_distance`, `wasserstein`, `status`); empty runs or columns render clear empty-state messages. All dynamic values are escaped with the stdlib `html.escape`. The CLI writes the file to `--output` and prints the output path, total runs, drifted runs, and column-row count to stderr (no JSON on stdout); a missing or empty database produces a valid zero dashboard and exits 0. Dashboard surface only — no schema change, no importer/query/metric/trend behavior change, no plots, no new dependencies, no version bump.
- Added a column-level drift CLI/reporting surface over the existing `drift_columns` backbone. New `dqt drift-history columns --db PATH` CLI command lists imported per-column drift metrics via the `read_drift_columns_sqlite` public API, printing a JSON array of column dicts to stdout (suppressed by global `--no-json`) and a human summary with the returned column count and drifted-column count to stderr. Supports `--run-id`, `--column-name`, and `--drift-detected true|false` filters; an invalid `--drift-detected` value exits 2; a missing DB or empty `drift_columns` table exits 0 with `[]`. Each row includes `run_id`, `column_name`, `kind`, `test`, `statistic`, `p_value`, `drift_detected`, `reference_n`, `current_n`, `status`, `skip_reason`, `psi`, `js_distance`, and `wasserstein`. The `dqt drift-history report` command and `build_drift_history_report` API gain an opt-in `--include-columns` / `include_columns=True` switch that appends a "Column-level drift metrics" section (Markdown table or dependency-free escaped HTML table with `run_id`, `column_name`, `kind`, `drift_detected`, `psi`, `js_distance`, `wasserstein`, `status`); when no column rows are available the section renders "No column-level drift rows available." and the section is omitted entirely unless requested. Reuses the accepted `read_drift_columns_sqlite` reader only — no schema change, no importer/query/metric behavior change, no new dependencies, no version bump.
- Added the SQLite column-level drift backbone: a `drift_columns` table (with index `idx_drift_columns_run` on `run_id`), an evidence-report column importer, and the `read_drift_columns_sqlite(db_path, *, run_id, column_name, drift_detected)` public Python API. `import_drift_history_sqlite` now also populates `drift_columns` by reading each imported `drift_runs.report_path` evidence report and persisting its `result.columns[]` (`column`→`column_name`, advanced metrics `psi`/`js_distance`/`wasserstein` included). Column import is idempotent (delete-then-insert per `run_id`) and skips gracefully when a `report_path` is null, missing, unreadable, or has no valid columns — a missing report artifact never fails the run-level import; the run-level import return value (number of newly inserted `drift_runs` rows) is unchanged. `read_drift_columns_sqlite` returns JSON-ready dicts ordered by `run_id` then `column_name`, with optional `run_id`/`column_name`/`drift_detected` filters; a missing DB or no matching rows returns `[]` and `StorageError` is raised on DB read failure. `drift_schema_version` metadata bumped from `"1"` to `"2"` via a guarded, idempotent upgrade (existing DBs are migrated on next `ensure_db`); `drift_runs` and the JSONL drift-history record shape are unchanged. Storage backbone only — no DuckDB, no dashboard, no plots, no CLI command, no new dependencies, no version bump.
- Added advanced per-column drift metrics to `detect_drift` / `detect_drift_frames`: PSI (Population Stability Index, dependency-free), Jensen-Shannon distance (scipy-guarded, range [0,1]), and Wasserstein distance (scipy-guarded, numeric columns only). All three are exposed as flat keys (`psi`, `js_distance`, `wasserstein`) on every per-column result entry; skipped and unsupported columns carry the keys with `None` values. No new dependencies — JS and Wasserstein use `scipy.spatial.distance.jensenshannon` and `scipy.stats.wasserstein_distance` from the existing `[stats]` extra; both are `None` when scipy is absent. PSI uses reference-quantile bins for numeric columns and the existing category bucketing for categorical columns. `DRIFT_REPORT_SCHEMA_VERSION` bumped from `"1"` to `"2"` to reflect the enriched column shape; JSONL history records are unchanged.
- Added `dqt drift-history report --db PATH --output PATH` CLI command and the `drift_history_report(db_path, *, current_dataset_id, limit, fmt)` public Python API. Turns imported `drift_runs` SQLite history into a readable Markdown monitoring report (`--format html` for dependency-free HTML), reusing the accepted `summarize_drift_trends_sqlite` and `read_drift_runs_sqlite` APIs. The report includes a title, `generated_at`, database path, optional `current_dataset_id`/`limit` filters, the full trend summary (`total_runs`, `drifted_runs`, `non_drifted_runs`, `drift_rate`, latest run fields, columns tested/drifted totals and averages), and a recent-runs table. The CLI writes the report to `--output` and prints the output path and run count to stderr (no JSON on stdout). A missing or empty database produces a valid zero report and exits 0. Reporting slice only — no schema change, no importer/query/trend behavior change, no new dependencies, no version bump.
- Added `summarize_drift_trends_sqlite(db_path, *, current_dataset_id, limit)` to the public Python API, backed by the internal `summarize_drift_trends` storage helper. Aggregates imported `drift_runs` records into a JSON-ready trend summary: `total_runs`, `drifted_runs`, `non_drifted_runs`, `drift_rate`, the latest run's `latest_run_id`/`latest_created_at`/`latest_drift_detected`, and `columns_tested`/`columns_drifted` totals and averages. Reuses the `read_drift_runs` query behavior (newest first, optional `current_dataset_id` and `limit` filters). A missing DB, empty table, or no matching rows returns a stable zero-summary; raises `StorageError` on DB read failure. Read-only trend slice — no CLI, no reports, no schema change, no version bump.
- Added `dqt drift-history trend --db PATH` CLI command. Summarizes imported drift runs from a SQLite monitoring database via the `summarize_drift_trends_sqlite` public API, printing the JSON-ready trend summary dict to stdout (suppressed by global `--no-json`) and a human summary with `total_runs`, `drifted_runs`, and `drift_rate` to stderr. Supports `--current-dataset-id` and `--limit` filters. Missing DB, empty table, or no matching rows exit 0 with a stable zero-summary. Read-only trend slice — no schema change, no reports, no version bump.
- Added `dqt drift-history list --db PATH` CLI command. Lists imported drift runs from a SQLite monitoring database via the `read_drift_runs_sqlite` public API, printing a JSON array of run dicts to stdout (suppressed by global `--no-json`) and a human summary with the returned run count to stderr. Supports `--limit`, `--current-dataset-id`, `--drift-detected true|false`, and `--status` filters. Missing DB or no matching rows exit 0 with `[]`. Read-only query slice — no schema change, no trend comparison, no reports, no version bump.
- Added `read_drift_runs_sqlite(db_path, *, limit, current_dataset_id, drift_detected, status)` to the public Python API, backed by the internal `read_drift_runs` storage query helper. Returns imported drift runs from the `drift_runs` SQLite table as JSON-ready dicts, newest first (`created_at` descending, `run_id` tie-break). Supports `limit`, `current_dataset_id`, `drift_detected`, and `status` filters. Missing DB or no matching rows returns `[]`; raises `StorageError` on DB read failure. Read-only query slice — no CLI, no trend comparison, no reports, no schema change, no version bump.
- Added `dqt drift-history import HISTORY_PATH --db PATH` CLI command. Imports a JSONL drift history file into a SQLite monitoring database via the `import_drift_history_sqlite` API (ensuring the schema exists first), prints `imported_count`/`history_path`/`db_path` as JSON to stdout (suppressed by global `--no-json`), and emits a human summary with the imported row count to stderr. `imported_count` is the number of newly inserted rows (`INSERT OR IGNORE`); re-importing the same file returns 0 while the database remains unchanged. Missing or empty history files exit 0 with `imported_count` 0. No schema change, no query/report helpers, no version bump.
- Added `dqt drift-history read HISTORY_PATH` CLI command (previously `dqt drift-history HISTORY_PATH`; moved under the new `drift-history` subcommand group). Reads a JSONL drift history file written by `dqt drift --history`, prints records as a JSON array to stdout (suppressed by global `--no-json`), and emits a human summary with record count to stderr. Missing, empty, and malformed-line files all exit 0. No filters, no sorting, no SQLite, no version bump.
- Added `read_drift_history(history_path)` to the public Python API. Reads append-only `drift_history.jsonl` files written by `detect_drift(..., history_path=...)`. Returns a list of `drift_history_record` dicts in append order; missing file returns `[]`; blank and malformed lines are skipped. First v2.5.0 monitoring-history productization slice — no CLI, no SQLite importer, no version bump.

## [2.4.0] - 2026-06-12

### Added
- Added `--history <path>` option to `dqt drift`, appending one compact `drift_history_record` JSON line per run to an append-only JSONL file; shares the evidence report's `run_id` when `--output` is also given. Default behavior is unchanged (no file written without the flag).
- Added `history_path` keyword to the `detect_drift` Python API for the same opt-in history record.
- Added `--output <path>` option to `dqt drift`, writing the drift result to a JSON evidence report wrapped in a versioned envelope (`schema_version`, `run_id`, `created_at`); default behavior is unchanged (no file written without the flag).
- Added `output_path` keyword to the `detect_drift` Python API for the same opt-in evidence report.
- Added `--fail-on-drift` option to `dqt drift` command, which causes the CLI to exit with code 2 if statistical drift is detected.
- Added statistical drift detection for comparing baseline and current CSV datasets.
- Added numeric Kolmogorov-Smirnov (KS) test for drift detection in numerical columns (requires `scipy`).
- Added Chi-square test of homogeneity for drift detection in categorical columns (requires `scipy`).
- Added `dqt drift <baseline.csv> <current.csv>` CLI command with support for `--alpha`, `--min-samples`, and `--max-categories` tuning.
- Added `[stats]` optional dependency extra (`pip install "data-quality-toolkit[stats]"`) for drift detection capabilities.
- Added README usage documentation and examples for the `dqt drift` command.

## [2.3.0] - 2026-06-11

### Added
- Added shared error contract used across CLI and UI error paths.
- Added opt-in CLI `--json-errors` output for machine-readable error reporting.
- Added Run-to-Run Comparison surface in the dashboard Run History page.
- Added UI compare service wrapper for compare workflow parity.
- Fixed CLI structured error output to preserve the `Hint:` label.
- Fixed Manifest Viewer error rendering to use the shared UI error path.
- Documented manifest and ELT pipeline API helpers.
- Expanded dashboard README into a full UI user guide.

## [2.2.1] - 2026-06-11

### Fixed
- Updated Streamlit-dependent UI smoke tests to skip cleanly when the optional `streamlit` `[ui]` extra is not installed.

### Notes
- Patch release to ensure release workflow coverage passes without requiring optional UI dependencies.

## [2.2.0] - 2026-06-09

### Added
- Column-level `fail_under` quality gates:
  - Configure minimum completeness thresholds per column in `dqt.yaml`
  - Example: `columns.order_amount.fail_under: 0.95` ensures critical columns meet specific trust floors
- Terminal Profiling Charts (`dqt chart <csv> --column <name>`):
  - High-signal terminal histograms for numeric distributions
  - Top-N horizontal bar charts for categorical columns
  - Accelerates visual profiling directly in the terminal without external dependencies
- Lineage Manifest CLI (`dqt manifest create --run-id <ID> --sessions-root <PATH>`):
  - Generates structured lineage metadata for an export run
  - Improves traceability and impact analysis for downstream data consumers
- Metadata overrides for optional backends (`orjson`, `msgspec`) in lineage serialization
- Git hygiene: Anchored `MANIFEST` pattern to root in `.gitignore` to prevent package tracking conflicts

### Fixed
- Lineage builder: Corrected type hints for optional serializer settings

### Notes
- Additive release focused on Trust (Column Gates), Visibility (Charts), and Traceability (Lineage)

## [2.1.0] - 2026-06-03


### Added

- **Chunked streaming profiling**: `dqt profile --chunked` streams large CSV files in configurable chunks without loading the full dataset into memory.
- **Chunked streaming assessment**: `dqt assess --chunked` supports partial quality assessment on large datasets using the chunked iterator.
- `load_chunks` iterator for memory-efficient CSV processing.
- Chunked aggregation primitives for per-chunk statistic accumulation and final aggregation.
- `run_profile_chunked` and `run_assessment_chunked` workflow entry points.
- Application ports abstraction for cleaner pipeline-to-loader interface decoupling.
- KPI workflow API with CLI decoupled from domain coupling.
- UI large-data chunked profile mode.
- UI tabbed navigation, advanced workflow panels, improved onboarding, and empty states.
- Guarded server-side export writes in the UI.
- Scalability benchmark harness coverage.
- Architecture boundary contracts verified with `import-linter`.
- Path guard utility.

### Changed

- `SAMPLE_SIZE` runtime mutation replaced with explicit parameter threading.
- Benchmark imports updated for the layered architecture layout.
- README aligned with current CLI, API, and UI surfaces.
- README clarified chunked V2 limitations and large-file guidance.

### Fixed

- Benchmark module import paths corrected after layered restructure.
- v2 column rule contract key enforcement tightened in assessment integration.

---

## [2.0.0] - 2026-05-29

### Added
- Harden JSONL history writes with atomic-like append and fsync
- Add warning when malformed lines are skipped during history import
- Add CI performance regression guard
- Document v2 `dqt.yaml` rule contract with `config/v2_rules.yaml` example

### Changed

- Apply v2 per-column weights to completeness scoring and critical-column penalty multiplier to quality_score
- Wire v2.0 `dqt.yaml` rule contract into issue detection (null, high-cardinality, and outlier thresholds, plus required columns)
- Implement v2.0 `dqt.yaml` rule contract parser with support for `dataset` and `columns` sections
- Remove unused `typer` dependency and stale references
- Remove obsolete `Initialize-Phase0.ps1` bootstrap script
- Implement dependency reproducibility with `constraints.txt` and wired CI installs

### Security

- Promote pip-audit CI step from advisory (`continue-on-error: true`) to blocking gate; build now fails on known CVEs

---

## [1.9.0] - 2026-05-29

### Added

- Penalty-weighted `quality_score` in assessment output and run history:
  - `score` — legacy completeness score (fraction of non-null values across all columns); value and behavior unchanged
  - `completeness_score` — explicit alias for `score`; same value, clearer name
  - `quality_score` — deducts severity-weighted penalties for schema and distribution issues from `completeness_score`; capped at `[0.0, 1.0]`
- `--score-field {score,completeness_score,quality_score}` flag on `assess`, `export-star`, and `export`:
  - Controls which score field drives the `--fail-under` quality gate
  - Default: `score` — existing `--fail-under` behavior is unchanged
  - `--score-field quality_score` enables penalty-aware gating without altering the completeness score
- `compare` output now includes `current_quality_score`, `previous_quality_score`, `current_completeness_score`, and `previous_completeness_score`; legacy records with absent values display `N/A` in stderr summary
- `assess` and `export-star` stderr summaries now display Score, Completeness Score, and Quality Score lines when the fields are present in the assessment result

### Notes

- Additive change; all existing CLI flags, exit codes, output formats, scoring formulas, and storage schema are unchanged

---

## [1.8.0] - 2026-05-22

### Security, Performance, and Memory Hardening, CVE Remediation, and Mypy Cleanup (HEAD `d83a08a`)

Four hardening gates, one CVE remediation gate, and one mypy cleanup gate completing the v1.8.0 release. No breaking changes to public CLI or output formats.

**Security / Tooling Hardening (`b429200`)**

- `pip-audit` wired into pre-commit (manual stage) and CI (`continue-on-error: true`) for advisory dependency CVE scanning
- `ruff` mccabe cyclomatic-complexity ceiling added: `max-complexity = 10` (`[tool.ruff.lint.mccabe]`)
- Bandit static security analysis confirmed active at `-ll -iii` threshold; no medium/high issues in `src/`
- 8 security surface regression tests added in `tests/unit/security/test_security_surface.py` locking path validation, loader rejection, network-off default, and `api_key=None` default
- `SECURITY.md` extended with "Path, output, and network stance" and "Security tooling" sections documenting `DQT_ALLOW_NETWORK`, output scope, bandit/ruff-S/pip-audit coverage

**Performance & Memory Baseline (`37dea11`)**

- Benchmark harness added at `benchmarks/baseline.py`: wall-clock (`time.perf_counter`), tracemalloc peak, and RSS delta for `load → profile → preprocess` across 10k×5, 100k×5, 100k×100, and 1M×5 shapes
- Baseline captured on 2026-05-22: 1M×5 profile = 13.3 s (nunique-bound on high-cardinality id column); 100k×100 preprocess = 2.24 s; full-file read regardless of `SAMPLE_SIZE` confirmed; `max_rows_in_memory` unenforced
- Findings and behavior reference documented in `benchmarks/README.md`

**Complexity / Profiling Performance Refactor (`052ab1f`)**

- `column_profiler.profile_columns`: replaced per-column `isna().sum()` / `nunique()` loop with single vectorised `df.isna().sum()` / `df.nunique(dropna=True)` bulk reductions (21–29% profiling wall-time reduction across tested shapes)
- `iqr_outlier_summary`: merged two `series.quantile()` calls into `series.quantile([0.25, 0.75])` (one sort instead of two)
- `plan_preprocessing`: caches `s = df[col]` per iteration, eliminating repeated column indexing
- Preprocessing wall time reduced 21–34%; profiling 21–29%; memory (`py_peak_mb`) unchanged
- No behavior changes; all output keys, semantics, and public signatures preserved; 19/19 targeted tests green

**Memory / Loader Hardening (`0f26948`)**

- **Behavior change**: `SAMPLE_SIZE` env now uses `nrows` in `pd.read_csv` — only the first N rows are loaded, eliminating full-file materialization. Previously the full file was read before in-memory random sampling. Sampling is now first-N (deterministic by position, not random seed).
- `max_rows_in_memory` enforced: `csv_loader` raises `ValueError` with row counts if `len(df) > settings.max_rows_in_memory`. Previously this setting was configured (`DEFAULT_MAX_ROWS_IN_MEMORY = 1_000_000`) but never read in any code path.
- Default full-load path unchanged when `SAMPLE_SIZE` is not set.
- 11 targeted tests added in `tests/unit/loader/test_csv_loader_memory_hardening.py`

**CVE Remediation (`6718b05`)**

- `python-dotenv` minimum version raised to `>=1.2.2`
- `pytest` minimum version raised to `>=9.0.3`
- `black` minimum version raised to `>=26.3.1`
- pip-audit advisory count reduced from 31 CVEs across 17 packages to 4 remaining deferred advisories (87% reduction)

**Lineage/Manifest Mypy Cleanup (`d83a08a`)**

- Declared `serde_impl`, `json_writer`, `lineage_schema_version`, and `manifest_file` fields in `Settings` with safe defaults, resolving 5 pre-existing `attr-defined` mypy errors in `lineage/manifest/serializer.py` and `lineage/manifest/builder.py`
- Targeted `lineage/manifest/` mypy errors: 5 → 0

**Validation summary**

- Full pytest suite: 636/636 tests pass
- ruff: all checks passed across `src/`, `tests/`, `benchmarks/`
- bandit `-ll -iii`: 0 medium, 0 high issues
- mypy: clean across all source files including `lineage/manifest/`; 0 `attr-defined` errors
- pip-audit: 31 CVEs → 4 remaining deferred advisories (87% reduction)

**Deferred**

- `starlette` orphaned transitive dependency: major-version jump required; separate investigation gate
- Remaining pip-audit advisories: local-env artifacts for `black`, `pytest`, `python-dotenv`; clear on fresh install

### Added
- Streamlit dashboard — Score Trend chart (score over time) and Latest Run issues breakdown panel, with ISO8601 timestamp x-axis
- Streamlit dashboard — Data Overview section: per-column dtype/null/null_pct/unique/min/max table, numeric summary, duplicate-row count, and high-cardinality warning (reads a CSV path)
- Streamlit dashboard — EDA Univariate Explorer: numeric distribution histogram, categorical top-values, IQR outlier summary, and null-rate chart
- Streamlit dashboard — EDA Bivariate Explorer: numeric↔numeric scatter with Pearson r, numeric↔categorical grouped stats, and categorical↔categorical crosstab
- Streamlit dashboard — Preprocessing Recommendations table: per-column impute/scale/encode/outlier/drop guidance derived from dtype, null rate, cardinality, and IQR (advisory only; no transformation applied; no sklearn dependency)
- `--db PATH` flag on `dqt assess` to persist a run into the dashboard-readable SQLite database
- CSV→dashboard walkthrough docs (`examples/dashboard/`)
- `dqt plan <csv>` CLI command: per-column preprocessing recommendations (impute / encode / scale / outlier / drop guidance) derived from dtype, null rate, cardinality, and IQR statistics; outputs JSON on stdout and a human summary on stderr; advisory only, no transformation applied

### Notes
- All dashboard changes are UI-only and additive; core CLI commands are unaffected
- The dashboard remains an optional local viewer behind the `[ui]` extra

---

## [1.7.0] - 2026-05-18

### Added
- Project-level config via `./dqt.yaml` (opt-in):
  - Supported keys: `null_threshold`, `fail_under`, `outdir`
  - Fills CLI defaults when the corresponding flag is omitted; explicit CLI args always take precedence
  - File absent or keys omitted: behavior is byte-for-byte unchanged from prior versions
  - Malformed YAML, non-mapping root, unknown keys, or wrong-typed values raise an error and exit 2

### Notes
- Additive change; omitting `./dqt.yaml` preserves all existing CLI behavior

---

## [1.6.0] - 2026-05-16

### Added
- `--fail-under FLOAT` quality gate flag for `assess`, `export-star`, and `export`:
  - Accepts a float threshold in the range 0.0–1.0 (default: `None`, preserving existing behavior)
  - Exits with code 2 and a clear stderr message when quality score is below the threshold
  - Score of 0.0 passes `--fail-under 0.0`; a threshold of 1.0 requires a perfect score
  - Invalid thresholds outside 0.0–1.0 exit 1 with an error message
- Pipeline Quality Gate section added to README with exit code table and usage examples
- Runnable `examples/pipeline_gate/` example package:
  - `examples/pipeline_gate/README.md`
  - `examples/pipeline_gate/run_gate.sh`
  - `examples/pipeline_gate/sample_pipeline_output.csv`

### Notes
- Additive change; omitting `--fail-under` preserves all existing exit code behavior

---

## [1.5.0] - 2026-05-15

### Added
- Experimental Streamlit dashboard (Phase 4):
  - `src/data_quality_toolkit/ui/app.py` — Run History page displaying past export runs from SQLite storage; 4 UI states (instructional / error / empty / dataframe)
  - `scripts/dashboard.py` — thin launcher; calls `data_quality_toolkit.ui.app.main()`
- `dqt dashboard` CLI subcommand — launches the Streamlit dashboard via subprocess; guards on missing Streamlit with an actionable error pointing to `pip install data-quality-toolkit[ui]`
- `[ui]` optional dependency: `pip install data-quality-toolkit[ui]` installs Streamlit (`>=1.30`)

### Changed
- README Known Limitations updated: Streamlit now installable via `pip install data-quality-toolkit[ui]`; `dqt dashboard` documented in Basic Usage section

### Notes
- Streamlit is an optional dependency; core CLI commands (`profile`, `assess`, `export`, `compare`) are unaffected

---

## [1.4.0] - 2026-05-15

### Added
- SQLite storage package (`data_quality_toolkit.storage`):
  - `connection.py` — `connect()`, `StorageError`, `_get_db_path()` resolver
  - `schema.py` — `ensure_db()` initialises schema and imports existing JSONL history on first use
  - `importer.py` — `import_jsonl_history()` seeds `runs` table from `quality_history.jsonl`
  - `writer.py` — `persist_export_run()` writes datasets, columns, runs, quality_metrics, issues atomically
  - `reader.py` — `read_run_history()` returns run records ordered by `ts ASC`
  - Schema tables: `datasets`, `columns`, `runs`, `quality_metrics`, `issues`, `schema_meta`
  - No external DB dependency; stdlib `sqlite3` only; Postgres deferred
- `export-star` now persists each run to SQLite additively (failure is non-fatal; CSV/JSONL output unaffected)
- `compare` now uses SQLite as primary run-history source with `quality_history.jsonl` fallback
  - DB path resolved via `DQT_DB_PATH` env var or inferred from `{outdir}/dqt.db`
  - Falls back to JSONL when DB absent, unreadable, or has fewer than 2 matching runs
  - Output shape unchanged — all existing callers and CLI unaffected

### Fixed
- `quality_metrics` writer now correctly stores `null_pct`, `distinct_count`, and `completeness` per column; previously these values were silently discarded due to a metric-name/column-id field swap

### Compatibility
- CSV, JSONL, and `quality_report.json` outputs preserved alongside SQLite; no breaking changes
- `compare` JSONL fallback ensures backward compatibility with existing export directories that predate SQLite

---

## [1.2.0] - 2026-05-01

### Added
- `compare` output now includes issue breakdown fields by severity and category:
  - `previous_issues_by_severity`, `current_issues_by_severity`, `issues_by_severity_delta`
  - `previous_issues_by_category`, `current_issues_by_category`, `issues_by_category_delta`
- `compare` CLI stderr summary now shows severity and category breakdown deltas when present

### Fixed
- CLI `--version` output now reads from package metadata; eliminates drift between reported version and installed package
- Stale `VERSION` constant assertion in test suite corrected to match package-metadata truth

### Validation
- Unit tests added for `cmd_compare` stderr summary and stdout JSON integrity (14 tests covering error path, success path, breakdown fields, stdout purity)

---

## [1.1.0] - 2026-04-18

### Added
- `all_null_column` detection: flags columns where every row is null (high severity, Completeness)
- Suppression logic: `all_null_column` replaces the generic `missing` issue for the same column
- Human-readable stderr summary for `profile` command (aligned with `assess` / `export-star`)

### Changed
- `compare` not-enough-history message now includes `--outdir` guidance and retry instructions
- `compare` success summary shows CSV filename instead of truncated hash; includes delta value on score line
- `pyproject.toml` metadata truth-aligned: removed unused runtime deps (`fastapi`, `uvicorn`, `streamlit`), removed duplicate entry, tightened description
- Pre-commit `pytest-focused` hook changed to `language: python` to fix PATH resolution in micromamba environments
- README and demo docs aligned to current verified behavior:
  - compare note updated to use `export` alias consistently
  - known limitations clarified with "for the same dataset" qualifier
  - version footer updated to `v1.0.2-internal`
  - `docs/demo_story.md` compare code block now shows two export runs before compare

### Validation
- Focused unit tests added for:
  - `all_null_column` rule (trigger, suppression, common contract)
  - `compare` UX message improvements
  - `profile` stderr summary
- Pre-commit clean on all changed files

---

## [1.0.0] - 2026-04-16

### Added
- End-to-end CLI workflow for:
  - `profile`
  - `assess`
  - `export` / `export-star`
- Structured issue output with normalized issue fields:
  - `type`
  - `column`
  - `severity`
  - `category`
  - `message`
- Schema issue detection for:
  - duplicate column names
  - blank / whitespace-only column names
  - padded column names
  - placeholder column names
- Constant-column detection via `constant_column`
- `fact_issues.csv` export for BI / star-schema workflows
- `quality_report.json` as a per-run summary artifact
- `duration_secs` as an export/runtime KPI
- `compare` command for latest-two-run comparison using `quality_history.jsonl`
- Configurable `--null-threshold` for:
  - `assess`
  - `export`
  - `export-star`
- Happy-path demo package:
  - `examples/demo/README.md`
  - `docs/demo_story.md`
- Issue-showcase demo package:
  - `examples/demo/issue_showcase/README.md`

### Changed
- README rewritten to reflect actual internal-v1 scope
- Demo and CLI docs aligned to verified Windows-safe invocation
- Product framing updated:
  - internal product brief
  - KPI table
  - known limitations
  - compare/history usage guidance
- Compare/history docs updated to explain:
  - at least two export runs are required
  - history is stored in `star/quality_history.jsonl`

### Fixed
- Improved CLI validation and messaging for:
  - blank / whitespace-only file paths
  - unsupported file extensions
  - missing files
  - missing required CSV argument
  - malformed CSV parser errors
- Improved empty CSV handling
- Improved zero-row / zero-column export behavior
- Added human-readable stderr summaries for:
  - `assess`
  - `export-star`

### Validation
- Focused unit and workflow tests added for:
  - schema issue detection
  - `quality_report.json`
  - `--null-threshold`
  - workflow-level threshold behavior
  - constant-column detection
  - compare/history behavior
- Real end-to-end demo runs verified on Windows

## [0.6.6] - 2025-08-24

### Added
- Semantic KPI / DAX generation support
- CLI commands:
  - `kpi-emit`
  - `kpi-graph`
  - `kpi-validate`

## [0.2.0] - 2025-08-23

### Added
- Zero-config Power BI packaging
- `build-pbi`
- `gen-dim-time`

## Notes

- CLI-first, CSV-first
- Not a SaaS platform or web UI release
