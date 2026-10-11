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
import math
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui import journey
from data_quality_toolkit.adapters.ui.components.dataset_context import (
    render_dataset_context_panel,
)
from data_quality_toolkit.adapters.ui.components.downloads import (
    csv_download_button,
    json_download_button,
)
from data_quality_toolkit.adapters.ui.components.errors import show_error
from data_quality_toolkit.adapters.ui.components.page_guidance import render_page_guidance
from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_metric_cards,
    render_page_header,
    render_section_header,
    render_status_chip,
)
from data_quality_toolkit.adapters.ui.components.source_hub import render_dataset_source_callout
from data_quality_toolkit.adapters.ui.components.states import render_warning_state
from data_quality_toolkit.adapters.ui.components.workspace_save_ui import (
    WORKSPACE_ROOT_EMPTY_STATE,
    _workspace_root_value,
)
from data_quality_toolkit.adapters.ui.eda import _load_df_and_assess
from data_quality_toolkit.adapters.ui.services.dataset_activation import (
    DatasetActivationError,
    activate_dataset_context,
    make_managed_context,
)
from data_quality_toolkit.adapters.ui.services.dataset_confirmation import (
    ConfirmationStatus,
    ConfirmedVersionHandoff,
    confirm_processed_version,
    resolve_confirmation_parent,
)
from data_quality_toolkit.adapters.ui.services.managed_frame_loader import (
    ManagedFrameLoadError,
    get_managed_frame,
)
from data_quality_toolkit.adapters.ui.services.managed_recipe_reprocessing import (
    LoadedRecipe,
    ReprocessedChild,
    confirm_reprocessed_child,
    create_recipe_draft,
    derive_action_reference,
    load_confirmed_recipe,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    ManagedTrustRoot,
    TrustAuthority,
    resolve_trust_authority,
)
from data_quality_toolkit.adapters.ui.services.preprocessing import (
    PREVIEW_ROWS,
    apply_recipe,
    is_large_frame,
    preview_frame,
    replay_refusal_code,
)
from data_quality_toolkit.adapters.ui.services.preprocessing_calculations import (
    CALC_OPERATIONS,
    MAX_BINS,
    MIN_BINS,
    OP_CALC_ARITHMETIC,
    OP_CALC_BINNING,
    OP_CALC_CONDITIONAL,
    OP_CALC_SCALAR,
    OP_CALC_STRING,
)
from data_quality_toolkit.adapters.ui.services.workspace_save import (
    WorkspaceSaveResult,
    build_workspace_filename,
    save_to_workspace,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext, get_dataset_context
from data_quality_toolkit.adapters.ui.state.keys import (
    PREP_ADD_STEP_BTN,
    PREP_CALC_ARITH_OP,
    PREP_CALC_BIN_COUNT,
    PREP_CALC_BIN_SRC,
    PREP_CALC_COND_CMP,
    PREP_CALC_COND_ELSE,
    PREP_CALC_COND_SRC,
    PREP_CALC_COND_THEN,
    PREP_CALC_COND_VALUE,
    PREP_CALC_LEFT,
    PREP_CALC_OUTPUT_EXISTING,
    PREP_CALC_OUTPUT_MODE,
    PREP_CALC_OUTPUT_NEW,
    PREP_CALC_RIGHT,
    PREP_CALC_SCALAR_OP,
    PREP_CALC_SCALAR_SRC,
    PREP_CALC_SCALAR_VALUE,
    PREP_CALC_STR_FIND,
    PREP_CALC_STR_LITERAL,
    PREP_CALC_STR_OP,
    PREP_CALC_STR_OTHER,
    PREP_CALC_STR_REPLACE,
    PREP_CALC_STR_SRC,
    PREP_CLEAR_RECIPE_BTN,
    PREP_COLUMNS,
    PREP_CONFIRMED_VERSION,
    PREP_CSV_PATH,
    PREP_DERIVED_KIND,
    PREP_DERIVED_SOURCE,
    PREP_EDIT_STEP_SELECT,
    PREP_ENCODING_STRATEGY,
    PREP_FILL_VALUE,
    PREP_MISSING_STRATEGY,
    PREP_MOVE_DOWN_BTN,
    PREP_MOVE_UP_BTN,
    PREP_OPERATION,
    PREP_OUTLIER_STRATEGY,
    PREP_RECIPE_STEPS,
    PREP_REMOVE_STEP_BTN,
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

# Workspace subfolder and widget keys for the opt-in recipe Save-to-Workspace action.
# Defined locally (not in state/keys.py); this gate does not add shared source keys.
_RECIPES_SUBFOLDER = "recipes"
_SAVE_RECIPE_JSON_BTN = "prep_save_recipe_json_btn"
_SAVE_RECIPE_STEPS_BTN = "prep_save_recipe_steps_btn"

# Transformed-dataset output: browser CSV download name, workspace subfolder, and the
# opt-in Save-to-Workspace button key. The full cleaned dataset is kept separate from the
# recipe artifacts (recipes/) and from EDA analysis snippets (analysis/).
_TRANSFORMED_SUBFOLDER = "preprocessed"
_TRANSFORMED_CSV_NAME = "preprocessed_dataset.csv"
_SAVE_TRANSFORMED_BTN = "prep_save_transformed_btn"

# Explicit lifecycle confirmation (stage 6). Downloading or saving the CSV above is
# deliberately NON-confirming: only this action registers a lifecycle version, and
# activation stays a separate, explicit choice.
_VERSION_LABEL = "prep_version_label"
_CONFIRM_VERSION_BTN = "prep_confirm_version_btn"
_SET_ACTIVE_BTN = "prep_set_active_btn"

# Trusted reload / reprocessing (stage 7, managed FULL only). Widget and session
# keys are local to this page — this gate adds no shared source keys. Session
# slots hold the immutable loaded recipe and its detached editable draft.
_RELOAD_RECIPE_BTN = "prep_reload_recipe_btn"
_RELOAD_REMOVE_STEP_BTN = "prep_reload_remove_step_btn"
_RELOAD_STEP_SELECT = "prep_reload_step_select"
_RELOAD_CONFIRM_CHILD_BTN = "prep_reload_confirm_child_btn"
_RELOAD_CHILD_LABEL = "prep_reload_child_label"
_RELOAD_LOADED_STATE = "prep_reload_loaded"
_RELOAD_DRAFT_STATE = "prep_reload_draft"

# Fixed operator copy for the trusted-reload surface. The original steps are shown
# by operation and target columns only; raw parameter values are never rendered,
# so a trusted reload never leaks the recipe's exact configured values.
_RELOAD_PARAMS_HIDDEN = "hidden"
_RELOAD_NOT_ACTIVE_NOTE = (
    "A confirmed child is a new immutable version. It is NOT made active — reopen "
    "it explicitly from Start to activate it."
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
    "Calc: arithmetic (column ↔ column)": OP_CALC_ARITHMETIC,
    "Calc: scalar operation": OP_CALC_SCALAR,
    "Calc: conditional column": OP_CALC_CONDITIONAL,
    "Calc: numeric binning": OP_CALC_BINNING,
    "Calc: string operation": OP_CALC_STRING,
}

_SAFETY_BANNER = (
    "Preview only — transforms run in-memory on a copy of the dataset. The "
    "original is never changed. Nothing is saved unless you export the recipe."
)

# One-line operator flow map shown under the safety banner so the numbered stage
# headers below read as a single guided sequence.
_FLOW_MAP = (
    "Flow: 1 Review recommendations → 2 Build recipe → 3 Preview & validate → "
    "4 Get transformed dataset → 5 Save or export the recipe → "
    "6 Confirm a processed version"
)

# Fixed, privacy-safe refusal shown when a managed-looking dataset context has
# no valid managed trust root (root-first authority, fail-closed).
_MANAGED_FAIL_CLOSED_MESSAGE = (
    "The managed dataset context is not backed by a valid managed trust root. "
    "Reopen the managed version explicitly to continue."
)

_MANAGED_LARGE_PREPROCESS_MESSAGE = (
    "Preprocess Studio needs full analysis mode. Reopen a full-analysis managed "
    "version to prepare data in-memory."
)

_ARITHMETIC_OPERATORS = ["add", "subtract", "multiply", "divide", "power"]
_SCALAR_OPERATORS = ["add", "subtract", "multiply", "divide", "power", "round"]
_POWER_HELP = (
    "Power / Exponentiation: the left operand is the base; the right operand is the "
    "exponent. Invalid, complex-producing, and non-finite results become null."
)
_OPERATOR_LABELS = {"power": "Power / Exponentiation (x^y)"}

_POWER_MODE_COLUMN_CONSTANT = "Column raised to constant"
_POWER_MODE_COLUMN_COLUMN = "Column raised to column"
_POWER_MODE_CONSTANT_COLUMN = "Constant raised to column"
_POWER_MODES = (
    _POWER_MODE_COLUMN_CONSTANT,
    _POWER_MODE_COLUMN_COLUMN,
    _POWER_MODE_CONSTANT_COLUMN,
)

_POWER_CONSTANT_CUSTOM = "Custom number"
_POWER_CONSTANT_PI = "π — Pi"
_POWER_CONSTANT_E = "e — Euler’s number"
_POWER_CONSTANT_SQRT2 = "√2 — Square root of two"
_POWER_CONSTANT_CHOICES = (
    _POWER_CONSTANT_CUSTOM,
    _POWER_CONSTANT_PI,
    _POWER_CONSTANT_E,
    _POWER_CONSTANT_SQRT2,
)
_POWER_CONSTANT_VALUES = {
    _POWER_CONSTANT_PI: ("π", math.pi),
    _POWER_CONSTANT_E: ("e", math.e),
    _POWER_CONSTANT_SQRT2: ("√2", math.sqrt(2.0)),
}
_POWER_MODE_KEY = "prep_calc_power_mode"
_POWER_CONSTANT_KEY = "prep_calc_power_constant"
_POWER_CUSTOM_MIN = -1_000_000_000.0
_POWER_CUSTOM_MAX = 1_000_000_000.0


def _format_calc_operator(operator: str) -> str:
    return _OPERATOR_LABELS.get(operator, operator)


def _resolve_power_constant(selection: str, custom_value: Any = 2.0) -> float:
    """Resolve a UI constant choice to a finite float without parsing expressions."""
    if selection == _POWER_CONSTANT_CUSTOM:
        value = float(custom_value)
    else:
        try:
            value = float(_POWER_CONSTANT_VALUES[selection][1])
        except KeyError as exc:
            raise ValueError(f"unknown power constant {selection!r}") from exc
    if not math.isfinite(value):
        raise ValueError("power constant must be finite")
    return value


def _format_power_number(value: float) -> str:
    return f"{value:.12g}"


def _power_constant_display_label(selection: str, value: float) -> str:
    if selection == _POWER_CONSTANT_CUSTOM:
        return _format_power_number(value)
    return _POWER_CONSTANT_VALUES[selection][0]


def _power_expression_preview(output_column: str, base_label: str, exponent_label: str) -> str:
    return f"{output_column} = {base_label} ^ {exponent_label}"


def _power_default_output_name(params: Mapping[str, Any]) -> str:
    if "left_column" in params and "right_column" in params:
        return f"{params['left_column']}__power__{params['right_column']}"
    return f"{params.get('source_column', 'result')}__power"


def _output_preview_name(params: Mapping[str, Any], default_name: str) -> str:
    name = str(params.get("output_column") or "").strip()
    return name or default_name


def _calculation_recipe_operation(selected_operation: str, params: Mapping[str, Any]) -> str:
    """Return the recipe operation needed by the collected calculated-column params."""
    if params.get("operator") != "power":
        return selected_operation
    if "left_column" in params and "right_column" in params:
        return OP_CALC_ARITHMETIC
    return OP_CALC_SCALAR


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


def _remove_step(state: MutableMapping[str, Any], index: int) -> None:
    """Remove the recipe step at *index* (no-op when out of range)."""
    steps = _current_steps(state)
    if 0 <= index < len(steps):
        steps.pop(index)
        state[PREP_RECIPE_STEPS] = steps


def _move_step(state: MutableMapping[str, Any], index: int, delta: int) -> None:
    """Swap the step at *index* with its neighbour *delta* away (no-op if invalid)."""
    steps = _current_steps(state)
    target = index + delta
    if 0 <= index < len(steps) and 0 <= target < len(steps):
        steps[index], steps[target] = steps[target], steps[index]
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
        "1 · Review recommendations",
        "Advisory only — per-column issues and suggested transforms (also shown on EDA "
        "Explorer). Nothing is applied automatically.",
    )
    plan = plan_preprocessing(df)
    if not plan:
        st.info("No columns to analyze.")
        return
    st.dataframe(pd.DataFrame(plan), hide_index=True)


def _collect_output_target(st: Any, df: pd.DataFrame) -> dict[str, Any]:
    """Collect the destination for a calculated column (new column by default).

    Existing-column update is opt-in and warns that only the in-memory preview
    copy is affected; the original file is never rewritten.
    """
    mode = st.selectbox(
        "Output column",
        ["Create new column", "Update existing column"],
        key=PREP_CALC_OUTPUT_MODE,
    )
    if mode == "Update existing column":
        st.warning(
            "Existing-column update rewrites the transformed preview copy only — the original "
            "file is never modified."
        )
        existing = st.selectbox(
            "Column to overwrite", list(df.columns), key=PREP_CALC_OUTPUT_EXISTING
        )
        return {"output_mode": "existing", "output_column": existing}
    new_name = st.text_input("New column name (blank = auto)", key=PREP_CALC_OUTPUT_NEW)
    return {"output_mode": "new", "output_column": new_name}


def _collect_power_constant(st: Any, label: str) -> tuple[float, str]:
    selection = st.selectbox("Constant", _POWER_CONSTANT_CHOICES, key=_POWER_CONSTANT_KEY)
    if selection == _POWER_CONSTANT_CUSTOM:
        value = _resolve_power_constant(
            selection,
            st.number_input(
                label,
                min_value=_POWER_CUSTOM_MIN,
                max_value=_POWER_CUSTOM_MAX,
                value=2.0,
                step=0.5,
                key=PREP_CALC_SCALAR_VALUE,
            ),
        )
    else:
        value = _resolve_power_constant(selection)
        st.caption(f"Resolved value: {_format_power_number(value)}")
    return value, _power_constant_display_label(selection, value)


def _collect_power_params(st: Any, columns: list[str]) -> tuple[dict[str, Any], str, str]:
    mode = st.selectbox("Power mode", _POWER_MODES, key=_POWER_MODE_KEY)
    if mode == _POWER_MODE_COLUMN_COLUMN:
        base = st.selectbox("Base column", columns, key=PREP_CALC_LEFT)
        exponent = st.selectbox("Exponent column", columns, key=PREP_CALC_RIGHT)
        return (
            {"left_column": base, "operator": "power", "right_column": exponent},
            str(base),
            str(exponent),
        )
    if mode == _POWER_MODE_CONSTANT_COLUMN:
        constant, constant_label = _collect_power_constant(st, "Base constant")
        exponent = st.selectbox("Exponent column", columns, key=PREP_CALC_SCALAR_SRC)
        return (
            {
                "source_column": exponent,
                "operator": "power",
                "scalar": constant,
                "constant_role": "base",
            },
            constant_label,
            str(exponent),
        )
    base = st.selectbox("Base column", columns, key=PREP_CALC_SCALAR_SRC)
    constant, constant_label = _collect_power_constant(st, "Exponent constant")
    return (
        {
            "source_column": base,
            "operator": "power",
            "scalar": constant,
            "constant_role": "exponent",
        },
        str(base),
        constant_label,
    )


def _collect_calc_params(st: Any, operation: str, df: pd.DataFrame) -> dict[str, Any]:
    """Collect parameters for the calculated-column operations."""
    columns = list(df.columns)
    power_preview: tuple[str, str] | None = None
    if operation == OP_CALC_ARITHMETIC:
        operator = st.selectbox(
            "Operator",
            _ARITHMETIC_OPERATORS,
            key=PREP_CALC_ARITH_OP,
            format_func=_format_calc_operator,
        )
        if operator == "power":
            params, base_label, exponent_label = _collect_power_params(st, columns)
            power_preview = (base_label, exponent_label)
        else:
            params = {
                "left_column": st.selectbox("Left column", columns, key=PREP_CALC_LEFT),
                "operator": operator,
                "right_column": st.selectbox("Right column", columns, key=PREP_CALC_RIGHT),
            }
    elif operation == OP_CALC_SCALAR:
        operator = st.selectbox(
            "Operator",
            _SCALAR_OPERATORS,
            key=PREP_CALC_SCALAR_OP,
            format_func=_format_calc_operator,
        )
        if operator == "power":
            params, base_label, exponent_label = _collect_power_params(st, columns)
            power_preview = (base_label, exponent_label)
        else:
            params = {
                "source_column": st.selectbox("Source column", columns, key=PREP_CALC_SCALAR_SRC),
                "operator": operator,
                "scalar": st.number_input(
                    "Scalar / decimals", value=0.0, key=PREP_CALC_SCALAR_VALUE
                ),
            }
    elif operation == OP_CALC_CONDITIONAL:
        params = {
            "source_column": st.selectbox("Source column", columns, key=PREP_CALC_COND_SRC),
            "comparator": st.selectbox(
                "Comparator", ["==", "!=", ">", ">=", "<", "<="], key=PREP_CALC_COND_CMP
            ),
            "compare_value": st.text_input("Compare value", key=PREP_CALC_COND_VALUE),
            "result_value": st.text_input("Value when true", key=PREP_CALC_COND_THEN),
            "fallback_value": st.text_input("Value when false", key=PREP_CALC_COND_ELSE),
        }
    elif operation == OP_CALC_BINNING:
        params = {
            "source_column": st.selectbox("Source column", columns, key=PREP_CALC_BIN_SRC),
            "num_bins": int(
                st.number_input(
                    "Number of bins",
                    min_value=MIN_BINS,
                    max_value=MAX_BINS,
                    value=4,
                    step=1,
                    key=PREP_CALC_BIN_COUNT,
                )
            ),
        }
    else:  # OP_CALC_STRING
        string_op = st.selectbox(
            "String operation",
            ["upper", "lower", "strip", "length", "replace", "concat"],
            key=PREP_CALC_STR_OP,
        )
        params = {
            "source_column": st.selectbox("Source column", columns, key=PREP_CALC_STR_SRC),
            "operation": string_op,
        }
        if string_op == "replace":
            params["find"] = st.text_input("Find (literal)", key=PREP_CALC_STR_FIND)
            params["replace"] = st.text_input("Replace with", key=PREP_CALC_STR_REPLACE)
        elif string_op == "concat":
            params["other_column"] = st.selectbox(
                "Append column (optional)", ["(none)", *columns], key=PREP_CALC_STR_OTHER
            )
            params["literal"] = st.text_input(
                "Append literal (optional)", key=PREP_CALC_STR_LITERAL
            )
    params.update(_collect_output_target(st, df))
    if power_preview is not None:
        preview = _power_expression_preview(
            _output_preview_name(params, _power_default_output_name(params)),
            power_preview[0],
            power_preview[1],
        )
        st.caption(f"Calculation preview: {preview}")
        st.caption(_POWER_HELP)
    return params


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
    if operation in CALC_OPERATIONS:
        return _collect_calc_params(st, operation, df)
    return {}


def _render_step_editor(
    st: Any, state: MutableMapping[str, Any], steps: list[dict[str, Any]]
) -> None:
    """Render remove / move-up / move-down controls for the current recipe."""
    render_section_header(st, "Edit recipe", "Remove or reorder steps before applying.")
    index = int(
        st.selectbox(
            "Step to edit",
            list(range(len(steps))),
            format_func=lambda i: f"{i + 1}. {steps[i]['operation']}",
            key=PREP_EDIT_STEP_SELECT,
        )
        or 0
    )
    remove_col, up_col, down_col = st.columns(3)
    with remove_col:
        if st.button("Remove step", key=PREP_REMOVE_STEP_BTN):
            _remove_step(state, index)
    with up_col:
        if st.button("Move up", key=PREP_MOVE_UP_BTN):
            _move_step(state, index, -1)
    with down_col:
        if st.button("Move down", key=PREP_MOVE_DOWN_BTN):
            _move_step(state, index, 1)


def _render_build_recipe(st: Any, df: pd.DataFrame, state: MutableMapping[str, Any]) -> None:
    render_section_header(
        st,
        "2 · Build your recipe",
        "A recipe is a plan of bounded, deterministic steps — it only runs in-memory on a "
        "copy of the dataset, in stage 3.",
    )
    label = st.selectbox("Operation", list(_OPERATIONS), key=PREP_OPERATION)
    operation = _OPERATIONS.get(label or "", "")
    if operation in CALC_OPERATIONS:
        # Calculated columns read their inputs from the parameter widgets below,
        # so the generic target-columns multiselect is not shown for them.
        columns: list[str] = []
    else:
        columns = st.multiselect("Target columns", list(df.columns), key=PREP_COLUMNS) or []
    params = _collect_params(st, operation, df)
    recipe_operation = _calculation_recipe_operation(operation, params)
    if st.button("Add step to recipe", key=PREP_ADD_STEP_BTN):
        _append_step(state, recipe_operation, list(columns), params)
    steps = _current_steps(state)
    if steps:
        st.caption("Planned steps (not yet applied):")
        st.dataframe(_recipe_table(steps), hide_index=True)
        _render_step_editor(st, state, steps)
        if st.button("Clear recipe", key=PREP_CLEAR_RECIPE_BTN):
            state[PREP_RECIPE_STEPS] = []
    else:
        st.caption(
            "No steps yet — pick an operation above and click 'Add step to recipe' to start."
        )


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
        "3 · Preview & validate (before/after)",
        "Transforms run in-memory on a copy of the dataset — the original is untouched.",
    )
    if not steps:
        st.info("Add at least one step in stage 2 to preview the transformed dataset.")
        return None
    transformed, executed = apply_recipe(df, steps)
    st.caption("Executed steps with status and warnings:")
    st.dataframe(_recipe_table(executed), hide_index=True)
    summary = summarize_before_after(df, transformed)
    _render_summary_cards(st, summary)
    _render_dtype_changes(st, summary)
    render_section_header(
        st, "Transformed preview", f"First {PREVIEW_ROWS} rows of the preview copy."
    )
    st.dataframe(preview_frame(transformed), hide_index=True)
    return transformed


