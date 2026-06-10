# Architecture & Design

```
data-quality-toolkit/
├── src/data_quality_toolkit/
│   ├── domain/                # Business rules: profiling, assessment, semantics/KPI
│   ├── application/           # Workflow orchestration: pipeline, compare, preprocessing
│   ├── adapters/
│   │   ├── cli/               # Command-line interface (dqt entrypoint)
│   │   ├── ui/                # Streamlit dashboard
│   │   ├── loaders/           # CSV loading and validation
│   │   ├── exporters/         # Star-schema CSV, quality_report, Power BI, dim_time
│   │   └── storage/           # SQLite-backed run history
│   ├── api.py                 # Public Python API
│   └── shared/                # Cross-cutting constants, settings, exceptions
├── tests/                     # Test suites (unit/, integration/)
├── docs/                      # Documentation
├── examples/                  # Demo packages
└── scripts/                   # Automation scripts
```

## Testing
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=data_quality_toolkit --cov-report=html

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
```
