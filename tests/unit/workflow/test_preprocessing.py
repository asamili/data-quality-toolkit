"""Unit tests for data_quality_toolkit.workflow.preprocessing."""

from __future__ import annotations

import pandas as pd

from data_quality_toolkit.workflow.preprocessing import iqr_outlier_summary, plan_preprocessing

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
