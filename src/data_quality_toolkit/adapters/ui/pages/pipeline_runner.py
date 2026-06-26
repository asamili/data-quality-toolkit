"""Pipeline Runner page: preview a dataset workflow as a safe, no-write dry run.

Pipeline Runner is the *operate* surface. It explains what a DQT run would do,
what evidence each step would produce, and which product page owns the detailed
workflow — all without writing files, database records, manifests, or any other
server-side output. The default render path is a **dry run**: it only builds and
displays a deterministic plan (see ``services.pipeline``).

The legacy write-capable ELT execution scaffold is preserved but demoted into a
secondary section that stays inert unless the user explicitly confirms it. This
module keeps Streamlit rendering thin; all plan logic lives in pure helpers.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.components.dataset_context import (
    render_dataset_context_panel,
)
from data_quality_toolkit.adapters.ui.components.downloads import json_download_button
from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_metric_cards,
    render_page_header,
    render_section_header,
    render_status_chip,
)
from data_quality_toolkit.adapters.ui.components.states import (
    render_empty_state,
    render_info_state,
    render_warning_state,
)
from data_quality_toolkit.adapters.ui.services.pipeline import (
    _load_pipeline_config_file,
    _run_elt_pipeline,
    build_pipeline_plan,
    default_pipeline_steps,
    normalize_step_selection,
    pipeline_plan_to_json_payload,
    summarize_pipeline_evidence,
)
from data_quality_toolkit.adapters.ui.state import keys
from data_quality_toolkit.adapters.ui.state.context import get_dataset_context

_INTRO = (
    "This is a dry run. Pipeline Runner previews the steps a workflow would take, "
    "the evidence each step would produce, and which page owns the detail — without "
    "writing any files, records, or manifests."
)

# Step id → step-selection session key (checkbox state).
_STEP_KEYS: dict[str, str] = {
    "load": keys.PIPE_STEP_LOAD,
    "preprocess": keys.PIPE_STEP_PREPROCESS,
    "quality": keys.PIPE_STEP_QUALITY,
    "statistics": keys.PIPE_STEP_STATISTICS,
    "drift": keys.PIPE_STEP_DRIFT,
    "manifest": keys.PIPE_STEP_MANIFEST,
}

# Plan status → status-chip tone.
_STATUS_TONE: dict[str, str] = {
    "ready": "ok",
    "deferred": "info",
    "blocked": "error",
    "skipped": "info",
}


def _selected_steps(st: Any, state: Mapping[str, Any]) -> list[str]:
    """Render one checkbox per workflow step and return the normalized selection."""
    selected: list[str] = []
    for step in default_pipeline_steps():
        step_id = step["step_id"]
        checked = st.checkbox(step["label"], value=True, key=_STEP_KEYS[step_id])
        if checked:
            selected.append(step_id)
    return normalize_step_selection(selected)


def _plan_table(plan: Mapping[str, Any]) -> pd.DataFrame:
    """Build a path-free table of the enabled steps for display."""
    return pd.DataFrame(
        [
            {
                "step": step["label"],
                "status": step["status"],
                "owned by": step["related_page"],
                "needs": step["input_summary"],
                "produces": step["output_summary"],
            }
            for step in plan["steps"]
            if step["enabled"]
        ]
    )


def _render_readiness(st: Any, state: Mapping[str, Any]) -> Any:
    """Render dataset readiness and return the active context (or ``None``)."""
    render_section_header(st, "Dataset readiness")
    context = get_dataset_context(state)
    if context is not None:
        render_dataset_context_panel(st, context)
        render_status_chip(st, "Dataset is ready for a dry-run plan.", tone="ok")
    else:
        render_empty_state(
            st,
            "No dataset loaded",
            "Load a dataset on the Start page first. You can still preview the plan "
            "below — every step will show as blocked until a dataset is active.",
        )
    return context


def _render_dry_run(st: Any, plan: Mapping[str, Any]) -> None:
    """Render the dry-run plan preview, evidence, CLI equivalence, and download."""
    render_section_header(
        st,
        "Dry-run preview",
        "Nothing here writes to disk or the database — it only describes the run.",
    )
    summary = summarize_pipeline_evidence(plan)
    render_metric_cards(
        st,
        [
            {"label": "Selected steps", "value": str(summary["selected_steps"])},
            {"label": "Ready", "value": str(summary["ready_steps"])},
            {"label": "Deferred", "value": str(summary["deferred_steps"])},
            {"label": "Evidence items", "value": str(summary["evidence_items_total"])},
        ],
    )

    for warning in plan["warnings"]:
        render_warning_state(st, warning)
    for blocker in plan["blockers"]:
        render_status_chip(st, blocker, tone="error")

    table = _plan_table(plan)
    if table.empty:
        render_info_state(st, "Select at least one step to preview a plan.")
    else:
        st.dataframe(table)

    _render_evidence(st, plan)

    render_section_header(
        st, "CLI equivalence", "Run the same workflow from the command line (not executed here)."
    )
    st.code(plan["cli_equivalent"])

    json_download_button(
        st,
        "Download dry-run plan (JSON)",
        pipeline_plan_to_json_payload(plan),
        "pipeline_dry_run_plan.json",
    )


def _render_evidence(st: Any, plan: Mapping[str, Any]) -> None:
    """Render per-step evidence and warnings as text (no charts, no paths)."""
    render_section_header(
        st, "Evidence plan", "What each selected step would produce, and who owns it."
    )
    for step in plan["steps"]:
        if not step["enabled"]:
            continue
        cli_hint = step["cli_hint"] or "UI-only (no CLI command)"
        lines = [
            f"**{step['label']}** — _{step['status']}_  ",
            f"Owned by: {step['related_page']} · CLI: `{cli_hint}`  ",
            f"{step['description']}  ",
            "Evidence: " + "; ".join(step["evidence_items"]),
        ]
        for warning in step["warnings"]:
            lines.append(f"⚠️ {warning}")
        st.markdown("\n".join(lines))


def _render_execution_scaffold(st: Any, state: MutableMapping[str, Any], run_id: str) -> None:
    """Render the legacy write-capable scaffold, gated behind explicit confirmation."""
    render_section_header(
        st,
        "Existing execution scaffold (advanced)",
        "Optional. This path can read lineage and produce output — keep it off unless you mean it.",
    )
    render_status_chip(
        st,
        "Write-capable: running the ELT scaffold can create or read run artifacts.",
        tone="warn",
    )
    sessions_root = st.text_input("Sessions Root", key=keys.PIPE_SESSIONS_ROOT)
    config_path = st.text_input("Pipeline YAML Config Path (optional)", key=keys.PIPE_CONFIG_PATH)
    confirmed = st.checkbox(
        "I understand this can read lineage and produce output.",
        value=False,
        key=keys.PIPE_CONFIRM_EXEC,
    )
    run_clicked = st.button("Run existing scaffold", key=keys.PIPE_RUN_BTN)

    if not run_clicked:
        return
    if not confirmed:
        render_warning_state(st, "Confirm the checkbox above before running the scaffold.")
        return
    _execute_scaffold(st, run_id, sessions_root, config_path)


def _execute_scaffold(st: Any, run_id: str, sessions_root: str, config_path: str) -> None:
    """Run the preserved ELT scaffold after explicit confirmation."""
    if not run_id or not sessions_root:
        st.error("Run ID and Sessions Root are required.")
        return
    if config_path:
        _, err = _load_pipeline_config_file(config_path)
        if err:
            st.error(f"Error loading config: {err}")
            return

    result, err = _run_elt_pipeline(run_id, sessions_root)
    if err:
        st.error(f"Pipeline error: {err}")
        return
    st.success("Pipeline executed successfully.")
    st.json(result)


def _render_pipeline_runner(st: Any, session_state: MutableMapping[str, Any] | None = None) -> None:
    """Render the Pipeline Runner page body."""
    state: MutableMapping[str, Any] = session_state if session_state is not None else {}
    render_page_header(
        st,
        "Pipeline Runner",
        "Preview a dataset workflow as a safe dry run before anything is written.",
        step_label="Step 7 of 11 — Pipeline Runner",
    )
    render_status_chip(st, _INTRO, tone="info")

    context = _render_readiness(st, state)

    render_section_header(st, "Run configuration")
    run_id = st.text_input("Run ID", key=keys.PIPE_RUN_ID)

    render_section_header(st, "Step selection")
    selected = _selected_steps(st, state)

    plan = build_pipeline_plan(context, selected, run_id)
    _render_dry_run(st, plan)

    _render_execution_scaffold(st, state, run_id)


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_pipeline_runner(st, st.session_state)  # type: ignore[arg-type, unused-ignore]
