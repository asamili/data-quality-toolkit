"""Unit tests for data_quality_toolkit.application.workflow.preprocessing."""

from __future__ import annotations

import json

import pandas as pd

from data_quality_toolkit.application.workflow.preprocessing import (
    RECIPE_SCHEMA_VERSION,
    STATUS_PENDING,
    frame_facts,
    iqr_outlier_summary,
    make_recipe_step,
    plan_preprocessing,
    recipe_to_json_payload,
    summarize_before_after,
)

# ---------------------------------------------------------------------------
# iqr_outlier_summary
# ---------------------------------------------------------------------------


def test_iqr_summary_returns_expected_fields() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0, 5.0]})
    result = iqr_outlier_summary(df, "n")
    assert result is not None
    assert {"q1", "q3", "iqr", "lower_fence", "upper_fence", "outlier_count"} <= result.keys()


def test_iqr_summary_detects_outlier() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0, 1000.0]})
    result = iqr_outlier_summary(df, "n")
    assert result is not None
    assert result["outlier_count"] >= 1


def test_iqr_summary_returns_none_for_non_numeric() -> None:
    df = pd.DataFrame({"s": ["a", "b", "c", "d"]})
    assert iqr_outlier_summary(df, "s") is None


def test_iqr_summary_returns_none_for_insufficient_values() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0]})
    assert iqr_outlier_summary(df, "n") is None


# ---------------------------------------------------------------------------
# plan_preprocessing — shape and output contract
# ---------------------------------------------------------------------------


def test_plan_returns_empty_for_empty_dataframe() -> None:
    assert plan_preprocessing(pd.DataFrame()) == []


def test_plan_returns_one_row_per_column() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    plan = plan_preprocessing(df)
    assert len(plan) == 2


def test_plan_row_has_required_keys() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0]})
    row = plan_preprocessing(df)[0]
    assert {"column", "dtype", "issues", "recommendations"} <= row.keys()


def test_plan_output_is_json_serializable() -> None:
    import json

    df = pd.DataFrame({"a": [1, None, 3], "b": ["x", "y", "z"]})
    plan = plan_preprocessing(df)
    # must not raise
    json.dumps(plan)


# ---------------------------------------------------------------------------
# plan_preprocessing — issue / recommendation logic
# ---------------------------------------------------------------------------


def test_plan_high_null_recommends_drop() -> None:
    data = [None] * 6 + [1.0] * 4
    df = pd.DataFrame({"n": data})
    plan = plan_preprocessing(df)
    assert "drop or flag column" in plan[0]["recommendations"]


def test_plan_moderate_null_numeric_recommends_median_impute() -> None:
    df = pd.DataFrame({"n": [1.0, None, 3.0, 4.0, 5.0]})
    plan = plan_preprocessing(df)
    assert "impute with median" in plan[0]["recommendations"]


def test_plan_moderate_null_categorical_recommends_mode_impute() -> None:
    df = pd.DataFrame({"s": ["a", None, "b", "b", "c"]})
    plan = plan_preprocessing(df)
    assert "impute with mode" in plan[0]["recommendations"]


def test_plan_high_cardinality_string_recommends_hash_encode() -> None:
    vals = [str(i) for i in range(100)]
    df = pd.DataFrame({"s": vals})
    plan = plan_preprocessing(df)
    assert "hash-encode" in plan[0]["recommendations"]


def test_plan_numeric_always_recommends_scaling() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0, 5.0]})
    plan = plan_preprocessing(df)
    assert "consider scaling" in plan[0]["recommendations"]


def test_plan_clean_column_has_no_issues() -> None:
    df = pd.DataFrame({"s": ["a", "b", "a", "b", "a"]})
    plan = plan_preprocessing(df)
    assert plan[0]["issues"] == "none"


def test_plan_numeric_with_outlier_recommends_outlier_treatment() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0, 1000.0]})
    plan = plan_preprocessing(df)
    assert "consider outlier treatment" in plan[0]["recommendations"]


