# BI Worked Example: DQT → Power BI

A concrete, honest walk from DQT outputs to a Power BI model. DQT prepares clean, BI-ready
tables; you build and secure the model in Power BI.

> This is local workflow guidance for DQT 2.10.0.

## 1. Produce the BI inputs

```bash
dqt export examples/demo/sample_orders.csv --outdir dist/
dqt gen-dim-time --start 2022-01-01 --end 2026-12-31 --out dist/time
dqt build-pbi --star dist/star --out dist/powerbi_package
```

`dqt export --outdir dist/` also creates/uses `dist/dqt.db`; that local SQLite file is the handoff
used by the Quality History UI page for trends and run comparison.

## 2. What `build-pbi` actually emits

Under `dist/powerbi_package/` (verified from source):

| Item | What it is |
|---|---|
| `star/*.csv` | Quality star schema: `dim_dataset`, `dim_column`, `fact_profile_runs`, `fact_quality_metrics` |
| `time/dim_time.csv` | Calendar + optional fiscal time dimension |
| `relationships.json` | Star relationships (fact → dimension, many-to-one, single cross-filter) |
| `parameters.json` | A single **`BaseFolder`** Power Query parameter (where the CSVs live) |
| `model.pbit` | Copied only if a template is bundled; otherwise a `model.pbit.README` placeholder |
| `README.txt` | Load instructions |

> The star schema describes **data quality** (profiling runs and quality metrics), not business
> sales. That is the point: it lets a BI team monitor dataset health over time.

## 3. How `dim_time` supports modeling

`dim_time.csv` includes `time_id` (YYYYMMDD), `date`, `year/month/day/quarter`, ISO fields
(`iso_year`, `week_iso`, `dow_iso`), `dow`/`week_start_date`, `is_weekend`, and — when `--fiscal`
is set — `fiscal_year`/`fiscal_quarter`. In Power BI: load it, **Mark as date table** on `date`,
and relate facts to `dim_time` on `time_id`. See [Date Table Configuration](../powerbi/date_table.md).

## 4. What you still do in Power BI

1. Open `model.pbit` (or load the CSVs) and supply the `BaseFolder` parameter.
2. Confirm relationships (DQT scaffolds them in `relationships.json`).
3. Author measures/DAX as needed (DQT can emit DAX from a user-supplied KPI catalog via
   `dqt kpi-emit`, or from its built-in current-star quality semantic catalog via
   `dqt kpi-builtin emit-dax`).
4. For **incremental refresh** → [guide](../powerbi/incremental_refresh.md). For **RLS** →
   [guide](../powerbi/rls_testing.md). Both are configured in Power BI.

## 5. Supporting quality monitoring in BI

Pair the package with the monitoring store for an end-to-end quality view:

```bash
dqt drift-history dashboard --db monitoring.db --output drift-dashboard.html --include-plots
dqt drift-history export-xlsx --db monitoring.db --out drift_monitoring.xlsx   # needs [powerbi]
```

Use the static HTML dashboard for CI artifacts, or load the `.xlsx`/CSVs into Power BI alongside
the star schema.

## Support / not-support

| DQT supports | Power BI / you handle |
|---|---|
| Star schema, `dim_time`, zero-config package, relationships scaffold, `BaseFolder` param, DAX from catalog | Loading, marking date table, measures, report design |
| Quality monitoring artifacts (HTML dashboard, xlsx) | Incremental refresh, RLS roles, service refresh config |

DQT does **not** generate incremental-refresh policies, RLS roles, telemetry, or service settings.
It now ships a **built-in current-star quality semantic catalog** — list it with
`dqt kpi-builtin catalog`, emit its DAX with `dqt kpi-builtin emit-dax`, and check a package
against the contract with `dqt kpi-builtin validate-contract`. Its Quality Score is a labeled
proxy (`quality_score_proxy`); the full canonical BI semantic model (true Quality Score, drift/PSI,
duplicate-rate, failed-quality-gate-count, Last Run Date) remains held for a later gate.

See also: [Golden Path](golden_path.md) · [Capability Matrix](../capability_matrix.md).
