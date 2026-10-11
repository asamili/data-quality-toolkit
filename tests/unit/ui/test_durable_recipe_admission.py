"""Strict admission of the twelve supported durable operations.

Every admitted operation branch and every distinct rejection family is covered.
``revalidate_durable_recipe`` performs no durable read/write and no session
mutation, so these tests never touch the filesystem: they pass a plain dict as
session state and a bare workspace-root string, asserting neither is consulted
for durable effect.
"""

from __future__ import annotations

from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.services.managed_recipe_reprocessing import (
    ADMITTED_OPERATIONS,
    STATUS_ADMITTED,
    STATUS_REJECTED,
    revalidate_durable_recipe,
)

_ROOT = "C:/nonexistent-workspace-root-never-read"


def _admit(steps: Any, *, state: dict[str, Any] | None = None) -> Any:
    return revalidate_durable_recipe(
        session_state={} if state is None else state,
        workspace_root=_ROOT,
        steps=steps,
    )


def _step(operation: str, columns: list[Any], parameters: dict[str, Any]) -> dict[str, Any]:
    return {"operation": operation, "columns": columns, "parameters": parameters}


# --- The twelve admitted operations (happy path) ----------------------------

_ADMITTED_CASES: list[tuple[str, dict[str, Any]]] = [
    ("type_cast", _step("type_cast", ["a"], {"target_type": "numeric"})),
    ("missing_value", _step("missing_value", ["a"], {"strategy": "median"})),
    ("missing_constant", _step("missing_value", ["a"], {"strategy": "constant", "fill_value": 0})),
    ("drop_duplicates", _step("drop_duplicates", [], {})),
    ("drop_duplicates_subset", _step("drop_duplicates", [], {"subset": ["a", "b"]})),
    ("iqr_outlier", _step("iqr_outlier", ["a"], {"strategy": "clip"})),
    ("encoding", _step("encoding", ["a"], {"strategy": "one_hot"})),
    ("encoding_card", _step("encoding", ["a"], {"strategy": "one_hot", "max_cardinality": 20})),
    ("scaling", _step("scaling", ["a"], {"strategy": "zscore"})),
    ("derived_column", _step("derived_column", [], {"source_column": "a", "derived_kind": "year"})),
    (
        "calc_arithmetic",
        _step(
            "calc_arithmetic",
            [],
            {"left_column": "a", "right_column": "b", "operator": "add", "output_mode": "new"},
        ),
    ),
    (
        "calc_scalar",
        _step(
            "calc_scalar",
            [],
            {"source_column": "a", "operator": "multiply", "scalar": 2.0},
        ),
    ),
    (
        "calc_scalar_power",
        _step(
            "calc_scalar",
            [],
            {
                "source_column": "a",
                "operator": "power",
                "scalar": 2.0,
                "constant_role": "exponent",
            },
        ),
    ),
    (
        "calc_conditional",
        _step(
            "calc_conditional",
            [],
            {
                "source_column": "a",
                "comparator": ">",
                "compare_value": 3,
                "result_value": "hi",
                "fallback_value": "lo",
            },
        ),
    ),
    (
        "calc_binning",
        _step("calc_binning", [], {"source_column": "a", "num_bins": 4}),
    ),
    (
        "calc_string_upper",
        _step("calc_string", [], {"source_column": "a", "operation": "upper"}),
    ),
    (
        "calc_string_replace",
        _step(
            "calc_string",
            [],
            {"source_column": "a", "operation": "replace", "find": "x", "replace": "y"},
        ),
    ),
    (
        "calc_string_concat",
        _step(
            "calc_string",
            [],
            {"source_column": "a", "operation": "concat", "other_column": "b"},
        ),
    ),
]


@pytest.mark.parametrize("name,step", _ADMITTED_CASES, ids=[c[0] for c in _ADMITTED_CASES])
def test_admits_each_supported_operation(name: str, step: dict[str, Any]) -> None:
    result = _admit([step])
    assert result.status == STATUS_ADMITTED, (name, result.reason_code)
    assert result.admitted
    assert result.step_index == -1