def _render_export(
    st: Any,
    df: pd.DataFrame,
    steps: list[dict[str, Any]],
    state: Mapping[str, Any],
    context: DatasetContext | None,
) -> None:
    render_section_header(
        st,
        "5 · Save or export the recipe",
        "The recipe is a reusable artifact (separate from the dataset in stage 4). "
        "Download it as JSON to replay later. In-memory only — no files are written here.",
    )
    if not steps:
        st.info("Build a recipe in stage 2 to enable export.")
        return
    transformed, executed = apply_recipe(df, steps)
    summary = summarize_before_after(df, transformed)
    payload = recipe_to_json_payload(executed, summary)
    steps_table = _recipe_table(executed)
    json_download_button(st, "Download recipe (JSON)", payload, "preprocess_recipe.json")
    csv_download_button(
        st, "Download recipe steps (CSV)", steps_table, "preprocess_recipe_steps.csv"
    )
    _render_recipe_workspace_save(st, state, context, payload, steps_table)


def _render_transformed_output(
    st: Any,
    transformed: pd.DataFrame | None,
    state: Mapping[str, Any],
    context: DatasetContext | None,
) -> None:
    """Offer the transformed dataset as a browser CSV download and opt-in workspace save.

    Rendered only when a transformed frame exists (i.e. the recipe produced one). Serves the
    ``apply_recipe`` output — never the original input. In-memory only: the source file is
    never overwritten, and nothing is written server-side on render.
    """
    if transformed is None:
        return
    render_section_header(
        st,
        "4 · Get your transformed dataset",
        "Download the cleaned dataset as CSV, or save it under your Workspace Root / "
        "preprocessed. In-memory only — the original file is never overwritten; existing "
        "files are not overwritten.",
    )
    csv_download_button(st, "Download transformed data (CSV)", transformed, _TRANSFORMED_CSV_NAME)
    workspace_root = _workspace_root_value(state)
    dataset_name = context.display_name if context is not None else None
    if st.button("Save transformed data to workspace", key=_SAVE_TRANSFORMED_BTN):
        _save_transformed_output(st, workspace_root, dataset_name, transformed)


