# Changelog

All notable changes to the Data Quality Toolkit project are documented in this file.

The format is inspired by Keep a Changelog and adapted for this project.

## [Unreleased]

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

## [2.1.0] - 2026-06-08

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
