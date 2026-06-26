# DQT v2.9.0 UI/UX Redesign Plan

## Status and Scope

This document records the accepted plan for a phased redesign of DQT's local Streamlit
interface. It is a specification for future implementation gates, not a statement that the
redesign has been implemented or accepted.

The current decision is to retain Streamlit as DQT's near-term UI framework. DQT remains a
CLI-first, local data-quality toolkit; this plan does not reposition it as a hosted web product.

This specification does not approve or claim:

- implementation of any item below;
- installation or activation of Plotly;
- model staging, model download, or local AI inference;
- private push, public snapshot, tag, or release readiness.

## Product Journey

The future UI should guide a user through one coherent flow rather than requiring paths and
identifiers to be re-entered independently on each page.

### 1. Start / Dataset Context

The user selects and validates a CSV once, chooses normal or large-file mode, and establishes
the dataset context used by later pages. Future shared state should retain safe dataset identity,
load mode, profile/assessment results, and explicit invalidation information. Changing or
clearing the dataset must clear derived state so stale results cannot appear.

### 2. Data Overview

The overview should present the dataset identity, shape, quality score, issue count, column
health, completeness, and a concise deterministic explanation. Values must come from existing
profiling and assessment results; rendering components must not recompute business metrics.

### 3. EDA and Statistics

EDA should provide richer descriptive statistics, missingness views, categorical frequencies,
numeric distributions, boxplots, and correlation views. Later phases may add more advanced
relationships and distribution techniques. Large-file mode must continue to disclose which
statistics are unavailable rather than silently approximating unsupported results.

### 4. Issue Triage

Users should be able to review issues by rule, severity, and column, filter the underlying
table, and download the evidence. Summary charts and tables must reconcile exactly with the
assessment output.

### 5. Drift and History

Quality history and drift monitoring should expose run selection, trend summaries, test results,
skipped-column reasons, and improved reference-versus-current distribution comparisons. The UI
must explain statistical evidence without claiming that drift proves a defect or a cause.

### 6. StoryLens Explanations

StoryLens should be an inline explanation pattern across supported features, not a separate
source of truth. Each explanation should show the observed evidence, why it matters, a bounded
recommended action, and its limitations. The UI should use neutral StoryLens provenance wording
instead of describing every deterministic explanation as AI-generated.

### 7. Export / BI / Artifacts

The UI should distinguish browser downloads from explicit server-side filesystem writes. A
future artifact center should show each available artifact's name, purpose, type, and status.
Server-side export must retain path validation and explicit confirmation.

### 8. Diagnostics / Settings

Diagnostics should report truthful, redacted runtime and capability information. Placeholder
values must not be presented as real configuration. Any writable-directory probe must use a
stable form with an explicit path and confirmation.

## Near-Term Frontend Decision

The accepted near-term direction is:

- retain Streamlit for layout, navigation, state, forms, metrics, and tables;
- plan to use Plotly for richer analytical UI charts in a separately admitted gate;
- retain the existing Matplotlib path for static CLI/API plot artifacts;
- avoid a React, Dash, Panel, or Shiny migration before v2.9.0.

Plotly is a planned option only. It is not currently declared, installed, or active as a result
of this document. Plotly requires separate dependency-source/license validation before any
public publication, and a future dependency gate must select a compatible constraint. Plotly
should remain within the UI
optional-dependency boundary rather than becoming a core dependency. Server-side static Plotly
image export is not a P0 requirement; underlying chart data can be downloadable while existing
Matplotlib exporters continue to produce static artifacts.

## P0 Redesign Intent

P0 is the minimum future implementation scope required to turn the current collection of pages
into a coherent upload/input → insight → action → export flow. P0 should:

1. establish shared dataset context and explicit state invalidation;
2. introduce consistent page shells, metric cards, states, filters, tables, and path rules;
3. deepen EDA with descriptive, missingness, distribution, boxplot, correlation, and issue views;
4. improve drift distribution presentation and explain its statistical tests;
5. extend deterministic StoryLens explanations to selected EDA, assessment, drift, monitoring,
   export, and lineage features;
6. separate browser downloads from confirmed server-side exports;
7. remove, correct, hide, or clearly label placeholder and experimental UI surfaces;
8. retain current large-file disclosures, path safety, API/CLI boundaries, and testability.

P1 and P2 capabilities such as duplicate-group drilldown, richer scatter/group analysis,
before/after profiles, KDE, violin plots, pairwise exploration, semantic type confidence, and a
web-native frontend proof of concept are not required for the P0 presentation lane.

## Planned Shared UI Architecture

Future implementation should add framework-thin, independently testable patterns for:

- dataset context and session-state keys;
- a Start page and shared page shell;
- metric and issue-summary cards;
- analytical chart wrappers and downloadable chart-data contracts;
- consistent empty, error, loading, and progress states;
- artifact/download presentation;
- the shared StoryLens panel;
- reusable filters and table-display rules;
- path/file inputs that preserve current loader and output-path safety.

The local path workflow remains the P0 input model because it matches DQT's CLI-first use case.
A browser file uploader is a possible later feature only after size limits and temporary-file
lifecycle rules are designed. StoryLens facts must never contain raw rows, cell values, secrets,
or absolute paths.

