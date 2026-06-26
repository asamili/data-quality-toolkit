"""Pipeline Runner services: dry-run plan modelling plus the existing ELT scaffold.

This module is intentionally Streamlit-free and side-effect free for the dry-run
path. The plan helpers (``default_pipeline_steps``, ``build_pipeline_plan`` and
friends) build deterministic, JSON-serializable data describing *what a run would
do* without touching the filesystem, the database, or any backend write workflow.

The legacy execution helpers (``_run_elt_pipeline`` / ``_load_pipeline_config_file``)
are preserved unchanged; the page keeps them behind an explicit confirmation gate.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

# ── Plan model ───────────────────────────────────────────────────────────────

# Canonical, stable ordering for the product workflow steps. The order is part of
# the contract: tests and the JSON download rely on it staying deterministic.
CANONICAL_STEP_IDS: tuple[str, ...] = (
    "load",
    "preprocess",
    "quality",
    "statistics",
    "drift",
    "manifest",
)

# Deterministic status vocabulary used across the plan.
STATUS_READY = "ready"
STATUS_BLOCKED = "blocked"
STATUS_DEFERRED = "deferred"
STATUS_SKIPPED = "skipped"

# Static, path-free templates. Dynamic fields (enabled/status/warnings and the
# concrete evidence for ``load``) are filled in by ``build_pipeline_plan``.
_STEP_TEMPLATES: dict[str, dict[str, Any]] = {
    "load": {
        "label": "Load / Dataset context",
        "category": "load",
        "description": (
            "Validate the active dataset and capture lightweight, path-safe " "context for the run."
        ),
        "input_summary": "An active dataset selected on the Start page.",
        "output_summary": "Dataset name, size, and readiness fingerprint.",
        "evidence_items": (
            "Dataset display name",
            "Approximate size in bytes",
            "Large-file mode flag",
        ),
        "related_page": "Start / Load Dataset",
        "cli_hint": "dqt profile <dataset.csv>",
    },
    "preprocess": {
        "label": "Preprocess recipe",
        "category": "prepare",
        "description": (
            "Assemble a bounded cleaning recipe and preview before/after deltas "
            "in memory (no overwrite of the source)."
        ),
        "input_summary": "Active dataset plus an optional cleaning recipe.",
        "output_summary": "Recipe steps (JSON) and before/after validation deltas.",
        "evidence_items": (
            "Cleaning recipe steps (JSON)",
            "Before/after row and column deltas",
            "Completeness change",
        ),
        "related_page": "Preprocess Studio",
        "cli_hint": None,
    },
    "quality": {
        "label": "Quality assessment",
        "category": "analyze",
        "description": "Profile the dataset and score it against the quality rules.",
        "input_summary": "Active dataset.",
        "output_summary": "Quality score, completeness, and flagged issues.",
        "evidence_items": (
            "Overall quality score",
            "Completeness score",
            "Flagged issue count",
            "Rule penalty breakdown",
        ),
        "related_page": "Quality Score / Rule Breakdown",
        "cli_hint": "dqt assess <dataset.csv>",
    },
    "statistics": {
        "label": "Statistics / EDA",
        "category": "analyze",
        "description": (
            "Compute descriptive statistics and exploratory summaries for the " "dataset."
        ),
        "input_summary": "Active dataset.",
        "output_summary": "Descriptive statistics, type summary, and correlations.",
        "evidence_items": (
            "Descriptive statistics table",
            "Column type summary",
            "Correlation table",
        ),
        "related_page": "Statistics Lab / EDA Explorer",
        "cli_hint": "dqt profile <dataset.csv>",
    },
    "drift": {
        "label": "Drift monitoring",
        "category": "monitor",
        "description": (
            "Review recorded distribution drift evidence from the local " "monitoring history."
        ),
        "input_summary": "A monitoring history database with prior runs.",
        "output_summary": "Drift run history and per-column drift evidence.",
        "evidence_items": (
            "Drift run history",
            "Per-column PSI / drift status",
            "Distribution evidence",
        ),
        "related_page": "Drift Monitoring",
        "cli_hint": "dqt drift-history list",
    },
    "manifest": {
        "label": "Export / Artifact manifest",
        "category": "deliver",
        "description": (
            "Summarize the lineage manifest and the artifacts a completed run " "would expose."
        ),
        "input_summary": "A completed run with recorded artifacts.",
        "output_summary": "Lineage manifest entry and artifact basenames.",
        "evidence_items": (
            "Lineage manifest entry",
            "Artifact basenames and categories",
            "Run metadata",
        ),
        "related_page": "Artifact Center / Export",
        "cli_hint": "dqt manifest create --run-id <run-id>",
    },
}

# Product step → ``dqt pipeline run`` flag (only the steps the ELT scaffold maps).
_STEP_TO_PIPELINE_FLAG: dict[str, str] = {
    "load": "--extract",
    "preprocess": "--transform",
    "quality": "--assess",
    "manifest": "--manifest",
}

# Steps whose readiness depends on artifacts beyond the active dataset context.
_DEFERRED_WHEN_LOADED = frozenset({"drift", "manifest"})

_RUN_ID_PLACEHOLDER = "<run-id>"
_SESSIONS_ROOT_PLACEHOLDER = "<sessions-root>"


def default_pipeline_steps() -> list[dict[str, Any]]:
    """Return the ordered, stable product workflow step templates.

    Each item is a fresh plain ``dict`` (evidence items materialized as a list)
    so callers may mutate the result without affecting the module templates.
    """
    steps: list[dict[str, Any]] = []
    for step_id in CANONICAL_STEP_IDS:
        template = _STEP_TEMPLATES[step_id]
        steps.append(
            {
                "step_id": step_id,
                "label": template["label"],
                "category": template["category"],
                "description": template["description"],
                "input_summary": template["input_summary"],
                "output_summary": template["output_summary"],
                "evidence_items": list(template["evidence_items"]),
                "related_page": template["related_page"],
                "cli_hint": template["cli_hint"],
            }
        )
    return steps


def normalize_step_selection(selected: Iterable[str] | None) -> list[str]:
    """Return canonical-ordered, de-duplicated, known step ids.

    ``None`` (or an empty selection) defaults to *all* steps enabled. Unknown
    ids are dropped silently so malformed input can never widen scope.
    """
    if selected is None:
        return list(CANONICAL_STEP_IDS)
    requested = {str(s) for s in selected}
    ordered = [sid for sid in CANONICAL_STEP_IDS if sid in requested]
    return ordered if ordered else list(CANONICAL_STEP_IDS)


def validate_pipeline_readiness(
    dataset_context: Any,
    selected_steps: Iterable[str] | None,
) -> dict[str, Any]:
    """Return ``{"ready", "warnings", "blockers"}`` for the selection.

    Readiness derives only from the presence of a dataset context. No file or
    network access occurs.
    """
    normalized = normalize_step_selection(selected_steps)
    warnings: list[str] = []
    blockers: list[str] = []

    if dataset_context is None:
        blockers.append("Load a dataset on the Start page before planning a run.")
    else:
        if getattr(dataset_context, "large_file_mode", False):
            warnings.append(
                "Large-file mode is active; analysis steps may use chunked or " "sampled reads."
            )
        if any(sid in _DEFERRED_WHEN_LOADED for sid in normalized):
            warnings.append(
                "Drift and manifest evidence require prior runs; those steps are "
                "previewed as deferred."
            )

    return {
        "ready": not blockers,
        "warnings": warnings,
        "blockers": blockers,
    }


def build_cli_equivalent(
    run_id: str | None,
    selected_steps: Iterable[str] | None,
    options: Mapping[str, Any] | None = None,
) -> str:
    """Return a deterministic, path-free ``dqt pipeline run`` command string.

    The command is for display only and is never executed. The sessions root is
    always rendered as a placeholder so no absolute local path can leak.
    """
    del options  # reserved for future flags; intentionally unused
    normalized = normalize_step_selection(selected_steps)
    safe_run_id = _safe_run_id(run_id)
    parts = [
        "dqt pipeline run",
        f"--run-id {safe_run_id}",
        f"--sessions-root {_SESSIONS_ROOT_PLACEHOLDER}",
    ]
    for step_id in CANONICAL_STEP_IDS:
        if step_id in normalized and step_id in _STEP_TO_PIPELINE_FLAG:
            parts.append(_STEP_TO_PIPELINE_FLAG[step_id])
    return " ".join(parts)


def build_pipeline_plan(
    dataset_context: Any,
    selected_steps: Iterable[str] | None,
    run_id: str | None,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a deterministic, JSON-serializable dry-run plan.

    No files, DB records, manifests, or server-side output are produced. The
    returned dict only contains plain ``str``/``int``/``bool``/``list``/``dict``
    values and never includes absolute paths, DataFrames, or raw rows.
    """
    del options  # reserved for future flags; intentionally unused
    normalized = set(normalize_step_selection(selected_steps))
    readiness = validate_pipeline_readiness(dataset_context, selected_steps)
    has_context = dataset_context is not None
    large_file = bool(getattr(dataset_context, "large_file_mode", False))

    steps: list[dict[str, Any]] = []
    for step in default_pipeline_steps():
        step_id = step["step_id"]
        enabled = step_id in normalized
        step_warnings: list[str] = []

        if not enabled:
            status = STATUS_SKIPPED
        elif not has_context:
            status = STATUS_BLOCKED
            step_warnings.append("Load a dataset on the Start page first.")
        elif step_id in _DEFERRED_WHEN_LOADED:
            status = STATUS_DEFERRED
            step_warnings.append(f"Requires prior run evidence; open {step['related_page']}.")
        else:
            status = STATUS_READY
            if large_file and step["category"] == "analyze":
                step_warnings.append(
                    "Large-file mode active; results may use chunked or sampled " "reads."
                )

        if step_id == "load" and has_context:
            step["evidence_items"] = _load_evidence(dataset_context)

        step["enabled"] = enabled
        step["status"] = status
        step["warnings"] = step_warnings
        steps.append(step)

    return {
        "kind": "pipeline_dry_run_plan",
        "version": 1,
        "run_id": _safe_run_id(run_id),
        "dataset_ready": has_context,
        "generated_step_count": sum(1 for s in steps if s["enabled"]),
        "warnings": list(readiness["warnings"]),
        "blockers": list(readiness["blockers"]),
        "steps": steps,
        "cli_equivalent": build_cli_equivalent(run_id, selected_steps),
    }


