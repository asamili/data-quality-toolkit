---
name: Improvement Cycle
about: Track a focused improvement cycle
title: 'Cycle: [SHORT NAME]'
labels: improvement, implementation
assignees: ''
---

## Improvement Cycle — [NAME]

## Overview

**Status**: Not Started | In Progress | Complete | Blocked
**Start Date**:
**Target Completion**:

## Objective

<!-- What does this cycle accomplish? Keep scope narrow: CLI-first, CSV-first. -->

## Scope

### Changes Planned

<!-- List the targeted files and what changes -->

- [ ] `src/...` — [what changes and why]
- [ ] `tests/...` — [what tests cover this]

### Out of Scope

<!-- Explicit boundary: what this cycle does NOT touch -->

## Acceptance Criteria

- [ ] Targeted pytest passes: `python -m pytest tests/<path>`
- [ ] `ruff` and `mypy` clean on changed files
- [ ] End-to-end CLI run produces correct output
- [ ] CHANGELOG.md updated if user-visible behavior changed
- [ ] Docs/demo updated if output or flags changed

## Risk Assessment

| File / Area       | Risk                | Notes |
|-------------------|---------------------|-------|
|                   | Low / Medium / High |       |

## Key Tasks

- [ ] Task 1
- [ ] Task 2
- [ ] Task 3

## Validation Notes

<!-- Record what was actually run to verify this cycle -->

## Known Limitations / Follow-On

<!-- Anything deferred to a future cycle -->