def test_admits_a_full_ordered_recipe() -> None:
    steps = [case[1] for case in _ADMITTED_CASES]
    result = _admit(steps)
    assert result.admitted
    assert len(result.operations) == len(steps)
    assert result.operations[0] == "type_cast"


def test_exactly_twelve_operations_are_admitted() -> None:
    assert len(ADMITTED_OPERATIONS) == 12
    assert len(set(ADMITTED_OPERATIONS)) == 12


# --- Distinct rejection families --------------------------------------------


def _reject(step: dict[str, Any]) -> Any:
    result = _admit([step])
    assert result.status == STATUS_REJECTED, result
    assert result.step_index == 0
    return result


def test_rejects_legacy_alias() -> None:
    assert _reject(_step("cast", ["a"], {"target_type": "numeric"})).reason_code == (
        "OPERATION_LEGACY_ALIAS"
    )


def test_rejects_unknown_operation() -> None:
    assert _reject(_step("teleport", ["a"], {})).reason_code == "OPERATION_UNSUPPORTED"


def test_rejects_unknown_step_key() -> None:
    step = _step("scaling", ["a"], {"strategy": "minmax"})
    step["surprise"] = 1
    assert _reject(step).reason_code == "STEP_UNKNOWN_KEY"


def test_rejects_unknown_parameter_key() -> None:
    assert (
        _reject(_step("scaling", ["a"], {"strategy": "minmax", "bogus": 1})).reason_code
        == "PARAMETER_UNKNOWN_KEY"
    )


def test_rejects_wrong_parameter_type() -> None:
    assert _reject(_step("scaling", ["a"], {"strategy": 5})).reason_code == "PARAMETER_TYPE_INVALID"


def test_rejects_invalid_enum() -> None:
    assert (
        _reject(_step("scaling", ["a"], {"strategy": "logscale"})).reason_code
        == "PARAMETER_ENUM_INVALID"
    )


def test_rejects_bool_as_number_in_bins() -> None:
    assert (
        _reject(_step("calc_binning", [], {"source_column": "a", "num_bins": True})).reason_code
        == "PARAMETER_BOOL_AS_NUMBER"
    )


def test_rejects_bool_as_fill_value() -> None:
    assert (
        _reject(
            _step("missing_value", ["a"], {"strategy": "constant", "fill_value": True})
        ).reason_code
        == "PARAMETER_BOOL_AS_NUMBER"
    )


def test_rejects_blank_column() -> None:
    assert _reject(_step("scaling", ["  "], {"strategy": "minmax"})).reason_code == "COLUMN_BLANK"


def test_rejects_untrimmed_column() -> None:
    assert _reject(_step("scaling", ["a "], {"strategy": "minmax"})).reason_code == (
        "COLUMN_UNTRIMMED"
    )


def test_rejects_duplicate_column() -> None:
    assert _reject(_step("scaling", ["a", "a"], {"strategy": "minmax"})).reason_code == (
        "COLUMN_DUPLICATE"
    )


def test_rejects_non_string_column() -> None:
    assert _reject(_step("scaling", [7], {"strategy": "minmax"})).reason_code == (
        "COLUMN_TYPE_INVALID"
    )


def test_rejects_illegal_conditional_field() -> None:
    # An ordered comparator with a non-numeric compare value: the engine would
    # refuse to evaluate it, so admission refuses it up front.
    assert (
        _reject(
            _step(
                "calc_conditional",
                [],
                {
                    "source_column": "a",
                    "comparator": ">",
                    "compare_value": "not-a-number",
                    "result_value": 1,
                    "fallback_value": 0,
                },
            )
        ).reason_code
        == "CONDITIONAL_FIELD_ILLEGAL"
    )


def test_rejects_unsafe_output_destination() -> None:
    assert (
        _reject(
            _step(
                "calc_scalar",
                [],
                {
                    "source_column": "a",
                    "operator": "add",
                    "scalar": 1.0,
                    "output_mode": "existing",
                    "output_column": "",
                },
            )
        ).reason_code
        == "OUTPUT_DESTINATION_UNSAFE"
    )


