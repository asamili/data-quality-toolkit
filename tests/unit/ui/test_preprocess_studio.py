"""Tests for the Preprocess Studio page (render + recipe-state helpers)."""

from __future__ import annotations

import inspect
import math
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.pages import preprocess_studio
from data_quality_toolkit.adapters.ui.pages.preprocess_studio import (
    _CONFIRM_VERSION_BTN,
    _MANAGED_FAIL_CLOSED_MESSAGE,
    _POWER_CONSTANT_CHOICES,
    _POWER_CONSTANT_CUSTOM,
    _POWER_CONSTANT_E,
    _POWER_CONSTANT_PI,
    _POWER_CONSTANT_SQRT2,
    _POWER_MODE_COLUMN_COLUMN,
    _POWER_MODE_COLUMN_CONSTANT,
    _POWER_MODE_CONSTANT_COLUMN,
    _POWER_MODES,
    _RELOAD_CONFIRM_CHILD_BTN,
    _RELOAD_DRAFT_STATE,
    _RELOAD_LOADED_STATE,
    _RELOAD_PARAMS_HIDDEN,
    _SAVE_TRANSFORMED_BTN,
    _SET_ACTIVE_BTN,
    _VERSION_LABEL,
    _append_step,
    _calculation_recipe_operation,
    _collect_calc_params,
    _confirm_reload_child,
    _current_steps,
    _load_recipe_into_state,
    _power_expression_preview,
    _reload_action_reference,
    _reload_draft_steps,
    _reload_remove_step,
    _render_confirm_version,
    _render_confirmed_version,
    _render_preprocess_studio,
    _render_recipe_reload,
    _render_transformed_output,
    _resolve_power_constant,
)
from data_quality_toolkit.adapters.ui.services import managed_frame_loader as _mfl
from data_quality_toolkit.adapters.ui.services.dataset_activation import DatasetActivationError
from data_quality_toolkit.adapters.ui.services.dataset_confirmation import (
    ConfirmationStatus,
    ConfirmedVersionHandoff,
    DatasetConfirmationResult,
    confirm_processed_version,
)
from data_quality_toolkit.adapters.ui.services.managed_recipe_reprocessing import (
    LoadedRecipe,
    derive_action_reference,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    ManagedTrustRoot,
    commit_trust_root,
    ensure_session_capability,
    make_source_locator,
    resolve_trust_authority,
)
from data_quality_toolkit.adapters.ui.services.preprocessing_calculations import (
    OP_CALC_ARITHMETIC,
    OP_CALC_SCALAR,
)
from data_quality_toolkit.adapters.ui.state.context import (
    DatasetContext,
    get_dataset_context,
    set_dataset_context,
)
from data_quality_toolkit.adapters.ui.state.keys import (
    DATASET_CONTEXT,
    DATASET_DERIVED_STATE_KEYS,
    PREP_CALC_ARITH_OP,
    PREP_CALC_SCALAR_OP,
    PREP_CONFIRMED_VERSION,
    PREP_RECIPE_STEPS,
    SRC_WORKSPACE_ROOT,
)
from data_quality_toolkit.application.workflow.preprocessing import (
    STATUS_ERROR,
    make_recipe_step,
    recipe_to_json_payload,
)

_PATCH_LOAD = "data_quality_toolkit.adapters.ui.pages.preprocess_studio._load_df_and_assess"

_DF = pd.DataFrame({"n": [1.0, 2.0, 2.0, 3.0], "c": ["a", "a", "a", "b"]})
_RESULT: dict[str, Any] = {"profile": {"rows": 4, "cols": 2}, "assessment": {"score": 1.0}}


