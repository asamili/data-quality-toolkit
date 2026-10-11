# StoryLens Governance

## Purpose

StoryLens produces plain-language explanations for the Data Overview surface. It translates DQT's deterministic quality metrics into short, human-readable summaries — without recomputing metrics, validating data, or becoming a source of truth.

DQT's scoring, drift detection, and quality gates are not affected by StoryLens. The feature is an explanation layer only.

## Operating Modes

StoryLens has two paths, one always active and one optional:

### Deterministic narrator (default, always active)

Seven pure functions in `narrator.py` produce explanations from DQT's computed metrics. These functions have no I/O, no network access, no randomness, and no external dependencies. They run unconditionally as part of the Data Overview and produce a structured `Explanation` value object consumed by the UI.

This path is the default output of StoryLens in all configurations.

### Optional local AI path (default-off)

An optional AI adapter can produce a short plain-language summary in place of the deterministic narrator's summary text. This path is disabled by default and is not activated unless **both** of the following conditions are met at runtime:

1. `DQT_STORYLENS_AI_ENABLED` is set to `true` (or `1`)
2. `DQT_STORYLENS_MODEL_DIR` is set to a local directory containing a staged model

If either condition is absent, the optional AI path is skipped silently and the deterministic narrator provides the full explanation.

### Fallback behavior

Any failure in the optional AI path — including disabled configuration, missing model directory, unavailable model, invalid AI output, or any runtime error — causes `try_explain` to return the deterministic `Explanation` value object without propagating an exception to the UI. The user sees the deterministic result; no error is surfaced.

## Safety Guarantees

- **AI is not required for normal DQT behavior.** Profiling, quality scoring, drift detection, history analytics, and all CLI/API operations are unaffected by StoryLens configuration.
- **No model is bundled in the package by default.** Installing `data-quality-toolkit` without the `[storylens-ai]` extra installs no AI weights, no model artifacts, and no heavy ML dependencies.
- **No model is downloaded on install or at runtime by default.** The optional AI adapter enforces `local_files_only=True` on every model load call. No network access occurs during inference. A missing or empty `DQT_STORYLENS_MODEL_DIR` causes the AI path to remain disabled.
- **Local inference is not enabled without explicit staging.** A future model-staging gate must admit a specific model revision before inference can run. This gate has not yet been completed for any release lane.
- **`try_explain` never breaks the UI path.** The fallback wrapper catches all exceptions and returns the deterministic explanation silently.
- **The deterministic fallback is always available.** The `Explanation` value object from the narrator path is always computed and always returned if the AI path is absent or fails.

## Validation and Output Boundaries

AI output is **validator-gated** before it can replace the deterministic summary. An 11-class validation matrix rejects AI output that:

- Contains numbers not present in the typed facts payload
- Contradicts the deterministic severity or drift status
- Makes causal claims (e.g., asserts a cause for drift)
- Omits required safety phrases (e.g., "Drift is a distribution change, not a defect")
- Contains prompt template markers, environment variable names, absolute paths, or model identifiers
- Exceeds the output length limit
- Matches PII patterns or credential-shaped tokens

When the validator rejects AI output, the deterministic `Explanation` is returned silently.

**AI contribution is bounded to the summary field only.** Evidence items, limitations, severity classification, and recommended-action guidance remain under deterministic control at all times — they are never overwritten by AI output.

Path and secret leakage patterns are rejected or redacted. Severity contradictions and revision-hash leakage are explicitly guarded.

## API and CLI Non-Exposure

- StoryLens optional AI internals are not public API features. No function in `api.py` exposes AI configuration or AI output directly.
- The CLI does not expose flags for local AI activation. `DQT_STORYLENS_AI_ENABLED` and `DQT_STORYLENS_MODEL_DIR` are environment variables, not CLI arguments.
- An import-linter contract (machine-enforced in CI) prevents `api.py` and CLI modules from importing the `ai_adapter` package. The contract is defined in `pyproject.toml` under `[tool.importlinter]`. This is a hard boundary, not a convention.

## Optional Dependency Governance

The optional AI dependencies are isolated behind a named extra:

```
pip install "data-quality-toolkit[storylens-ai]"
```

This extra pulls in `transformers` and `torch` (CPU-only). These packages are not part of the default install.

- `pip install data-quality-toolkit` installs no AI packages.
- `pip install "data-quality-toolkit[ui]"` adds Streamlit for the dashboard; it does not install AI packages.
- Optional AI dependencies are absent from the runtime unless the `[storylens-ai]` extra is explicitly requested.

CI passes without the `[storylens-ai]` extra. Unit tests for the optional AI adapter use mocked inference; no real model is required to run the test suite.

## Public/Private Boundary

This document is public-facing. It describes the design and governance posture of StoryLens for reviewers, contributors, and recruiters.

This document describes governance posture; it is not itself a release announcement.

This document does not contain:
- Local file paths or private repository references
- Tokens, checksums, or revision hashes that imply model availability
- Internal gate identifiers presented as user-facing feature claims
- Private evidence or audit artifacts

## Current Status

| Area | Status |
|---|---|
| Deterministic StoryLens (narrator path) | Available — production-ready |
| Optional local AI path (adapter, validator, fallback) | Implemented — governed, default-off |
| Model staging / inference activation | Not activated in this release lane |
| CLI/API exposure of AI internals | Not present |
| Public release / public snapshot | Not claimed by this document |

The governed `try_explain` wrapper is called from Data Overview, but this wiring does not mean
optional AI is activated. With the default configuration it returns the deterministic fallback;
the optional path additionally requires explicit runtime enablement and a separately admitted,
locally staged model. No model staging, download, or inference activation has been admitted. A
future model-staging gate is required before local inference can run in any release lane.

## Value Summary

StoryLens demonstrates a specific pattern of responsible optional-AI design:

- **Deterministic by default.** DQT's quality results are always computed deterministically. AI is a controlled supplement, not a dependency.
- **Governed optional enhancement.** The optional AI path requires explicit environment configuration, a future model-staging gate, and passes a validator before its output can reach the user.
- **Machine-enforced isolation.** The import-linter contract prevents AI internals from reaching the public API or CLI surface, enforced in CI — not by convention.
- **Lightweight by default.** The default install has no heavy ML dependencies. Optional AI packages are opt-in and isolated.

This pattern keeps DQT's pipeline-grade data quality behavior reliable and independent of AI availability while making optional AI a safe, bounded enhancement when explicitly enabled.
