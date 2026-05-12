# Contributing to Data Quality Toolkit

Contributions are welcome. Prioritize small, safe, high-leverage improvements over broad rewrites.

## Project Priorities

When contributing, prefer work that improves:
- MVP usability
- output correctness
- end-to-end reliability
- product demoability
- measurable outputs and KPI visibility

Avoid broad refactors unless they are clearly necessary.

## Working Style

Before proposing or making edits:
1. identify the target files
2. assess the risk level
3. define the smallest safe validation plan

Keep changes:
- small
- reviewable
- testable
- easy to revert

## High-Risk Files

Do not modify these unless explicitly approved:

- `src/data_quality_toolkit/shared/models.py`
- `src/data_quality_toolkit/shared/settings.py`
- `src/data_quality_toolkit/workflow/runner.py`
- `src/data_quality_toolkit/exporters/star_schema_export.py`
- `src/data_quality_toolkit/shared/compat.py`

## Setup

```bash
git clone <repo-url>
cd data-quality-toolkit
<path-to-python> -m pip install -e ".[dev]"
<path-to-python> -m pre_commit install
````

## Preferred Commands

### Targeted pytest

```bash
<path-to-python> -m pytest ...
```

### File-scoped pre-commit

```bash
<path-to-python> -m pre_commit run --files ...
```

### Direct CLI invocation

```bash
<path-to-python> -m data_quality_toolkit.cli.main ...
```

## Preferred Workflow

1. Inspect only the relevant files.
2. Propose the smallest possible patch.
3. Explain why it is safe.
4. Run targeted tests first.
5. Run file-scoped pre-commit if relevant.
6. Only then consider wider validation.

If a focused pytest run triggers the repo-wide coverage threshold, treat that as coverage-noise unless the targeted tests themselves failed.

## Testing Expectations

Prefer:

* focused test file
* focused folder
* branch-compatible validation

Avoid:

* repo-wide validation for tiny patches
* unrelated cleanup bundled into the same diff

## Documentation Expectations

When behavior changes, update the relevant docs:

* `README.md`
* demo docs
* `CHANGELOG.md`

Keep docs aligned to actual repo behavior.
Do not describe unbuilt features as if they are shipped.

## Commit Guidance

Prefer small, specific commits, for example:

* `docs: update README with current CLI behavior`
* `feat(cli): add configurable null-threshold`
* `feat(workflow): add compare-last-two-runs`
* `test(workflow): add compare behavior coverage`

## Good Contribution Areas

Useful contribution areas include:

* CSV workflow usability
* assessment rules
* export/report clarity
* compare/history usability
* demo improvements
* documentation truth-alignment
* focused tests

## Avoid Without Explicit Approval

Do not start these without explicit approval:

* broad architecture refactors
* API/server work
* web UI work
* platform expansion
* major packaging redesign
* large rewrites of `issue_detector.py`

## Project Scope

This project is currently a v1:

* CLI-first
* CSV-first
* demo-driven
* not yet a SaaS platform or web UI

Contributions should reinforce that scope rather than expand it prematurely.