def test_rejects_output_collision_across_steps() -> None:
    step = _step(
        "calc_scalar",
        [],
        {"source_column": "a", "operator": "add", "scalar": 1.0, "output_column": "out"},
    )
    second = _step(
        "calc_scalar",
        [],
        {"source_column": "b", "operator": "add", "scalar": 1.0, "output_column": "out"},
    )
    result = _admit([step, second])
    assert result.status == STATUS_REJECTED
    assert result.reason_code == "OUTPUT_COLLISION"
    assert result.step_index == 1


def test_rejects_value_engine_would_clamp() -> None:
    assert (
        _reject(_step("calc_binning", [], {"source_column": "a", "num_bins": 999})).reason_code
        == "PARAMETER_WOULD_CLAMP"
    )


def test_rejects_value_engine_would_ignore() -> None:
    # ``errors`` is accepted but never consulted by type_cast; a non-default value
    # would be silently ignored.
    assert (
        _reject(
            _step("type_cast", ["a"], {"target_type": "numeric", "errors": "raise"})
        ).reason_code
        == "PARAMETER_WOULD_IGNORE"
    )


def test_rejects_value_engine_would_skip() -> None:
    # An empty find makes the engine skip the replace entirely.
    assert (
        _reject(
            _step("calc_string", [], {"source_column": "a", "operation": "replace", "find": ""})
        ).reason_code
        == "PARAMETER_WOULD_SKIP"
    )


def test_rejects_value_engine_would_normalize() -> None:
    # constant_role is stripped+lowercased by the engine; a non-canonical spelling
    # would be normalized away.
    assert (
        _reject(
            _step(
                "calc_scalar",
                [],
                {"source_column": "a", "operator": "power", "scalar": 2.0, "constant_role": "Base"},
            )
        ).reason_code
        == "PARAMETER_WOULD_NORMALIZE"
    )


def test_rejects_columns_where_not_applicable() -> None:
    assert (
        _reject(
            _step("calc_scalar", ["a"], {"source_column": "a", "operator": "add", "scalar": 1.0})
        ).reason_code
        == "COLUMNS_NOT_APPLICABLE"
    )


def test_rejects_missing_required_columns() -> None:
    assert _reject(_step("scaling", [], {"strategy": "minmax"})).reason_code == "COLUMNS_REQUIRED"


def test_rejects_ignored_concat_sentinel() -> None:
    assert (
        _reject(
            _step(
                "calc_string",
                [],
                {"source_column": "a", "operation": "concat", "other_column": "(none)"},
            )
        ).reason_code
        == "PARAMETER_WOULD_IGNORE"
    )


# --- Envelope-level rejections ----------------------------------------------


def test_rejects_non_sequence_steps() -> None:
    result = _admit({"not": "a list"})
    assert result.reason_code == "STEPS_NOT_A_SEQUENCE"
    assert result.step_index == -1


def test_rejects_empty_steps() -> None:
    assert _admit([]).reason_code == "STEPS_EMPTY"


def test_rejects_blank_workspace_root() -> None:
    result = revalidate_durable_recipe(
        session_state={}, workspace_root="   ", steps=[_ADMITTED_CASES[0][1]]
    )
    assert result.reason_code == "WORKSPACE_ROOT_BLANK"


def test_rejects_non_mapping_step() -> None:
    assert _admit(["nope"]).reason_code == "STEP_NOT_A_MAPPING"


def test_reports_offending_step_index() -> None:
    good = _ADMITTED_CASES[0][1]
    bad = _step("scaling", ["a"], {"strategy": "nope"})
    result = _admit([good, good, bad])
    assert result.status == STATUS_REJECTED
    assert result.step_index == 2


# --- No durable / session effect --------------------------------------------


def test_admission_never_mutates_session_state() -> None:
    state = {"unrelated": 1}
    _admit([_ADMITTED_CASES[0][1]], state=state)
    _admit([_step("scaling", ["a"], {"strategy": "nope"})], state=state)
    assert state == {"unrelated": 1}