def _save_transformed_output(
    st: Any,
    workspace_root: str,
    dataset_name: str | None,
    transformed: pd.DataFrame,
) -> None:
    """Build a safe filename and save the transformed CSV under Workspace Root / preprocessed."""
    if not workspace_root.strip():
        st.info(WORKSPACE_ROOT_EMPTY_STATE)
        return
    filename = build_workspace_filename(
        artifact="preprocessed_dataset", extension="csv", dataset=dataset_name
    )
    result = save_to_workspace(
        workspace_root, _TRANSFORMED_SUBFOLDER, filename, transformed.to_csv(index=False)
    )
    _render_save_result(st, result)


def _render_recipe_workspace_save(
    st: Any,
    state: Mapping[str, Any],
    context: DatasetContext | None,
    payload: Any,
    steps_table: pd.DataFrame,
) -> None:
    """Offer opt-in Save-to-Workspace for the recipe outputs (additive; downloads stay)."""
    render_section_header(
        st,
        "Save to Workspace",
        "Optionally save these recipe outputs under your Workspace Root / recipes. "
        "Existing files are not overwritten.",
    )
    workspace_root = _workspace_root_value(state)
    dataset_name = context.display_name if context is not None else None
    # Save the exact same content served by the browser downloads above.
    if st.button("Save recipe JSON to workspace", key=_SAVE_RECIPE_JSON_BTN):
        _save_recipe_output(
            st,
            workspace_root,
            dataset_name,
            "preprocess_recipe",
            "json",
            json.dumps(payload, indent=2, default=str),
        )
    if st.button("Save recipe steps CSV to workspace", key=_SAVE_RECIPE_STEPS_BTN):
        _save_recipe_output(
            st,
            workspace_root,
            dataset_name,
            "preprocess_recipe_steps",
            "csv",
            steps_table.to_csv(index=False),
        )


