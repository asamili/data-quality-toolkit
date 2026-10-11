# Python API Examples

Embed DQT directly in Python scripts and notebooks — no CLI required. These snippets are grounded
in the DQT v2.10.0 API. For the authoritative reference see
[docs/api.md](../../docs/api.md).

> Snippets here are illustrative and were not executed when this file was written. Import names are
> stable; internal modules are implementation details and are not part of the public API.

> **Start here:** the runnable notebook [01_quickstart.ipynb](../01_quickstart.ipynb) walks through
> profiling, assessment, and a preprocessing plan on `demo/sample_orders.csv`.

## Install

```bash
pip install -e .
# optional extras: [stats] drift · [ui] dashboard · [powerbi] xlsx · [duckdb] mirror · [viz] plots
```

## Core: profile, assess, plan

```python
from data_quality_toolkit import profile_csv, assess_csv, plan_csv

# Profile — shape and per-column stats. No disk writes.
result = profile_csv("examples/demo/sample_orders.csv")
print(result["profile"]["rows"], result["profile"]["cols"])

# Assess — profile + quality score + detected issues. No disk writes.
result = assess_csv("examples/demo/sample_orders.csv")
print(result["assessment"]["score"])
for issue in result["assessment"]["issues"]:
    print(issue["type"], issue["column"], issue["severity"])

# Use as a gate — raise your own exception on failure:
if result["assessment"]["quality_score"] < 0.9:
    raise ValueError("Quality gate failed")

# Plan — per-column preprocessing recommendations. No disk writes; source untouched.
plan = plan_csv("examples/demo/sample_orders.csv")
for col in plan["columns"]:
    print(col["column"], col["issues"], col["recommendations"])
```

## Export and compare

```python
from data_quality_toolkit import export_csv, compare_runs

# Full pipeline: profile -> assess -> star-schema CSVs + quality_report.json + <output_dir>/dqt.db.
result = export_csv("examples/demo/sample_orders.csv", output_dir="dist/demo")
print(result["export_paths"])

# Trend from the last two export runs (run export twice on the same output_dir first).
diff = compare_runs("examples/demo/sample_orders.csv", output_dir="dist/demo")
print(diff["score_delta"])
```

## BI hand-off: time dimension and Power BI package

```python
from data_quality_toolkit import generate_dim_time, build_powerbi_package

dim = generate_dim_time("2022-01-01", "2026-12-31", output_dir="dist/time")
print(dim["rows"], dim["path"])

pkg = build_powerbi_package("dist/demo/star", "dist/powerbi_package")
print(pkg["package_dir"], pkg["files"])
```

See the [BI hand-off guide](../bi/README.md).

## User-supplied KPI catalog

```python
from data_quality_toolkit import kpi_validate, kpi_emit, kpi_graph

result = kpi_validate("config/kpi_catalog.yaml")
print(result["status"], result["kpis"])      # "valid", 8

kpi_emit(
    "config/kpi_catalog.yaml",
    dax_out="dist/powerbi_package/dax/quality_measures.dax",
    tmsl_out="dist/powerbi_package/dax/model.tmsl.json",
)
kpi_graph("config/kpi_catalog.yaml", out="dist/semantics/kpi_graph", graph_format="mermaid")
```

## Lineage manifest

```python
from data_quality_toolkit import create_manifest

manifest = create_manifest(run_id="20240101-123456", sessions_root="dist/sessions/")
print(manifest["run_id"], len(manifest["artifacts"]))
```

## Monitoring helpers (drift history)

```python
from data_quality_toolkit import (
    summarize_drift_trends_sqlite,
    evaluate_drift_rate_threshold,
    read_drift_columns_sqlite,
    evaluate_psi_threshold,
)

summary = summarize_drift_trends_sqlite("monitoring.db")
print(evaluate_drift_rate_threshold(summary, max_drift_rate=0.30))

columns = read_drift_columns_sqlite("monitoring.db")
print(evaluate_psi_threshold(columns, max_psi=0.20))
```

Optional monitoring exporters (`export_drift_history_xlsx`, `export_monitoring_duckdb`,
`export_drift_plots`, `send_drift_notification`) are documented in [docs/api.md](../../docs/api.md).
`send_drift_notification` is **dry-run by default**; a real POST needs `DQT_ALLOW_NETWORK=true`.

## Built-in quality semantic catalog

> **New in v2.10.0.** **Current-star / proxy scope only**:
> the Quality Score measure is the labeled `quality_score_proxy`, **not** the true assessment
> `quality_score`. The true Quality Score plus drift/PSI, duplicate-rate, failed-quality-gate-count,
> and Last Run Date measures are **held**. Do not claim full canonical BI semantic model completion.

```python
from data_quality_toolkit import (
    get_builtin_quality_catalog,
    emit_builtin_quality_dax,
    validate_builtin_quality_semantic_contract,
)

catalog = get_builtin_quality_catalog()
print(catalog["version"], catalog["measure_count"])

dax = emit_builtin_quality_dax()           # output_path=None returns text without writing
print(dax["measure_count"])

check = validate_builtin_quality_semantic_contract("dist/powerbi_package")
print(check["valid"], check["input_mode"])
```

More: [semantics/README.md](../semantics/README.md).

## Notes

- All CSV functions accept optional kwargs (`sep`, `encoding`, `na_values`, `sample_size`).
- `dqt.yaml` is **not** loaded by the Python API — pass options explicitly as keyword arguments.

## See also

- [Python API reference](../../docs/api.md) · [Example Coverage Map](../COVERAGE_MAP.md)
- [Quickstart notebook](../01_quickstart.ipynb)
