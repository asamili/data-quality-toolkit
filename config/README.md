# Configuration Directory

This directory contains configuration templates and examples for the Data Quality Toolkit.

## 📁 File Inventory

```
config/
├── kpi_catalog.yaml    # KPI definitions
├── README.md           # This file
└── v2_rules.yaml       # v2 Rule Contract example
```

## 🔧 Available Configurations

### KPI Catalog
**File**: `config/kpi_catalog.yaml`
**Purpose**: Define business KPIs and their DAX formulas.

### Quality Rules (v2 Rule Contract)
**File**: `config/v2_rules.yaml`
**Purpose**: Define dataset-level quality thresholds and per-column rules.

```yaml
dataset:
  fail_under: 0.85
  score_field: quality_score

columns:
  customer_id:
    required: true
    critical: true
  order_amount:
    null_threshold: 0.05
    weight: 2.0
```
See `config/v2_rules.yaml` for the complete example.

---
**Note on Rule Contract (v2.0):**
- **Active behavior:** `required` column detection, `null_threshold`, `high_cardinality_threshold`, `outlier_threshold`, `weight` (for weighted completeness scoring), and `critical` penalty multiplier.
- **Parsed/Deferred behavior:** `unique`, `dtype`, `accepted_values` (currently parsed by the loader but not enforced in issue detection).
- Unknown rule keys in `dqt.yaml` cause an immediate config error to prevent invalid silent configurations.
- Default behavior (no `dqt.yaml`) remains unchanged.
