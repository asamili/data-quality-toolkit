"""Preprocess Studio page: build, preview, validate, and export safe cleaning recipes.

Preprocess Studio is the *prepare* surface. It lets a user assemble a recipe of
bounded, deterministic transforms (type casts, missing-value handling,
deduplication, IQR outlier handling, encoding, scaling, derived columns), apply
it **in-memory on a copy** of the loaded dataset, review before/after validation,
and export the recipe as JSON to replay later. Nothing is written server-side
during render; the original dataset is never overwritten. Transform logic lives
in pure helpers (``services.preprocessing`` + ``workflow.preprocessing``); this
module keeps Streamlit rendering thin.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, MutableMapping
from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.components.dataset_context import (
    render_dataset_context_panel,
)
from data_quality_toolkit.adapters.ui.components.downloads import (
    csv_download_button,
    json_download_button,
)
from data_quality_toolkit.adapters.ui.components.errors import show_error
from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_metric_cards,
    render_page_header,
    render_section_header,
    render_status_chip,
)
from data_quality_toolkit.adapters.ui.components.states import render_warning_state
from data_quality_toolkit.adapters.ui.eda import _load_df_and_assess
from data_quality_toolkit.adapters.ui.services.preprocessing import (
    PREVIEW_ROWS,
    apply_recipe,
    is_large_frame,
    preview_frame,
)
from data_quality_toolkit.adapters.ui.state.context import get_dataset_context
from data_quality_toolkit.adapters.ui.state.keys import (
    PREP_ADD_STEP_BTN,
    PREP_CLEAR_RECIPE_BTN,
    PREP_COLUMNS,
    PREP_CSV_PATH,
    PREP_DERIVED_KIND,
    PREP_DERIVED_SOURCE,
    PREP_ENCODING_STRATEGY,
    PREP_FILL_VALUE,
    PREP_MISSING_STRATEGY,
    PREP_OPERATION,
    PREP_OUTLIER_STRATEGY,
    PREP_RECIPE_STEPS,
    PREP_SCALING_STRATEGY,
    PREP_TARGET_TYPE,
)
from data_quality_toolkit.application.workflow.preprocessing import (
    OP_DERIVED,
    OP_DROP_DUPLICATES,
    OP_ENCODING,
    OP_MISSING,
    OP_OUTLIER,
    OP_SCALING,
    OP_TYPE_CAST,
    make_recipe_step,
    plan_preprocessing,
    recipe_to_json_payload,
    summarize_before_after,
)

# Human label → operation identifier (drives the build-recipe selector).
_OPERATIONS: dict[str, str] = {
    "Type cast": OP_TYPE_CAST,
    "Missing values": OP_MISSING,
    "Drop duplicates": OP_DROP_DUPLICATES,
    "IQR outliers": OP_OUTLIER,
    "Encoding": OP_ENCODING,
    "Scaling": OP_SCALING,
    "Derived column": OP_DERIVED,
}

_SAFETY_BANNER = (
    "Preview only — transforms run in-memory on a copy of the dataset. The "
    "original is never changed. Nothing is saved unless you export the recipe."
)


# ── recipe-state helpers (pure; testable without Streamlit) ──────────────────


def _current_steps(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    steps = state.get(PREP_RECIPE_STEPS)
    return list(steps) if isinstance(steps, list) else []


def _append_step(
    state: MutableMapping[str, Any],
    operation: str,
    columns: list[str],
    parameters: Mapping[str, Any],
) -> None:
    """Append a recipe step to session state (no-op for an empty operation)."""
    if not operation:
        return
    steps = _current_steps(state)
    steps.append(make_recipe_step(operation, columns, dict(parameters)))
    state[PREP_RECIPE_STEPS] = steps


def _recipe_table(steps: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "step_id": s["step_id"],
                "operation": s["operation"],
                "columns": ", ".join(s["columns"]) or "—",
                "parameters": json.dumps(s["parameters"], default=str),
                "status": s.get("status", "pending"),
                "warning": s.get("warning") or "—",
            }
            for s in steps
        ]
    )


# ── sections ─────────────────────────────────────────────────────────────────


def _render_recommendations(st: Any, df: pd.DataFrame) -> None:
    render_section_header(
        st,
        "Recommended actions",
        "Advisory per-column issues and suggested transforms (also shown on EDA Explorer).",
    )
    plan = plan_preprocessing(df)
    if not plan:
        st.info("No columns to analyze.")
        return
    st.dataframe(pd.DataFrame(plan), hide_index=True)


def _collect_params(st: Any, operation: str, df: pd.DataFrame) -> dict[str, Any]:
    if operation == OP_TYPE_CAST:
        return {
            "target_type": st.selectbox(
                "Target type", ["numeric", "string", "datetime", "boolean"], key=PREP_TARGET_TYPE
            )
        }
    if operation == OP_MISSING:
        strategy = st.selectbox(
            "Strategy", ["drop", "mean", "median", "mode", "constant"], key=PREP_MISSING_STRATEGY
        )
        params: dict[str, Any] = {"strategy": strategy}
        if strategy == "constant":
            params["fill_value"] = st.text_input("Fill value (plain text)", key=PREP_FILL_VALUE)
        return params
    if operation == OP_OUTLIER:
        return {
            "strategy": st.selectbox(
                "Strategy", ["flag", "clip", "remove"], key=PREP_OUTLIER_STRATEGY
            )
        }
    if operation == OP_ENCODING:
        return {
            "strategy": st.selectbox(
                "Strategy", ["one_hot", "frequency", "label"], key=PREP_ENCODING_STRATEGY
            )
        }
    if operation == OP_SCALING:
        return {
            "strategy": st.selectbox("Strategy", ["minmax", "zscore"], key=PREP_SCALING_STRATEGY)
        }
    if operation == OP_DERIVED:
        return {
            "source_column": st.selectbox(
                "Source column", list(df.columns), key=PREP_DERIVED_SOURCE
            ),
            "derived_kind": st.selectbox(
                "Derived value",
                ["year", "month", "day", "day_of_week", "text_length"],
                key=PREP_DERIVED_KIND,
            ),
        }
    return {}


def _render_build_recipe(st: Any, df: pd.DataFrame, state: MutableMapping[str, Any]) -> None:
    render_section_header(st, "Build recipe", "Add bounded, deterministic steps to your recipe.")
    label = st.selectbox("Operation", list(_OPERATIONS), key=PREP_OPERATION)
    operation = _OPERATIONS.get(label or "", "")
    columns = st.multiselect("Target columns", list(df.columns), key=PREP_COLUMNS) or []
    params = _collect_params(st, operation, df)
    if st.button("Add step to recipe", key=PREP_ADD_STEP_BTN):
        _append_step(state, operation, list(columns), params)
    steps = _current_steps(state)
    if steps:
        st.dataframe(_recipe_table(steps), hide_index=True)
        if st.button("Clear recipe", key=PREP_CLEAR_RECIPE_BTN):
            state[PREP_RECIPE_STEPS] = []
    else:
        st.caption("No steps yet. Add a step above to build a recipe.")


def _render_summary_cards(st: Any, summary: Mapping[str, Any]) -> None:
    before, after = summary["before"], summary["after"]
    render_metric_cards(
        st,
        [
            {
                "label": "Rows",
                "value": f"{after['row_count']:,}",
                "delta": after["row_count"] - before["row_count"],
            },
            {
                "label": "Columns",
                "value": f"{after['column_count']:,}",
                "delta": after["column_count"] - before["column_count"],
            },
            {
                "label": "Missing cells",
                "value": f"{after['missing_cells']:,}",
                "delta": after["missing_cells"] - before["missing_cells"],
            },
            {
                "label": "Duplicate rows",
                "value": f"{after['duplicate_rows']:,}",
                "delta": after["duplicate_rows"] - before["duplicate_rows"],
            },
            {"label": "Completeness", "value": f"{after['completeness'] * 100:.2f}%"},
        ],
    )


def _render_dtype_changes(st: Any, summary: Mapping[str, Any]) -> None:
    changes = summary["dtype_changes"]
    added, removed = summary["added_columns"], summary["removed_columns"]
    if not changes and not added and not removed:
        st.caption("No dtype or column changes.")
        return
    rows = [{"column": c, "from": v["from"], "to": v["to"]} for c, v in changes.items()]
    rows += [{"column": c, "from": "—", "to": "added"} for c in added]
    rows += [{"column": c, "from": "removed", "to": "—"} for c in removed]
    st.dataframe(pd.DataFrame(rows), hide_index=True)


def _render_apply_and_validation(
    st: Any, df: pd.DataFrame, steps: list[dict[str, Any]]
) -> pd.DataFrame | None:
    render_section_header(
        st,
        "Preview & before/after validation",
        "Transforms run in-memory on a copy of the dataset.",
    )
    if not steps:
        st.info("Add at least one recipe step to preview a transformed dataset.")
        return None
    transformed, executed = apply_recipe(df, steps)
    st.dataframe(_recipe_table(executed), hide_index=True)
    summary = summarize_before_after(df, transformed)
    _render_summary_cards(st, summary)
    _render_dtype_changes(st, summary)
    render_section_header(
        st, "Transformed preview", f"First {PREVIEW_ROWS} rows of the preview copy."
    )
    st.dataframe(preview_frame(transformed), hide_index=True)
    return transformed


def _render_export(st: Any, df: pd.DataFrame, steps: list[dict[str, Any]]) -> None:
    render_section_header(
        st,
        "Export recipe",
        "Download the recipe as JSON to replay later. In-memory only — no files are written here.",
    )
    if not steps:
        st.info("Build a recipe to enable export.")
        return
    transformed, executed = apply_recipe(df, steps)
    summary = summarize_before_after(df, transformed)
    payload = recipe_to_json_payload(executed, summary)
    json_download_button(st, "Download recipe (JSON)", payload, "preprocess_recipe.json")
    csv_download_button(
        st, "Download recipe steps (CSV)", _recipe_table(executed), "preprocess_recipe_steps.csv"
    )


# ── page body ────────────────────────────────────────────────────────────────


def _render_preprocess_studio(
    st: Any, session_state: MutableMapping[str, Any] | None = None
) -> None:
    """Render the Preprocess Studio page body."""
    state: MutableMapping[str, Any] = session_state if session_state is not None else {}
    render_page_header(
        st,
        "Preprocess Studio",
        "Build a reversible cleaning recipe, preview it in-memory, and export it to replay.",
        step_label="Step 6 of 11 — Preprocess Studio",
    )
    render_status_chip(st, _SAFETY_BANNER, tone="warn")

    context = get_dataset_context(state)
    if context is not None:
        render_dataset_context_panel(st, context)
        if context.large_file_mode:
            render_warning_state(
                st,
                "Preprocess Studio needs full analysis mode. Return to Start and select full "
                "analysis to prepare data in-memory.",
            )
            return
        csv_path = context.source_path
    else:
        csv_path = st.text_input(
            "CSV path", placeholder="e.g., ./data/my_dataset.csv", key=PREP_CSV_PATH
        )
    if not csv_path:
        st.info("💡 Start with a dataset context or enter a CSV path above to prepare data.")
        return

    df, result, err = _load_df_and_assess(csv_path)
    if err is not None:
        show_error(st, "Load Error", err)
        return
    if df is None:
        return

    if is_large_frame(df):
        render_warning_state(
            st,
            f"Large dataset ({len(df):,} rows). The preview shows the first {PREVIEW_ROWS} rows; "
            "transforms still run in-memory on the full copy.",
        )

    _render_recommendations(st, df)
    _render_build_recipe(st, df, state)
    steps = _current_steps(state)
    _render_apply_and_validation(st, df, steps)
    _render_export(st, df, steps)


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_preprocess_studio(st, st.session_state)  # type: ignore[arg-type, unused-ignore]
