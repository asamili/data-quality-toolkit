# Example Coverage Map

This map links every DQT product surface to its example and tells you, at a glance, what is
**current local behavior**, what is **new in v2.10.0**, and what is only **planned**.
It is the companion index to the [examples README](README.md).

> **Version posture.** These examples target DQT v2.10.0; version metadata reports `2.10.0`.
> Nothing here implies a tag, release, public snapshot, package publication, or version bump.
> Grounded in `docs/capability_matrix.md`, `docs/cli.md`, and `docs/api.md`.

## Legend

- **Current local / implemented** — implemented behavior in the source tree.
- **Example exists** — a runnable example/walkthrough already lived in the repo before this gate.
- **Example added** — example doc added with this directory's new files.
- **Example added (walkthrough)** — the complete end-to-end walkthrough notebook; outputs
  stripped.
- **New in v2.10.0** — added after v2.9.0; current-star / proxy scope plus accepted UI/statistics/export posture.
- **Planned / future** — not implemented, not shipped.
- **Do not claim** — explicitly unsupported; must not be described as a product capability.

## Coverage matrix

| Surface / feature | Current local / implemented | Example exists | Example added | New in v2.10.0 | Planned / future | Do not claim |
|---|---|---|---|---|---|---|
| Python API (`profile_csv`, `assess_csv`, …) | Yes | [01_quickstart.ipynb](01_quickstart.ipynb) | [api/README.md](api/README.md) | — | — | — |
| Complete end-to-end walkthrough (notebook) | Yes | [complete_dqt_walkthrough.ipynb](complete_dqt_walkthrough.ipynb) | added (walkthrough) | — | — | execution-validated |
| CLI command surface | Yes | scattered in guides | [cli/README.md](cli/README.md) | — | — | — |
| UI walkthrough (Streamlit) | Yes (optional `[ui]`) | [dashboard/README.md](dashboard/README.md) | linked from index | — | — | live service / SaaS UI |
| Data quality checks (issues) | Yes | [demo/issue_showcase](demo/issue_showcase/README.md) | covered in cli/ | — | — | — |
| Profiling | Yes | [demo/README.md](demo/README.md) | cli/ + api/ | — | — | — |
| EDA / statistics | Yes (EDA UI; stats `[stats]`) | [dashboard/README.md](dashboard/README.md) | — | Distributions, Power & Sample Size, CSV downloads, workspace saves | — | — |
| Preprocessing plan | Yes | [01_quickstart.ipynb](01_quickstart.ipynb) | cli/ + api/ | — | — | mutating source data |
| Validation / scoring / quality score | Yes | [pipeline_gate](pipeline_gate/README.md) | cli/ | — | — | — |
| Drift detection (`dqt drift`) | Yes (`[stats]`) | [golden_path](../docs/guides/golden_path.md) | cli/ | — | — | — |
| Drift history / monitoring | Yes | [golden_path](../docs/guides/golden_path.md) | cli/ | — | — | live monitoring service |
| Power BI export / package | Yes | [bi_worked_example](../docs/guides/bi_worked_example.md) | [bi/README.md](bi/README.md) | — | — | full PBI semantic model completion |
| Time dimension (`gen-dim-time`) | Yes | [bi_worked_example](../docs/guides/bi_worked_example.md) | bi/ + cli/ | — | — | — |
| User-defined KPI catalog | Yes | `config/kpi_catalog.yaml` | [semantics/README.md](semantics/README.md) | — | — | — |
| Built-in quality semantic catalog (`kpi-builtin`) | Yes (current-star / proxy) | mention in guides | [semantics/README.md](semantics/README.md) | Yes | — | full canonical BI semantic model |
| Semantic-contract validation | Yes (current-star contract) | mention in guides | semantics/ | Yes | — | full-model contract |
| Pipeline runner / workflow (`dqt run`) | Yes (declarative scaffold / dry-run) | [dashboard](dashboard/README.md) | cli/ (with disclaimer) | — | — | ETL/ELT engine, warehouse connectors |
| Lineage / manifest | Yes | [dashboard](dashboard/README.md) | cli/ + api/ | — | — | — |
| Configuration (`dqt.yaml`, rules) | Yes | `config/v2_rules.yaml` | cli/ | — | — | enforcing parsed-but-deferred rule keys |
| Fixture / example-data strategy | Yes | this directory | README + this map | — | consolidation of duplicate fixtures | — |
| Canonical DQT BI semantic model (full) | No (held) | — | — | — | Yes | shipped / complete |
| HTTP service / `/v1/export` workflow (n8n) | No | `n8n/*` | [../n8n/README.md](../n8n/README.md) (boundary) | — | Yes (illustrative) | shipped service, SaaS, deployment, orchestration |
| StoryLens optional local AI | Default-off; UI-only | [dashboard](dashboard/README.md) | — | — | model-staging (future gate) | AI enabled / model bundled / inference on by default |
| `examples/demo/Uber_Data.csv` public use | Local only | — | boundary note in README | — | — | license-cleared / public-safe |

## Public / private boundary summary

- **Public-safe synthetic fixtures:** `demo/sample_orders.csv`, `demo/issue_showcase/issue_demo.csv`,
  `demo.csv`, `tiny.csv`, `pipeline_gate/sample_pipeline_output.csv`.
- **Requires review before public use:** `demo/Uber_Data.csv` (license / PII — not cleared).
- **Scope wording:** anything about the built-in quality catalog (`kpi-builtin`,
  `quality_score_proxy`) is new in v2.10.0 and current-star / proxy scoped — keep the scope banner.
- **Roadmap-only:** the full canonical BI semantic model and the n8n HTTP-service workflow. The
  `n8n/` directory is git-ignored (untracked, local-only) and already cannot enter a tracked-file
  public snapshot; see [../n8n/README.md](../n8n/README.md).
- **Never claim:** DQT as a SaaS / live service / deployed runtime / orchestration platform, AI
  inference enabled by default.

## Related references

- [Capability Matrix](../docs/capability_matrix.md) — authoritative feature → surface → evidence map.
- [CLI Reference](../docs/cli.md) · [Python API](../docs/api.md)
- [Public Safety Boundary](../docs/public_safety_boundary.md)
