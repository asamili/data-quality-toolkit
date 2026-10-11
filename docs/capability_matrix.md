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
| CSV / star export | Produce BI-ready star-schema artifacts from a CSV | `dqt export` / `dqt export-star` | `export_csv` | Export page | Fact + dimension CSVs, quality history JSONL | — | unit, integration | Safe | API default `emit_manifest=False`; CLI opt-in via `--manifest`; confirmed UI Export emits `artifacts.json` into the confirmed output directory (disclosed before confirmation; emission failure warns without failing the export) |
| Compare runs | Track run-to-run quality changes for a dataset | `dqt compare` | `compare_runs`, `compare_runs_history` | Compare service | Diff dict JSON | — | unit, seam | Safe | Requires a prior `export_csv` run |
| Drift detection | Catch statistical distribution shift between two datasets | `dqt drift` | `detect_drift` | Drift Monitoring | Drift JSON evidence; JSONL history record | scipy `[stats]` | unit, integration | Safe | KS test (numeric) + chi-square (categorical) |
| Statistical analysis | Profile numeric data, run first-wave hypothesis/A-B workflows, look up theoretical distributions, and plan power/sample size | `dqt stats profile/select-test/test/ab` | `stats_profile_csv`, `select_statistical_test`, `run_statistical_test`, `compare_ab` | Statistics Lab | Status/result dicts; UI tables with CSV downloads and opt-in workspace saves | scipy `[stats]` for p-values, A/B tests, distribution lookups, and power/sample-size helpers | unit, API, CLI, UI | Safe | Selection is dependency-free; scipy paths degrade with structured unavailable statuses. Distributions and Power & Sample Size are UI/service wiring over the existing statistics kernels. Lightweight result downloads are browser-side; workspace saves require explicit user action and a configured Workspace Root. Deferred: notebook/ipwidgets workflow, DB/SQL utilities, generated PDF/report workflow, and statsmodels-dependent advanced tests |
| Drift history | Persist and inspect the full audit trail of drift runs | `dqt drift-history read/import/list/columns/trend` | `read_drift_history`, `import_drift_history_sqlite`, `read_drift_runs_sqlite`, `read_drift_columns_sqlite`, `read_drift_distributions_sqlite`, `summarize_drift_trends_sqlite` | Quality History page | JSONL → SQLite rows | — | unit, integration | Safe | Append-only JSONL; stable SQLite schema |
| Monitoring view-model | Coherent, presentation-agnostic view of drift monitoring state | (via report/dashboard) | `build_monitoring_overview`, `list_run_rows`, `build_column_drift`, `build_distribution_series`, `build_run_detail` | Monitoring service | Value objects (typed) | — | unit, seam/parity | Safe | API + UI share the same view-model; no duplication |
| Thresholds / notification | Alert when drift rate or PSI exceeds a limit | `dqt drift-history notify/report/dashboard --fail-on-drift-rate/psi` | `evaluate_drift_rate_threshold`, `evaluate_psi_threshold`, `send_drift_notification`, `drift_history_report`, `drift_dashboard` | — | Payload dict, Markdown/HTML report, static HTML dashboard | — | unit | Safe | SSRF-validated webhook; dry-run by default; real send needs `DQT_ALLOW_NETWORK=true` |
| BI export / Power BI | Hand off monitoring data to BI tools | `dqt build-pbi`, `dqt drift-history export-xlsx/export-duckdb/plot` | `build_powerbi_package`, `export_drift_history_xlsx`, `export_monitoring_duckdb`, `export_drift_plots` | Export page (star-schema guidance and confirmed server-side export) | PBI package, .xlsx workbook, .duckdb mirror, PNG charts | openpyxl `[powerbi]`, duckdb `[duckdb]`, matplotlib `[viz]` | unit, integration | Safe | Monitoring xlsx/DuckDB/PNG exports are CLI/API surfaces today; DuckDB is export/mirror only — never a live backend |
| KPI catalog | Define semantic KPIs and emit DAX / TMSL for Power BI | `dqt kpi-validate`, `dqt kpi-emit`, `dqt kpi-graph` | `kpi_validate`, `kpi_emit`, `kpi_graph` | KPI Catalog page | DAX file, TMSL file, dependency graph (.mmd / .dot) | — | unit | Safe | Dependency-cycle detection; Mermaid or Graphviz output; for **user-supplied** catalogs |
| Built-in quality semantics | Ship DQT's own current-star quality measures and validate a star / Power BI package against them | `dqt kpi-builtin catalog / emit-dax / validate-contract` | `get_builtin_quality_catalog`, `emit_builtin_quality_dax`, `validate_builtin_quality_semantic_contract` | — | Catalog JSON, built-in quality DAX, contract-validation result | — | unit | Safe | Built-in **current-star / proxy** catalog; Quality Score is a labeled proxy (`quality_score_proxy`); true Quality Score, drift / PSI, duplicate-rate, failed-gate count, and Last Run Date measures are **held** |
| Time dimension | Generate a BI date/calendar dimension table | `dqt gen-dim-time` | `generate_dim_time` | Dim Time page | `dim_time.csv` | — | unit | Safe | Fiscal-year-aware; configurable week start |
| Lineage / manifest | Provenance and metadata for a pipeline run | `dqt manifest` | `create_manifest`, `create_elt_pipeline` | Artifact Center + Manifest Viewer pages (shared read-only loader; rebuild is a separately confirmed write) | Manifest JSON (private/local evidence) | — | unit | Safe | Dual impl: msgspec (fast) + pydantic (fallback); pure read-only reader (`lineage/manifest/reader.py`) never writes or scans |
| StoryLens deterministic narrator | Plain-language explanation of a data overview result | — | — (UI seam only) | Data Overview, StoryLens component | `Explanation` object | — | unit | Safe | **Intentionally not exposed** on CLI or public API; deterministic; always returns |
| StoryLens optional local AI fallback | Richer, model-generated summary when local AI is enabled | — | — | Data Overview | Bounded ≤ 400-char AI summary; deterministic fallback in all other cases | transformers + torch `[storylens-ai]` | unit (fallback path) | Safe — default OFF | AI disabled by default; requires `DQT_STORYLENS_AI_ENABLED=true` + local model dir; machine-checked non-exposure contract (import-linter); never raises |
| UI pages | Visual exploration of profiling, EDA, statistics, drift, KPIs, lineage, and exports | `dqt dashboard` / `dqt ui` (launcher) | — | 16-step journey (all pages numbered) | Interactive local Streamlit app | streamlit `[ui]` | UI tests | Safe | Subprocess launcher; CLI-first workflows never require Streamlit; see UI Product Spine below |
| CLI command surface | Fully scriptable access to DQT capabilities | Top-level commands plus grouped families such as `drift-history`, `kpi-builtin`, and `stats` | — | — | Machine JSON (stdout) + human summary (stderr) | — | CLI tests | Safe | Extras gated with `pip install` hints; `--no-json` suppresses machine output |
| Public Python API | Embed DQT in Python scripts, notebooks, or libraries | — | `data_quality_toolkit.api` — 50+ public names | — | Typed `TypedDict` results; lazy imports | — | seam/parity/API unit tests | Safe | Stable `__all__`; lazy imports guard optional deps; no import triggers model load |

