# Scripts Directory

Utility and helper scripts for the Data Quality Toolkit. Most toolkit
functionality is exposed through the `dqt` CLI; these scripts are thin
convenience wrappers.

## Available Scripts

| Script | Purpose |
|--------|---------|
| `dashboard.py` | Launch the Streamlit dashboard (`python scripts/dashboard.py`). |
| `export_star_schema.py` | Convenience entry point for star-schema export. |
| `validate_kpis.py` | Convenience entry point for KPI catalog validation. |
| `commands/tests.txt` | Cheat sheet of common `pytest` invocations. |
| `powershell/release-workflow.ps1` | Local release helper for Windows. |

For the full feature set, prefer the CLI:

```bash
dqt --help
```

## Running a Script

```bash
python scripts/<script_name>.py [arguments]
```

## Related Documentation

- [README](../README.md)
- [Contributing](../CONTRIBUTING.md)