def pipeline_plan_to_json_payload(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe projection of *plan* suitable for in-memory download.

    The plan is already composed of JSON-native types; this returns a shallow,
    ordered copy so the caller cannot accidentally mutate shared state.
    """
    return {
        "kind": plan.get("kind", "pipeline_dry_run_plan"),
        "version": plan.get("version", 1),
        "run_id": plan.get("run_id", _RUN_ID_PLACEHOLDER),
        "dataset_ready": bool(plan.get("dataset_ready", False)),
        "generated_step_count": int(plan.get("generated_step_count", 0)),
        "warnings": list(plan.get("warnings", [])),
        "blockers": list(plan.get("blockers", [])),
        "cli_equivalent": plan.get("cli_equivalent", ""),
        "steps": [dict(step) for step in plan.get("steps", [])],
    }


def summarize_pipeline_evidence(plan: Mapping[str, Any]) -> dict[str, int]:
    """Return deterministic counts over the plan for metric cards."""
    steps = list(plan.get("steps", []))
    enabled = [s for s in steps if s.get("enabled")]
    return {
        "total_steps": len(steps),
        "selected_steps": len(enabled),
        "ready_steps": sum(1 for s in enabled if s.get("status") == STATUS_READY),
        "blocked_steps": sum(1 for s in enabled if s.get("status") == STATUS_BLOCKED),
        "deferred_steps": sum(1 for s in enabled if s.get("status") == STATUS_DEFERRED),
        "evidence_items_total": sum(len(s.get("evidence_items", [])) for s in enabled),
    }


def _load_evidence(dataset_context: Any) -> list[str]:
    """Return concrete, path-free evidence lines for the load step."""
    display_name = str(getattr(dataset_context, "display_name", "") or "(unknown)")
    size_bytes = int(getattr(dataset_context, "size_bytes", 0) or 0)
    large_file = bool(getattr(dataset_context, "large_file_mode", False))
    return [
        f"Dataset: {display_name}",
        f"Approximate size: {size_bytes} bytes",
        f"Large-file mode: {large_file}",
    ]


def _safe_run_id(run_id: str | None) -> str:
    """Collapse whitespace and fall back to a placeholder for empty run ids."""
    if not run_id:
        return _RUN_ID_PLACEHOLDER
    collapsed = "-".join(str(run_id).split())
    return collapsed or _RUN_ID_PLACEHOLDER


# ── Existing execution scaffold (preserved; gated behind confirmation) ───────


def _run_elt_pipeline(
    run_id: str, sessions_root: str | Path
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        from data_quality_toolkit.api import create_elt_pipeline

        pipeline = create_elt_pipeline(run_id, sessions_root)
        result = pipeline.run()
        return dataclasses.asdict(result), None
    except Exception as e:
        return None, str(e)


def _load_pipeline_config_file(path: str | Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        from data_quality_toolkit.shared.config import load_pipeline_config

        config = load_pipeline_config(path)
        return config, None
    except Exception as e:
        return None, str(e)
