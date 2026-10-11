# Power BI Incremental Refresh with DQT Outputs

## Overview

Power BI's **native incremental refresh** updates large models by refreshing only new or
changed partitions. DQT does not implement incremental refresh — it produces clean, BI-ready
tables that you then wire into Power BI's own incremental-refresh feature.

> **Scope.** This page explains how DQT's exported tables support a Power BI incremental-refresh
> setup. The refresh policy itself is configured by you in Power BI Desktop / Service.

## What DQT provides

`dqt export` writes a star schema, and `dqt build-pbi` assembles a zero-config Power BI package
under the output directory (default `dist/powerbi_package/`):

- `star/` — `dim_dataset.csv`, `dim_column.csv`, `fact_profile_runs.csv`, `fact_quality_metrics.csv`
- `time/dim_time.csv` — the time dimension (`dqt gen-dim-time`, fiscal-aware)
- `relationships.json` — star relationships (fact → dimension, many-to-one, single cross-filter)
- `parameters.json` — a single **`BaseFolder`** Power Query parameter (folder where the CSVs live)
- `model.pbit` — copied only if a template is bundled; otherwise a `model.pbit.README` placeholder
- `README.txt` — load instructions

```bash
dqt export data/orders.csv --outdir dist/
dqt build-pbi --star dist/star --out dist/powerbi_package
```

## What DQT does NOT provide

DQT does **not** generate any of the following — configure them yourself in Power BI Desktop /
Service:

- Incremental-refresh policies, partitions, or refresh schedules
- `RangeStart` / `RangeEnd` parameters — the emitted `parameters.json` defines **only** `BaseFolder`
- Service refresh settings, deployment rules, or `.pbit` incremental-refresh automation
- Any `config/*.yaml` refresh configuration (none is read by DQT)

## Configuring incremental refresh in Power BI

1. Load the DQT package (`model.pbit`, or the CSVs under `star/` and `time/`), entering the
   `BaseFolder` parameter value when prompted.
2. Add `RangeStart` and `RangeEnd` **DateTime** parameters in Power Query.
3. Filter each fact query on its date column between `RangeStart` (inclusive) and `RangeEnd`
   (exclusive). Keep the filter foldable so it pushes down to the source.
4. On the fact table, set up Incremental refresh (historical window + incremental window) and
   publish to the Service.

> Tip: relate facts to `dim_time` on `time_id`. DQT already scaffolds this relationship in
> `relationships.json` when the fact carries a `time_id` column.

## Validation

DQT ships no incremental-refresh validator. Validate inside Power BI: confirm `RangeStart` /
`RangeEnd` are typed `DateTime`, that the date filter folds to the source, and that a development
refresh returns the expected partitions before publishing.

## External references

- [Microsoft: Incremental refresh overview](https://learn.microsoft.com/power-bi/connect-data/incremental-refresh-overview)
- [Microsoft: Query folding](https://learn.microsoft.com/power-query/query-folding-basics)

## Related documentation

- [Date Table Configuration](date_table.md)
- [RLS Testing Guide](rls_testing.md)

---

**Last Updated**: June 2026
**Toolkit Version**: 2.10.0