def _save_recipe_output(
    st: Any,
    workspace_root: str,
    dataset_name: str | None,
    artifact: str,
    extension: str,
    data: str,
) -> None:
    """Build a safe filename and save one recipe output under Workspace Root / recipes."""
    if not workspace_root.strip():
        st.info(WORKSPACE_ROOT_EMPTY_STATE)
        return
    filename = build_workspace_filename(
        artifact=artifact, extension=extension, dataset=dataset_name
    )
    result = save_to_workspace(workspace_root, _RECIPES_SUBFOLDER, filename, data)
    _render_save_result(st, result)


def _render_save_result(st: Any, result: WorkspaceSaveResult) -> None:
    """Render the save outcome using basename / workspace-relative fields only."""
    if result.status == "saved":
        st.success(f"Saved to workspace: {result.relative_path}")
    elif result.status == "invalid":
        st.info(result.message)
    else:
        st.error(result.message or "Could not save recipe output.")


# ── stage 6: explicit lifecycle confirmation ─────────────────────────────────


def _render_confirm_version(
    st: Any,
    df: pd.DataFrame,
    steps: list[dict[str, Any]],
    state: MutableMapping[str, Any],
    context: DatasetContext | None,
) -> None:
    """Offer explicit confirmation of the transformed output as a dataset version.

    Confirmation is never implied by a download or an unmanaged workspace save: it
    writes an immutable CSV, its recipe, and a lifecycle sidecar (written last).
    Making the confirmed version active stays a separate action.
    """
    render_section_header(
        st,
        "6 · Confirm a processed version",
        "Register the transformed dataset as an immutable version with its recipe and "
        "lineage. Downloading or saving the CSV above does not confirm a version, and "
        "confirming does not change your active dataset.",
    )
    if context is None:
        st.info("Select a dataset on Start to confirm a processed version.")
        return
    if not steps:
        st.info("Build and preview a recipe first — there is nothing to confirm yet.")
        return

    label_value = st.text_input("Version label (e.g. cleaned v2)", key=_VERSION_LABEL)
    label = str(label_value or state.get(_VERSION_LABEL) or "").strip()
    if st.button("Confirm processed version", key=_CONFIRM_VERSION_BTN, type="primary"):
        _run_confirmation(st, state, context, df, steps, label)
    _render_confirmed_version(st, state)


