"""Tests for the Preprocess Studio transform engine (adapters/ui/services/preprocessing)."""

from __future__ import annotations

import inspect

import pandas as pd

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
    is_large_frame,
    preview_frame,
)
from data_quality_toolkit.application.workflow.preprocessing import (
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