## Deterministic StoryLens Direction

The planned cross-feature flow is:

```text
domain/application metrics
  -> feature facts builder
  -> deterministic narrator
  -> Explanation
  -> shared StoryLens panel
```

Feature facts and deterministic narrators should remain independent of the optional AI adapter.
The following contracts are planning candidates only and do not exist as a result of this spec:

- `AssessmentSummaryFacts`
- `EDAFindingFacts`
- `IssueDistributionFacts`
- `DriftExplanationFacts`
- `QualityHistoryFacts`
- `MonitoringThresholdFacts`
- `ExportArtifactFacts`
- `ManifestFacts`

The first future StoryLens changes should correct the Data Overview provenance label, add
selected deterministic EDA and issue explanations, and wire the existing deterministic drift,
no-drift, insufficient-history, and export-artifact narrators where their required facts exist.
KPI, Dim Time, Pipeline Runner, and Diagnostics explanations may wait.

Optional local AI remains default-off and is not activated or expanded by this plan. No new
feature facts should enter the AI adapter without a separate future gate. AI internals remain
unexposed through the public API and CLI, and the existing import-linter boundary must remain
green. Model staging, download, inference, and activation remain blocked unless separately
admitted. Any future AI mapping must retain validator gating, bounded summary replacement,
deterministic fallback, and preservation of evidence, limitations, and severity.

## Page Direction

| Current page | Planned direction | P0 emphasis |
|---|---|---|
| Data Overview | Redesign as Overview & Score | Shared context, score/issue summaries, truthful StoryLens label |
| EDA Explorer | Redesign as Explore | P0 statistics and analytical charts |
| Run History | Retain as Quality History | Trends, issue changes, insufficient-history explanation |
| Drift Explorer | Redesign as Drift & Monitoring | Test guidance and distribution comparison |
| Export | Redesign as Artifacts & Export | Accurate download/write distinction and artifact summary |
| KPI Catalog | Retain with shared shell | Validation and generated-artifact consistency |
| Dim Time | Retain with shared shell | Validation, preview, and download |
| Manifest Viewer | Redesign as Lineage | Summary, failures, artifacts, deterministic explanation |
| Pipeline Runner | Defer or mark experimental | Do not imply selected steps work until its service contract is fixed |
| Settings & Diagnostics | Redesign as Diagnostics | Truthful values and stable safe-probe form |

## P0 Acceptance Criteria

P0 should not be accepted until:

- a dataset is selected once and reused safely by Overview and EDA;
- changing or clearing it invalidates derived state;
- issue and chart totals reconcile with their source results;
- P0 charts handle empty, constant, all-null, and mixed-type data;
- StoryLens labels deterministic output truthfully and never fabricates metrics;
- optional AI remains default-off and no new AI exposure is introduced;
- browser downloads and confirmed filesystem writes are visually distinct;
- placeholder/experimental surfaces are corrected, hidden, or clearly labeled;
- existing UI, seam/parity, path-safety, and import-linter tests remain green;
- new state, component, chart-contract, narrator, download, and journey tests pass.

Browser end-to-end and visual-regression tooling are future candidates, not P0 acceptance
requirements.

## Phased Implementation Gates

Each phase below requires separate admission. This document does not open or approve any phase.

### G27E-UI-FOUNDATION

Add the Start page, shared dataset state, page shell, common states, navigation cleanup, and
truthful handling of experimental or placeholder pages. No EDA, chart-dependency, or AI-runtime
work belongs in this phase.

### G27F-EDA-P0

Implement pure P0 statistical presentation models and the planned analytical chart layer. Any
Plotly declaration or installation requires explicit dependency admission and source/license
validation. This phase must add calculation, figure-contract, edge-case, and render tests.

### G27G-STORYLENS-DETERMINISTIC

Correct StoryLens provenance wording and implement the first AI-independent facts builders and
deterministic cross-feature narrators. Model staging, inference, new AI facts, and CLI/API AI
exposure remain forbidden.

### G27H-DRIFT-MONITORING-UX

Improve drift/history presentation, statistical-test guidance, distribution comparison, and
deterministic monitoring explanations while retaining the existing read-only API/view-model seam
and database schema.

### G27I-ARTIFACT-CENTER

Redesign Export and Lineage around consistent artifact metadata, downloads, explicit writes, and
deterministic artifact explanations. Existing path guards and confirmation behavior remain
mandatory.

### G27J-UI-DOCS-ALIGNMENT

Synchronize the README, capability matrix, governance, architecture, and final UI copy with the
implemented behavior. This phase must not claim unimplemented features or release readiness.

### G27K-UI-VALIDATION

Perform a read-only final UI, architecture, safety, and test audit. A successful result may
recommend—but cannot perform—a separately admitted private-push gate.

## Publication and Release Boundary

The redesign plan does not change DQT's publication state. Private push remains postponed, and
public snapshot, tag, and release actions remain blocked pending their own admitted gates. No
frontend, charting, or StoryLens item in this document may be presented as completed until its
implementation and validation gates have passed.
