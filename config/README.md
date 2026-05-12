# Configuration Directory

This directory contains configuration templates and examples for the Data Quality Toolkit.

## 📁 Directory Structure (Phase 1+)

```
config/
├── README.md                   # This file
├── pipeline/                   # Pipeline configurations
│   ├── default.yaml           # Default pipeline settings
│   ├── quick.yaml            # Quick profiling only
│   └── full.yaml             # Complete analysis
├── semantics/                 # Semantic layer
│   ├── kpi_catalog.yaml     # KPI definitions
│   └── business_rules.yaml  # Business logic
├── powerbi/                  # Power BI specific
│   ├── incremental_refresh.yaml
│   ├── rls_policy.yaml
│   └── relationships.yaml
├── quality/                  # Quality rules
│   ├── rules.yaml           # Assessment rules
│   └── thresholds.yaml     # Quality thresholds
└── deployment/              # Deployment configs
    ├── dev.env             # Development settings
    ├── staging.env         # Staging settings
    └── prod.env            # Production settings
```

## 🔧 Configuration Files (Coming in Phases 1-3)

### Pipeline Configuration
**File**: `pipeline/default.yaml`
**Phase**: 1
**Purpose**: Define end-to-end pipeline behavior

```yaml
# Example structure (Phase 1+)
pipeline:
  name: "Default Pipeline"
  version: "1.0.0"

stages:
  load:
    enabled: true
    options:
      sample_size: 10000
      encoding: "utf-8"

  profile:
    enabled: true
    options:
      compute_statistics: true
      detect_patterns: true

  assess:
    enabled: true
    rules_file: "config/quality/rules.yaml"

  transform:
    enabled: true
    steps:
      - clean
      - deduplicate
      - standardize

  export:
    enabled: true
    format: "powerbi"
    options:
      star_schema: true
      include_measures: true
```

### KPI Catalog
**File**: `config/kpi_catalog.yaml`
**Phase**: 3
**Purpose**: Define business KPIs and their DAX formulas

```yaml
# Example structure (Phase 3+)
catalog:
  version: "1.0.0"
  owner: "Analytics Team"

kpis:
  # Basic metrics
  revenue_total:
    name: "Total Revenue"
    formula: "SUM(fact_sales[amount])"
    format: "currency"
    grain: "company"
    tags: ["financial", "primary"]

  # Derived metrics
  revenue_growth_yoy:
    name: "Revenue Growth YoY"
    dependencies: ["revenue_total"]
    formula: |
      VAR CurrentYear = [revenue_total]
      VAR PreviousYear = CALCULATE([revenue_total], SAMEPERIODLASTYEAR(dim_time[date]))
      RETURN DIVIDE(CurrentYear - PreviousYear, PreviousYear)
    format: "percentage"
    grain: "year"
    tags: ["financial", "growth"]
```

### RLS Policy
**File**: `powerbi/rls_policy.yaml`
**Phase**: 4
**Purpose**: Define row-level security rules

```yaml
# Example structure (Phase 4+)
policies:
  version: "1.0.0"

roles:
  OwnerOnly:
    description: "Users see only their own data"
    filter: "[owner_email] = USERPRINCIPALNAME()"
    tables:
      - fact_sales
      - fact_orders

  RegionalManager:
    description: "Managers see their region"
    filter: |
      [region] IN (
        SELECT region
        FROM UserRegions
        WHERE email = USERPRINCIPALNAME()
      )
    tables:
      - fact_sales
      - dim_customer
      - dim_store
```

### Quality Rules
**File**: `quality/rules.yaml`
**Phase**: 1
**Purpose**: Define data quality assessment rules

```yaml
# Example structure (Phase 1+)
rules:
  version: "1.0.0"

  completeness:
    - column: "*"
      threshold: 0.95
      severity: "warning"
    - column: "id"
      threshold: 1.0
      severity: "critical"

  uniqueness:
    - columns: ["order_id"]
      threshold: 1.0
      severity: "critical"

  validity:
    - column: "email"
      pattern: "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$"
      severity: "warning"
    - column: "age"
      min: 0
      max: 150
      severity: "error"

  consistency:
    - check: "start_date <= end_date"
      severity: "error"
```

