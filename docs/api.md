# Python API

Install once (`pip install -e .`), then import directly — no CLI required.

```python
from data_quality_toolkit import (
    profile_csv, assess_csv, export_csv, compare_runs, plan_csv,
    kpi_validate, kpi_emit, kpi_graph, generate_dim_time,
    create_manifest, create_elt_pipeline,
)

# Profile: returns shape and per-column stats. No disk writes.
result = profile_csv("data/orders.csv")
print(result["profile"]["rows"], result["profile"]["cols"])

# Assess: profile + quality score + detected issues. No disk writes.
result = assess_csv("data/orders.csv")
print(result["assessment"]["score"])          # e.g. 0.87
print(result["assessment"]["quality_score"])  # penalty-weighted score
for issue in result["assessment"]["issues"]:
    print(issue["type"], issue["column"], issue["severity"])

# Assess with quality gate — raise your own exception on failure:
result = assess_csv("data/orders.csv")
if result["assessment"]["quality_score"] < 0.9:
    raise ValueError("Quality gate failed")

# Export: full pipeline — profile → assess → star-schema CSVs + quality_report.json + SQLite history.
result = export_csv("data/orders.csv", output_dir="dist/")
print(result["export_paths"])

# Compare: trend analysis from the last two export runs.
result = compare_runs("data/orders.csv", output_dir="dist/")
print(result["score_delta"])

# Plan: per-column preprocessing recommendations (impute/scale/encode/drop). No disk writes.
result = plan_csv("data/orders.csv")
for col in result["columns"]:
    print(col["column"], col["issues"], col["recommendations"])

# KPI catalog validation (schema, semantics, cycles). No disk writes.
result = kpi_validate("config/kpi_catalog.yaml")
print(result["status"], result["kpis"])       # "valid", 8

# KPI emit: generate DAX measures + TMSL model JSON from catalog.
result = kpi_emit(
    "config/kpi_catalog.yaml",
    dax_out="dist/powerbi_package/dax/quality_measures.dax",
    tmsl_out="dist/powerbi_package/dax/model.tmsl.json",
)
print(result["dax"], result["tmsl"])

# KPI graph: export dependency graph as Mermaid (.mmd) or Graphviz (.dot).
result = kpi_graph("config/kpi_catalog.yaml", out="dist/semantics/kpi_graph", graph_format="mermaid")
print(result["graph"])                        # path to written .mmd file

# Time dimension: generate dim_time.csv (optional output_dir writes to disk).
result = generate_dim_time("2018-01-01", "2030-12-31", output_dir="dist/time")
print(result["rows"], result["path"])

# Manifest: build a lineage manifest (artifacts, gates, sessions) for a specific run.
manifest = create_manifest(run_id="20240101-123456", sessions_root="dist/sessions/")
print(manifest["run_id"], len(manifest["artifacts"]))

# ELT Pipeline: create an orchestration object for complex extract/transform/load workflows.
pipeline = create_elt_pipeline(run_id="manual-run-001", sessions_root="dist/sessions/")
pipeline.extract("data/raw.csv")
pipeline.load("data/silver.csv")
pipeline.assess()
result = pipeline.run()
print(result.status)
```

Optional CSV-parsing kwargs (`sep`, `encoding`, `na_values`, `sample_size`) are accepted by all CSV functions.

> **Note:** `dqt.yaml` is not loaded by the Python API — pass options explicitly as keyword arguments.