def _run_confirmation(
    st: Any,
    state: MutableMapping[str, Any],
    context: DatasetContext,
    df: pd.DataFrame,
    steps: list[dict[str, Any]],
    label: str,
) -> None:
    """Validate the preview locally, then delegate to the confirmation service."""
    transformed, executed = apply_recipe(df, steps)
    if not executed:
        st.error("Add at least one recipe step before confirming a version.")
        return
    # One shared predicate decides replay success for both confirmation paths, so
    # this feedback can never drift from what the services enforce.
    if replay_refusal_code(steps, executed):
        st.error("Fix the failing recipe step before confirming a version.")
        return

    summary = summarize_before_after(df, transformed)
    result = confirm_processed_version(
        workspace_root=_workspace_root_value(state),
        csv_bytes=transformed.to_csv(index=False).encode("utf-8"),
        recipe=recipe_to_json_payload(executed, summary),
        parent=context,
        label=label,
        filename_stem=context.display_name,
        # Root-first: a valid managed trust root outranks the passed context, and
        # a managed-looking context without valid trust fails closed.
        session_state=state,
    )
    _handle_confirmation_result(st, state, result)


def _handle_confirmation_result(
    st: Any,
    state: MutableMapping[str, Any],
    result: Any,
) -> None:
    """Render the outcome and store a handoff only for a fully confirmed version."""
    if result.status is ConfirmationStatus.CONFIRMED and result.record is not None:
        state[PREP_CONFIRMED_VERSION] = ConfirmedVersionHandoff(
            record=result.record,
            csv_path=result.csv_path,
            csv_relative_path=result.csv_relative_path,
        )
        st.success(result.message)
        st.caption(f"Dataset: {result.csv_relative_path}")
        st.caption(f"Recipe: {result.recipe_relative_path}")
        st.caption(f"Sidecar: {result.sidecar_relative_path}")
        return

    # Nothing below is a confirmed version, so no handoff may survive to offer
    # activation — including a handoff left by an earlier successful confirmation.
    state.pop(PREP_CONFIRMED_VERSION, None)
    if result.status is ConfirmationStatus.SAVED_UNMANAGED:
        st.warning(result.message)
        return
    if result.capability_unsupported:
        # A limit of the location, not a mistake the operator made: label it so
        # the fix (confirm somewhere that supports hard links) is obvious, and
        # keep the guidance the service composed exactly as written.
        show_error(st, "Confirmation not supported here", result.message)
        return
    show_error(st, "Confirmation error", result.message)


