"""Tests for the Preprocess Studio transform engine (adapters/ui/services/preprocessing)."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.services import preprocessing as svc
from data_quality_toolkit.adapters.ui.services.preprocessing import (
    apply_drop_duplicates,
    apply_encoding,
    apply_iqr_outlier_strategy,
    apply_missing_value_strategy,
    apply_recipe,
    apply_safe_derived_column,
    apply_scaling,
    apply_type_cast,
    deterministic_output_names,
    is_large_frame,
    preview_frame,
)
from data_quality_toolkit.application.workflow.preprocessing import (
    OUTPUT_COLLISION,
    STATUS_APPLIED,
    STATUS_ERROR,
    STATUS_SKIPPED,
    make_recipe_step,
)

_DF = pd.DataFrame(
    {
        "n": [1.0, 2.0, 3.0, 4.0, 100.0],
        "z": [5.0, 5.0, 5.0, 5.0, 5.0],
        "cat": ["a", "b", "a", "b", "a"],
        "num_str": ["1", "2", "3", "x", "5"],
    }
)


# ── structural contract ──────────────────────────────────────────────────────


def test_service_stays_streamlit_free() -> None:
    assert "import streamlit" not in inspect.getsource(svc)


# ── type cast ────────────────────────────────────────────────────────────────


def test_type_cast_numeric_coerces_invalid_to_null_and_warns() -> None:
    out, status = apply_type_cast(_DF, ["num_str"], "numeric")
    assert status["status"] == STATUS_APPLIED
    assert pd.api.types.is_numeric_dtype(out["num_str"])
    assert int(out["num_str"].isna().sum()) == 1
    assert status["warning"] is not None


def test_type_cast_does_not_mutate_input() -> None:
    before = _DF.copy()
    apply_type_cast(_DF, ["num_str"], "numeric")
    pd.testing.assert_frame_equal(_DF, before)


def test_type_cast_missing_column_skips() -> None:
    out, status = apply_type_cast(_DF, ["nope"], "numeric")
    assert status["status"] == STATUS_SKIPPED
    pd.testing.assert_frame_equal(out, _DF)


def test_type_cast_boolean_maps_known_tokens() -> None:
    df = pd.DataFrame({"flag": ["yes", "no", "maybe", None]})
    out, status = apply_type_cast(df, ["flag"], "boolean")
    assert status["status"] == STATUS_APPLIED
    assert out["flag"].tolist()[:2] == [True, False]
    assert pd.isna(out["flag"].iloc[2])  # unknown token → null


# ── missing values ───────────────────────────────────────────────────────────


def test_missing_drop_removes_rows() -> None:
    df = pd.DataFrame({"a": [1.0, None, 3.0]})
    out, status = apply_missing_value_strategy(df, ["a"], "drop")
    assert status["status"] == STATUS_APPLIED
    assert len(out) == 2


def test_missing_median_fills_numeric() -> None:
    df = pd.DataFrame({"a": [1.0, None, 3.0]})
    out, _ = apply_missing_value_strategy(df, ["a"], "median")
    assert int(out["a"].isna().sum()) == 0
    assert out["a"].iloc[1] == 2.0


def test_missing_mode_fills_categorical() -> None:
    df = pd.DataFrame({"c": ["a", None, "a", "b"]})
    out, _ = apply_missing_value_strategy(df, ["c"], "mode")
    assert out["c"].iloc[1] == "a"


def test_missing_constant_uses_plain_value() -> None:
    df = pd.DataFrame({"c": ["a", None]})
    out, _ = apply_missing_value_strategy(df, ["c"], "constant", fill_value="UNKNOWN")
    assert out["c"].iloc[1] == "UNKNOWN"


# ── duplicates ───────────────────────────────────────────────────────────────


def test_drop_duplicates_removes_exact_rows() -> None:
    df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
    out, status = apply_drop_duplicates(df)
    assert len(out) == 2
    assert "removed 1 duplicate row(s)" in status["detail"]


def test_drop_duplicates_subset() -> None:
    df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "y", "z"]})
    out, _ = apply_drop_duplicates(df, subset=["a"])
    assert len(out) == 2


# ── outliers ─────────────────────────────────────────────────────────────────


def test_iqr_flag_adds_boolean_column() -> None:
    out, status = apply_iqr_outlier_strategy(_DF, ["n"], "flag")
    assert status["status"] == STATUS_APPLIED
    assert "n__outlier" in out.columns
    assert bool(out["n__outlier"].iloc[-1]) is True


def test_iqr_clip_bounds_values() -> None:
    out, _ = apply_iqr_outlier_strategy(_DF, ["n"], "clip")
    assert out["n"].max() < 100.0


def test_iqr_remove_drops_outlier_rows() -> None:
    out, _ = apply_iqr_outlier_strategy(_DF, ["n"], "remove")
    assert len(out) < len(_DF)


def test_iqr_non_numeric_skips() -> None:
    out, status = apply_iqr_outlier_strategy(_DF, ["cat"], "flag")
    assert status["status"] == STATUS_SKIPPED


# ── encoding ─────────────────────────────────────────────────────────────────


def test_encoding_one_hot_expands_columns() -> None:
    out, status = apply_encoding(_DF, ["cat"], "one_hot")
    assert status["status"] == STATUS_APPLIED
    assert any(c.startswith("cat_") for c in out.columns)


def test_encoding_cardinality_guard_skips_and_warns() -> None:
    df = pd.DataFrame({"hi": [str(i) for i in range(10)]})
    out, status = apply_encoding(df, ["hi"], "one_hot", max_cardinality=5)
    assert "skipped one-hot" in (status["warning"] or "")
    assert list(out.columns) == ["hi"]  # untouched


def test_encoding_label_is_deterministic() -> None:
    out, _ = apply_encoding(_DF, ["cat"], "label")
    assert "cat__label" in out.columns
    # 'a' sorts before 'b' → code 0 / 1 deterministically
    assert out["cat__label"].iloc[0] == 0


def test_encoding_frequency_counts() -> None:
    out, _ = apply_encoding(_DF, ["cat"], "frequency")
    assert out["cat__freq"].iloc[0] == 3  # 'a' appears 3 times


# ── scaling ──────────────────────────────────────────────────────────────────


def test_scaling_minmax_range() -> None:
    out, status = apply_scaling(_DF, ["n"], "minmax")
    assert status["status"] == STATUS_APPLIED
    assert out["n"].min() == 0.0
    assert out["n"].max() == 1.0


def test_scaling_zero_variance_sets_zero_and_warns() -> None:
    out, status = apply_scaling(_DF, ["z"], "zscore")
    assert (out["z"] == 0.0).all()
    assert "zero variance" in (status["warning"] or "")


# ── derived columns ──────────────────────────────────────────────────────────


def test_derived_datetime_parts() -> None:
    df = pd.DataFrame({"d": ["2024-01-15", "2024-06-30"]})
    out, status = apply_safe_derived_column(df, "d", "year")
    assert status["status"] == STATUS_APPLIED
    assert out["d__year"].tolist() == [2024, 2024]


def test_derived_text_length() -> None:
    df = pd.DataFrame({"s": ["ab", "abcd"]})
    out, _ = apply_safe_derived_column(df, "s", "text_length")
    assert out["s__text_length"].tolist() == [2, 4]


def test_derived_missing_source_skips() -> None:
    out, status = apply_safe_derived_column(_DF, "nope", "year")
    assert status["status"] == STATUS_SKIPPED


# ── empty-frame / bounds guards ──────────────────────────────────────────────


def test_apply_on_empty_frame_does_not_raise() -> None:
    empty = pd.DataFrame()
    out, status = apply_scaling(empty, ["a"], "minmax")
    assert status["status"] == STATUS_SKIPPED
    assert out.empty


def test_is_large_frame_and_preview_bounds() -> None:
    assert is_large_frame(_DF) is False
    assert len(preview_frame(_DF, rows=2)) == 2


# ── replay engine ────────────────────────────────────────────────────────────


def test_apply_recipe_replays_steps_in_order() -> None:
    steps = [
        make_recipe_step("type_cast", ["num_str"], {"target_type": "numeric"}),
        make_recipe_step("drop_duplicates", [], {}),
    ]
    out, executed = apply_recipe(_DF, steps)
    assert [s["status"] for s in executed] == [STATUS_APPLIED, STATUS_APPLIED]
    assert pd.api.types.is_numeric_dtype(out["num_str"])
    # each executed step carries before/after facts
    assert all(s["before"] is not None and s["after"] is not None for s in executed)


def test_apply_recipe_does_not_mutate_input_steps() -> None:
    steps = [make_recipe_step("scaling", ["n"], {"strategy": "minmax"})]
    apply_recipe(_DF, steps)
    assert steps[0]["status"] == "pending"  # original untouched
    assert steps[0]["before"] is None


def test_apply_recipe_unknown_operation_is_skipped() -> None:
    steps = [make_recipe_step("totally_unknown", ["n"], {})]
    out, executed = apply_recipe(_DF, steps)
    assert executed[0]["status"] == STATUS_SKIPPED
    pd.testing.assert_frame_equal(out, _DF)


def test_apply_recipe_error_is_isolated() -> None:
    # bad param type forces an internal failure that must be caught, not raised
    steps = [
        make_recipe_step("encoding", ["cat"], {"strategy": "one_hot", "max_cardinality": "bad"})
    ]
    out, executed = apply_recipe(_DF, steps)
    assert executed[0]["status"] == STATUS_ERROR
    assert executed[0]["warning"]


# ── generated-output collision safety ────────────────────────────────────────

# Every column a transformation below would generate already exists and carries
# sentinel values, so a silent overwrite is visible rather than merely plausible.
_PROTECTED = pd.DataFrame(
    {
        "age": [1.0, 2.0, 3.0, 100.0],
        "age__outlier": ["keep-a", "keep-b", "keep-c", "keep-d"],
        "city": ["x", "y", "x", "y"],
        "city__freq": [-1, -2, -3, -4],
        "city__label": [-5, -6, -7, -8],
        "comment": ["ab", "cde", "f", "ghij"],
        "comment__text_length": [-9, -9, -9, -9],
        "when": ["2020-01-02", "2021-03-04", "2022-05-06", "2023-07-08"],
        "when__year": [-11, -12, -13, -14],
    }
)

_ApplyCall = Callable[[pd.DataFrame], tuple[pd.DataFrame, dict[str, Any]]]


def _refused(status: dict[str, Any]) -> bool:
    return status["status"] == STATUS_ERROR and OUTPUT_COLLISION in (status["warning"] or "")


def _iqr_flag(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    return apply_iqr_outlier_strategy(df, ["age"], "flag")


def _frequency(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    return apply_encoding(df, ["city"], "frequency")


def _label(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    return apply_encoding(df, ["city"], "label")


def _derived_year(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    return apply_safe_derived_column(df, "when", "year")


def _derived_text_length(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    return apply_safe_derived_column(df, "comment", "text_length")


@pytest.mark.parametrize(
    ("call", "destination"),
    [
        # The original collision report: flagging "age" destroyed the user's
        # age__outlier column without a warning of any kind.
        (_iqr_flag, "age__outlier"),
        (_frequency, "city__freq"),
        (_label, "city__label"),
        (_derived_year, "when__year"),
        (_derived_text_length, "comment__text_length"),
    ],
)
def test_generated_output_collision_is_refused_and_preserves_the_column(
    call: _ApplyCall, destination: str
) -> None:
    out, status = call(_PROTECTED)
    assert _refused(status)
    assert destination in (status["warning"] or "")
    # The refusal is total: the whole frame, sentinels included, is untouched.
    pd.testing.assert_frame_equal(out, _PROTECTED)


def test_collision_diagnostics_name_no_source_value() -> None:
    _out, status = _iqr_flag(_PROTECTED)
    warning = status["warning"] or ""
    assert "keep-a" not in warning
    assert "100.0" not in warning


# One-hot destinations depend on the values present, so only execution can know
# that expanding "c" would land on the user's existing "c_a".
_ONE_HOT_FRAME = pd.DataFrame({"c": ["a", "a", "b", "b"], "c_a": [10, 20, 30, 40]})


def test_one_hot_collision_with_an_existing_column_is_refused() -> None:
    out, status = apply_encoding(_ONE_HOT_FRAME, ["c"], "one_hot")
    assert _refused(status)
    assert "c_a" in (status["warning"] or "")
    pd.testing.assert_frame_equal(out, _ONE_HOT_FRAME)
    # The pre-fix defect duplicated the label rather than only replacing values.
    assert list(out.columns).count("c_a") == 1


def test_one_hot_collision_between_two_generated_outputs_is_refused() -> None:
    # Expanding "p" emits "p_q_r"; expanding "p_q" emits "p_q_r" as well.
    frame = pd.DataFrame({"p": ["q_r", "q_r"], "p_q": ["r", "s"]})
    out, status = apply_encoding(frame, ["p", "p_q"], "one_hot")
    assert _refused(status)
    assert "p_q_r" in (status["warning"] or "")
    pd.testing.assert_frame_equal(out, frame)


def test_multi_output_operation_refuses_atomically() -> None:
    frame = pd.DataFrame(
        {
            "safe": [1.0, 2.0, 3.0, 50.0],
            "age": [1.0, 2.0, 3.0, 100.0],
            "age__outlier": ["keep", "keep", "keep", "keep"],
        }
    )
    out, status = apply_iqr_outlier_strategy(frame, ["safe", "age"], "flag")
    assert _refused(status)
    # The non-colliding sibling output is not written either.
    assert "safe__outlier" not in out.columns
    pd.testing.assert_frame_equal(out, frame)


def test_one_hot_refusal_writes_no_partial_dummy_and_keeps_the_source() -> None:
    frame = pd.DataFrame({"c": ["a", "b"], "c_a": [1, 2], "n": [1.0, 2.0]})
    out, status = apply_encoding(frame, ["c"], "one_hot")
    assert _refused(status)
    assert "c_b" not in out.columns  # no subset of the dummy set was committed
    assert "c" in out.columns  # the source the expansion would consume survives
    pd.testing.assert_frame_equal(out, frame)


def test_non_colliding_generated_outputs_still_apply() -> None:
    flagged, status = apply_iqr_outlier_strategy(_DF, ["n"], "flag")
    assert status["status"] == STATUS_APPLIED
    assert flagged["n__outlier"].tolist() == [False, False, False, False, True]

    counted, status = apply_encoding(_DF, ["cat"], "frequency")
    assert status["status"] == STATUS_APPLIED
    assert counted["cat__freq"].tolist() == [3, 2, 3, 2, 3]

    dummies, status = apply_encoding(_DF, ["cat"], "one_hot")
    assert status["status"] == STATUS_APPLIED
    assert {"cat_a", "cat_b"}.issubset(dummies.columns)


def test_in_place_type_cast_still_rewrites_its_selected_column() -> None:
    out, status = apply_type_cast(_PROTECTED, ["age"], "string")
    assert status["status"] == STATUS_APPLIED
    assert out["age"].dtype == "string"
    # Rewriting "age" grants no permission over the unrelated "age__outlier".
    assert out["age__outlier"].tolist() == _PROTECTED["age__outlier"].tolist()


def test_in_place_scaling_still_rewrites_its_selected_column() -> None:
    out, status = apply_scaling(_PROTECTED, ["age"], "minmax")
    assert status["status"] == STATUS_APPLIED
    assert out["age"].tolist() == [0.0, 1.0 / 99.0, 2.0 / 99.0, 1.0]
    assert out["age__outlier"].tolist() == _PROTECTED["age__outlier"].tolist()


def test_row_only_drop_duplicates_is_unchanged() -> None:
    frame = pd.DataFrame({"a": [1, 1, 2], "a__outlier": ["s", "s", "t"]})
    out, status = apply_drop_duplicates(frame)
    assert status["status"] == STATUS_APPLIED
    assert len(out) == 2
    assert out["a__outlier"].tolist() == ["s", "t"]


def test_missing_value_behaviour_is_unchanged() -> None:
    frame = pd.DataFrame({"a": [1.0, None, 3.0], "a__outlier": ["s", "t", "u"]})
    out, status = apply_missing_value_strategy(frame, ["a"], "median")
    assert status["status"] == STATUS_APPLIED
    assert out["a"].tolist() == [1.0, 2.0, 3.0]
    assert out["a__outlier"].tolist() == ["s", "t", "u"]


def test_iqr_clip_and_remove_create_no_destination_to_collide_with() -> None:
    clipped, status = apply_iqr_outlier_strategy(_PROTECTED, ["age"], "clip")
    assert status["status"] == STATUS_APPLIED
    assert clipped["age__outlier"].tolist() == _PROTECTED["age__outlier"].tolist()

    removed, status = apply_iqr_outlier_strategy(_PROTECTED, ["age"], "remove")
    assert status["status"] == STATUS_APPLIED
    assert removed["age__outlier"].tolist() == ["keep-a", "keep-b", "keep-c"]


def test_derived_unknown_kind_is_still_skipped_not_refused() -> None:
    out, status = apply_safe_derived_column(_PROTECTED, "when", "century")
    assert status["status"] == STATUS_SKIPPED
    pd.testing.assert_frame_equal(out, _PROTECTED)


def test_collision_inside_a_recipe_is_recorded_as_an_error_step() -> None:
    steps = [
        make_recipe_step("scaling", ["age"], {"strategy": "minmax"}),
        make_recipe_step("iqr_outlier", ["age"], {"strategy": "flag"}),
        make_recipe_step("drop_duplicates", [], {}),
    ]
    out, executed = apply_recipe(_PROTECTED, steps)
    assert [step["status"] for step in executed] == [
        STATUS_APPLIED,
        STATUS_ERROR,
        STATUS_APPLIED,
    ]
    assert OUTPUT_COLLISION in executed[1]["warning"]
    # The refused step contributed nothing to the frame the replay carried on with.
    assert out["age__outlier"].tolist() == _PROTECTED["age__outlier"].tolist()
    assert list(out.columns) == list(_PROTECTED.columns)


# ── deterministic destination names shared with recipe admission ─────────────


@pytest.mark.parametrize(
    ("operation", "columns", "parameters", "expected"),
    [
        ("iqr_outlier", ["age"], {"strategy": "flag"}, ["age__outlier"]),
        ("iqr_outlier", ["age"], {"strategy": "clip"}, []),
        ("iqr_outlier", ["age"], {"strategy": "remove"}, []),
        ("encoding", ["city"], {"strategy": "frequency"}, ["city__freq"]),
        ("encoding", ["city"], {"strategy": "label"}, ["city__label"]),
        # Value-dependent: admission is told nothing execution alone can prove.
        ("encoding", ["city"], {"strategy": "one_hot"}, []),
        ("derived_column", [], {"source_column": "w", "derived_kind": "year"}, ["w__year"]),
        (
            "derived_column",
            [],
            {"source_column": "c", "derived_kind": "text_length"},
            ["c__text_length"],
        ),
        ("derived_column", [], {"source_column": "c", "derived_kind": "bogus"}, []),
        ("type_cast", ["age"], {"target_type": "numeric"}, []),
        ("scaling", ["age"], {"strategy": "minmax"}, []),
        ("drop_duplicates", [], {}, []),
        ("totally_unknown", ["age"], {}, []),
    ],
)
def test_deterministic_output_names(
    operation: str, columns: list[str], parameters: dict[str, Any], expected: list[str]
) -> None:
    assert deterministic_output_names(operation, columns, parameters) == expected
