# Scripts Directory

This directory contains utility and automation scripts for the Data Quality Toolkit.

## 📁 Script Overview

| Script | Phase | Purpose | Status |
|--------|-------|---------|--------|
| `generate_dim_time.py` | 2 | Generate date dimension table | 🔜 Planned |
| `export_star_schema.py` | 1-2 | Export star schema CSVs | 🔜 Planned |
| `build_powerbi_template.py` | 2 | Assemble Power BI package | 🔜 Planned |
| `validate_kpis.py` | 3 | Validate KPI catalog and DAG | 🔜 Planned |
| `configure_incremental_refresh.py` | 4 | Setup incremental refresh | 🔜 Planned |
| `generate_rls.py` | 4 | Generate RLS policies | 🔜 Planned |
| `validate_config.py` | 1 | Validate configuration files | 🔜 Planned |
| `migrate_config.py` | 8 | Migrate configurations | 🔜 Planned |
| `validate_rls.py` | 4 | Test RLS policies | 🔜 Planned |
| `benchmark.py` | 7 | Performance benchmarking | 🔜 Planned |

## 📊 Script Specifications

### generate_dim_time.py
**Phase**: 2
**Purpose**: Generate a complete date dimension table with all required attributes

#### CLI Interface
```bash
python scripts/generate_dim_time.py \
  --start 2020-01-01 \
  --end 2025-12-31 \
  --fiscal-start 10 \
  --holidays US \
  --week-start monday \
  --output dist/star/dim_time.csv
```

#### Parameters
- `--start`: Start date (YYYY-MM-DD)
- `--end`: End date (YYYY-MM-DD)
- `--fiscal-start`: Fiscal year start month (1-12)
- `--holidays`: Holiday calendar (US, UK, EU, or path to custom file)
- `--week-start`: Week start day (monday or sunday)
- `--output`: Output file path

#### Output
CSV file with columns:
- time_id, date, year, quarter, month, month_name
- week_iso, day, day_of_week, day_name
- is_weekend, is_holiday, fiscal_year, fiscal_quarter

---

### export_star_schema.py
**Phase**: 1-2
**Purpose**: Transform flat data into star schema structure

#### CLI Interface
```bash
python scripts/export_star_schema.py \
  --input data/transactions.csv \
  --mapping config/star_mapping.yaml \
  --output dist/star/
```

#### Parameters
- `--input`: Input CSV file or directory
- `--mapping`: Star schema mapping configuration
- `--output`: Output directory for fact/dimension tables

#### Output
- `fact_*.csv`: Fact tables
- `dim_*.csv`: Dimension tables
- `relationships.json`: Table relationships

---

### build_powerbi_template.py
**Phase**: 2
**Purpose**: Assemble complete Power BI package from components

#### CLI Interface
```bash
python scripts/build_powerbi_template.py \
  --star dist/star/ \
  --semantics config/kpi_catalog.yaml \
  --template templates/model.pbit \
  --output dist/powerbi_package/
```

#### Parameters
- `--star`: Directory containing star schema CSVs
- `--semantics`: KPI catalog configuration
- `--template`: Base Power BI template file
- `--output`: Output directory for package

#### Output
Complete Power BI package:
```
powerbi_package/
├── model.pbit
├── star/
│   └── *.csv
├── dax/
│   └── quality_measures.dax
├── relationships.json
├── roles.tmsl.json
└── parameters.json
```

---

### validate_kpis.py
**Phase**: 3
**Purpose**: Validate KPI definitions and check for circular dependencies

#### CLI Interface
```bash
python scripts/validate_kpis.py \
  --config config/kpi_catalog.yaml \
  --output reports/kpi_validation.json \
  --verbose
```

#### Parameters
- `--config`: KPI catalog YAML file
- `--output`: Validation report output (optional)
- `--verbose`: Show detailed validation messages

#### Validations
- YAML syntax correctness
- DAG cycle detection
- DAX syntax validation
- Dependency resolution
- Grain consistency
- Unit/scale validation

#### Output
- Exit code: 0 (success) or 1 (validation failed)
- Console report of issues
- Optional JSON validation report

---

### configure_incremental_refresh.py
**Phase**: 4
**Purpose**: Generate incremental refresh configuration for Power BI

#### CLI Interface
```bash
python scripts/configure_incremental_refresh.py \
  --config config/incremental_refresh.yaml \
  --model dist/powerbi_package/model.pbit \
  --output dist/powerbi_package/
```

#### Parameters
- `--config`: Incremental refresh configuration
- `--model`: Power BI model file
- `--output`: Output directory

#### Output
- `parameters.json`: RangeStart/RangeEnd parameters
- Updated model queries with filters

---

### generate_rls.py
**Phase**: 4
**Purpose**: Generate row-level security roles and filters

#### CLI Interface
```bash
python scripts/generate_rls.py \
  --config config/rls_policy.yaml \
  --users config/user_roles.csv \
  --output dist/powerbi_package/roles.tmsl.json
```

#### Parameters
- `--config`: RLS policy configuration
- `--users`: User-role mapping CSV (optional)
- `--output`: Output TMSL file

#### Output
- `roles.tmsl.json`: Tabular model security roles
- Role definitions with DAX filters

---

### validate_config.py
**Phase**: 1
**Purpose**: Validate all configuration files against schemas