---

## UI Product Spine

The optional Streamlit app organizes work as a **16-step journey** — each page carries a
`Step N of 16` label — following the navigation-registry order (Start → Analyze → Prepare
→ Operate → Deliver → System):

1. **Start / Load Dataset** — select and validate a local CSV once; later pages reuse it.
2. **Data Overview** — shape, quality score, issue count, and column health.
3. **EDA Explorer** — charts and visual exploration, including missingness, configurable
   histograms, categorical top-N with optional missing bucket, correlation heatmap,
   bounded scatter sampling, numeric-by-category summaries, datetime trends, and outlier
   summaries.
4. **Statistics Lab** — DQT-native profile, descriptive statistics, hypothesis-test
   selection, statistical test runner, numeric A/B comparison, theoretical Distributions,
   Power & Sample Size planning, and the existing scipy-guarded inferential tier
   (normality checks, Welch t-test and Mann-Whitney, ANOVA and Kruskal-Wallis).
   A user-selected **Wilcoxon signed-rank** test is available for paired/dependent
   numeric columns; it is an explicit option and does not change automatic test
   recommendations.
   An informational **Assumption checks** panel displays normality (Shapiro-Wilk),
   equal-variance (Levene), sample-size, and missing-value checks to help operators
   interpret tests; it does not change which test is selected or any p-value verdict.
   Result tables can be downloaded as CSV, and supported outputs can be saved to
   Workspace by explicit user action. The scipy paths degrade gracefully with
   cautious wording when scipy is unavailable.
5. **Quality Score** — explains the score: completeness, capped rule penalties, exclusions,
   and a per-rule breakdown.
6. **Preprocess Studio** — a dependency-free, in-memory recipe workflow with before/after
   validation and JSON/CSV recipe export; source data is not mutated.
7. **Pipeline Runner** — a dry-run and evidence workflow with a CLI-equivalent preview;
   legacy write-capable execution is gated behind explicit confirmation.
8. **Drift Monitoring** — read-only drift evidence from a local monitoring database.
9. **Export** — CLI/API guidance plus optional server-side star-schema export. A
   confirmed export also writes an `artifacts.json` lineage manifest inside the
   confirmed output directory (disclosed before the confirmation checkbox) and
   records a session-only Latest Export context, with an explicit
   Open Artifact Center next action (never automatic navigation).
10. **Quality History** — quality-score trend, latest-run issues, and run comparison.
11. **Artifact Center** — a standalone surface to review generated outputs and
    downloads. Its Latest Export section shows the most recent successful Export
    from session state with no manual path or ID re-entry; session manifests load
    read-only, and **Rebuild artifacts.json** is a separately confirmed write
    limited to an existing session directory.