class FakeSt:
    """Minimal Streamlit recorder supporting columns/selectbox/multiselect/button."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.text_values: dict[str, str] = {}
        self.select_values: dict[str, Any] = {}
        self.number_values: dict[str, Any] = {}

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def _rec(self, name: str, *a: Any, **k: Any) -> None:
        self.calls.append((name, a, k))

    def __getattr__(self, name: str) -> Any:
        def recorder(*a: Any, **k: Any) -> None:
            self._rec(name, *a, **k)

        return recorder

    def columns(self, n: int) -> list[FakeSt]:
        self._rec("columns", n)
        return [FakeSt() for _ in range(n)]

    def text_input(self, label: str, **k: Any) -> str:
        self._rec("text_input", label, **k)
        return self.text_values.get(label, str(k.get("value", "")))

    def selectbox(self, label: str, options: Any = (), **k: Any) -> Any:
        self._rec("selectbox", label, options, **k)
        return self.select_values.get(label, options[0] if options else None)

    def number_input(self, label: str, **k: Any) -> Any:
        self._rec("number_input", label, **k)
        return self.number_values.get(label, k.get("value", 0))

    def multiselect(self, label: str, options: Any = (), **k: Any) -> list[Any]:
        self._rec("multiselect", label, options, **k)
        return []

    def button(self, label: str, **k: Any) -> bool:
        self._rec("button", label, **k)
        return False

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))


# ── recipe-state helpers ─────────────────────────────────────────────────────


def test_append_step_grows_recipe() -> None:
    state: dict[str, Any] = {}
    _append_step(state, "scaling", ["n"], {"strategy": "minmax"})
    _append_step(state, "drop_duplicates", [], {})
    assert len(_current_steps(state)) == 2


def test_append_step_ignores_empty_operation() -> None:
    state: dict[str, Any] = {}
    _append_step(state, "", ["n"], {})
    assert _current_steps(state) == []


def test_current_steps_ignores_malformed_state() -> None:
    assert _current_steps({PREP_RECIPE_STEPS: "not-a-list"}) == []


# ── page render ──────────────────────────────────────────────────────────────


def test_render_empty_path_shows_info() -> None:
    st = FakeSt()
    _render_preprocess_studio(st, {})
    assert st.called("header")
    assert st.called("info")
    assert not st.called("dataframe")


def test_render_load_error_shows_error() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "bad.csv"
    with patch(_PATCH_LOAD, return_value=(None, None, "file not found")):
        _render_preprocess_studio(st, {})
    assert st.called("error")
    assert not st.called("metric")


def test_render_large_file_context_blocks_without_loading() -> None:
    st = FakeSt()
    context = DatasetContext(
        source_path="C:/safe/data.csv",
        display_name="data.csv",
        size_bytes=10,
        modified_ns=1,
        large_file_mode=True,
    )
    with patch(_PATCH_LOAD) as load:
        _render_preprocess_studio(st, {DATASET_CONTEXT: context})
    load.assert_not_called()
    assert st.called("warning")


def test_render_shows_recommendations_without_steps() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_preprocess_studio(st, {})
    assert st.called("dataframe")  # recommendations table
    text = st.texts()
    assert "1 · Review recommendations" in text
    assert "2 · Build your recipe" in text
    assert "5 · Save or export the recipe" in text


def test_render_with_seeded_recipe_shows_before_after_and_export() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    state: dict[str, Any] = {PREP_RECIPE_STEPS: [make_recipe_step("drop_duplicates", [], {})]}
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_preprocess_studio(st, state)
    assert st.called("metric")  # before/after summary cards
    assert st.called("download_button")  # recipe export
    text = st.texts()
    assert "3 · Preview & validate (before/after)" in text
    assert "Transformed preview" in text


def test_render_does_not_draw_charts() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    state: dict[str, Any] = {
        PREP_RECIPE_STEPS: [make_recipe_step("scaling", ["n"], {"strategy": "minmax"})]
    }
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_preprocess_studio(st, state)
    assert not st.called("bar_chart")
    assert not st.called("scatter_chart")
    assert not st.called("line_chart")


# ── operator-flow structure (numbered stages + guidance) ─────────────────────


def test_render_shows_flow_map_caption() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_preprocess_studio(st, {})
    text = st.texts()
    assert "Flow: 1 Review recommendations" in text
    assert "5 Save or export the recipe" in text


def test_render_seeded_recipe_shows_numbered_stages_in_order() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    state: dict[str, Any] = {PREP_RECIPE_STEPS: [make_recipe_step("drop_duplicates", [], {})]}
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_preprocess_studio(st, state)
    text = st.texts()
    stages = [
        "1 · Review recommendations",
        "2 · Build your recipe",
        "3 · Preview & validate (before/after)",
        "4 · Get your transformed dataset",
        "5 · Save or export the recipe",
    ]
    positions = [text.index(stage) for stage in stages]
    assert positions == sorted(positions)


def test_render_seeded_recipe_states_original_never_overwritten() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    state: dict[str, Any] = {PREP_RECIPE_STEPS: [make_recipe_step("drop_duplicates", [], {})]}
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_preprocess_studio(st, state)
    assert "never overwritten" in st.texts()


def test_render_without_steps_shows_actionable_empty_state() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_preprocess_studio(st, {})
    text = st.texts()
    assert "No steps yet — pick an operation above" in text
    assert "Add at least one step in stage 2" in text


# ── transformed-dataset output ────────────────────────────────────────────────


def _download_call(st: FakeSt, file_name: str) -> dict[str, Any] | None:
    """Return the kwargs of the download_button call serving *file_name*, if any."""
    for name, _a, k in st.calls:
        if name == "download_button" and k.get("file_name") == file_name:
            return k
    return None


def test_render_seeded_recipe_offers_transformed_data_download() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    state: dict[str, Any] = {PREP_RECIPE_STEPS: [make_recipe_step("drop_duplicates", [], {})]}
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_preprocess_studio(st, state)
    assert "Save transformed data to workspace" in st.texts()
    call = _download_call(st, "preprocessed_dataset.csv")
    assert call is not None
    # The served payload is the transformed frame (drop_duplicates on _DF → 3 rows),
    # not the 4-row original input: header + 3 data rows == 4 CSV lines.
    lines = str(call["data"]).strip().splitlines()
    assert len(lines) == 4


def test_render_without_steps_hides_transformed_output() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_preprocess_studio(st, {})
    assert "Save transformed data to workspace" not in st.texts()
    assert _download_call(st, "preprocessed_dataset.csv") is None


# ── calculated-column operator controls ──────────────────────────────────────


def _selectbox_call(st: FakeSt, key: str) -> tuple[Any, dict[str, Any]]:
    for name, args, kwargs in st.calls:
        if name == "selectbox" and kwargs.get("key") == key:
            return args, kwargs
    raise AssertionError(f"selectbox with key {key!r} was not rendered")


def test_arithmetic_operator_selector_includes_power_with_clear_label() -> None:
    st = FakeSt()

    _collect_calc_params(st, OP_CALC_ARITHMETIC, _DF)

    args, kwargs = _selectbox_call(st, PREP_CALC_ARITH_OP)
    options = list(args[1])
    assert "power" in options
    assert kwargs["format_func"]("power") == "Power / Exponentiation (x^y)"


def test_scalar_operator_selector_includes_power_with_clear_label() -> None:
    st = FakeSt()

    _collect_calc_params(st, OP_CALC_SCALAR, _DF)

    args, kwargs = _selectbox_call(st, PREP_CALC_SCALAR_OP)
    options = list(args[1])
    assert "power" in options
    assert kwargs["format_func"]("power") == "Power / Exponentiation (x^y)"


def test_power_help_identifies_base_exponent_and_null_behavior() -> None:
    st = FakeSt()
    st.select_values["Operator"] = "power"

    params = _collect_calc_params(st, OP_CALC_SCALAR, _DF)

    text = st.texts()
    assert params["operator"] == "power"
    assert "Power / Exponentiation" in text
    assert "left operand is the base" in text
    assert "right operand is the exponent" in text
    assert "non-finite results become null" in text


def test_power_exposes_exactly_three_operand_modes() -> None:
    assert _POWER_MODES == (
        "Column raised to constant",
        "Column raised to column",
        "Constant raised to column",
    )


def test_power_mode_labels_distinguish_base_and_exponent_fields() -> None:
    st = FakeSt()
    st.select_values["Operator"] = "power"
    st.select_values["Power mode"] = _POWER_MODE_CONSTANT_COLUMN

    params = _collect_calc_params(st, OP_CALC_SCALAR, _DF)

    labels = {str(args[0]) for name, args, _kwargs in st.calls if args and name == "selectbox"}
    labels.update(
        str(args[0]) for name, args, _kwargs in st.calls if args and name == "number_input"
    )
    assert params["constant_role"] == "base"
    assert "Base constant" in labels
    assert "Exponent column" in labels


def test_power_constant_selector_contains_only_safe_choices() -> None:
    assert _POWER_CONSTANT_CHOICES == (
        "Custom number",
        "π — Pi",
        "e — Euler’s number",
        "√2 — Square root of two",
    )


def test_power_named_constants_resolve_to_trusted_values() -> None:
    assert math.isclose(_resolve_power_constant(_POWER_CONSTANT_PI), math.pi)
    assert math.isclose(_resolve_power_constant(_POWER_CONSTANT_E), math.e)
    assert math.isclose(_resolve_power_constant(_POWER_CONSTANT_SQRT2), math.sqrt(2.0))


def test_power_custom_number_uses_numeric_control() -> None:
    st = FakeSt()
    st.select_values["Operator"] = "power"
    st.select_values["Constant"] = _POWER_CONSTANT_CUSTOM
    st.number_values["Exponent constant"] = 2.5

    params = _collect_calc_params(st, OP_CALC_SCALAR, _DF)

    assert params["scalar"] == 2.5
    assert any(
        name == "number_input" and args and args[0] == "Exponent constant"
        for name, args, _kwargs in st.calls
    )
    assert not any(
        name == "text_input" and args and "constant" in str(args[0]).lower()
        for name, args, _kwargs in st.calls
    )


def test_power_constant_raised_to_column_wires_scalar_recipe_base() -> None:
    st = FakeSt()
    st.select_values["Operator"] = "power"
    st.select_values["Power mode"] = _POWER_MODE_CONSTANT_COLUMN
    st.select_values["Constant"] = _POWER_CONSTANT_E
    st.select_values["Exponent column"] = "c"

    params = _collect_calc_params(st, OP_CALC_ARITHMETIC, _DF)

    assert _calculation_recipe_operation(OP_CALC_ARITHMETIC, params) == OP_CALC_SCALAR
    assert params["operator"] == "power"
    assert params["constant_role"] == "base"
    assert math.isclose(params["scalar"], math.e)
    assert params["source_column"] == "c"
    assert "right_column" not in params


def test_power_column_raised_to_constant_wires_scalar_recipe_exponent() -> None:
    st = FakeSt()
    st.select_values["Operator"] = "power"
    st.select_values["Power mode"] = _POWER_MODE_COLUMN_CONSTANT
    st.select_values["Constant"] = _POWER_CONSTANT_PI
    st.select_values["Base column"] = "n"

    params = _collect_calc_params(st, OP_CALC_SCALAR, _DF)

    assert _calculation_recipe_operation(OP_CALC_SCALAR, params) == OP_CALC_SCALAR
    assert params["operator"] == "power"
    assert params["constant_role"] == "exponent"
    assert math.isclose(params["scalar"], math.pi)
    assert params["source_column"] == "n"


def test_power_column_raised_to_column_wires_arithmetic_recipe() -> None:
    st = FakeSt()
    st.select_values["Operator"] = "power"
    st.select_values["Power mode"] = _POWER_MODE_COLUMN_COLUMN
    st.select_values["Base column"] = "n"
    st.select_values["Exponent column"] = "c"

    params = _collect_calc_params(st, OP_CALC_SCALAR, _DF)

    assert _calculation_recipe_operation(OP_CALC_SCALAR, params) == OP_CALC_ARITHMETIC
    assert params == {
        "left_column": "n",
        "operator": "power",
        "right_column": "c",
        "output_mode": "new",
        "output_column": "",
    }


def test_power_expression_preview_represents_all_modes() -> None:
    assert _power_expression_preview("result_column", "pressure", "π") == (
        "result_column = pressure ^ π"
    )
    assert _power_expression_preview("result_column", "base_column", "exponent_column") == (
        "result_column = base_column ^ exponent_column"
    )
    assert _power_expression_preview("result_column", "e", "exponent_column") == (
        "result_column = e ^ exponent_column"
    )


def test_power_preview_is_rendered_before_step_add() -> None:
    st = FakeSt()
    st.select_values["Operator"] = "power"
    st.select_values["Constant"] = _POWER_CONSTANT_E

    _collect_calc_params(st, OP_CALC_SCALAR, _DF)

    assert "Calculation preview: n__power = n ^ e" in st.texts()


def test_no_arbitrary_expression_input_or_symbolic_parser_is_added() -> None:
    st = FakeSt()
    st.select_values["Operator"] = "power"

    _collect_calc_params(st, OP_CALC_SCALAR, _DF)

    text_input_labels = [
        str(args[0]).lower() for name, args, _kwargs in st.calls if name == "text_input" and args
    ]
    assert all("formula" not in label and "expression" not in label for label in text_input_labels)
    source = inspect.getsource(preprocess_studio)
    assert "eval(" not in source
    assert "exec(" not in source
    assert "import ast" not in source


def test_non_power_operator_options_remain_unchanged() -> None:
    st = FakeSt()

    _collect_calc_params(st, OP_CALC_ARITHMETIC, _DF)
    _collect_calc_params(st, OP_CALC_SCALAR, _DF)

    arithmetic_args, _ = _selectbox_call(st, PREP_CALC_ARITH_OP)
    scalar_args, _ = _selectbox_call(st, PREP_CALC_SCALAR_OP)
    assert list(arithmetic_args[1]) == ["add", "subtract", "multiply", "divide", "power"]
    assert list(scalar_args[1]) == ["add", "subtract", "multiply", "divide", "power", "round"]


# ── stage 6: explicit version confirmation + set-active handoff ───────────────

_STEPS = [make_recipe_step("drop_duplicates", [], {})]
_LABEL_INPUT = "Version label (e.g. cleaned v2)"


class ClickSt(FakeSt):
    """FakeSt with per-key button clicks (buttons are opt-in, never auto-fired)."""

    def __init__(self) -> None:
        super().__init__()
        self.clicks: dict[str, bool] = {}

    def button(self, label: str, **k: Any) -> bool:
        self._rec("button", label, **k)
        return bool(self.clicks.get(k.get("key", label), False))


def _buttons(st: FakeSt) -> list[str]:
    return [str(a[0]) for name, a, _k in st.calls if name == "button" and a]


def _ws(tmp_path: Path) -> Path:
    return tmp_path / "ws"


def _file_context(tmp_path: Path) -> DatasetContext:
    """A legacy unmanaged context backed by a real file (parent identity is read)."""
    src = tmp_path / "src" / "customers.csv"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"n,c\n1.0,a\n1.0,a\n2.0,b\n")
    stat = src.stat()
    return DatasetContext(
        source_path=str(src),
        display_name="customers.csv",
        size_bytes=int(stat.st_size),
        modified_ns=int(stat.st_mtime_ns),
    )


def _confirmed_state(tmp_path: Path) -> dict[str, Any]:
    """Run a real confirmation and return the resulting session state."""
    st = ClickSt()
    st.clicks[_CONFIRM_VERSION_BTN] = True
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(_ws(tmp_path)), _VERSION_LABEL: "cleaned v2"}
    _render_confirm_version(st, _DF, _STEPS, state, _file_context(tmp_path))
    return state


def test_confirm_section_writes_nothing_and_does_not_confirm_on_render(tmp_path: Path) -> None:
    st = ClickSt()  # no clicks
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(_ws(tmp_path)), _VERSION_LABEL: "cleaned v2"}

    _render_confirm_version(st, _DF, _STEPS, state, _file_context(tmp_path))

    assert "Confirm processed version" in _buttons(st)
    assert PREP_CONFIRMED_VERSION not in state
    assert not (_ws(tmp_path) / "preprocessed").exists()


def test_browser_download_and_workspace_save_are_non_confirming(tmp_path: Path) -> None:
    st = ClickSt()
    st.clicks[_SAVE_TRANSFORMED_BTN] = True
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(_ws(tmp_path))}

    _render_transformed_output(st, _DF, state, _file_context(tmp_path))

    # The CSV download stays available and the unmanaged save runs, but neither
    # registers a lifecycle version.
    assert st.called("download_button")
    assert PREP_CONFIRMED_VERSION not in state
    assert list((_ws(tmp_path) / "preprocessed").glob("*.dqtv.json")) == []


def test_confirm_stores_handoff_and_shows_confirmed_identity(tmp_path: Path) -> None:
    st = ClickSt()
    st.clicks[_CONFIRM_VERSION_BTN] = True
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(_ws(tmp_path)), _VERSION_LABEL: "cleaned v2"}

    _render_confirm_version(st, _DF, _STEPS, state, _file_context(tmp_path))

    handoff = state[PREP_CONFIRMED_VERSION]
    assert isinstance(handoff, ConfirmedVersionHandoff)
    assert handoff.label == "cleaned v2"
    text = st.texts()
    assert handoff.short_version_id in text
    assert "preprocessed/customers.csv" in text
    assert "Set active" in _buttons(st)
    assert str(tmp_path) not in text  # no absolute path exposure


def test_confirm_requires_a_label(tmp_path: Path) -> None:
    st = ClickSt()
    st.clicks[_CONFIRM_VERSION_BTN] = True
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(_ws(tmp_path))}  # no label

    _render_confirm_version(st, _DF, _STEPS, state, _file_context(tmp_path))

    assert st.called("error")
    assert PREP_CONFIRMED_VERSION not in state
    assert not (_ws(tmp_path) / "preprocessed").exists()


def test_confirm_requires_a_workspace_root(tmp_path: Path) -> None:
    st = ClickSt()
    st.clicks[_CONFIRM_VERSION_BTN] = True
    state: dict[str, Any] = {_VERSION_LABEL: "cleaned v2"}  # no workspace root

    _render_confirm_version(st, _DF, _STEPS, state, _file_context(tmp_path))

    assert st.called("error")
    assert PREP_CONFIRMED_VERSION not in state


def test_confirm_requires_an_active_dataset_context(tmp_path: Path) -> None:
    st = ClickSt()
    st.clicks[_CONFIRM_VERSION_BTN] = True
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(_ws(tmp_path)), _VERSION_LABEL: "v"}

    _render_confirm_version(st, _DF, _STEPS, state, None)

    assert st.called("info")
    assert "Confirm processed version" not in _buttons(st)
    assert PREP_CONFIRMED_VERSION not in state


def test_confirm_requires_a_non_empty_recipe(tmp_path: Path) -> None:
    st = ClickSt()
    st.clicks[_CONFIRM_VERSION_BTN] = True
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(_ws(tmp_path)), _VERSION_LABEL: "v"}

    _render_confirm_version(st, _DF, [], state, _file_context(tmp_path))

    assert st.called("info")
    assert "Confirm processed version" not in _buttons(st)
    assert PREP_CONFIRMED_VERSION not in state


def test_confirm_blocked_when_a_recipe_step_errored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    errored = [{**make_recipe_step("drop_duplicates", [], {}), "status": STATUS_ERROR}]
    monkeypatch.setattr(preprocess_studio, "apply_recipe", lambda df, steps: (_DF, errored))
    st = ClickSt()
    st.clicks[_CONFIRM_VERSION_BTN] = True
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(_ws(tmp_path)), _VERSION_LABEL: "v"}

    _render_confirm_version(st, _DF, _STEPS, state, _file_context(tmp_path))

    assert st.called("error")
    assert PREP_CONFIRMED_VERSION not in state
    assert not (_ws(tmp_path) / "preprocessed").exists()


def test_saved_unmanaged_warns_and_offers_no_set_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        preprocess_studio,
        "confirm_processed_version",
        lambda **_k: DatasetConfirmationResult(
            status=ConfirmationStatus.SAVED_UNMANAGED,
            record=None,
            message="Files were saved, but lifecycle confirmation did not complete.",
        ),
    )
    st = ClickSt()
    st.clicks[_CONFIRM_VERSION_BTN] = True
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(_ws(tmp_path)), _VERSION_LABEL: "v"}

    _render_confirm_version(st, _DF, _STEPS, state, _file_context(tmp_path))

    assert st.called("warning")
    assert not st.called("success")
    assert PREP_CONFIRMED_VERSION not in state
    assert "Set active" not in _buttons(st)


def test_failed_result_offers_no_set_active_and_drops_stale_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _confirmed_state(tmp_path)
    assert PREP_CONFIRMED_VERSION in state
    monkeypatch.setattr(
        preprocess_studio,
        "confirm_processed_version",
        lambda **_k: DatasetConfirmationResult(
            status=ConfirmationStatus.FAILED, record=None, message="Could not confirm."
        ),
    )
    st = ClickSt()
    st.clicks[_CONFIRM_VERSION_BTN] = True

    _render_confirm_version(st, _DF, _STEPS, state, _file_context(tmp_path))

    assert st.called("error")
    # A stale handoff must not survive to offer activation next to a failure.
    assert PREP_CONFIRMED_VERSION not in state
    assert "Set active" not in _buttons(st)


def test_set_active_activates_confirmed_version_and_reruns(tmp_path: Path) -> None:
    state = _confirmed_state(tmp_path)
    handoff = state[PREP_CONFIRMED_VERSION]
    st = ClickSt()
    st.clicks[_SET_ACTIVE_BTN] = True

    _render_confirmed_version(st, state)

    context = get_dataset_context(state)
    assert context is not None
    assert context.managed is True
    assert context.version_id == handoff.version_id
    assert context.content_id == handoff.record.content_id
    assert st.called("rerun")


def test_set_active_delegates_to_the_shared_activation_service(tmp_path: Path) -> None:
    state = _confirmed_state(tmp_path)
    st = ClickSt()
    st.clicks[_SET_ACTIVE_BTN] = True

    with patch(
        "data_quality_toolkit.adapters.ui.pages.preprocess_studio.activate_dataset_context"
    ) as activate:
        _render_confirmed_version(st, state)

    activate.assert_called_once()


def test_activation_failure_preserves_the_prior_active_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _confirmed_state(tmp_path)
    prior = _file_context(tmp_path)
    state[DATASET_CONTEXT] = prior

    def boom(*_a: Any, **_k: Any) -> None:
        raise DatasetActivationError("nope")

    monkeypatch.setattr(preprocess_studio, "activate_dataset_context", boom)
    st = ClickSt()
    st.clicks[_SET_ACTIVE_BTN] = True

    _render_confirmed_version(st, state)

    assert get_dataset_context(state) is prior
    assert st.called("error")
    assert not st.called("rerun")


def test_set_active_with_missing_file_preserves_prior_context(tmp_path: Path) -> None:
    state = _confirmed_state(tmp_path)
    prior = _file_context(tmp_path)
    state[DATASET_CONTEXT] = prior
    Path(state[PREP_CONFIRMED_VERSION].csv_path).unlink()
    st = ClickSt()
    st.clicks[_SET_ACTIVE_BTN] = True

    _render_confirmed_version(st, state)

    assert get_dataset_context(state) is prior
    assert st.called("error")
    assert not st.called("rerun")


def test_confirmed_handoff_is_declared_dataset_derived_state() -> None:
    assert PREP_CONFIRMED_VERSION in DATASET_DERIVED_STATE_KEYS


def test_dataset_switch_clears_the_confirmed_handoff(tmp_path: Path) -> None:
    state = _confirmed_state(tmp_path)
    state[DATASET_CONTEXT] = _file_context(tmp_path)
    assert PREP_CONFIRMED_VERSION in state

    # A genuine dataset switch invalidates the handoff through the shared contract.
    changed = set_dataset_context(
        state,
        DatasetContext(
            source_path="C:/safe/other.csv",
            display_name="other.csv",
            size_bytes=99,
            modified_ns=99,
        ),
    )

    assert changed is True
    assert PREP_CONFIRMED_VERSION not in state


def test_render_seeded_recipe_shows_confirmation_stage() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    state: dict[str, Any] = {PREP_RECIPE_STEPS: [make_recipe_step("drop_duplicates", [], {})]}

    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_preprocess_studio(st, state)

    text = st.texts()
    assert "6 · Confirm a processed version" in text
    assert text.index("5 · Save or export the recipe") < text.index("6 · Confirm a processed")


# --- managed root-first dispatch ------------------------------------------

_PATCH_MANAGED_FRAME = "data_quality_toolkit.adapters.ui.pages.preprocess_studio.get_managed_frame"
_MANAGED_ABS = "C:\\workspace\\versions\\v1\\data.csv"


@pytest.fixture(autouse=True)
def _clean_managed_caches() -> Iterator[None]:
    _mfl.clear_managed_caches()
    yield
    _mfl.clear_managed_caches()


def _trusted_prep_session(
    *, large: bool = False, absolute: str = _MANAGED_ABS
) -> tuple[dict[str, Any], ManagedTrustRoot]:
    state: dict[str, Any] = {}
    capability = ensure_session_capability(state)
    root = commit_trust_root(
        state,
        capability,
        version_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        content_id="sha256:" + "a" * 64,
        root_content_id="sha256:" + "b" * 64,
        parent_version_id=None,
        version_label="cleaned v2",
        locator=make_source_locator(
            display_name="data.csv",
            relative_posix="versions/v1/data.csv",
            absolute_path=absolute,
        ),
        size_bytes=2048,
        modified_ns=10,
        large_file_mode=large,
    )
    return state, root


def _managed_mirror_prep_session() -> dict[str, Any]:
    return {
        DATASET_CONTEXT: DatasetContext(
            source_path=_MANAGED_ABS,
            display_name="data.csv",
            size_bytes=2048,
            modified_ns=10,
            managed=True,
            version_id=str(uuid.uuid4()),
            family_id=str(uuid.uuid4()),
            content_id="sha256:" + "a" * 64,
            root_content_id="sha256:" + "b" * 64,
            version_label="cleaned v2",
        )
    }


def _prep_texts(st: FakeSt) -> str:
    return " ".join(str(x) for _, a, _ in st.calls for x in a if isinstance(x, str))


def test_managed_preprocess_uses_managed_frame_not_legacy_loader() -> None:
    st = FakeSt()
    session, _root = _trusted_prep_session()
    with (
        patch(_PATCH_MANAGED_FRAME, return_value=_DF) as managed,
        patch(_PATCH_LOAD) as legacy,
    ):
        _render_preprocess_studio(st, session)
    managed.assert_called_once()
    legacy.assert_not_called()


def test_managed_large_preprocess_refuses_dataframe_materialization() -> None:
    st = FakeSt()
    session, _root = _trusted_prep_session(large=True)
    with (
        patch(_PATCH_MANAGED_FRAME) as managed,
        patch(_PATCH_LOAD) as legacy,
    ):
        _render_preprocess_studio(st, session)
    managed.assert_not_called()
    legacy.assert_not_called()
    assert st.called("warning")


def test_managed_mirror_without_trust_fails_closed_in_preprocess() -> None:
    st = FakeSt()
    with (
        patch(_PATCH_MANAGED_FRAME) as managed,
        patch(_PATCH_LOAD) as legacy,
    ):
        _render_preprocess_studio(st, _managed_mirror_prep_session())
    managed.assert_not_called()
    legacy.assert_not_called()
    assert st.called("error")
    assert _MANAGED_FAIL_CLOSED_MESSAGE in _prep_texts(st)


def test_manual_path_cannot_override_valid_trust_in_preprocess() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "C:/manual/other.csv"
    session, _root = _trusted_prep_session()
    with (
        patch(_PATCH_MANAGED_FRAME, return_value=_DF) as managed,
        patch(_PATCH_LOAD) as legacy,
    ):
        _render_preprocess_studio(st, session)
    managed.assert_called_once()
    legacy.assert_not_called()
    assert not st.called("text_input")


def test_managed_preprocess_identity_is_privacy_safe() -> None:
    st = FakeSt()
    session, root = _trusted_prep_session()
    with (
        patch(_PATCH_MANAGED_FRAME, return_value=_DF),
        patch(_PATCH_LOAD),
    ):
        _render_preprocess_studio(st, session)
    text = _prep_texts(st)
    assert root.locator.display_name in text  # privacy-safe identity is shown
    assert _MANAGED_ABS not in text  # absolute managed path never rendered


def test_managed_loader_refusal_is_privacy_safe_in_preprocess() -> None:
    st = FakeSt()
    session, _root = _trusted_prep_session()
    with patch(_PATCH_MANAGED_FRAME, side_effect=_mfl.ManagedFrameLoadError("SOURCE_MISSING")):
        _render_preprocess_studio(st, session)
    assert st.called("error")
    text = _prep_texts(st)
    assert _MANAGED_ABS not in text
    assert "C:\\workspace" not in text


def test_unmanaged_preprocess_flow_unchanged_without_trust() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with (
        patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)) as legacy,
        patch(_PATCH_MANAGED_FRAME) as managed,
    ):
        _render_preprocess_studio(st, {})
    legacy.assert_called_once()
    managed.assert_not_called()


def test_confirmation_receives_session_state_for_root_first_authority() -> None:
    """The page hands session state to confirmation so trust stays authoritative."""
    signature = inspect.signature(preprocess_studio.confirm_processed_version)
    assert "session_state" in signature.parameters
    source = inspect.getsource(preprocess_studio._run_confirmation)
    assert "session_state=state" in source


# --- stage 7: trusted reload & reprocessing ---------------------------------

_RELOAD_STEPS = [
    make_recipe_step("scaling", ["n"], {"strategy": "minmax"}),
    make_recipe_step("drop_duplicates", [], {}),
]


def _confirmed_managed_session(
    tmp_path: Path,
) -> tuple[dict[str, Any], ManagedTrustRoot, Path]:
    """Confirm one real managed version and commit trust that points at it."""
    root = tmp_path / "ws"
    root.mkdir()
    parent_file = root / "source.csv"
    parent_file.write_bytes(b"n,c\n1,a\n2,a\n2,b\n3,b\n")
    parent = DatasetContext(
        source_path=str(parent_file),
        display_name="orders",
        size_bytes=parent_file.stat().st_size,
        modified_ns=1,
    )
    recipe = recipe_to_json_payload(_RELOAD_STEPS, None)
    result = confirm_processed_version(
        workspace_root=str(root),
        csv_bytes=b"n,c\n10,a\n20,b\n",
        recipe=recipe,
        parent=parent,
        label="cleaned v1",
        filename_stem="orders",
    )
    assert result.status is ConfirmationStatus.CONFIRMED
    record = result.record
    assert record is not None
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    capability = ensure_session_capability(state)
    trust_root = commit_trust_root(
        state,
        capability,
        version_id=record.version_id,
        family_id=record.family_id,
        content_id=record.content_id,
        root_content_id=record.root_content_id,
        parent_version_id=(record.parent.version_id if record.parent else None),
        version_label=record.label,
        locator=make_source_locator(
            display_name="orders.csv",
            relative_posix=result.csv_relative_path,
            absolute_path=result.csv_path,
        ),
        size_bytes=record.size_bytes,
        modified_ns=10,
        large_file_mode=False,
    )
    return state, trust_root, root


def test_reload_action_reference_matches_discovery_projection() -> None:
    _state, root = _trusted_prep_session()
    assert _reload_action_reference(root) == derive_action_reference(version_id=root.version_id)


def test_load_recipe_into_state_loads_and_drafts(tmp_path: Path) -> None:
    state, trust_root, _root = _confirmed_managed_session(tmp_path)
    loaded = _load_recipe_into_state(state, trust_root)
    assert loaded.loaded
    assert isinstance(state[_RELOAD_LOADED_STATE], LoadedRecipe)
    draft = _reload_draft_steps(state)
    assert [s["operation"] for s in draft] == ["scaling", "drop_duplicates"]


def test_load_recipe_failure_clears_reload_state(tmp_path: Path) -> None:
    state, trust_root, _root = _confirmed_managed_session(tmp_path)
    state[_RELOAD_LOADED_STATE] = "stale"
    state[_RELOAD_DRAFT_STATE] = [{"operation": "x"}]
    state[SRC_WORKSPACE_ROOT] = ""  # a blank root forces a load failure
    loaded = _load_recipe_into_state(state, trust_root)
    assert not loaded.loaded
    assert _RELOAD_LOADED_STATE not in state
    assert _RELOAD_DRAFT_STATE not in state


def test_reload_remove_step_edits_only_the_draft(tmp_path: Path) -> None:
    state, trust_root, _root = _confirmed_managed_session(tmp_path)
    _load_recipe_into_state(state, trust_root)
    loaded = state[_RELOAD_LOADED_STATE]
    _reload_remove_step(state, 0)
    assert [s["operation"] for s in _reload_draft_steps(state)] == ["drop_duplicates"]
    # The immutable loaded recipe is untouched by the draft edit.
    assert [s["operation"] for s in loaded.steps] == ["scaling", "drop_duplicates"]


def test_confirm_reload_child_creates_child_without_activating(tmp_path: Path) -> None:
    state, trust_root, root = _confirmed_managed_session(tmp_path)
    _load_recipe_into_state(state, trust_root)
    parent_version = trust_root.version_id

    child = _confirm_reload_child(state, _DF, "child v1")

    assert child is not None
    assert child.confirmed
    assert child.record is not None
    assert child.record.parent is not None
    assert child.record.parent.version_id == parent_version
    assert child.record.version_id != parent_version
    # The child artifacts exist and the active trust root is still the parent —
    # activation stays a separate, explicit reopen action.
    assert (root / Path(child.csv_relative_path)).is_file()
    decision = resolve_trust_authority(state)
    assert decision.root is not None
    assert decision.root.version_id == parent_version


def test_confirm_reload_child_without_load_returns_none(tmp_path: Path) -> None:
    state, _trust_root, _root = _confirmed_managed_session(tmp_path)
    assert _confirm_reload_child(state, _DF, "child") is None


def test_render_recipe_reload_hides_parameter_values(tmp_path: Path) -> None:
    state, trust_root, _root = _confirmed_managed_session(tmp_path)
    _load_recipe_into_state(state, trust_root)
    st = ClickSt()

    _render_recipe_reload(st, state, trust_root, _DF)

    text = st.texts()
    assert "7 · Reprocess the confirmed recipe" in text
    # The original steps are rendered by operation/columns only; the recipe's raw
    # parameter value ("minmax") is never surfaced.
    frames = [a[0] for name, a, _k in st.calls if name == "dataframe" and a]
    assert frames, "expected the original-steps table to render"
    rendered = frames[-1]
    assert (rendered["parameters"] == _RELOAD_PARAMS_HIDDEN).all()
    assert "minmax" not in text


def test_render_recipe_reload_prompts_before_load(tmp_path: Path) -> None:
    state, trust_root, _root = _confirmed_managed_session(tmp_path)
    st = ClickSt()  # no load click

    _render_recipe_reload(st, state, trust_root, _DF)

    assert "Load confirmed recipe" in _buttons(st)
    assert st.called("info")
    assert _RELOAD_DRAFT_STATE not in state


def test_render_recipe_reload_confirms_child_on_click(tmp_path: Path) -> None:
    state, trust_root, root = _confirmed_managed_session(tmp_path)
    _load_recipe_into_state(state, trust_root)
    st = ClickSt()
    st.clicks[_RELOAD_CONFIRM_CHILD_BTN] = True
    st.text_values["Child version label"] = "child v2"

    _render_recipe_reload(st, state, trust_root, _DF)

    assert st.called("success")
    # A second confirmed sibling now exists under preprocessed/.
    sidecars = list((root / "preprocessed").glob("*.dqtv.json"))
    assert len(sidecars) == 2


# --- stage 7: replay evidence integrity ------------------------------------

# One-hot encoding "c" would write a second "c_a", so it refuses before touching
# the frame while the steps around it succeed: PASS -> ERROR -> PASS.
_COLLIDING_DF = pd.DataFrame(
    {"n": [1.0, 2.0, 2.0, 3.0], "c": ["a", "a", "b", "b"], "c_a": [1, 2, 3, 4]}
)
_PARTIAL_DRAFT = [
    make_recipe_step("scaling", ["n"], {"strategy": "minmax"}),
    make_recipe_step("encoding", ["c"], {"strategy": "one_hot"}),
    make_recipe_step("type_cast", ["c_a"], {"target_type": "numeric"}),
]


def _sidecars(root: Path) -> list[Path]:
    return list((root / "preprocessed").glob("*.dqtv.json"))


def test_confirm_reload_child_refuses_a_partially_failed_replay(tmp_path: Path) -> None:
    state, trust_root, root = _confirmed_managed_session(tmp_path)
    _load_recipe_into_state(state, trust_root)
    state[_RELOAD_DRAFT_STATE] = [dict(step) for step in _PARTIAL_DRAFT]
    before = sorted(p.name for p in (root / "preprocessed").iterdir())

    child = _confirm_reload_child(state, _COLLIDING_DF, "partial child")

    assert child is not None
    assert not child.confirmed
    assert child.reason_code == "REPLAY_FAILED"
    # No child CSV, no recipe artifact, and still exactly the parent sidecar.
    assert sorted(p.name for p in (root / "preprocessed").iterdir()) == before
    assert len(_sidecars(root)) == 1


def test_reload_confirm_click_reports_the_refused_replay(tmp_path: Path) -> None:
    state, trust_root, root = _confirmed_managed_session(tmp_path)
    _load_recipe_into_state(state, trust_root)
    state[_RELOAD_DRAFT_STATE] = [dict(step) for step in _PARTIAL_DRAFT]
    st = ClickSt()
    st.clicks[_RELOAD_CONFIRM_CHILD_BTN] = True
    st.text_values["Child version label"] = "partial child"

    _render_recipe_reload(st, state, trust_root, _COLLIDING_DF)

    assert st.called("error")
    assert not st.called("success")
    assert len(_sidecars(root)) == 1


def test_both_confirmation_paths_share_one_replay_predicate() -> None:
    """The page mirrors the shared predicate; it owns no separate safety rule."""
    assert not hasattr(preprocess_studio, "STATUS_ERROR")
    assert "replay_refusal_code(steps, executed)" in inspect.getsource(
        preprocess_studio._run_confirmation
    )
    # The reprocessed path hands its real evidence to the authoritative service
    # rather than deciding anything about the replay itself.
    assert "executed_steps=executed" in inspect.getsource(preprocess_studio._confirm_reload_child)
