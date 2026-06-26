# DQT Capability Matrix

## Product Statement

DQT is a CLI-first CSV data-quality toolkit that profiles datasets, gates pipelines on a
quality score, detects statistical drift, and turns drift history into SQLite-backed
monitoring and BI-ready exports — with an optional, default-off local-AI narrator that
never compromises determinism.

## Purpose

This matrix maps every DQT capability across CLI, public Python API, UI, outputs, optional
dependencies, and test evidence. It is the single reference for understanding what DQT does,
how each capability is reached, and what guarantees back it.

Every row is grounded in the source tree (`src/`), the test suite (`tests/`), the CLI help
(`dqt --help`), and the public API (`data_quality_toolkit.api`).

---

## Capability Matrix

| Capability | User problem solved | CLI surface | Public API surface | UI surface | Output / artifact | Optional dep | Test evidence | Public-safe | Notes / intentional asymmetry |
|---|---|---|---|---|---|---|---|---|---|
| CSV profiling | Understand a dataset fast — column types, nulls, cardinality, distributions | `dqt profile` | `profile_csv` | Data Overview, EDA Explorer | Profile JSON (stdout) | — | unit, integration | Safe | Full in-memory and streaming `chunksize` modes |
| Quality assessment / scoring | Trust data before using it; fail a pipeline when quality drops | `dqt assess --fail-under` | `assess_csv` | Assessment service | Score + issues JSON; exit code 2 on breach | — | unit, seam/parity | Safe | Pipeline gate; chunked mode reduces rule set |
| Preprocessing plan | Know how to clean a dataset before ML or BI | `dqt plan` | `plan_csv` | Preprocess Studio | Per-column recommendations JSON / UI table download | — | unit, UI | Safe | Preprocess Studio is a dependency-free, in-memory recipe workflow with before/after validation and JSON/CSV recipe export; source data is not mutated |
| CSV / star export | Produce BI-ready star-schema artifacts from a CSV | `dqt export` / `dqt export-star` | `export_csv` | Export page | Fact + dimension CSVs, quality history JSONL | — | unit, integration | Safe | `emit_manifest` opt-in |
| Compare runs | Track run-to-run quality changes for a dataset | `dqt compare` | `compare_runs`, `compare_runs_history` | Compare service | Diff dict JSON | — | unit, seam | Safe | Requires a prior `export_csv` run |
| Drift detection | Catch statistical distribution shift between two datasets | `dqt drift` | `detect_drift` | Drift Monitoring | Drift JSON evidence; JSONL history record | scipy `[stats]` | unit, integration | Safe | KS test (numeric) + chi-square (categorical) |
| Drift history | Persist and inspect the full audit trail of drift runs | `dqt drift-history read/import/list/columns/trend` | `read_drift_history`, `import_drift_history_sqlite`, `read_drift_runs_sqlite`, `read_drift_columns_sqlite`, `read_drift_distributions_sqlite`, `summarize_drift_trends_sqlite` | Quality History page | JSONL → SQLite rows | — | unit, integration | Safe | Append-only JSONL; stable SQLite schema |
| Monitoring view-model | Coherent, presentation-agnostic view of drift monitoring state | (via report/dashboard) | `build_monitoring_overview`, `list_run_rows`, `build_column_drift`, `build_distribution_series`, `build_run_detail` | Monitoring service | Value objects (typed) | — | unit, seam/parity | Safe | API + UI share the same view-model; no duplication |
| Thresholds / notification | Alert when drift rate or PSI exceeds a limit | `dqt drift-history notify/report/dashboard --fail-on-drift-rate/psi` | `evaluate_drift_rate_threshold`, `evaluate_psi_threshold`, `send_drift_notification`, `drift_history_report`, `drift_dashboard` | — | Payload dict, Markdown/HTML report, static HTML dashboard | — | unit | Safe | SSRF-validated webhook; dry-run by default; real send needs `DQT_ALLOW_NETWORK=true` |
| BI export / Power BI | Hand off monitoring data to BI tools | `dqt build-pbi`, `dqt drift-history export-xlsx/export-duckdb/plot` | `build_powerbi_package`, `export_drift_history_xlsx`, `export_monitoring_duckdb`, `export_drift_plots` | Export page (star-schema guidance and confirmed server-side export) | PBI package, .xlsx workbook, .duckdb mirror, PNG charts | openpyxl `[powerbi]`, duckdb `[duckdb]`, matplotlib `[viz]` | unit, integration | Safe | Monitoring xlsx/DuckDB/PNG exports are CLI/API surfaces today; DuckDB is export/mirror only — never a live backend |
| KPI catalog | Define semantic KPIs and emit DAX / TMSL for Power BI | `dqt kpi-validate`, `dqt kpi-emit`, `dqt kpi-graph` | `kpi_validate`, `kpi_emit`, `kpi_graph` | KPI Catalog page | DAX file, TMSL file, dependency graph (.mmd / .dot) | — | unit | Safe | Dependency-cycle detection; Mermaid or Graphviz output |
| Time dimension | Generate a BI date/calendar dimension table | `dqt gen-dim-time` | `generate_dim_time` | Dim Time page | `dim_time.csv` | — | unit | Safe | Fiscal-year-aware; configurable week start |
| Lineage / manifest | Provenance and metadata for a pipeline run | `dqt manifest` | `create_manifest`, `create_elt_pipeline` | Manifest Viewer page | Manifest JSON | — | unit | Safe | Dual impl: msgspec (fast) + pydantic (fallback) |
| StoryLens deterministic narrator | Plain-language explanation of a data overview result | — | — (UI seam only) | Data Overview, StoryLens component | `Explanation` object | — | unit | Safe | **Intentionally not exposed** on CLI or public API; deterministic; always returns |
| StoryLens optional local AI fallback | Richer, model-generated summary when local AI is enabled | — | — | Data Overview | Bounded ≤ 400-char AI summary; deterministic fallback in all other cases | transformers + torch `[storylens-ai]` | unit (fallback path) | Safe — default OFF | AI disabled by default; requires `DQT_STORYLENS_AI_ENABLED=true` + local model dir; machine-checked non-exposure contract (import-linter G20B); never raises |
| UI pages | Visual exploration of profiling, drift, KPIs, lineage, and exports | `dqt dashboard` / `dqt ui` (launcher) | — | 11-step product spine + utility pages | Interactive local Streamlit app | streamlit `[ui]` | UI tests | Safe | Subprocess launcher; CLI-first workflows never require Streamlit; see UI Product Spine below |
| CLI command surface | Fully scriptable access to every DQT capability | 21 top-level commands + 11 `drift-history` subcommands | — | — | Machine JSON (stdout) + human summary (stderr) | — | CLI tests | Safe | Extras gated with `pip install` hints; `--no-json` suppresses machine output |
| Public Python API | Embed DQT in Python scripts, notebooks, or libraries | — | `data_quality_toolkit.api` — 50+ public names | — | Typed `TypedDict` results; lazy imports | — | seam/parity/API unit tests | Safe | Stable `__all__`; lazy imports guard optional deps; no import triggers model load |