# ---------------------------------------------------------------------------
# recipe model — make_recipe_step
# ---------------------------------------------------------------------------


def test_make_recipe_step_has_required_keys() -> None:
    step = make_recipe_step("type_cast", ["a"], {"target_type": "numeric"})
    assert {
        "step_id",
        "operation",
        "columns",
        "parameters",
        "before",
        "after",
        "status",
        "warning",
    } <= step.keys()
    assert step["status"] == STATUS_PENDING
    assert step["before"] is None and step["after"] is None
    assert step["warning"] is None


def test_make_recipe_step_is_deterministic() -> None:
    a = make_recipe_step("scaling", ["x", "y"], {"strategy": "minmax"})
    b = make_recipe_step("scaling", ["x", "y"], {"strategy": "minmax"})
    assert a["step_id"] == b["step_id"]


def test_make_recipe_step_id_changes_with_params() -> None:
    a = make_recipe_step("scaling", ["x"], {"strategy": "minmax"})
    b = make_recipe_step("scaling", ["x"], {"strategy": "zscore"})
    assert a["step_id"] != b["step_id"]


def test_make_recipe_step_normalizes_columns_to_strings() -> None:
    step = make_recipe_step("missing_value", [1, 2], {"strategy": "drop"})
    assert step["columns"] == ["1", "2"]


# ---------------------------------------------------------------------------
# recipe model — frame_facts / summarize_before_after
# ---------------------------------------------------------------------------


def test_frame_facts_counts_rows_columns_and_missing() -> None:
    df = pd.DataFrame({"a": [1, None, 3], "b": ["x", "y", "z"]})
    facts = frame_facts(df)
    assert facts["row_count"] == 3
    assert facts["column_count"] == 2
    assert facts["missing_cells"] == 1
    assert 0.0 <= facts["completeness"] <= 1.0


def test_frame_facts_handles_empty_frame() -> None:
    facts = frame_facts(pd.DataFrame())
    assert facts["row_count"] == 0
    assert facts["column_count"] == 0
    assert facts["completeness"] == 1.0


def test_summarize_before_after_reports_row_and_dtype_changes() -> None:
    before = pd.DataFrame({"a": ["1", "2", "2"], "b": [1, 2, 2]})
    after = before.drop_duplicates().copy()
    after["a"] = after["a"].astype("Int64")
    summary = summarize_before_after(before, after)
    assert summary["before"]["row_count"] == 3
    assert summary["after"]["row_count"] == 2
    assert "a" in summary["dtype_changes"]
    assert summary["dtype_changes"]["a"]["from"] != summary["dtype_changes"]["a"]["to"]


def test_summarize_before_after_tracks_added_and_removed_columns() -> None:
    before = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    after = pd.DataFrame({"a": [1, 2], "c": [5, 6]})
    summary = summarize_before_after(before, after)
    assert summary["added_columns"] == ["c"]
    assert summary["removed_columns"] == ["b"]


# ---------------------------------------------------------------------------
# recipe model — recipe_to_json_payload
# ---------------------------------------------------------------------------


def test_recipe_to_json_payload_is_json_serializable() -> None:
    steps = [make_recipe_step("scaling", ["x"], {"strategy": "minmax"})]
    summary = summarize_before_after(pd.DataFrame({"x": [1, 2]}), pd.DataFrame({"x": [0.0, 1.0]}))
    payload = recipe_to_json_payload(steps, summary)
    assert payload["schema_version"] == RECIPE_SCHEMA_VERSION
    assert len(payload["steps"]) == 1
    # must not raise
    json.dumps(payload)


def test_recipe_to_json_payload_is_deterministic_without_summary() -> None:
    steps = [make_recipe_step("drop_duplicates", [], {})]
    first = recipe_to_json_payload(steps)
    second = recipe_to_json_payload(steps)
    assert json.dumps(first) == json.dumps(second)
    assert first["summary"] is None