def _render_confirmed_version(st: Any, state: MutableMapping[str, Any]) -> None:
    """Show the confirmed identity and offer the separate Set-active action."""
    handoff = state.get(PREP_CONFIRMED_VERSION)
    if not isinstance(handoff, ConfirmedVersionHandoff):
        return
    st.caption(
        f"Confirmed version: {handoff.label} ({handoff.short_version_id}) — "
        f"{handoff.csv_relative_path}. Confirmed is not active."
    )
    if st.button("Set active", key=_SET_ACTIVE_BTN):
        _activate_confirmed_version(st, state, handoff)


def _activate_confirmed_version(
    st: Any,
    state: MutableMapping[str, Any],
    handoff: ConfirmedVersionHandoff,
) -> None:
    """Activate the newly confirmed version through the shared transition service.

    Transition and invalidation logic is owned by ``dataset_activation``; a failure
    there leaves the previously active dataset and its state untouched.
    """
    csv_path = Path(handoff.csv_path)
    try:
        stat = csv_path.stat()
    except OSError:
        st.error("The confirmed dataset file is unreadable. The active dataset is unchanged.")
        return
    try:
        context = make_managed_context(
            handoff.record,
            source_path=str(csv_path),
            display_name=csv_path.name,
            size_bytes=int(stat.st_size),
            modified_ns=int(stat.st_mtime_ns),
        )
        activate_dataset_context(state, context)
    except DatasetActivationError:
        st.error("Could not set this version active. The active dataset is unchanged.")
        return
    st.success(f"Active dataset is now {handoff.label}.")
    st.rerun()