---

## UI Product Spine

The optional Streamlit app organizes work as an **11-step product spine** — each spine
page carries a `Step N of 11` label — with additional utility pages available alongside it:

1. **Start / Load Dataset** — select and validate a local CSV once; later pages reuse it.
2. **Data Overview** — shape, quality score, issue count, and column health.
3. **EDA Explorer** — charts and visual exploration.
4. **Statistics Lab** — descriptive statistics plus a scipy-guarded inferential tier
   (normality checks, Welch t-test and Mann-Whitney, ANOVA and Kruskal-Wallis, and A/B
   comparison); the inferential tests degrade gracefully with cautious wording when scipy
   is unavailable.
5. **Quality Score** — explains the score: completeness, capped rule penalties, exclusions,
   and a per-rule breakdown.
6. **Preprocess Studio** — a dependency-free, in-memory recipe workflow with before/after
   validation and JSON/CSV recipe export; source data is not mutated.
7. **Pipeline Runner** — a dry-run and evidence workflow with a CLI-equivalent preview;
   legacy write-capable execution is gated behind explicit confirmation.
8. **Drift Monitoring** — read-only drift evidence from a local monitoring database.
9. **Artifact Center** — a standalone surface to review generated outputs and downloads.
10. **Settings / Governance** — truthful runtime, capability, and threshold diagnostics.
11. **Help / About** — orientation and the deterministic-by-default posture.

