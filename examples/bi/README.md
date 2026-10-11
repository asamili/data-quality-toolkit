# BI / Export Hand-off Examples

How to turn DQT outputs into Power BI inputs. DQT prepares clean, BI-ready tables; **you** build and
secure the model in Power BI. Grounded in DQT v2.10.0 behavior. For
the full narrative see the [BI worked example](../../docs/guides/bi_worked_example.md).

> Recipes to run yourself — nothing here was executed when this file was written.

## 1. Produce the BI inputs

```bash
dqt export examples/demo/sample_orders.csv --outdir dist/demo
dqt gen-dim-time --start 2022-01-01 --end 2026-12-31 --out dist/time
dqt build-pbi --star dist/demo/star --out dist/powerbi_package
```

The export output directory also creates/uses `dist/demo/dqt.db`; Quality History reads that local
database for score trends and run comparison.

## 2. What `build-pbi` emits

Under `dist/powerbi_package/`:

| Item | What it is |
|---|---|
| `star/*.csv` | Quality star schema: `dim_dataset`, `dim_column`, `fact_profile_runs`, `fact_quality_metrics` |
| `time/dim_time.csv` | Calendar + optional fiscal time dimension |
| `relationships.json` | Star relationships (fact → dimension, many-to-one, single cross-filter) |
| `parameters.json` | A single `BaseFolder` Power Query parameter (where the CSVs live) |
| `model.pbit` | Copied only if a template is bundled; otherwise a `model.pbit.README` placeholder |
| `README.txt` | Load instructions |

> The star schema describes **data quality** (profiling runs and quality metrics), not business
> sales. That is the point: it lets a BI team monitor dataset health over time.

## 3. Time dimension

`dim_time.csv` includes `time_id` (YYYYMMDD), `date`, `year/month/day/quarter`, ISO fields, weekend
flag, and — when `--fiscal` is set — `fiscal_year` / `fiscal_quarter`. In Power BI: load it, **Mark as
date table** on `date`, and relate facts on `time_id`. See
[Date Table Configuration](../../docs/powerbi/date_table.md).

## 4. Quality monitoring artifacts for BI

```bash
dqt drift-history dashboard   --db monitoring.db --output drift-dashboard.html --include-plots
dqt drift-history export-xlsx --db monitoring.db --out drift_monitoring.xlsx   # needs [powerbi]
```

Use the static HTML dashboard for CI artifacts, or load the `.xlsx` / CSVs into Power BI alongside the
star schema.

## 5. Semantic measures (DAX)

```bash
# From a user-supplied KPI catalog
dqt kpi-emit --config config/kpi_catalog.yaml --dax-out dist/semantics/measures.dax

# From the built-in current-star quality catalog (see boundary note below)
dqt kpi-builtin emit-dax --out dist/builtin/quality_measures.dax
dqt kpi-builtin validate-contract --package dist/powerbi_package
```

See [semantics/README.md](../semantics/README.md) for both catalogs.

## What DQT supports vs what you do in Power BI

| DQT supports | Power BI / you handle |
|---|---|
| Star schema, `dim_time`, zero-config package, relationships scaffold, `BaseFolder` param, DAX from a catalog | Loading, marking the date table, authoring measures, report design |
| Quality monitoring artifacts (static HTML dashboard, xlsx) | Incremental refresh, RLS roles, service refresh config |

DQT does **not** generate incremental-refresh policies, RLS roles, telemetry, or service settings, and
it is **not** a BI server or SaaS — these are configured in Power BI.

## Boundary notes

> **Built-in quality catalog scope (new in v2.10.0).** The built-in catalog is
> **current-star / proxy** scoped: its Quality Score is the labeled `quality_score_proxy`, not the
> true assessment `quality_score`. **Do not claim full Power BI semantic model completion.**

> **Full canonical BI semantic model — PLANNED / FUTURE.** A true named measure set (true Quality
> Score, Drift Rate, Max/Average PSI, Duplicate Rate, Failed-Quality-Gate Count, Last Run Date) is
> **not implemented and not shipped**.

## See also

- [BI worked example](../../docs/guides/bi_worked_example.md) · [Power BI docs](../../docs/powerbi/)
- [Semantic catalogs](../semantics/README.md) · [Example Coverage Map](../COVERAGE_MAP.md)