### Incremental Refresh
**File**: `powerbi/incremental_refresh.yaml`
**Phase**: 4
**Purpose**: Configure incremental refresh policies

```yaml
# Example structure (Phase 4+)
refresh:
  version: "1.0.0"

  tables:
    fact_sales:
      enabled: true
      date_column: "transaction_date"
      historical_period:
        value: 3
        unit: "years"
      incremental_period:
        value: 10
        unit: "days"
      detect_changes: false

    fact_events:
      enabled: true
      date_column: "event_timestamp"
      historical_period:
        value: 1
        unit: "year"
      incremental_period:
        value: 1
        unit: "day"
      detect_changes: true
      change_column: "modified_date"
```

## 🎯 Configuration Priority

### Phase 1 (Days 1-2)
- Basic pipeline configuration
- Simple quality rules
- CSV loader settings

### Phase 2 (Days 3-4)
- Star schema mappings
- Power BI parameters
- Date table configuration

### Phase 3 (Days 5-6)
- KPI catalog
- DAX templates
- Semantic relationships

### Phase 4 (Day 7)
- RLS policies
- Incremental refresh
- Security parameters

## 📝 Configuration Best Practices

### 1. Environment-Specific Settings
- Use `.env` files for environment variables
- Never commit secrets or credentials
- Use different configs for dev/staging/prod

### 2. Version Control
- Version all configuration files
- Document changes in comments
- Use semantic versioning

### 3. Validation
- Validate YAML syntax before use
- Test configurations in development first
- Use schema validation where possible

### 4. Organization
- Group related configurations
- Use clear, descriptive names
- Follow consistent structure

## 🔍 Configuration Validation

### Validate Configuration Files
```bash
# Validate YAML syntax (Phase 1+)
python scripts/validate_config.py config/

# Validate specific config
python scripts/validate_config.py config/pipeline/default.yaml

# Test configuration
dqt validate --config config/pipeline/default.yaml
```

### Schema Validation
Each configuration type has a JSON schema for validation:
- `schemas/pipeline.schema.json`
- `schemas/kpi_catalog.schema.json`
- `schemas/rls_policy.schema.json`

## 🌐 Environment Variables

### Required Variables
```bash
# Data processing
MAX_ROWS_IN_MEMORY=1000000
SAMPLE_SIZE=10000

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Export
EXPORT_BASE_DIR=./dist
PBI_BASE_FOLDER_PARAMETER=./dist

# Optional: LLM integration
LORAX_BASE_URL=http://localhost:8080
LORAX_TIMEOUT_SECS=30
```

### Security Variables
```bash
# Never commit these
API_KEY=<secret>
DB_PASSWORD=<secret>
ENCRYPTION_KEY=<secret>
```

## 📦 Configuration Loading

### Priority Order
1. Command-line arguments
2. Environment variables
3. Configuration files
4. Default values

### Example Usage
```python
from data_quality_toolkit.config import load_config

# Load configuration
config = load_config(
    config_file="config/pipeline/default.yaml",
    overrides={"profile.sample_size": 5000}
)

# Access settings
sample_size = config.profile.sample_size
```

## 🚀 Quick Start Templates

### Minimal Configuration
```yaml
# config/quick.yaml
pipeline:
  stages:
    - profile
    - export
```

### Full Analysis
```yaml
# config/full.yaml
pipeline:
  stages:
    - load
    - profile
    - assess
    - transform
    - export
  options:
    detailed: true
    include_all: true
```

## 🔄 Migration Guide

When upgrading configurations:

1. Check version compatibility
2. Backup existing configs
3. Run migration script
4. Validate new configs
5. Test in development

```bash
# Migrate configurations (Phase 8+)
python scripts/migrate_config.py \
  --from-version 1.0.0 \
  --to-version 2.0.0 \
  --config-dir config/
```

## 📚 Related Documentation

- [Configuration Guide](../docs/configuration.md)
- [Environment Setup](../docs/setup.md)
- [Security Best Practices](../SECURITY.md)
- [Examples](../examples/configs/)

---

**Status**: Phase 0 - Structure defined, implementations coming in Phase 1+
**Last Updated**: August 2025
