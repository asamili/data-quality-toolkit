# Semantic Catalog Examples

DQT works with two distinct kinds of semantic catalog:

1. **User-defined KPI catalogs** — *your* business KPIs, validated and emitted as Power BI DAX/TMSL.
   **Current / implemented.**
2. **Built-in quality semantic catalog** — DQT's own quality measures over its star-schema output.
   **New in v2.10.0; current-star / proxy scope only.**

Grounded in [docs/cli.md](../../docs/cli.md) and [docs/api.md](../../docs/api.md). This is local
DQT v2.10.0 guidance, not a release, tag, or publish note.

---

## 1. User-defined KPI catalog (current / implemented)

Define KPIs in a YAML catalog, validate them, and emit Power BI DAX + a TMSL model. The repo ships a
worked example at [`config/kpi_catalog.yaml`](../../config/kpi_catalog.yaml) (8 KPIs over the quality
star schema: completeness %, null rate, a 0–100 quality score, dataset/column counts, etc.).

### CLI

```bash
# Validate (schema, semantics, dependency cycles)
dqt kpi-validate --config config/kpi_catalog.yaml

# Emit DAX measures + TMSL model JSON
dqt kpi-emit --config config/kpi_catalog.yaml \
    --dax-out dist/semantics/measures.dax \
    --tmsl-out dist/semantics/model.tmsl.json

# Export the dependency graph (Mermaid or Graphviz)
dqt kpi-graph --config config/kpi_catalog.yaml --out dist/semantics/kpi_graph.mmd
```

### Python API

```python
from data_quality_toolkit import kpi_validate, kpi_emit, kpi_graph

result = kpi_validate("config/kpi_catalog.yaml")
print(result["status"], result["kpis"])      # "valid", 8

kpi_emit("config/kpi_catalog.yaml",
         dax_out="dist/semantics/measures.dax",
         tmsl_out="dist/semantics/model.tmsl.json")
kpi_graph("config/kpi_catalog.yaml", out="dist/semantics/kpi_graph", graph_format="mermaid")
```

A KPI entry looks like:

```yaml
- id: completeness_pct
  title: "Completeness %"
  expression: "AVERAGE('fact_quality_metrics'[completeness])"
  grain: global
  unit: percent
  scale: 100
  depends_on: []
  format_string: "0.00%"
```

These commands operate on **catalogs you supply**. They do not ship DQT's own measures — that is the
built-in catalog below.

---

## 2. Built-in quality semantic catalog — `kpi-builtin`

> **New in v2.10.0. Current-star / proxy scope only. Do not
> claim full canonical BI semantic model completion.**

DQT ships a small **built-in current-star quality semantic catalog**: the quality measures it can
express over its **own** star-schema / Power BI package outputs. This is separate from the
user-supplied `kpi-emit` / `kpi-graph` / `kpi-validate` commands above.

### CLI

```bash
# Print the built-in quality semantic catalog as JSON
dqt kpi-builtin catalog

# Emit DAX for the built-in catalog (write to a file)
dqt kpi-builtin emit-dax --out dist/builtin/quality_measures.dax

# Validate a Power BI package (or a star directory) against the built-in quality contract
dqt kpi-builtin validate-contract --package dist/powerbi_package
dqt kpi-builtin validate-contract --star dist/demo/star
```

Exit codes: `0` success · `2` contract-validation failure or argparse error · `1` runtime error.

### Python API

```python
from data_quality_toolkit import (
    get_builtin_quality_catalog,
    emit_builtin_quality_dax,
    validate_builtin_quality_semantic_contract,
)

catalog = get_builtin_quality_catalog()
print(catalog["version"], catalog["measure_count"])

result = emit_builtin_quality_dax("dist/builtin/quality_measures.dax")
print(result["output_path"], result["measure_count"])

check = validate_builtin_quality_semantic_contract("dist/powerbi_package")  # input_mode="auto"
print(check["valid"], check["input_mode"])
```

### Scope and boundary — read before using

- The catalog is **current-star / proxy** scoped. Its Quality Score measure is the **labeled proxy**
  `quality_score_proxy` (title *"Quality Score (proxy)"*) — it is **not** the true assessment
  `quality_score`.
- The `quality_score_proxy` / current-star scope is **not a final, full BI semantic model**.
- The following measures are intentionally **held** and are **not** in the catalog: a true Quality
  Score, drift / PSI semantic measures, a duplicate-rate measure, a failed-quality-gate count, and a
  Last Run Date.

---

## 3. Full canonical DQT BI semantic model

> **PLANNED / FUTURE — not implemented, not shipped, do not rely on.**

A true, canonical named measure set (true *Quality Score*, *Drift Rate*, *Max PSI* / *Average PSI*,
*Duplicate Rate*, *Failed Quality Gate Count*, *Last Run Date*) mapping `fact_issues` /
`fact_quality_metrics` / drift history to Power BI measures is **planned for a later release**.
It is **not** present in the built-in catalog and must not be described as shipped or complete.

## See also

- [BI hand-off guide](../bi/README.md) · [Example Coverage Map](../COVERAGE_MAP.md)
- [Capability Matrix](../../docs/capability_matrix.md)
- [CLI Reference](../../docs/cli.md) · [Python API](../../docs/api.md)
