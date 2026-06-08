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
- `src/data_quality_toolkit/domain/` — domain rules, profiling, and assessment
- `src/data_quality_toolkit/application/` — workflow orchestration and pipeline
- `src/data_quality_toolkit/adapters/` — CLI, exporters, storage, and UI
- `.github/workflows/` — CI/CD workflows
- `pyproject.toml`

## Setup

```bash
git clone https://github.com/asamili/data-quality-toolkit
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
<path-to-python> -m data_quality_toolkit.adapters.cli.main ...
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

This project is CLI-first and CSV-first. Contributions should reinforce that scope rather than expand it prematurely.

## Architecture (v2)

The codebase follows a layered architecture:

- `domain/` — business rules: profiling, assessment, semantics, KPI
- `application/` — workflow orchestration: pipeline, compare, preprocessing
- `adapters/` — CLI, exporters, storage (SQLite), UI (Streamlit)
- `infrastructure/` — (reserved for future external-system integration)
- `shared/` — cross-cutting: constants, settings, exceptions

Keep changes within the correct layer. Do not introduce cross-layer imports that skip a boundary.

## Reporting Issues

Use the [bug report](.github/ISSUE_TEMPLATE/bug_report.md) or [feature request](.github/ISSUE_TEMPLATE/feature_request.md) template. Include:

- The command you ran
- Expected vs actual behavior
- Minimal reproduction steps
- Small synthetic or sample data only (e.g., `examples/demo/sample_orders.csv`) — do not attach real or sensitive data

## Pull Requests

- Fork or branch from `main`
- Keep PRs focused: one fix or feature per PR
- Describe what changed and why in the PR body
- Include the validation commands you ran and their results
- Link the related issue if one exists

## Security Reporting

Do not open a public GitHub issue to report a security vulnerability. See [SECURITY.md](SECURITY.md) for the private reporting process.

## Data and Secrets

Do not commit:

- Secrets, tokens, credentials, or `.env` files
- Customer data, proprietary data, or real personal data
- Large local datasets

Use synthetic examples such as the bundled `examples/demo/sample_orders.csv`.

## Conduct

Keep collaboration respectful and professional. Focus feedback on code and behavior, not people.
