# DQT Repo Inventory

**Source:** Generated from `tools/_results/step0/` baseline artifacts
**Baseline date:** 2026-02-20 (artifact generation date)
**Document date:** 2026-04-29
**Status:** Human-readable baseline — not auto-generated; stale by ~2 months relative to current repo state
**Limitation:** Reflects repo state as of 2026-02-20. Current source may differ.

---

## Package

**Name:** `data_quality_toolkit`
**Root:** `src/data_quality_toolkit/`
**CLI entry:** `python -m data_quality_toolkit.cli.main`

---

## Top-Level Directory Structure

```
data_quality_toolkit/
├── src/data_quality_toolkit/   # Package source
├── tests/                      # Test suite
├── scripts/                    # PowerShell and Python helper scripts
├── docs/                       # Documentation
├── config/                     # Configuration samples
├── deploy/                     # Deployment artifacts
├── docker/                     # Docker configuration
├── examples/                   # Usage examples
├── notebooks/                  # Jupyter notebooks
├── tools/                      # Inventory and analysis tooling
│   ├── _results/               # Generated inventory outputs
│   └── logs/                   # Step execution logs
├── dist/                       # Build/distribution output
├── demo_output/                # Demo export artifacts
└── data/                       # Sample data
```

---

## Layer Summary

| Layer | Modules | Tests | Test Ratio | Status |
|---|---|---|---|---|
| api | 5 | 6 | 1.20 | ✅ |
| assessment | 3 | 1 | 0.33 | ❌ |
| cli | 16 | 12 | 0.75 | ⚠️ |
| exporters | 11 | 13 | 1.18 | ✅ |
| lineage | 23 | 11 | 0.48 | ❌ |
| loaders | 9 | 10 | 1.11 | ✅ |
| other | 1 | 0 | 0.00 | ❌ |
| packaging | 1 | 1 | 1.00 | ✅ |
| profiling | 5 | 1 | 0.20 | ❌ |
| security | 4 | 3 | 0.75 | ⚠️ |
| semantics | 8 | 7 | 0.88 | ⚠️ |
| shared | 10 | 33 | 3.30 | ✅ |
| telemetry | 5 | 10 | 2.00 | ✅ |
| ui | 51 | 25 | 0.49 | ❌ |
| utils | 8 | 6 | 0.75 | ⚠️ |
| workflow | 12 | 11 | 0.92 | ⚠️ |
| **Total** | **172** | **179** | — | — |

Test ratio: ✅ ≥ 1.0 / ⚠️ 0.5–0.99 / ❌ < 0.5

---

## Notable Cross-Layer Dependencies

- `workflow` is the heaviest cross-layer consumer (25 imports)
- `cli` depends on `workflow`, `utils`, `shared` (16 imports)
- `exporters` depends heavily on `utils` (16 imports)
- `lineage` depends on `shared` and `utils` (15 imports)
- `shared` is the most tested layer (ratio 3.30)
- `ui` is the largest layer (51 modules) with lowest test ratio (0.49)

---

## Key Protected Files

```
src/data_quality_toolkit/shared/models.py
src/data_quality_toolkit/shared/settings.py
src/data_quality_toolkit/workflow/runner.py
src/data_quality_toolkit/exporters/star_schema_export.py
src/data_quality_toolkit/shared/compat.py
```

---

## Available Inventory Artifacts (tools/_results/)

| File | Location | Date |
|---|---|---|
| `REPO_INVENTORY.json` | `tools/_results/step0/` | 2026-02-20 |
| `inventory_modules.csv` | `tools/_results/step0/` | 2026-02-20 |
| `inventory_tests.csv` | `tools/_results/step0/` | 2026-02-20 |
| `inventory_layer_summary.csv` | `tools/_results/step0/` | 2026-02-20 |
| `inventory_dashboard.json` | `tools/_results/step0/` | 2026-02-20 |
| `API_ENDPOINTS.json` | `tools/_results/step2/` | 2026-02-20 |
| `FRONTEND_INVENTORY.json` | `tools/_results/step4/` | 2026-02-20 |
| `COMPLEXITY.radon.json` | `tools/_results/step5/` | 2026-02-20 |
| `OPS_INVENTORY.json` | `tools/_results/step6/` | 2026-02-20 |

---

## Regeneration Note

No committed inventory-generation script exists in the current repo.
Previous inventory was produced by step-based tooling (see `tools/logs/`).
To refresh this file, a new bounded DQT-INV task must be admitted and approved.
