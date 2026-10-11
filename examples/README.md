# Data Quality Toolkit — Examples

This directory contains small datasets and runnable demo assets for the Data Quality
Toolkit (DQT). Use these examples to understand and test the product end-to-end: profiling,
quality assessment, export, drift/monitoring, BI hand-off, and semantic catalogs.

Every command shown here reflects **current local behavior** in DQT v2.10.0.
Examples never run themselves — you run them locally.

> **Version posture.** These examples target DQT v2.10.0; version metadata reports `2.10.0`.
> Nothing here implies a public release, tag, package publication, or public snapshot. Examples
> below are tiered so you always know what is current local behavior, what is new in v2.10.0,
> and what is only planned. See the [Example Coverage Map](COVERAGE_MAP.md) for the full matrix.

## Example tiers

| Tier | Meaning | How it is marked |
|---|---|---|
| **Current local / implemented** | Implemented local behavior in the source tree | default (no banner) |
| **New in v2.10.0** | Added after v2.9.0; current-star / proxy scope plus accepted UI/statistics/export posture | "v2.10.0" scope banner |
| **Planned / future** | Not implemented, not shipped | "PLANNED / FUTURE — do not rely on" banner |

## Recommended starting points

- **Complete end-to-end walkthrough (notebook):**
  [complete_dqt_walkthrough.ipynb](complete_dqt_walkthrough.ipynb) — the full DQT surface tour
  (profiling → EDA → assessment/gate → preprocessing → export/compare → drift/monitoring →
  BI / Power BI → semantic catalogs → pipeline/UI guidance) with scope banners.
  Current local example; outputs stripped.
- **Python API quickstart (notebook):** [01_quickstart.ipynb](01_quickstart.ipynb) — `profile_csv`,
  `assess_csv`, `plan_csv`, and chart-data helpers on `demo/sample_orders.csv`. Open in Jupyter or
  VS Code (`pip install data-quality-toolkit ipykernel`).
- **CLI cookbook:** [cli/README.md](cli/README.md) — copy-paste recipes for every current CLI surface.
- **Python API guide:** [api/README.md](api/README.md) — embed DQT in scripts and notebooks.
- **CLI demo package:** [demo/README.md](demo/README.md) — happy-path + issue-detection walkthrough.

## Example index

| Area | Example | Tier |
|---|---|---|
| End-to-end walkthrough (all surfaces) | [complete_dqt_walkthrough.ipynb](complete_dqt_walkthrough.ipynb) | Current (local) |
| Profiling / assess / export / compare | [demo/README.md](demo/README.md) (`sample_orders.csv`, 170×14 synthetic) | Current |
| Issue detection + threshold tuning | [demo/issue_showcase/README.md](demo/issue_showcase/README.md) (`issue_demo.csv`, 5×4) | Current |
| CI / pipeline quality gate | [pipeline_gate/README.md](pipeline_gate/README.md) (`run_gate.sh`, exit codes) | Current |
| UI walkthrough (Streamlit) | [dashboard/README.md](dashboard/README.md) | Current |
| CLI cookbook | [cli/README.md](cli/README.md) | Current |
| Python API snippets | [api/README.md](api/README.md) | Current |
| Power BI / export hand-off | [bi/README.md](bi/README.md) | Current |
| Semantic catalogs (user KPI + built-in quality) | [semantics/README.md](semantics/README.md) | Current (user KPI) + new in v2.10.0 (built-in quality) |
| Coverage map (all surfaces) | [COVERAGE_MAP.md](COVERAGE_MAP.md) | Reference |

## Current directory structure

```text
examples/
  README.md                 # this file
  COVERAGE_MAP.md            # surface -> example -> tier matrix
  01_quickstart.ipynb        # Python API quickstart notebook
  complete_dqt_walkthrough.ipynb  # full end-to-end walkthrough notebook (all surfaces)
  demo.csv                   # small simple CSV (one missing value)
  tiny.csv                   # minimal three-row CSV
  demo/
    README.md                # happy-path + issue-detection CLI demo
    sample_orders.csv        # synthetic orders, 170 rows x 14 cols
    Uber_Data.csv            # large real-world input (see boundary note below)
    issue_showcase/
      README.md              # crafted CSV that triggers all rule types
      issue_demo.csv         # 5 rows x 4 cols, every column intentionally broken
  pipeline_gate/
    README.md                # quality-gate recipe for CI/ETL
    sample_pipeline_output.csv
    run_gate.sh              # minimal shell gate example
  dashboard/
    README.md                # full Streamlit UI walkthrough
  cli/
    README.md                # CLI cookbook
  api/
    README.md                # Python API snippets
  bi/
    README.md                # Power BI / export hand-off guide
  semantics/
    README.md                # user KPI catalog + built-in quality catalog (new in v2.10.0)
```

> Generated outputs (e.g. `dist/`) are git-ignored and are **not** committed under `examples/`.
> Earlier revisions of this file referenced a checked-in `demo/dist/star/` tree; no such tree
> exists or should exist — `dqt export` writes star-schema artifacts to a `--outdir` you choose.

## Available datasets

| File | Description | Best for |
|---|---|---|
| `demo/sample_orders.csv` | Synthetic orders — multi-region, mixed statuses, nullable fields (170×14) | Primary demo, business-domain quality checks |
| `demo/issue_showcase/issue_demo.csv` | Tiny crafted dataset that triggers all rule types (5×4) | Focused issue detection |
| `tiny.csv` | Minimal three-row CSV | Fast smoke checks |
| `demo.csv` | Small simple CSV with a missing value | Basic CLI testing |
| `demo/Uber_Data.csv` | Large real-world aggregated NYC Uber + weather data (~1.7 MB) | Large-data mode demos |

> **Boundary note — `demo/Uber_Data.csv`.** This is real-world aggregated data, **not** confirmed
> public-safe. It **requires license / PII review before any public use** and must not be treated
> as license-cleared. The synthetic CSVs above are the preferred demo inputs.

## Basic CLI commands

Run from the repository root. On Windows, if `dqt` is not on your PATH, replace `dqt` with your
interpreter, e.g. `python -m data_quality_toolkit.adapters.cli.main <command>`.

```bash
# Profile a dataset
dqt profile examples/demo/sample_orders.csv

# Assess quality
dqt assess examples/demo/sample_orders.csv

# Export star-schema quality artifacts
dqt export examples/demo/sample_orders.csv --outdir dist/demo
```

See the [CLI cookbook](cli/README.md) for the full set of recipes.

## Notes

These examples are for local development, demonstrations, and documentation. Do not place
production or sensitive data in this directory.

## Further reading

- [Demo story / product walkthrough](../docs/demo_story.md)
- [Golden Path guide](../docs/guides/golden_path.md)
- [BI worked example](../docs/guides/bi_worked_example.md)
- [Capability Matrix](../docs/capability_matrix.md)
