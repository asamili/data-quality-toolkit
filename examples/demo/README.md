# Demo Package

This directory contains demo datasets and runnable examples for the Data Quality Toolkit (DQT).

---

## Available datasets

| File | Description | Rows | Columns | Best for |
|------|-------------|-----:|--------:|----------|
| `Uber_Data.csv` | Uber NYC pickups (Jan–Jun 2015) | 29,101 | 13 | Happy-path demo, near-clean data |
| `sample_orders.csv` | Synthetic orders — multi-region, mixed statuses, nullable fields | 170 | 14 | Business-domain demo, issue detection |

Both datasets are safe for public use. `sample_orders.csv` is fully synthetic with no real names, addresses, or identifiers.

---

## Running the demo

> **Windows:** use the full interpreter path if `dqt` is not on your PATH.
> Replace `<path-to-python>` with your virtual environment interpreter.

### Option A — Uber_Data.csv (near-clean, happy path)

**Step 1 — Profile**

```bash
dqt profile examples/demo/Uber_Data.csv
# Windows fallback:
<path-to-python> -m data_quality_toolkit.cli.main profile examples/demo/Uber_Data.csv
```

**Step 2 — Assess**

```bash
dqt assess examples/demo/Uber_Data.csv
```

**Step 3 — Export star-schema artifacts**

```bash
dqt export examples/demo/Uber_Data.csv --outdir dist/demo
```

Produces artifacts under `dist/demo/star/`:

```
dim_dataset.csv
dim_column.csv
fact_profile_runs.csv
fact_quality_metrics.csv
fact_issues.csv
quality_report.json
```

**Step 4 — Compare runs** (requires two prior exports)

```bash
dqt export examples/demo/Uber_Data.csv --outdir dist/demo   # run twice
dqt compare examples/demo/Uber_Data.csv --outdir dist/demo
```

> History is stored in `dist/demo/star/quality_history.jsonl`. If fewer than two runs exist, `compare` returns `not_enough_runs`.

---

### Option B — sample_orders.csv (synthetic business data, issue detection)

`sample_orders.csv` is a synthetic 170-row business orders dataset. It is designed to trigger realistic quality issues so you can see DQT's issue detection in action.

**Columns:** `order_id`, `customer_segment`, `region`, `product_category`, `order_date`, `ship_date`, `order_status`, `quantity`, `unit_price`, `discount_pct`, `amount`, `currency`, `sales_channel`, `notes`

**Intentional quality characteristics:**
- `discount_pct`: ~25% null (nullable by design — not all orders have a discount)
- `notes`: ~35% null (optional free-text field)
- `currency`: single value throughout (constant-column flag expected)

**Step 1 — Profile**

```bash
dqt profile examples/demo/sample_orders.csv
# Windows fallback:
<path-to-python> -m data_quality_toolkit.cli.main profile examples/demo/sample_orders.csv
```

Expected output: 170 rows, 14 columns, two columns with nulls.

**Step 2 — Assess**

```bash
dqt assess examples/demo/sample_orders.csv
```

Expected: quality score ~95–96%, three issues flagged (`discount_pct` missing, `notes` missing, `currency` constant). These issues are intentional — this dataset is for showing issue detection, not for showing a clean result.

**Step 3 — Export**

```bash
dqt export examples/demo/sample_orders.csv --outdir dist/sample-orders
```

---

## What to review after a run

1. **`quality_report.json`** — top-level summary: score, `issues_total`, counts by severity and category.
2. **`fact_issues.csv`** — issue table: which column, what type, what severity.
3. **`fact_quality_metrics.csv`** — per-column completeness. Sort by `null_pct` descending.

---

## Further reading

- [Full CLI reference](../../README.md)
- [Issue-showcase demo](issue_showcase/README.md) — crafted CSV that intentionally triggers all rule types