# ── stage 7: trusted reload & reprocessing (managed FULL) ────────────────────


def _reload_action_reference(root: ManagedTrustRoot) -> str:
    """Return the privacy-safe action reference for the active managed version."""
    return derive_action_reference(version_id=root.version_id)


def _reload_draft_steps(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the current detached draft steps (empty when no draft is loaded)."""
    steps = state.get(_RELOAD_DRAFT_STATE)
    return list(steps) if isinstance(steps, list) else []


def _load_recipe_into_state(
    state: MutableMapping[str, Any], root: ManagedTrustRoot
) -> LoadedRecipe:
    """Load and revalidate the active version's confirmed recipe into a draft.

    On success stores the immutable loaded recipe and a deeply detached editable
    draft in session state; on any typed failure clears both so a stale draft can
    never survive a failed reload. Never activates and never mutates the durable
    recipe.
    """
    workspace_root = _workspace_root_value(state)
    loaded = load_confirmed_recipe(
        session_state=state,
        workspace_root=workspace_root,
        action_reference=_reload_action_reference(root),
    )
    if not loaded.loaded:
        state.pop(_RELOAD_LOADED_STATE, None)
        state.pop(_RELOAD_DRAFT_STATE, None)
        return loaded
    draft = create_recipe_draft(
        session_state=state, workspace_root=workspace_root, loaded_recipe=loaded
    )
    if not draft.drafted:
        state.pop(_RELOAD_LOADED_STATE, None)
        state.pop(_RELOAD_DRAFT_STATE, None)
        return loaded
    state[_RELOAD_LOADED_STATE] = loaded
    state[_RELOAD_DRAFT_STATE] = draft.steps
    return loaded


def _reload_remove_step(state: MutableMapping[str, Any], index: int) -> None:
    """Remove one step from the detached draft (no-op when out of range)."""
    steps = _reload_draft_steps(state)
    if 0 <= index < len(steps):
        steps.pop(index)
        state[_RELOAD_DRAFT_STATE] = steps


def _confirm_reload_child(
    state: MutableMapping[str, Any], df: pd.DataFrame, label: str
) -> ReprocessedChild | None:
    """Execute the detached draft on ``df`` and confirm one immutable child.

    The draft is executed only through the existing ``apply_recipe`` service, and
    the replay evidence it returns is handed to the trusted reprocessing service
    together with the draft. That service, not this page, verifies the replay and
    re-admits every step before any durable write, so a partially failed replay
    is refused here and by any other caller alike. Returns ``None`` when no
    confirmed recipe is loaded.
    """
    loaded = state.get(_RELOAD_LOADED_STATE)
    if not isinstance(loaded, LoadedRecipe) or loaded.record is None:
        return None
    steps = _reload_draft_steps(state)
    transformed, executed = apply_recipe(df, steps)
    return confirm_reprocessed_child(
        session_state=state,
        workspace_root=_workspace_root_value(state),
        parent_record=loaded.record,
        steps=steps,
        executed_steps=executed,
        csv_bytes=transformed.to_csv(index=False).encode("utf-8"),
        label=label,
    )


def _reload_steps_table(steps: list[dict[str, Any]]) -> pd.DataFrame:
    """Render the original steps by operation and columns only — never parameters."""
    return pd.DataFrame(
        [
            {
                "step": index + 1,
                "operation": str(step.get("operation", "")),
                "columns": ", ".join(str(c) for c in (step.get("columns") or [])) or "—",
                "parameters": _RELOAD_PARAMS_HIDDEN,
            }
            for index, step in enumerate(steps)
        ]
    )


def _render_reload_draft_editor(
    st: Any, state: MutableMapping[str, Any], steps: list[dict[str, Any]]
) -> None:
    index = int(
        st.selectbox(
            "Draft step to drop",
            list(range(len(steps))),
            format_func=lambda i: f"{i + 1}. {steps[i].get('operation', '')}",
            key=_RELOAD_STEP_SELECT,
        )
        or 0
    )
    if st.button("Remove draft step", key=_RELOAD_REMOVE_STEP_BTN):
        _reload_remove_step(state, index)


def _render_reload_confirm(st: Any, state: MutableMapping[str, Any], df: pd.DataFrame) -> None:
    label_value = st.text_input("Child version label", key=_RELOAD_CHILD_LABEL)
    label = str(label_value or state.get(_RELOAD_CHILD_LABEL) or "").strip()
    if not st.button("Confirm reprocessed child", key=_RELOAD_CONFIRM_CHILD_BTN, type="primary"):
        return
    child = _confirm_reload_child(state, df, label)
    if child is None:
        st.info("Load the confirmed recipe above before confirming a child.")
        return
    if child.confirmed and child.record is not None:
        st.success(child.message)
        st.caption(f"Child dataset: {child.csv_relative_path}")
        st.caption(_RELOAD_NOT_ACTIVE_NOTE)
    else:
        show_error(st, "Reprocessing error", child.message)


def _render_recipe_reload(
    st: Any, state: MutableMapping[str, Any], root: ManagedTrustRoot, df: pd.DataFrame
) -> None:
    """Trusted reload of the active managed version's confirmed recipe.

    Loads the immutable original recipe, shows it by operation/columns only,
    exposes a detached editable draft the operator runs through the existing
    preprocessing services, and confirms the result as one new child version that
    is deliberately not made active.
    """
    render_section_header(
        st,
        "7 · Reprocess the confirmed recipe",
        "Reload this managed version's confirmed recipe, edit a detached draft, and "
        "confirm a new child version. The child is not made active automatically.",
    )
    if st.button("Load confirmed recipe", key=_RELOAD_RECIPE_BTN):
        loaded = _load_recipe_into_state(state, root)
        if not loaded.loaded:
            show_error(st, "Recipe reload error", loaded.message)
    steps = _reload_draft_steps(state)
    if not isinstance(state.get(_RELOAD_LOADED_STATE), LoadedRecipe):
        st.info("Load the confirmed recipe to start a detached, editable draft.")
        return
    st.caption("Original recipe (operation and columns only — parameter values are hidden):")
    st.dataframe(_reload_steps_table(steps), hide_index=True)
    if steps:
        _render_reload_draft_editor(st, state, steps)
    else:
        st.caption("The draft is empty. Loading again restores the original steps.")
    _render_reload_confirm(st, state, df)


# ── page body ────────────────────────────────────────────────────────────────


def _render_preprocess_body(
    st: Any,
    df: pd.DataFrame,
    state: MutableMapping[str, Any],
    context: DatasetContext | None,
) -> None:
    """Render recommendations, recipe building, preview, export, and confirmation.

    Shared verbatim by the legacy path-based flow and the managed root-first
    flow so the preprocessing surface is identical for both.
    """
    if is_large_frame(df):
        render_warning_state(
            st,
            f"Large dataset ({len(df):,} rows). The preview shows the first {PREVIEW_ROWS} rows; "
            "transforms still run in-memory on the full copy.",
        )

    _render_recommendations(st, df)
    _render_build_recipe(st, df, state)
    steps = _current_steps(state)
    transformed = _render_apply_and_validation(st, df, steps)
    _render_transformed_output(st, transformed, state, context)
    _render_export(st, df, steps, state, context)
    _render_confirm_version(st, df, steps, state, context)


def _render_managed_preprocess_studio(
    st: Any, state: MutableMapping[str, Any], root: ManagedTrustRoot
) -> None:
    """Render Preprocess Studio for a trusted managed version (root-first).

    Managed LARGE refuses DataFrame materialization outright; managed FULL
    dispatches through the managed frame loader. The downstream context is
    derived from the trust root, so confirmation lineage and displayed identity
    both descend from verified managed provenance rather than a stale mirror.
    """
    if root.large_file_mode:
        render_warning_state(st, _MANAGED_LARGE_PREPROCESS_MESSAGE)
        return
    try:
        df = get_managed_frame(state)
    except ManagedFrameLoadError as exc:
        show_error(st, "Managed Dataset Error", str(exc))
        return
    _render_preprocess_body(st, df, state, resolve_confirmation_parent(state, None))
    _render_recipe_reload(st, state, root, df)


def _render_preprocess_studio(
    st: Any, session_state: MutableMapping[str, Any] | None = None
) -> None:
    """Render the Preprocess Studio page body."""
    state: MutableMapping[str, Any] = session_state if session_state is not None else {}
    render_page_header(
        st,
        "Preprocess Studio",
        "Build a reversible cleaning recipe, preview it in-memory, and export it to replay.",
        step_label=journey.step_label("preprocess_studio"),
    )
    render_page_guidance(
        st,
        purpose="Build a safe, reversible preprocessing recipe and preview it in-memory.",
        inputs="The shared dataset and the operations/calculations you choose.",
        workflow="1 Review recommendations, 2 build your recipe, 3 preview & validate "
        "before/after, 4 get the transformed dataset, 5 save or export the recipe.",
        outputs="Transformed dataset CSV, transformed preview, recipe JSON, and recipe-steps CSV.",
        safety="Transforms run on an in-memory copy — the original file is never overwritten; "
        "calculations use no eval/exec.",
        next_step="Export or Pipeline Runner",
    )
    render_status_chip(st, _SAFETY_BANNER, tone="warn")
    st.caption(_FLOW_MAP)

    context = get_dataset_context(state)
    decision = resolve_trust_authority(state)

    # The shared identity callout always renders exactly once (accepted discovery/history
    # contract). Trust governs data dispatch and provenance below it, never the
    # identity surface itself.
    if decision.managed and decision.root is not None:
        # Root-first: valid managed trust governs even over a stale mirror or
        # a manually entered path.
        render_dataset_source_callout(st, context, session_state=state)
        _render_managed_preprocess_studio(st, state, decision.root)
        return
    render_dataset_source_callout(st, context)
    if decision.authority is TrustAuthority.FAIL_CLOSED:
        show_error(st, "Managed Dataset Error", _MANAGED_FAIL_CLOSED_MESSAGE)
        return

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
        st.caption("Advanced/manual CSV path override.")
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

    _render_preprocess_body(st, df, state, context)


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_preprocess_studio(st, st.session_state)  # type: ignore[arg-type, unused-ignore]
