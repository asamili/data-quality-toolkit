"""Focused tests for the safe, non-eval calculated-column transforms."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.pages.preprocess_studio import (
    _current_steps,
    _move_step,
    _remove_step,
)
from data_quality_toolkit.adapters.ui.services.preprocessing import apply_recipe
from data_quality_toolkit.adapters.ui.services.preprocessing_calculations import (
    OP_CALC_ARITHMETIC,
    apply_arithmetic,
    apply_binning,
    apply_conditional,
    apply_scalar,
    apply_string_op,
)
from data_quality_toolkit.application.workflow.preprocessing import (
    STATUS_APPLIED,
    STATUS_SKIPPED,
    make_recipe_step,
)

_NUM = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [2.0, 0.0, 2.0, 4.0]})


# ── arithmetic ───────────────────────────────────────────────────────────────


def test_arithmetic_add_creates_new_column() -> None:
    out, status = apply_arithmetic(
        _NUM,
        {"left_column": "a", "right_column": "b", "operator": "add", "output_column": "sum"},
    )
    assert status["status"] == STATUS_APPLIED
    assert out["sum"].tolist() == [3.0, 2.0, 5.0, 8.0]
    # original frame is never mutated
    assert "sum" not in _NUM.columns


def test_arithmetic_divide_by_zero_is_null_not_error() -> None:
    out, status = apply_arithmetic(
        _NUM,
        {"left_column": "a", "right_column": "b", "operator": "divide", "output_column": "d"},
    )
    assert status["status"] == STATUS_APPLIED
    assert pd.isna(out["d"].iloc[1])  # divided by zero row -> null
    assert out["d"].iloc[0] == 0.5


def test_arithmetic_subtract_still_works() -> None:
    out, status = apply_arithmetic(
        _NUM,
        {"left_column": "a", "right_column": "b", "operator": "subtract", "output_column": "d"},
    )
    assert status["status"] == STATUS_APPLIED
    assert out["d"].tolist() == [-1.0, 2.0, 1.0, 0.0]


def test_arithmetic_missing_column_is_skipped() -> None:
    out, status = apply_arithmetic(
        _NUM, {"left_column": "a", "right_column": "missing", "operator": "add"}
    )
    assert status["status"] == STATUS_SKIPPED
    assert "missing" in (status["warning"] or "")


def test_arithmetic_non_numeric_coerces_to_null_without_crashing() -> None:
    df = pd.DataFrame({"s": ["x", "y"], "n": [1.0, 2.0]})
    out, status = apply_arithmetic(
        df, {"left_column": "s", "right_column": "n", "operator": "add", "output_column": "r"}
    )
    assert status["status"] == STATUS_APPLIED
    assert out["r"].isna().all()


def test_arithmetic_power_between_columns() -> None:
    df = pd.DataFrame({"base": [2.0, 3.0, 4.0], "exp": [3.0, 2.0, 0.5]})
    out, status = apply_arithmetic(
        df,
        {
            "left_column": "base",
            "right_column": "exp",
            "operator": "power",
            "output_column": "p",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert out["p"].tolist() == [8.0, 9.0, 2.0]


def test_arithmetic_power_invalid_rows_become_null_and_warn() -> None:
    df = pd.DataFrame(
        {
            "base": [
                0.0,
                -4.0,
                None,
                "x",
                2.0,
                1e308,
                float("inf"),
                float("-inf"),
                4.0,
                3.0,
            ],
            "exp": [-1.0, 0.5, 2.0, 2.0, None, 2.0, 1.0, 1.0, "bad", 2.0],
        }
    )
    out, status = apply_arithmetic(
        df,
        {
            "left_column": "base",
            "right_column": "exp",
            "operator": "power",
            "output_column": "p",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert "9 invalid or non-finite power result(s) set to null" in (status["warning"] or "")
    assert pd.isna(out["p"].iloc[0])  # zero raised to a negative exponent
    assert pd.isna(out["p"].iloc[1])  # negative base raised to a fractional exponent
    assert pd.isna(out["p"].iloc[2])  # missing base
    assert pd.isna(out["p"].iloc[3])  # non-numeric base
    assert pd.isna(out["p"].iloc[4])  # missing exponent
    assert pd.isna(out["p"].iloc[5])  # overflow
    assert pd.isna(out["p"].iloc[6])  # positive infinity
    assert pd.isna(out["p"].iloc[7])  # negative infinity
    assert pd.isna(out["p"].iloc[8])  # non-numeric exponent
    assert out["p"].iloc[9] == 9.0  # valid rows remain available
    assert not pd.api.types.is_complex_dtype(out["p"])


# ── scalar ───────────────────────────────────────────────────────────────────


def test_scalar_multiply() -> None:
    out, status = apply_scalar(
        _NUM, {"source_column": "a", "operator": "multiply", "scalar": 2, "output_column": "x2"}
    )
    assert status["status"] == STATUS_APPLIED
    assert out["x2"].tolist() == [2.0, 4.0, 6.0, 8.0]


def test_scalar_divide_by_zero_scalar_is_skipped() -> None:
    out, status = apply_scalar(_NUM, {"source_column": "a", "operator": "divide", "scalar": 0})
    assert status["status"] == STATUS_SKIPPED
    assert "divide by zero" in (status["warning"] or "")


def test_scalar_round() -> None:
    df = pd.DataFrame({"a": [1.234, 5.678]})
    out, status = apply_scalar(
        df, {"source_column": "a", "operator": "round", "scalar": 1, "output_column": "r"}
    )
    assert status["status"] == STATUS_APPLIED
    assert out["r"].tolist() == [1.2, 5.7]


def test_scalar_invalid_value_is_skipped() -> None:
    _, status = apply_scalar(
        _NUM, {"source_column": "a", "operator": "add", "scalar": "not-a-number"}
    )
    assert status["status"] == STATUS_SKIPPED


def test_scalar_power_positive_integer_constant() -> None:
    out, status = apply_scalar(
        _NUM,
        {"source_column": "a", "operator": "power", "scalar": 2, "output_column": "squared"},
    )
    assert status["status"] == STATUS_APPLIED
    assert out["squared"].tolist() == [1.0, 4.0, 9.0, 16.0]


def test_scalar_power_fractional_constant_for_positive_bases() -> None:
    df = pd.DataFrame({"a": [4.0, 9.0, 16.0]})
    out, status = apply_scalar(
        df, {"source_column": "a", "operator": "power", "scalar": 0.5, "output_column": "root"}
    )
    assert status["status"] == STATUS_APPLIED
    assert out["root"].tolist() == [2.0, 3.0, 4.0]


def test_scalar_power_negative_constant_for_nonzero_bases() -> None:
    df = pd.DataFrame({"a": [2.0, 4.0]})
    out, status = apply_scalar(
        df, {"source_column": "a", "operator": "power", "scalar": -1, "output_column": "inv"}
    )
    assert status["status"] == STATUS_APPLIED
    assert out["inv"].tolist() == [0.5, 0.25]


def test_scalar_power_missing_constant_role_defaults_to_exponent() -> None:
    df = pd.DataFrame({"a": [2.0, 3.0]})
    out, status = apply_scalar(
        df, {"source_column": "a", "operator": "power", "scalar": 3, "output_column": "cubed"}
    )
    assert status["status"] == STATUS_APPLIED
    assert out["cubed"].tolist() == [8.0, 27.0]


def test_scalar_power_constant_role_exponent_performs_column_power_constant() -> None:
    df = pd.DataFrame({"a": [2.0, 3.0]})
    out, status = apply_scalar(
        df,
        {
            "source_column": "a",
            "operator": "power",
            "scalar": 2,
            "constant_role": "exponent",
            "output_column": "squared",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert out["squared"].tolist() == [4.0, 9.0]


def test_scalar_power_constant_role_base_performs_constant_power_column() -> None:
    df = pd.DataFrame({"exp": [2.0, 3.0]})
    out, status = apply_scalar(
        df,
        {
            "source_column": "exp",
            "operator": "power",
            "scalar": 2,
            "constant_role": "base",
            "output_column": "pow",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert out["pow"].tolist() == [4.0, 8.0]


def test_scalar_power_positive_constant_base_integer_exponents() -> None:
    df = pd.DataFrame({"exp": [0.0, 1.0, 3.0]})
    out, status = apply_scalar(
        df,
        {
            "source_column": "exp",
            "operator": "power",
            "scalar": 2,
            "constant_role": "base",
            "output_column": "pow",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert out["pow"].tolist() == [1.0, 2.0, 8.0]


def test_scalar_power_positive_constant_base_fractional_exponents() -> None:
    df = pd.DataFrame({"exp": [0.5, 1.5]})
    out, status = apply_scalar(
        df,
        {
            "source_column": "exp",
            "operator": "power",
            "scalar": 4,
            "constant_role": "base",
            "output_column": "pow",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert out["pow"].tolist() == [2.0, 8.0]


def test_scalar_power_positive_constant_base_negative_exponents() -> None:
    df = pd.DataFrame({"exp": [-1.0, -2.0]})
    out, status = apply_scalar(
        df,
        {
            "source_column": "exp",
            "operator": "power",
            "scalar": 2,
            "constant_role": "base",
            "output_column": "pow",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert out["pow"].tolist() == [0.5, 0.25]


def test_scalar_power_zero_base_negative_exponent_becomes_null() -> None:
    df = pd.DataFrame({"exp": [-1.0, 2.0]})
    out, status = apply_scalar(
        df,
        {
            "source_column": "exp",
            "operator": "power",
            "scalar": 0,
            "constant_role": "base",
            "output_column": "pow",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert pd.isna(out["pow"].iloc[0])
    assert out["pow"].iloc[1] == 0.0


def test_scalar_power_negative_base_integer_exponent_works() -> None:
    df = pd.DataFrame({"exp": [2.0, 3.0]})
    out, status = apply_scalar(
        df,
        {
            "source_column": "exp",
            "operator": "power",
            "scalar": -2,
            "constant_role": "base",
            "output_column": "pow",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert out["pow"].tolist() == [4.0, -8.0]


def test_scalar_power_negative_base_fractional_exponent_becomes_null() -> None:
    df = pd.DataFrame({"exp": [0.5, 2.0]})
    out, status = apply_scalar(
        df,
        {
            "source_column": "exp",
            "operator": "power",
            "scalar": -4,
            "constant_role": "base",
            "output_column": "pow",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert "1 invalid or non-finite power result(s) set to null" in (status["warning"] or "")
    assert pd.isna(out["pow"].iloc[0])
    assert out["pow"].iloc[1] == 16.0
    assert not pd.api.types.is_complex_dtype(out["pow"])


def test_scalar_power_constant_base_missing_and_non_numeric_exponents_become_null() -> None:
    df = pd.DataFrame({"exp": [None, "bad", 3.0]})
    out, status = apply_scalar(
        df,
        {
            "source_column": "exp",
            "operator": "power",
            "scalar": 2,
            "constant_role": "base",
            "output_column": "pow",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert "2 invalid or non-finite power result(s) set to null" in (status["warning"] or "")
    assert pd.isna(out["pow"].iloc[0])
    assert pd.isna(out["pow"].iloc[1])
    assert out["pow"].iloc[2] == 8.0


def test_scalar_power_constant_base_overflow_becomes_null_and_valid_rows_remain() -> None:
    df = pd.DataFrame({"exp": [2.0, 1.0]})
    out, status = apply_scalar(
        df,
        {
            "source_column": "exp",
            "operator": "power",
            "scalar": 1e308,
            "constant_role": "base",
            "output_column": "pow",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert "1 invalid or non-finite power result(s) set to null" in (status["warning"] or "")
    assert pd.isna(out["pow"].iloc[0])
    assert math.isclose(out["pow"].iloc[1], 1e308)


def test_scalar_power_constant_base_infinity_is_not_retained() -> None:
    df = pd.DataFrame({"exp": [float("inf"), 2.0]})
    out, status = apply_scalar(
        df,
        {
            "source_column": "exp",
            "operator": "power",
            "scalar": 2,
            "constant_role": "base",
            "output_column": "pow",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert pd.isna(out["pow"].iloc[0])
    assert out["pow"].iloc[1] == 4.0
    assert not pd.api.types.is_complex_dtype(out["pow"])


@pytest.mark.parametrize(
    ("constant", "expected"),
    [
        (math.pi, math.pow(2.0, math.pi)),
        (math.e, math.pow(2.0, math.e)),
        (math.sqrt(2.0), math.pow(2.0, math.sqrt(2.0))),
    ],
)
def test_scalar_power_named_constants_work_as_exponent_constants(
    constant: float, expected: float
) -> None:
    df = pd.DataFrame({"a": [2.0]})
    out, status = apply_scalar(
        df,
        {
            "source_column": "a",
            "operator": "power",
            "scalar": constant,
            "constant_role": "exponent",
            "output_column": "pow",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert math.isclose(out["pow"].iloc[0], expected)


@pytest.mark.parametrize(
    ("constant", "expected"),
    [
        (math.pi, math.pi**2),
        (math.e, math.e**2),
        (math.sqrt(2.0), 2.0),
    ],
)
def test_scalar_power_named_constants_work_as_base_constants(
    constant: float, expected: float
) -> None:
    df = pd.DataFrame({"exp": [2.0]})
    out, status = apply_scalar(
        df,
        {
            "source_column": "exp",
            "operator": "power",
            "scalar": constant,
            "constant_role": "base",
            "output_column": "pow",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert math.isclose(out["pow"].iloc[0], expected)


# ── conditional ──────────────────────────────────────────────────────────────


def test_conditional_numeric_greater_than() -> None:
    out, status = apply_conditional(
        _NUM,
        {
            "source_column": "a",
            "comparator": ">",
            "compare_value": "2",
            "result_value": "big",
            "fallback_value": "small",
            "output_column": "flag",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert out["flag"].tolist() == ["small", "small", "big", "big"]


def test_conditional_string_equality() -> None:
    df = pd.DataFrame({"c": ["a", "b", "a"]})
    out, status = apply_conditional(
        df,
        {
            "source_column": "c",
            "comparator": "==",
            "compare_value": "a",
            "result_value": "yes",
            "fallback_value": "no",
            "output_column": "eq",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert out["eq"].tolist() == ["yes", "no", "yes"]


def test_conditional_non_numeric_value_for_ordered_comparator_is_skipped() -> None:
    _, status = apply_conditional(
        _NUM, {"source_column": "a", "comparator": ">", "compare_value": "abc"}
    )
    assert status["status"] == STATUS_SKIPPED


# ── binning ──────────────────────────────────────────────────────────────────


def test_binning_creates_labels() -> None:
    df = pd.DataFrame({"n": list(range(10))})
    out, status = apply_binning(df, {"source_column": "n", "num_bins": 2, "output_column": "bin"})
    assert status["status"] == STATUS_APPLIED
    assert out["bin"].dropna().nunique() == 2


def test_binning_insufficient_distinct_is_skipped() -> None:
    df = pd.DataFrame({"n": [5.0, 5.0, 5.0]})
    _, status = apply_binning(df, {"source_column": "n", "num_bins": 4})
    assert status["status"] == STATUS_SKIPPED


# ── string operations ────────────────────────────────────────────────────────


def test_string_upper() -> None:
    df = pd.DataFrame({"s": ["ab", "cd"]})
    out, status = apply_string_op(
        df, {"source_column": "s", "operation": "upper", "output_column": "u"}
    )
    assert status["status"] == STATUS_APPLIED
    assert out["u"].tolist() == ["AB", "CD"]


def test_string_length() -> None:
    df = pd.DataFrame({"s": ["ab", "abc"]})
    out, status = apply_string_op(
        df, {"source_column": "s", "operation": "length", "output_column": "len"}
    )
    assert status["status"] == STATUS_APPLIED
    assert out["len"].tolist() == [2, 3]


def test_string_replace_is_literal() -> None:
    df = pd.DataFrame({"s": ["a-b", "c-d"]})
    out, status = apply_string_op(
        df,
        {
            "source_column": "s",
            "operation": "replace",
            "find": "-",
            "replace": "_",
            "output_column": "r",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert out["r"].tolist() == ["a_b", "c_d"]


def test_string_replace_empty_find_is_skipped() -> None:
    df = pd.DataFrame({"s": ["a", "b"]})
    _, status = apply_string_op(df, {"source_column": "s", "operation": "replace", "find": ""})
    assert status["status"] == STATUS_SKIPPED


def test_string_concat_with_other_column_and_literal() -> None:
    df = pd.DataFrame({"a": ["x", "y"], "b": ["1", "2"]})
    out, status = apply_string_op(
        df,
        {
            "source_column": "a",
            "operation": "concat",
            "other_column": "b",
            "literal": "_z",
            "output_column": "c",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert out["c"].tolist() == ["x1_z", "y2_z"]


# ── output modes ─────────────────────────────────────────────────────────────


def test_apply_into_existing_column_overwrites_without_adding_column() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
    out, status = apply_arithmetic(
        df,
        {
            "left_column": "a",
            "right_column": "b",
            "operator": "add",
            "output_mode": "existing",
            "output_column": "a",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert out["a"].tolist() == [4.0, 6.0]
    assert list(out.columns) == ["a", "b"]  # no new column added


def test_create_new_duplicate_output_name_is_rejected_without_overwrite() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0], "sum": [10.0, 20.0]})
    out, status = apply_arithmetic(
        df,
        {
            "left_column": "a",
            "right_column": "b",
            "operator": "add",
            "output_mode": "new",
            "output_column": "sum",
        },
    )
    assert status["status"] == STATUS_SKIPPED
    assert "already exists" in (status["warning"] or "")
    assert "overwrite mode" in (status["warning"] or "")
    assert out["sum"].tolist() == [10.0, 20.0]


def test_existing_mode_missing_target_is_skipped() -> None:
    _, status = apply_arithmetic(
        _NUM,
        {
            "left_column": "a",
            "right_column": "b",
            "operator": "add",
            "output_mode": "existing",
            "output_column": "nope",
        },
    )
    assert status["status"] == STATUS_SKIPPED


# ── replay integration ───────────────────────────────────────────────────────


def test_calc_step_replays_through_apply_recipe() -> None:
    step = make_recipe_step(
        OP_CALC_ARITHMETIC,
        [],
        {"left_column": "a", "right_column": "b", "operator": "add", "output_column": "sum"},
    )
    final_df, executed = apply_recipe(_NUM, [step])
    assert executed[0]["status"] == STATUS_APPLIED
    assert "sum" in final_df.columns
    assert final_df["sum"].tolist() == [3.0, 2.0, 5.0, 8.0]


# ── step editing helpers ─────────────────────────────────────────────────────


def _recipe_state() -> dict:
    return {
        "prep_recipe_steps": [
            make_recipe_step("scaling", ["a"], {"strategy": "minmax"}),
            make_recipe_step("drop_duplicates", [], {}),
        ]
    }


def test_remove_step_drops_selected_index() -> None:
    state = _recipe_state()
    _remove_step(state, 0)
    steps = _current_steps(state)
    assert len(steps) == 1
    assert steps[0]["operation"] == "drop_duplicates"


def test_remove_step_out_of_range_is_noop() -> None:
    state = _recipe_state()
    _remove_step(state, 9)
    assert len(_current_steps(state)) == 2


def test_move_step_swaps_neighbours() -> None:
    state = _recipe_state()
    _move_step(state, 0, 1)
    steps = _current_steps(state)
    assert steps[0]["operation"] == "drop_duplicates"
    assert steps[1]["operation"] == "scaling"


def test_move_step_past_bounds_is_noop() -> None:
    state = _recipe_state()
    _move_step(state, 0, -1)
    assert _current_steps(state)[0]["operation"] == "scaling"


# ── output-collision delegation ──────────────────────────────────────────────

# Calculated columns were already protected; R4 routes that protection through
# the one shared output-destination policy. These pin the established behaviour
# so the delegation cannot quietly change it.

_COLLIDE = pd.DataFrame(
    {
        "a": [1.0, 2.0],
        "b": [3.0, 4.0],
        "s": ["x", "y"],
        "a__multiply__b": ["keep", "keep"],
        "a__add": ["keep", "keep"],
        "a__flag": ["keep", "keep"],
        "a__bin": ["keep", "keep"],
        "s__upper": ["keep", "keep"],
    }
)


def _calc_collision(call: Any, params: dict[str, Any], destination: str) -> None:
    out, status = call(_COLLIDE, params)
    # Skipped, not errored: the calculated contract is deliberately unchanged.
    assert status["status"] == STATUS_SKIPPED
    assert "already exists" in (status["warning"] or "")
    assert "overwrite mode" in (status["warning"] or "")
    assert out[destination].tolist() == ["keep", "keep"]
    pd.testing.assert_frame_equal(out, _COLLIDE)


def test_arithmetic_default_destination_collision_is_refused() -> None:
    _calc_collision(
        apply_arithmetic,
        {"left_column": "a", "right_column": "b", "operator": "multiply"},
        "a__multiply__b",
    )


def test_scalar_default_destination_collision_is_refused() -> None:
    _calc_collision(
        apply_scalar,
        {"source_column": "a", "operator": "add", "scalar": 1.0},
        "a__add",
    )


def test_conditional_default_destination_collision_is_refused() -> None:
    _calc_collision(
        apply_conditional,
        {"source_column": "a", "comparator": ">", "compare_value": 1},
        "a__flag",
    )


def test_binning_default_destination_collision_is_refused() -> None:
    _calc_collision(
        apply_binning,
        {"source_column": "a", "num_bins": 2},
        "a__bin",
    )


def test_string_default_destination_collision_is_refused() -> None:
    _calc_collision(
        apply_string_op,
        {"source_column": "s", "operation": "upper"},
        "s__upper",
    )


def test_explicit_overwrite_still_replaces_exactly_the_named_column() -> None:
    out, status = apply_scalar(
        _COLLIDE,
        {
            "source_column": "a",
            "operator": "add",
            "scalar": 10.0,
            "output_mode": "existing",
            "output_column": "a__add",
        },
    )
    assert status["status"] == STATUS_APPLIED
    assert out["a__add"].tolist() == [11.0, 12.0]
    # The authorised destination is the only one replaced.
    assert list(out.columns) == list(_COLLIDE.columns)
    assert out["a__multiply__b"].tolist() == ["keep", "keep"]


def test_calculated_step_cannot_overwrite_a_generated_output_column() -> None:
    frame = pd.DataFrame({"n": [1.0, 2.0, 3.0, 100.0], "a": [1.0, 2.0, 3.0, 4.0]})
    flagged, status = apply_recipe(
        frame, [make_recipe_step("iqr_outlier", ["n"], {"strategy": "flag"})]
    )
    assert status[0]["status"] == STATUS_APPLIED

    out, calc_status = apply_scalar(
        flagged,
        {"source_column": "a", "operator": "add", "scalar": 1.0, "output_column": "n__outlier"},
    )
    assert calc_status["status"] == STATUS_SKIPPED
    assert out["n__outlier"].tolist() == flagged["n__outlier"].tolist()
