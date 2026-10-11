# CLI Cookbook

Copy-paste recipes for the DQT command-line interface, grounded in current implemented behavior
for DQT v2.10.0. For the authoritative reference see [docs/cli.md](../../docs/cli.md).

> These are recipes to run yourself. Nothing here was executed when this file was written, and no
> output files are committed. Run from the repository root.

> **Windows-safe invocation.** If `dqt` is not on your PATH, replace `dqt` with your interpreter:
> `python -m data_quality_toolkit.adapters.cli.main <command> …`

## Profile — understand a dataset

```bash
dqt profile examples/demo/sample_orders.csv
```

Shape, column types, null rates, cardinality, and distributions as JSON on stdout. No files written.

## Assess — score quality and gate a pipeline

```bash
# Score quality and list detected issues
dqt assess examples/demo/sample_orders.csv

# Tune missing-data sensitivity (default null threshold = 0.20)
dqt assess examples/demo/issue_showcase/issue_demo.csv --null-threshold 0.05

# Use as a pipeline gate: exit 2 when below threshold
dqt assess examples/demo/sample_orders.csv --fail-under 0.90
```

Exit codes: `0` pass · `1` error · `2` below `--fail-under`. See the runnable
[pipeline gate example](../pipeline_gate/README.md).

## Plan — preprocessing recommendations

```bash
dqt plan examples/demo/sample_orders.csv
```

Per-column impute / encode / scale / drop guidance. No files written; source data untouched.

## Chart — terminal distribution

```bash
dqt chart examples/demo/sample_orders.csv --column unit_price
```

Renders a column distribution chart to the terminal (CLI-only; no API/UI equivalent).

## Export — star-schema quality artifacts

```bash
dqt export examples/demo/sample_orders.csv --outdir dist/demo
```

Writes `dist/demo/star/` (`dim_dataset.csv`, `dim_column.csv`, `fact_profile_runs.csv`,
`fact_quality_metrics.csv`, `fact_issues.csv`), a per-run `quality_report.json`, an append-only
`quality_history.jsonl`, and a `<output_dir>/dqt.db` SQLite run-history database used by Quality History.

## Compare — run-to-run trend

```bash
# Run export twice on the same --outdir, then compare the latest two runs
dqt export examples/demo/sample_orders.csv --outdir dist/demo
dqt export examples/demo/sample_orders.csv --outdir dist/demo
dqt compare examples/demo/sample_orders.csv --outdir dist/demo
```

With fewer than two runs, `compare` returns `not_enough_runs`.

## Manifest — lineage for a run

```bash
dqt manifest create --run-id RUN_ID --sessions-root dist/demo/star/
```

## Drift — detect distribution shift (needs `[stats]`)

```bash
# Compare a baseline snapshot against a current snapshot; append a history record
dqt drift baseline.csv current.csv --alpha 0.05 \
    --output drift_report.json --history drift_history.jsonl

# Make drift fail a pipeline
dqt drift baseline.csv current.csv --fail-on-drift
```

KS test (numeric) + chi-square (categorical). The repo ships tiny `baseline.csv` / `current.csv`
at its root for a quick try.

## Drift history — monitoring store and analytics

```bash
# Promote JSONL history into a SQLite monitoring DB
dqt drift-history import drift_history.jsonl --db monitoring.db

# Inspect
dqt drift-history list    --db monitoring.db
dqt drift-history trend   --db monitoring.db
dqt drift-history columns --db monitoring.db

# Gate on monitored metrics (exit 2 on breach)
dqt drift-history trend   --db monitoring.db --fail-on-drift-rate 0.30
dqt drift-history columns --db monitoring.db --fail-on-psi 0.20

# Dependency-free static HTML dashboard (no server, no JS)
dqt drift-history dashboard --db monitoring.db --output drift-dashboard.html --include-plots

# Optional exports
dqt drift-history export-xlsx   --db monitoring.db --out drift_monitoring.xlsx   # needs [powerbi]
dqt drift-history export-duckdb --db monitoring.db --out monitoring.duckdb        # needs [duckdb]
dqt drift-history plot          --db monitoring.db --out plots/ --chart all       # needs [viz]

# Build (dry-run by default) a drift webhook notification
dqt drift-history notify --db monitoring.db --webhook-url https://hooks.example.com/dqt
```

Notifications are **dry-run by default**; an actual POST requires `--send` **and**
`DQT_ALLOW_NETWORK=true`, and is SSRF-guarded. DuckDB is **export/mirror only**, never a live backend.

## BI hand-off — time dimension and Power BI package

```bash
# Generate a fiscal-aware time dimension
dqt gen-dim-time --start 2022-01-01 --end 2026-12-31 --out dist/time

# Assemble a zero-config Power BI package from a star-schema directory
dqt build-pbi --star dist/demo/star --out dist/powerbi_package
```

See the [BI hand-off guide](../bi/README.md) for what the package contains and what you still do
in Power BI.

## KPI catalog (user-supplied)

```bash
dqt kpi-validate --config config/kpi_catalog.yaml
dqt kpi-emit     --config config/kpi_catalog.yaml --dax-out measures.dax --tmsl-out model.tmsl.json
dqt kpi-graph    --config config/kpi_catalog.yaml --out kpi_graph.mmd
```

These operate on **your** KPI catalog. See [semantics/README.md](../semantics/README.md).

## Built-in quality semantic catalog — `kpi-builtin`

> **New in v2.10.0.** **Current-star / proxy scope only**
> (`quality_score_proxy`). This is **not** the full canonical BI semantic model. Do not claim
> full BI semantic model completion.

```bash
dqt kpi-builtin catalog
dqt kpi-builtin emit-dax --out dist/builtin/quality_measures.dax
dqt kpi-builtin validate-contract --package dist/powerbi_package
```

Details and scope: [semantics/README.md](../semantics/README.md).

## UI launcher (optional `[ui]`)

```bash
dqt dashboard                 # launch the Streamlit dashboard
dqt ui --db monitoring.db     # preferred launcher; seeds the Drift Monitoring page
```

CLI-first automation never requires Streamlit. Walkthrough: [dashboard/README.md](../dashboard/README.md).

## Pipeline runner — declarative scaffold

```bash
dqt run --run-id RUN_ID --sessions-root dist/sessions/
```

> `dqt run` is a **declarative scaffold / dry-run** workflow — it records step selections and reads
> existing session artifacts. **DQT is not an ETL/ELT engine**: it does not transform data, load data
> into targets, or connect to warehouses. Pipeline execution and scheduling remain your responsibility.

## See also

- [Example Coverage Map](../COVERAGE_MAP.md) · [CLI Reference](../../docs/cli.md)
- [Golden Path](../../docs/guides/golden_path.md) · [Capability Matrix](../../docs/capability_matrix.md)
