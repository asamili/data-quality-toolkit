# Changelog

All notable changes to the Data Quality Toolkit project are documented in this file.

The format is inspired by Keep a Changelog and adapted for this project.

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
- Public snapshot synchronized in the v1.5.0 release cycle.

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
