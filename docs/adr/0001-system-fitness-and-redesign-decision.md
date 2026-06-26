# ADR 0001: System Fitness and Redesign Decision

**Status:** Accepted
**Date:** 2026-06-21

## Context

DQT v2.9.0 was reviewed across its full surface: CLI commands, public Python API, Streamlit UI, application workflow, domain logic, adapters, export paths, tests, packaging metadata, public/private boundary, and optional StoryLens AI governance. The review asked whether DQT required a full architectural redesign before v2.9.0 or whether the existing architecture was fit for its intended purpose.

Three options were evaluated:

- **Option A — Premium Minimal:** Harden the existing architecture with targeted improvements (import-linter contracts, clean API surface, docs, public-safety boundary) without structural redesign. Lowest risk. Ready for a near-term v2.9.0 release lane.
- **Option B — Productized Service Architecture:** Introduce explicit service-boundary wiring and ports/adapters contracts as an incremental architectural step. A future candidate; does not require a rewrite and can be done one boundary at a time.
- **Option C — Feature-module / plugin architecture:** Decompose DQT into independently installable feature plugins. Adds engineering risk and is likely over-engineering at the current feature scale.

## Decision

**DQT is system-fit. No full redesign is required before v2.9.0.**

- Continue with the current layered architecture (`domain/`, `application/`, `adapters/`, `lineage/`, `shared/`, `utils/`, `api.py`).
- Proceed with **Option A "Premium Minimal" hardening** before any public-facing release. This includes import-linter contract enforcement, stable public API, public safety boundary documentation, and governed optional-AI design.
- Keep **Option B** (service-boundary / ports wiring) as a future incremental candidate after v2.9.0. It is compatible with the current architecture and does not require a rewrite.
- **Defer Option C** (plugin / feature-module architecture) until after v2.9.0. It is not a near-term requirement; the current feature surface does not justify the added complexity.

## Evidence

The following findings grounded this decision:

- Import-linter contracts enforced across 150 analyzed files: 5/5 contracts kept, 0 broken. This includes the `Public API and CLI must not import StoryLens optional AI internals` contract.
- Test suite: 2401 tests collected; broad green across unit, integration, and golden tests. Tests use synthetic fixtures only.
- CLI / public API / UI parity confirmed in the capability matrix. No undocumented asymmetries found.
- Public API (`api.py`) is stable and bounded. CLI entry point is clean.
- Optional local AI (StoryLens) is default-off, not exposed through CLI or public API, and governed by a documented fallback chain and validator-gated output boundary.
- Capability matrix, StoryLens governance summary, and public safety boundary document were added as part of the current decision cycle. These confirm that the existing architecture is well-understood and appropriately documented.
- No source code security issues identified that would block a v2.9.0 release lane under Option A.

Internal gate evidence (G23A, G24B, G24C, G24E, G25A) is recorded in the private repository history. This ADR summarizes accepted findings without reproducing private gate artifacts.

## Consequences

**Positive:**
- Avoids a risky rewrite before v2.9.0. The architecture is coherent and understandable; a redesign would add risk without corresponding functional benefit at this scale.
- Public API remains stable. Downstream users and integrations are not disrupted.
- Option A hardening improves product clarity and public-readiness incrementally. Each improvement (docs, boundary docs, import-linter, governed AI) can be validated and committed independently.
- Option B is available as a future incremental path. Service boundaries can be tightened one at a time without requiring a full structural redesign.

**Constraints accepted:**
- Plugin architecture (Option C) is not available in v2.9.0. Feature bundling continues as the default distribution model.
- Option B service-boundary improvements are deferred to a post-v2.9.0 planning gate. The current import-linter contracts are the enforced boundary mechanism for now.
- The `lineage/` package sits outside the primary layered contracts (open review item: DQT-ARCH-G5). This is a known, documented constraint, not a blocker.

## Non-Goals

This ADR does not approve, authorize, or constitute:

- Private push to the remote repository
- Public snapshot sync or public repo access
- Public release, tag, or version promotion
- Model staging, model download, or local AI inference activation
- Public exposure of StoryLens optional AI through CLI or public API
- Implementation of Option B service-boundary wiring
- Implementation of Option C plugin/feature-module architecture

Each of those requires a separate admitted gate.

## Future Candidates

The following gates are candidates for the lane following this ADR, in approximate priority order:

1. **Private push gate** — push current `main` to `origin` after confirming private remote state.
2. **Public snapshot safety gate** — validate public/private exclusion, demo dataset licenses (notably `examples/demo/Uber_Data.csv`), and public-safe content before any public repo sync.
3. **Public-safe demo dataset review** — resolve `Uber_Data.csv` license provenance and attribution before including in a public snapshot.
4. **Option B service-boundary planning** — incremental ports/adapters tightening post-v2.9.0, if prioritized.
5. **Model-staging gate** — only if local AI inference activation is explicitly chosen for a future release lane. Not a near-term requirement.