Utility pages available alongside the spine: Quality History, Export, KPI Catalog, Dim Time,
and Manifest Viewer. The UI is deterministic by default; optional local AI remains default-off
and is not activated by the UI.

---

## Intentional Asymmetries

**StoryLens is UI-only by design.**
The StoryLens narrator and optional local AI fallback are not exposed through the public
Python API or CLI. This is a machine-enforced decision: an import-linter contract (G20B)
prevents any import of `application.explanation.ai_adapter` or
`application.explanation.ai_narrator` from `api.py` or any CLI module. The deterministic
narrator is therefore never a surprise dependency.

**Optional local AI is default-off and never required.**
`DQT_STORYLENS_AI_ENABLED` defaults to `false`. When unset (or set to any non-truthy
value), the deterministic fallback is returned immediately — no model, no inference, no
optional dependency needed. Even when the flag is enabled, a missing model directory,
absent optional dependencies, a generation error, or a validator rejection each fall back
to the deterministic result silently. AI text is bounded to ≤ 400 characters and only
replaces the `summary` field; all safety-critical fields (`evidence`, `limitations`,
`severity`) come from the deterministic path.

**DuckDB is export/mirror only.**
`export_monitoring_duckdb` and `dqt drift-history export-duckdb` create a read-only mirror
of the SQLite monitoring store. DuckDB is never a live monitoring backend. The SQLite store
is opened read-only and is never mutated by the export.

**Terminal chart support is CLI-oriented.**
`dqt chart` renders a column distribution chart to the terminal. There is no corresponding
`chart_csv` public API function and no UI equivalent. This is intentional — interactive
chart exploration is covered by the EDA Explorer UI page.

---

## Governance and Safety

**Optional dependencies are isolated by extras.**
Each optional capability requires an explicit install step:
- `[stats]` — scipy (drift detection)
- `[ui]` — streamlit (interactive dashboard)
- `[powerbi]` — openpyxl (Excel export)
- `[duckdb]` — duckdb (SQLite → DuckDB mirror)
- `[viz]` — matplotlib (PNG charts)
- `[storylens-ai]` — transformers + torch (optional local AI)

No optional dependency is imported at module load time. All optional-dep calls use lazy
imports inside functions and raise a gated error with a `pip install` hint when the dep is
absent.

**StoryLens AI internals are kept out of the public API and CLI by machine-checked contract.**
The import-linter contract "Public API and CLI must not import StoryLens optional AI
internals" (G20B) is enforced on every CI run. 5 of 5 architecture contracts pass with 0
violations across 150 source files and 295 dependency edges.

**Deterministic fallback is always available.**
Every StoryLens path that touches AI goes through `try_explain`, which never raises and
always returns an `Explanation` value object. The deterministic fallback is used when:
AI is disabled, model directory is missing, optional deps are absent, generation fails, or
the validator rejects the output.

**Public snapshot and release are not yet complete.**
This matrix describes the current state of the private repository. A separate public-safety
gate is required before any public snapshot, tag, or release.

---

## Portfolio Value

This matrix proves three things at a glance:

1. **Product coherence.** Every capability traces to a real module, real CLI/API symbol,
   and real test evidence. Nothing is claimed without a backing implementation.

2. **CLI/API/UI alignment.** Core profiling and assessment paths reuse the hardened loading and
   workflow behavior. The monitoring UI service is routed through the public API and shared
   view-model; some other UI services still call internal workflow, exporter, or storage seams
   directly. Those limitations are candidates for later incremental service-boundary work.

3. **Governed optional-AI maturity.** The StoryLens path shows how to add AI to a library
   without compromising its determinism: flag off by default, lazy imports, validator gate,
   bounded output, machine-checked non-exposure. This is a senior-grade AI-safety pattern,
   not an afterthought.
