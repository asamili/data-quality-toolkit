# DQT Golden Path

A beginner-friendly walk through DQT as one system: take a CSV from raw file to BI-ready
outputs. Every command below is real and runnable against the bundled demo dataset
`examples/demo/sample_orders.csv`.

> Commands here reflect DQT 2.10.0 behavior.

## 0. Install

```bash
pip install -e .
# optional extras as needed:
pip install "data-quality-toolkit[stats]"    # drift detection (scipy)
pip install "data-quality-toolkit[ui]"       # Streamlit dashboard
pip install "data-quality-toolkit[powerbi]"  # Excel export (openpyxl)
```

## 1. Profile — understand the dataset

```bash
dqt profile examples/demo/sample_orders.csv
```

Shape, column types, null rates, cardinality, and distributions (JSON on stdout). No files written.

## 2. Assess — score quality and gate the pipeline

```bash
# Score quality and see detected issues
dqt assess examples/demo/sample_orders.csv

# Use it as a pipeline gate: exit code 2 when below threshold
dqt assess examples/demo/sample_orders.csv --fail-under 0.90
```

**Decision point:** wire `dqt assess --fail-under <score>` into CI/ETL. Exit `0` = pass,
`2` = below threshold (halt/alert), `1` = error.

## 3. Plan — know how to clean it (optional)

```bash
dqt plan examples/demo/sample_orders.csv
```

Per-column impute / encode / scale / drop recommendations. No files written; source data untouched.

## 4. Export — produce BI-ready quality artifacts

```bash
dqt export examples/demo/sample_orders.csv --outdir dist/
```

Writes a star schema under `dist/star/` (`dim_dataset.csv`, `dim_column.csv`,
`fact_profile_runs.csv`, `fact_quality_metrics.csv`, `fact_issues.csv`), a per-run
`quality_report.json`, an append-only `quality_history.jsonl`, and the export-created
`dist/dqt.db` used by Quality History.

**Track trends across runs:**

```bash
# after two or more exports of the same dataset
dqt compare examples/demo/sample_orders.csv --outdir dist/
```

## 5. Drift — detect distribution shift (needs [stats])

```bash
# Compare a baseline vs a current snapshot; append a history record
dqt drift baseline.csv current.csv --alpha 0.05 \
    --output drift_report.json --history drift_history.jsonl

# Make drift fail a pipeline
dqt drift baseline.csv current.csv --fail-on-drift
```

KS test (numeric) + chi-square (categorical). JSON evidence to stdout; human summary to stderr.

## 6. Monitor — promote drift history into a monitoring store

```bash
# Build a SQLite monitoring DB from the JSONL history
dqt drift-history import drift_history.jsonl --db monitoring.db

# Inspect trends and per-column metrics (PSI / JS / Wasserstein)
dqt drift-history trend   --db monitoring.db
dqt drift-history columns --db monitoring.db

# Gate on monitored metrics (exit 2 on breach)
dqt drift-history trend   --db monitoring.db --fail-on-drift-rate 0.30
dqt drift-history columns --db monitoring.db --fail-on-psi 0.20

# Render a dependency-free static HTML dashboard (no server, no JS)
dqt drift-history dashboard --db monitoring.db --output drift-dashboard.html --include-plots
```

**Explore interactively (optional, needs [ui]):**

```bash
dqt ui --db monitoring.db
```

The optional Streamlit UI is a local 16-page / 16-step journey. Its Deliver phase runs
Export (step 9) → Quality History (step 10) → Artifact Center (step 11), then KPI Catalog,
Dim Time, and Manifest Viewer: an Export-created `dqt.db` feeds Quality History, and a
successful confirmed Export hands its artifacts to Artifact Center's Latest Export section
with no manual path or ID re-entry (the confirmed export also writes a private/local
`artifacts.json` lineage manifest inside its output directory, disclosed before
confirmation). Artifact Center and Manifest Viewer load existing session manifests
read-only; rebuilding an `artifacts.json` is a separately confirmed write limited to an
existing session directory. Its Statistics Lab includes
Distributions, Power & Sample Size, lightweight CSV downloads, and opt-in workspace saves where a
Workspace Root is configured. The static dashboard and the Streamlit UI read the same monitoring
view-model, so they never disagree.

## 7. BI readiness — hand off to Power BI

```bash
# Generate a fiscal-aware time dimension
dqt gen-dim-time --start 2022-01-01 --end 2026-12-31 --out dist/time

# Assemble a zero-config Power BI package from the star schema
dqt build-pbi --star dist/star --out dist/powerbi_package
```

You get `star/`, `time/dim_time.csv`, `relationships.json`, `parameters.json` (a single
`BaseFolder` parameter), a `model.pbit` (or a `model.pbit.README` placeholder if no template is
bundled), and `README.txt`. Continue with the **[BI worked example](bi_worked_example.md)**.

> DQT also ships a **built-in current-star quality semantic catalog**: `dqt kpi-builtin catalog`
> lists its measures (including a `quality_score_proxy`), `dqt kpi-builtin emit-dax` emits their
> DAX, and `dqt kpi-builtin validate-contract --package dist/powerbi_package` checks the package
> against the contract. The full canonical BI semantic model stays held (see below).

## Artifacts at a glance

| Step | Command | Output |
|---|---|---|
| Profile | `dqt profile` | JSON (stdout) |
| Assess/gate | `dqt assess --fail-under` | score + issues; exit 2 on breach |
| Export | `dqt export --outdir` | `dist/star/*.csv`, `quality_report.json`, `quality_history.jsonl`, `dist/dqt.db` |
| Drift | `dqt drift … --history` | `drift_report.json`, `drift_history.jsonl` |
| Monitor | `dqt drift-history …` | `monitoring.db`, HTML dashboard |
| BI | `dqt gen-dim-time`, `dqt build-pbi` | `dist/time/dim_time.csv`, `dist/powerbi_package/` |

## What DQT does and doesn't do

- **Does:** profiling, quality scoring + pipeline gate, drift detection + monitoring, star-schema
  and time-dimension exports, a zero-config Power BI package, KPI/DAX emission from a catalog.
- **Doesn't (you do it in Power BI):** incremental-refresh policies, RLS roles, service refresh
  settings. DQT ships a built-in current-star quality semantic catalog (a `quality_score_proxy`
  measure, DAX emission, and contract validation via `dqt kpi-builtin`); the full canonical BI
  semantic model — a true Quality Score plus drift/PSI, duplicate-rate, failed-quality-gate-count,
  and Last Run Date measures — remains held for a later gate.

See also: [CLI Reference](../cli.md) · [Python API](../api.md) · [Capability Matrix](../capability_matrix.md).