12. **KPI Catalog** — validate a KPI catalog YAML and download DAX, TMSL, and the
    dependency graph.
13. **Dim Time** — generate a time dimension table and download it as CSV.
14. **Manifest Viewer** — inspect a lineage manifest's summary, datasets, artifacts, and
    gate failures (basenames only). Loading is read-only through the same shared
    manifest reader as Artifact Center; rebuilding is a separately confirmed write.
15. **Settings / Governance** — truthful runtime, capability, and threshold diagnostics.
16. **Help / About** — orientation and the deterministic-by-default posture.

The UI is deterministic by default; optional local AI remains default-off and is not
activated by the UI.

---

## Intentional Asymmetries

**StoryLens is UI-only by design.**
The StoryLens narrator and optional local AI fallback are not exposed through the public
Python API or CLI. This is a machine-enforced decision: an import-linter contract
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
- `[stats]` — scipy (drift detection, p-values, and first-wave statistical/A-B tests)
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
internals" is enforced on every CI run. At 2.10.0, all 9 architecture contracts
pass with 0 violations across 273 analyzed files and 1442 dependencies.

**Deterministic fallback is always available.**
Every StoryLens path that touches AI goes through `try_explain`, which never raises and
always returns an `Explanation` value object. The deterministic fallback is used when:
AI is disabled, model directory is missing, optional deps are absent, generation fails, or
the validator rejects the output.

**DQT 2.10.0 includes the work below.**
DQT v2.9.0 was the previous public release. This matrix describes the 2.10.0 state of the
repository, including the built-in-quality and statistics/API/CLI/EDA/UI work
added since v2.9.0. Package version metadata is `2.10.0`.

---

## Since v2.9.0 — Implemented, Planned, and Held

Each item below carries an explicit
**Status** label: some are implemented in 2.10.0, while others remain
planned or held gaps tracked for later releases. Implemented items are scoped narrowly
to their stated status and are not claimed beyond it; held measures and deferred workflows
are intentionally absent from the capability matrix above.

- **Built-in current-star quality semantic catalog** — DQT now ships a built-in quality
  semantic catalog over its own current-star facts, surfaced through the API
  (`get_builtin_quality_catalog`, `emit_builtin_quality_dax`,
  `validate_builtin_quality_semantic_contract`) and the `dqt kpi-builtin` CLI family. Built-in
  quality **DAX emission** and built-in **semantic-contract validation** (for the current
  star / Power BI package contract) are implemented. The Power BI semantic story is improved
  but still limited to **current-star / proxy** measures: the catalog's Quality Score is a
  labeled proxy (`quality_score_proxy`), not the true assessment `quality_score`.
  **Status: implemented (current-star / proxy scope).**
- **Statistics/API/CLI/EDA/Statistics Lab surface** — DQT now ships statistics
  kernel modules for descriptive summaries, distributions, intervals, effect size,
  bootstrap, and power; typed hypothesis contracts; a 14-test selection matrix; an explicit
  p-value engine; A/B orchestration; public API/root exports (`stats_profile_csv`,
  `select_statistical_test`, `run_statistical_test`, `compare_ab`); typed result contracts;
  the additive `dqt stats` CLI family; EDA Explorer improvements; and Statistics Lab
  workflows for profile, hypothesis selection, statistical test running, numeric A/B, and
  theoretical distribution lookup, plus UI-only Power & Sample Size planning and
  lightweight result download / workspace-save actions. Scipy remains optional behind
  `[stats]`, with structured unavailable statuses when absent, and no new dependency was
  added.
  **Status: implemented (included in 2.10.0).**
- **Advanced statistics expansion** — statsmodels-dependent advanced power/regression/posthoc
  branches, Bayesian branches, notebook/ipwidgets workflows, generated PDF/report workflows,
  and DB/SQL utility surfaces are intentionally deferred. **Status: held / planned gaps.**
- **Canonical DQT BI semantic model (full)** — a true, canonical named measure set
  (true *Quality Score*, *Drift Rate*, *Max PSI* / *Average PSI*, *Duplicate Rate*, *Failed
  Quality Gate Count*, *Last Run Date*) mapping `fact_issues` / `fact_quality_metrics` / drift
  history to Power BI measures. These measures are **held** and intentionally not present in
  the built-in catalog above. **Status: planned (gap).**
- **Power BI guidance refresh** — `docs/powerbi/*` guidance needs alignment with the real
  `dqt gen-dim-time` / `generate_dim_time` surface. **Status: planned (separate gate).**
- **Shared formatting / threshold-validation kernel** across CLI and UI, to remove duplicated
  percent/severity formatting and range-check logic. **Status: planned.**
- **Onboarding / golden-path docs** — a beginner [Golden Path](guides/golden_path.md) and a
  [BI worked example](guides/bi_worked_example.md). **Status: added.**

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