#### CLI Interface
```bash
# Validate all configs
python scripts/validate_config.py config/

# Validate specific file
python scripts/validate_config.py config/pipeline/default.yaml

# Use specific schema
python scripts/validate_config.py \
  --config config/kpi_catalog.yaml \
  --schema schemas/kpi_catalog.schema.json
```

#### Parameters
- `config`: Configuration file or directory
- `--schema`: JSON schema file (optional)
- `--fix`: Attempt to fix common issues

#### Output
- Validation results
- Error descriptions
- Suggested fixes

---

### migrate_config.py
**Phase**: 8
**Purpose**: Migrate configurations between versions

#### CLI Interface
```bash
python scripts/migrate_config.py \
  --from-version 1.0.0 \
  --to-version 2.0.0 \
  --config-dir config/ \
  --backup
```

#### Parameters
- `--from-version`: Source version
- `--to-version`: Target version
- `--config-dir`: Configuration directory
- `--backup`: Create backup before migration

#### Output
- Migrated configuration files
- Migration report
- Backup directory (if requested)

---

### validate_rls.py
**Phase**: 4
**Purpose**: Test RLS policies with sample data

#### CLI Interface
```bash
python scripts/validate_rls.py \
  --model dist/powerbi_package/model.pbit \
  --test-config tests/rls_test_cases.yaml \
  --report reports/rls_validation.html
```

#### Parameters
- `--model`: Power BI model file
- `--test-config`: Test cases configuration
- `--report`: HTML report output

#### Output
- Test results (pass/fail)
- Coverage report
- HTML test report

---

### benchmark.py
**Phase**: 7
**Purpose**: Run performance benchmarks

#### CLI Interface
```bash
python scripts/benchmark.py \
  --data samples/100k_rows.csv \
  --iterations 5 \
  --profile all \
  --output reports/benchmark.json
```

#### Parameters
- `--data`: Test data file
- `--iterations`: Number of test runs
- `--profile`: Components to benchmark (all, profile, assess, export)
- `--output`: Results output file

#### Output
- Performance metrics (p50, p95, p99)
- Memory usage statistics
- Bottleneck analysis
- Comparison charts

## 🧪 Testing Scripts

All scripts should be tested before use:

```bash
# Test individual script
pytest tests/scripts/test_generate_dim_time.py

# Test all scripts
pytest tests/scripts/

# Integration test
make test-scripts
```

## 📝 Script Development Guidelines

### Structure Template
```python
#!/usr/bin/env python
"""
Script: [name]
Purpose: [description]
Phase: [1-8]
Author: [name]
Date: [date]
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from data_quality_toolkit import __version__

logger = logging.getLogger(__name__)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="[Script description]",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Input file or directory"
    )

    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Output file or directory"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}"
    )

    return parser.parse_args()


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )


def main():
    """Main entry point."""
    args = parse_args()
    setup_logging(args.verbose)

    try:
        logger.info(f"Starting {Path(__file__).name}")

        # Script logic here

        logger.info("Script completed successfully")
        return 0

    except Exception as e:
        logger.error(f"Script failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

### Best Practices

1. **Error Handling**
   - Use try/except blocks
   - Provide helpful error messages
   - Return appropriate exit codes

2. **Logging**
   - Use structured logging
   - Include progress indicators
   - Log important decisions

3. **Validation**
   - Validate inputs early
   - Check file existence
   - Verify output permissions

4. **Documentation**
   - Include docstrings
   - Provide --help text
   - Add usage examples

5. **Testing**
   - Write unit tests
   - Include integration tests
   - Test edge cases

## 🔧 Utility Functions

Common utilities available to all scripts:

```python
from data_quality_toolkit.scripts.utils import (
    validate_date_range,
    ensure_output_dir,
    load_yaml_config,
    write_json_report,
    format_bytes,
    timer_context
)
```

## 🚀 Running Scripts

### Direct Execution
```bash
python scripts/script_name.py [arguments]
```

### Via Make
```bash
make generate-dim-time START=2020-01-01 END=2025-12-31
```

### In Pipeline
```yaml
# config/pipeline.yaml
hooks:
  post_export:
    - script: scripts/generate_dim_time.py
      args: ["--output", "{output_dir}/dim_time.csv"]
```

## 📊 Script Monitoring

Scripts emit telemetry for monitoring:

```json
{
  "script": "generate_dim_time.py",
  "start_time": "2025-08-19T10:00:00Z",
  "end_time": "2025-08-19T10:00:05Z",
  "duration_seconds": 5,
  "status": "success",
  "rows_processed": 2191,
  "output_size_bytes": 185432
}
```

## 🔍 Troubleshooting

### Common Issues

1. **Import Errors**
   - Ensure toolkit is installed: `pip install -e .`
   - Check Python path: `echo $PYTHONPATH`

2. **Permission Errors**
   - Check output directory permissions
   - Run with appropriate user

3. **Memory Issues**
   - Use `--sample-size` for large files
   - Increase system memory
   - Use chunked processing

### Debug Mode
```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
python scripts/script_name.py --verbose

# Profile script performance
python -m cProfile scripts/script_name.py
```

## 📚 Related Documentation

- [CLI Documentation](../docs/cli.md)
- [Configuration Guide](../docs/configuration.md)
- [Development Guide](../CONTRIBUTING.md)
- [API Reference](../docs/api.md)

---

**Status**: Phase 0 - Script placeholders created, implementation begins in Phase 1+
**Last Updated**: August 2025
