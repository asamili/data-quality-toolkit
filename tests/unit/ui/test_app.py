"""Unit tests for the dashboard UI helpers (eda + services) and the app shell.

No live Streamlit required. Helper functions moved from app.py into
adapters/ui/services during the G1 UI restructure; imports point at their
canonical homes.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from data_quality_toolkit.adapters.storage.connection import StorageError
from data_quality_toolkit.adapters.ui.eda import (
    _bivariate_categorical_categorical,
    _bivariate_numeric_categorical,
    _bivariate_numeric_numeric,
    _build_overview_table,
    _build_trend_df,
    _categorical_top_values,
    _duplicate_row_count,
    _extract_latest_issues,
    _extract_trend_data,
    _high_cardinality_flags,
    _iqr_outlier_summary,
    _load_df_and_assess,
    _numeric_distribution,
    _numeric_summary,
    _plan_preprocessing,
)
from data_quality_toolkit.adapters.ui.services.assessment import (
    _load_run_history,
    _run_assess_csv,
)
from data_quality_toolkit.adapters.ui.services.export import _export_csv_to_dir
from data_quality_toolkit.adapters.ui.services.kpi import (
    _generate_dim_time_csv,
    _kpi_emit_to_bytes,
    _kpi_graph_to_str,
    _run_kpi_validate,
)


def test_module_imports_without_streamlit() -> None:
    """app module must be importable when Streamlit is absent (deferred import)."""
    import data_quality_toolkit.adapters.ui.app as _cached

    real_st = sys.modules.get("streamlit")
    sys.modules["streamlit"] = None  # type: ignore[assignment]
    try:
        del sys.modules["data_quality_toolkit.adapters.ui.app"]
        mod = importlib.import_module("data_quality_toolkit.adapters.ui.app")
        assert callable(mod.main)
    finally:
        if real_st is not None:
            sys.modules["streamlit"] = real_st
        else:
            sys.modules.pop("streamlit", None)
        sys.modules["data_quality_toolkit.adapters.ui.app"] = _cached


def test_main_is_callable() -> None:
    import data_quality_toolkit.adapters.ui.app as app

    assert callable(app.main)


def test_load_run_history_missing_db_returns_empty(tmp_path: Path) -> None:
    records, err = _load_run_history(str(tmp_path / "nonexistent.db"), "ds1")
    assert records == []
    assert err is None


def test_load_run_history_storage_error_returns_message(tmp_path: Path) -> None:
    with patch(
        "data_quality_toolkit.adapters.ui.services.assessment.read_run_history",
        side_effect=StorageError("db corrupt"),
    ):
        records, err = _load_run_history(str(tmp_path / "some.db"), "ds1")
    assert records is None
    assert err is not None
    assert "db corrupt" in err


def test_load_run_history_strips_input_whitespace(tmp_path: Path) -> None:
    path_with_spaces = "  " + str(tmp_path / "nonexistent.db") + "  "
    records, err = _load_run_history(path_with_spaces, " ds1 ")
    assert records == []
    assert err is None


def test_extract_trend_data_normal() -> None:
    records = [
        {"ts": "2025-01-01T00:00:00", "score": 0.9, "rows": 100},
        {"ts": "2025-01-02T00:00:00", "score": 0.85, "rows": 200},
    ]
    result = _extract_trend_data(records)
    assert result == [
        {"ts": "2025-01-01T00:00:00", "score": 0.9},
        {"ts": "2025-01-02T00:00:00", "score": 0.85},
    ]


def test_extract_trend_data_skips_missing_score() -> None:
    records: list[dict[str, Any]] = [
        {"ts": "2025-01-01T00:00:00", "score": None},
        {"ts": "2025-01-02T00:00:00", "score": 0.8},
    ]
    result = _extract_trend_data(records)
    assert len(result) == 1
    assert result[0]["score"] == pytest.approx(0.8)


def test_extract_trend_data_skips_missing_ts() -> None:
    records: list[dict[str, Any]] = [
        {"ts": None, "score": 0.9},
        {"ts": "2025-01-02T00:00:00", "score": 0.8},
    ]
    result = _extract_trend_data(records)
    assert len(result) == 1
    assert result[0]["ts"] == "2025-01-02T00:00:00"


def test_extract_trend_data_empty_input() -> None:
    assert _extract_trend_data([]) == []


def test_extract_trend_data_preserves_input_order() -> None:
    records = [
        {"ts": "2025-01-03T00:00:00", "score": 0.7},
        {"ts": "2025-01-01T00:00:00", "score": 0.9},
        {"ts": "2025-01-02T00:00:00", "score": 0.8},
    ]
    result = _extract_trend_data(records)
    assert [r["ts"] for r in result] == [
        "2025-01-03T00:00:00",
        "2025-01-01T00:00:00",
        "2025-01-02T00:00:00",
    ]


def test_build_trend_df_returns_dataframe_with_ts_index() -> None:
    trend = [
        {"ts": "2025-01-01T00:00:00", "score": 0.9},
        {"ts": "2025-01-02T00:00:00", "score": 0.8},
    ]
    df = _build_trend_df(trend)
    assert df is not None
    assert list(df.columns) == ["Score"]
    assert pd.api.types.is_datetime64_any_dtype(df.index)
    assert len(df) == 2


def test_build_trend_df_drops_unparseable_ts() -> None:
    trend = [
        {"ts": "not-a-date", "score": 0.9},
        {"ts": "2025-01-02T00:00:00", "score": 0.8},
    ]
    df = _build_trend_df(trend)
    assert df is not None
    assert len(df) == 1


def test_build_trend_df_returns_none_when_all_ts_invalid() -> None:
    trend = [{"ts": "bad", "score": 0.9}, {"ts": "also-bad", "score": 0.8}]
    assert _build_trend_df(trend) is None


def test_build_trend_df_returns_none_on_empty_input() -> None:
    assert _build_trend_df([]) is None


def test_extract_latest_issues_returns_both_dicts() -> None:
    records = [
        {"issues_by_severity": {"warning": 1}, "issues_by_category": {"schema": 2}},
        {"issues_by_severity": {"critical": 3}, "issues_by_category": {"data": 4}},
    ]
    sev, cat = _extract_latest_issues(records)
    assert sev == {"critical": 3}
    assert cat == {"data": 4}


def test_extract_latest_issues_missing_fields_return_empty_dicts() -> None:
    records = [{"score": 0.9}]
    sev, cat = _extract_latest_issues(records)
    assert sev == {}
    assert cat == {}


def test_extract_latest_issues_uses_last_record() -> None:
    records = [
        {"issues_by_severity": {"warning": 1}, "issues_by_category": {}},
        {"issues_by_severity": {"critical": 5}, "issues_by_category": {"data": 2}},
    ]
    sev, _ = _extract_latest_issues(records)
    assert sev == {"critical": 5}


def test_app_has_script_entrypoint() -> None:
    """app.py must have if __name__ == '__main__': main() so streamlit run invokes UI."""
    import ast
    import inspect

    import data_quality_toolkit.adapters.ui.app as app_mod

    src = Path(inspect.getfile(app_mod)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    has_guard = any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        and any(
            isinstance(c, ast.Constant) and c.value == "__main__" for c in node.test.comparators
        )
        for node in tree.body
    )
    assert (
        has_guard
    ), "app.py is missing if __name__ == '__main__': main() — streamlit run will show a blank page"


def test_build_overview_table_includes_all_fields() -> None:
    profile = {
        "rows": 10,
        "cols": 2,
        "columns": [
            {"name": "a", "dtype": "int64", "nulls": 2, "unique": 8, "min": 1.0, "max": 9.0},
            {"name": "b", "dtype": "object", "nulls": 0, "unique": 3},
        ],
    }
    table = _build_overview_table(profile)
    assert table[0] == {
        "column": "a",
        "dtype": "int64",
        "nulls": 2,
        "null_pct": 20.0,
        "unique": 8,
        "min": 1.0,
        "max": 9.0,
    }
    assert table[1]["null_pct"] == 0.0
    assert table[1]["min"] is None
    assert table[1]["max"] is None


def test_build_overview_table_zero_rows_null_pct_safe() -> None:
    profile = {
        "rows": 0,
        "columns": [{"name": "a", "dtype": "object", "nulls": 0, "unique": 0}],
    }
    table = _build_overview_table(profile)
    assert table[0]["null_pct"] == 0.0


def test_build_overview_table_empty_columns() -> None:
    assert _build_overview_table({"rows": 5, "columns": []}) == []


def test_numeric_summary_returns_describe_for_numeric() -> None:
    df = pd.DataFrame({"n": [1, 2, 3], "s": ["x", "y", "z"]})
    summary = _numeric_summary(df)
    assert summary is not None
    assert "n" in summary.columns
    assert "s" not in summary.columns


def test_numeric_summary_none_when_no_numeric_columns() -> None:
    df = pd.DataFrame({"s": ["x", "y"]})
    assert _numeric_summary(df) is None


def test_duplicate_row_count_counts_repeats() -> None:
    df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
    assert _duplicate_row_count(df) == 1


def test_duplicate_row_count_zero_when_unique() -> None:
    df = pd.DataFrame({"a": [1, 2, 3]})
    assert _duplicate_row_count(df) == 0


def test_high_cardinality_flags_flags_unique_columns() -> None:
    profile = {
        "rows": 10,
        "columns": [
            {"name": "id", "unique": 10},
            {"name": "cat", "unique": 2},
        ],
    }
    assert _high_cardinality_flags(profile) == ["id"]


def test_high_cardinality_flags_empty_when_zero_rows() -> None:
    profile = {"rows": 0, "columns": [{"name": "id", "unique": 0}]}
    assert _high_cardinality_flags(profile) == []


def test_high_cardinality_flags_empty_when_no_columns() -> None:
    assert _high_cardinality_flags({"rows": 5, "columns": []}) == []


# ── _numeric_distribution ─────────────────────────────────────────────────────


def test_numeric_distribution_returns_dataframe_with_count_column() -> None:
    df = pd.DataFrame({"n": [float(i) for i in range(1, 11)]})
    result = _numeric_distribution(df, "n")
    assert result is not None
    assert "count" in result.columns
    assert len(result) > 0
    assert result.index.dtype == object  # string bin labels


def test_numeric_distribution_returns_none_for_non_numeric() -> None:
    df = pd.DataFrame({"s": ["a", "b", "c"]})
    assert _numeric_distribution(df, "s") is None


def test_numeric_distribution_returns_none_for_single_value() -> None:
    df = pd.DataFrame({"n": [5.0]})
    assert _numeric_distribution(df, "n") is None


def test_numeric_distribution_returns_none_for_all_same_values() -> None:
    df = pd.DataFrame({"n": [3.0, 3.0, 3.0, 3.0]})
    assert _numeric_distribution(df, "n") is None


# ── _categorical_top_values ───────────────────────────────────────────────────


def test_categorical_top_values_returns_count_dataframe() -> None:
    df = pd.DataFrame({"c": ["a", "b", "a", "c", "a"]})
    result = _categorical_top_values(df, "c")
    assert result is not None
    assert "count" in result.columns
    assert result.loc["a", "count"] == 3


def test_categorical_top_values_returns_none_for_numeric() -> None:
    df = pd.DataFrame({"n": [1, 2, 3]})
    assert _categorical_top_values(df, "n") is None


def test_categorical_top_values_respects_n_limit() -> None:
    df = pd.DataFrame({"c": [str(i) for i in range(25)]})
    result = _categorical_top_values(df, "c", n=5)
    assert result is not None
    assert len(result) == 5


def test_categorical_top_values_returns_none_for_empty_series() -> None:
    df = pd.DataFrame({"c": pd.Series([], dtype="object")})
    assert _categorical_top_values(df, "c") is None


# ── _iqr_outlier_summary ──────────────────────────────────────────────────────


def test_iqr_outlier_summary_returns_correct_fields() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0, 5.0]})
    result = _iqr_outlier_summary(df, "n")
    assert result is not None
    assert set(result.keys()) == {"q1", "q3", "iqr", "lower_fence", "upper_fence", "outlier_count"}
    assert result["q1"] == pytest.approx(2.0)
    assert result["q3"] == pytest.approx(4.0)
    assert result["iqr"] == pytest.approx(2.0)
    assert result["outlier_count"] == 0


def test_iqr_outlier_summary_detects_outliers() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0, 5.0, 100.0]})
    result = _iqr_outlier_summary(df, "n")
    assert result is not None
    assert result["outlier_count"] >= 1


def test_iqr_outlier_summary_returns_none_for_non_numeric() -> None:
    df = pd.DataFrame({"s": ["a", "b", "c", "d", "e"]})
    assert _iqr_outlier_summary(df, "s") is None


def test_iqr_outlier_summary_returns_none_for_insufficient_values() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0]})
    assert _iqr_outlier_summary(df, "n") is None


# ── _bivariate_numeric_numeric ────────────────────────────────────────────────


def test_bivariate_numeric_numeric_returns_scatter_df_and_r() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [2.0, 4.0, 6.0, 8.0]})
    scatter_df, r = _bivariate_numeric_numeric(df, "a", "b")
    assert scatter_df is not None
    assert list(scatter_df.columns) == ["a", "b"]
    assert len(scatter_df) == 4
    assert r is not None
    assert r == pytest.approx(1.0)


def test_bivariate_numeric_numeric_returns_none_for_non_numeric_column() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "s": ["x", "y", "z"]})
    scatter_df, r = _bivariate_numeric_numeric(df, "a", "s")
    assert scatter_df is None
    assert r is None


def test_bivariate_numeric_numeric_returns_none_for_insufficient_rows() -> None:
    df = pd.DataFrame({"a": [1.0], "b": [2.0]})
    scatter_df, r = _bivariate_numeric_numeric(df, "a", "b")
    assert scatter_df is None
    assert r is None


def test_bivariate_numeric_numeric_returns_none_for_all_same_values_in_one_col() -> None:
    df = pd.DataFrame({"a": [3.0, 3.0, 3.0], "b": [1.0, 2.0, 3.0]})
    scatter_df, r = _bivariate_numeric_numeric(df, "a", "b")
    assert scatter_df is None
    assert r is None


# ── _bivariate_numeric_categorical ────────────────────────────────────────────


def test_bivariate_numeric_categorical_returns_grouped_stats() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0], "c": ["a", "a", "b", "b"]})
    result = _bivariate_numeric_categorical(df, "n", "c")
    assert result is not None
    assert "count" in result.columns
    assert "mean" in result.columns
    assert "median" in result.columns
    assert result.loc["a", "count"] == 2


def test_bivariate_numeric_categorical_returns_none_when_numeric_col_is_string() -> None:
    df = pd.DataFrame({"s": ["x", "y"], "c": ["a", "b"]})
    assert _bivariate_numeric_categorical(df, "s", "c") is None


def test_bivariate_numeric_categorical_returns_none_when_categorical_col_is_numeric() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0], "m": [3.0, 4.0]})
    assert _bivariate_numeric_categorical(df, "n", "m") is None


def test_bivariate_numeric_categorical_returns_none_for_empty_series() -> None:
    df = pd.DataFrame({"n": pd.Series([], dtype="float64"), "c": pd.Series([], dtype="object")})
    assert _bivariate_numeric_categorical(df, "n", "c") is None


# ── _bivariate_categorical_categorical ────────────────────────────────────────


def test_bivariate_categorical_categorical_returns_crosstab() -> None:
    df = pd.DataFrame({"a": ["x", "x", "y"], "b": ["p", "q", "p"]})
    result = _bivariate_categorical_categorical(df, "a", "b")
    assert result is not None
    assert result.loc["x", "p"] == 1
    assert result.loc["x", "q"] == 1


def test_bivariate_categorical_categorical_returns_none_when_col_is_numeric() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0], "c": ["a", "b"]})
    assert _bivariate_categorical_categorical(df, "n", "c") is None


def test_bivariate_categorical_categorical_returns_none_for_empty_df() -> None:
    df = pd.DataFrame({"a": pd.Series([], dtype="object"), "b": pd.Series([], dtype="object")})
    assert _bivariate_categorical_categorical(df, "a", "b") is None


def test_bivariate_categorical_categorical_shape_matches_unique_value_counts() -> None:
    df = pd.DataFrame({"a": ["x", "y", "x"], "b": ["p", "p", "q"]})
    result = _bivariate_categorical_categorical(df, "a", "b")
    assert result is not None
    assert result.shape == (2, 2)


# ── _plan_preprocessing ───────────────────────────────────────────────────────


def test_plan_preprocessing_empty_dataframe_returns_empty_list() -> None:
    assert _plan_preprocessing(pd.DataFrame()) == []


def test_plan_preprocessing_returns_one_row_per_column() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"], "c": [1.0, 2.0, 3.0]})
    plan = _plan_preprocessing(df)
    assert len(plan) == 3
    assert [r["column"] for r in plan] == ["a", "b", "c"]


def test_plan_preprocessing_high_null_recommends_drop() -> None:
    df = pd.DataFrame({"a": [1, None, None, None, None, None]})
    plan = _plan_preprocessing(df)
    assert "drop or flag column" in plan[0]["recommendations"]


def test_plan_preprocessing_moderate_null_numeric_recommends_median_impute() -> None:
    df = pd.DataFrame({"n": [1.0, None, 3.0, 4.0, 5.0]})
    plan = _plan_preprocessing(df)
    assert "impute with median" in plan[0]["recommendations"]


def test_plan_preprocessing_moderate_null_categorical_recommends_mode_impute() -> None:
    df = pd.DataFrame({"c": ["a", None, "b", "c", "d"]})
    plan = _plan_preprocessing(df)
    assert "impute with mode" in plan[0]["recommendations"]


def test_plan_preprocessing_high_cardinality_recommends_hash_encode() -> None:
    df = pd.DataFrame({"id": [str(i) for i in range(10)]})
    plan = _plan_preprocessing(df)
    assert "drop or hash-encode" in plan[0]["recommendations"]


def test_plan_preprocessing_numeric_always_recommends_scaling() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0, 5.0]})
    plan = _plan_preprocessing(df)
    assert "consider scaling" in plan[0]["recommendations"]


def test_plan_preprocessing_numeric_with_outliers_recommends_treatment() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0, 100.0]})
    plan = _plan_preprocessing(df)
    assert "consider outlier treatment" in plan[0]["recommendations"]


def test_plan_preprocessing_clean_categorical_no_issues() -> None:
    df = pd.DataFrame({"c": ["a", "b", "a", "b", "a"]})
    plan = _plan_preprocessing(df)
    assert plan[0]["issues"] == "none"
    assert "label or one-hot encode" in plan[0]["recommendations"]


# ── _run_assess_csv ───────────────────────────────────────────────────────────

_FAKE_ASSESS_OUT: dict = {
    "run_id": "r1",
    "dataset_id": "sha1:abc",
    "ts": "2025-01-01T00:00:00Z",
    "meta": {},
    "profile": {"rows": 3, "cols": 2, "memory_mb": 0.01, "columns": []},
    "assessment": {"score": 0.9, "issues": [], "run_id": "r1", "dataset_id": "sha1:abc", "ts": ""},
}


def test_run_assess_csv_success() -> None:
    with patch(
        "data_quality_toolkit.adapters.ui.services.assessment._assess_csv",
        return_value=_FAKE_ASSESS_OUT,
    ):
        out, err = _run_assess_csv("data.csv")
    assert err is None
    assert out is not None
    assert out["assessment"]["score"] == pytest.approx(0.9)
    assert out["profile"]["rows"] == 3


def test_run_assess_csv_file_not_found() -> None:
    with patch(
        "data_quality_toolkit.adapters.ui.services.assessment._assess_csv",
        side_effect=FileNotFoundError("data.csv not found"),
    ):
        out, err = _run_assess_csv("data.csv")
    assert out is None
    assert err is not None
    assert "not found" in err


def test_run_assess_csv_value_error() -> None:
    with patch(
        "data_quality_toolkit.adapters.ui.services.assessment._assess_csv",
        side_effect=ValueError("empty or has no columns"),
    ):
        out, err = _run_assess_csv("empty.csv")
    assert out is None
    assert err is not None
    assert "empty" in err


def test_run_assess_csv_strips_whitespace() -> None:
    with patch(
        "data_quality_toolkit.adapters.ui.services.assessment._assess_csv",
        return_value=_FAKE_ASSESS_OUT,
    ) as mock:
        _run_assess_csv("  data.csv  ")
    mock.assert_called_once_with("data.csv")


# ── _load_df_and_assess ───────────────────────────────────────────────────────

_FAKE_DF = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
_FAKE_META = {"dataset_id": "sha1:abc", "source_path": "data.csv", "rows": 3, "cols": 2}
_FAKE_PROF = {
    "run_id": "r1",
    "dataset_id": "sha1:abc",
    "ts": "2025-01-01T00:00:00Z",
    "rows": 3,
    "cols": 2,
    "memory_mb": 0.01,
    "columns": [],
}
_FAKE_INNER_ASSESSMENT = {
    "score": 0.9,
    "issues": [],
    "run_id": "r1",
    "dataset_id": "sha1:abc",
    "ts": "",
}

_LOAD_CSV_H = "data_quality_toolkit.adapters.loaders.file.csv_loader.load_csv"
_RUN_PROF = "data_quality_toolkit.domain.profiling.profiling_orchestrator.run_profiling"
_ASSESS = "data_quality_toolkit.domain.assessment.quality_checker.assess"


def test_load_df_and_assess_success() -> None:
    with (
        patch(_LOAD_CSV_H, return_value=(_FAKE_DF, _FAKE_META)),
        patch(_RUN_PROF, return_value=_FAKE_PROF),
        patch(_ASSESS, return_value=_FAKE_INNER_ASSESSMENT),
    ):
        df, result, err = _load_df_and_assess("data.csv")
    assert err is None
    assert df is not None
    assert result is not None
    assert result["assessment"]["score"] == pytest.approx(0.9)
    assert result["profile"]["rows"] == 3
    assert result["dataset_id"] == "sha1:abc"


def test_load_df_and_assess_file_not_found() -> None:
    with patch(_LOAD_CSV_H, side_effect=FileNotFoundError("data.csv not found")):
        df, result, err = _load_df_and_assess("data.csv")
    assert df is None
    assert result is None
    assert err is not None
    assert "not found" in err


def test_load_df_and_assess_value_error() -> None:
    with patch(_LOAD_CSV_H, side_effect=ValueError("empty or has no columns")):
        df, result, err = _load_df_and_assess("empty.csv")
    assert df is None
    assert result is None
    assert err is not None
    assert "empty" in err


def test_load_df_and_assess_strips_whitespace() -> None:
    with (
        patch(_LOAD_CSV_H, return_value=(_FAKE_DF, _FAKE_META)) as mock_load,
        patch(_RUN_PROF, return_value=_FAKE_PROF),
        patch(_ASSESS, return_value=_FAKE_INNER_ASSESSMENT),
    ):
        _load_df_and_assess("  data.csv  ")
    mock_load.assert_called_once_with("data.csv")


def test_load_df_and_assess_result_has_profile_and_assessment() -> None:
    with (
        patch(_LOAD_CSV_H, return_value=(_FAKE_DF, _FAKE_META)),
        patch(_RUN_PROF, return_value=_FAKE_PROF),
        patch(_ASSESS, return_value=_FAKE_INNER_ASSESSMENT),
    ):
        df, result, err = _load_df_and_assess("data.csv")
    assert err is None
    assert result is not None
    assert "profile" in result
    assert "assessment" in result
    assert df is not None
    assert len(df) == 3


# ── _run_kpi_validate ─────────────────────────────────────────────────────────

_REAL_CATALOG = "config/kpi_catalog.yaml"


def test_run_kpi_validate_valid_catalog() -> None:
    result, err = _run_kpi_validate(_REAL_CATALOG)
    assert err is None
    assert result is not None
    assert result["status"] == "valid"
    assert result["kpis"] > 0


def test_run_kpi_validate_missing_file_returns_error() -> None:
    result, err = _run_kpi_validate("nonexistent/catalog.yaml")
    assert result is None
    assert err is not None
    assert len(err) > 0


def test_run_kpi_validate_strips_whitespace() -> None:
    result, err = _run_kpi_validate("  " + _REAL_CATALOG + "  ")
    assert err is None
    assert result is not None
    assert result["status"] == "valid"


# ── _generate_dim_time_csv ────────────────────────────────────────────────────


def test_generate_dim_time_csv_returns_csv_string() -> None:
    csv_str, row_count, err = _generate_dim_time_csv("2024-01-01", "2024-01-05")
    assert err is None
    assert row_count == 5
    assert csv_str is not None
    assert "date_key" in csv_str or len(csv_str) > 0


def test_generate_dim_time_csv_bad_dates_returns_error() -> None:
    csv_str, row_count, err = _generate_dim_time_csv("not-a-date", "also-bad")
    assert csv_str is None
    assert row_count is None
    assert err is not None


def test_generate_dim_time_csv_with_fiscal_year() -> None:
    csv_str, row_count, err = _generate_dim_time_csv(
        "2024-01-01", "2024-01-03", week_start=1, fiscal_year_start=7
    )
    assert err is None
    assert row_count == 3
    assert csv_str is not None


# ── _kpi_emit_to_bytes ────────────────────────────────────────────────────────


def test_kpi_emit_to_bytes_returns_dax_and_tmsl() -> None:
    dax_bytes, tmsl_bytes, err = _kpi_emit_to_bytes(_REAL_CATALOG)
    assert err is None
    assert dax_bytes is not None and len(dax_bytes) > 0
    assert tmsl_bytes is not None and len(tmsl_bytes) > 0


def test_kpi_emit_to_bytes_missing_catalog_returns_error() -> None:
    dax_bytes, tmsl_bytes, err = _kpi_emit_to_bytes("nonexistent/catalog.yaml")
    assert dax_bytes is None
    assert tmsl_bytes is None
    assert err is not None


# ── _kpi_graph_to_str ─────────────────────────────────────────────────────────


def test_kpi_graph_to_str_returns_mermaid_content() -> None:
    content, err = _kpi_graph_to_str(_REAL_CATALOG, graph_format="mermaid")
    assert err is None
    assert content is not None
    assert len(content) > 0


def test_kpi_graph_to_str_returns_graphviz_content() -> None:
    content, err = _kpi_graph_to_str(_REAL_CATALOG, graph_format="graphviz")
    assert err is None
    assert content is not None
    assert len(content) > 0


def test_kpi_graph_to_str_missing_catalog_returns_error() -> None:
    content, err = _kpi_graph_to_str("nonexistent/catalog.yaml")
    assert content is None
    assert err is not None


# ── _export_csv_to_dir ────────────────────────────────────────────────────────


def test_export_csv_to_dir_relative_path_returns_error() -> None:
    result, err = _export_csv_to_dir("/data/test.csv", "relative/path")
    assert result is None
    assert err is not None
    assert "absolute" in err.lower()


def test_export_csv_to_dir_traversal_path_returns_error() -> None:
    result, err = _export_csv_to_dir("/data/test.csv", "/safe/../etc")
    assert result is None
    assert err is not None
    assert ".." in err or "traversal" in err.lower()


def test_export_csv_to_dir_valid_path_calls_export_csv(tmp_path: Path) -> None:
    out_dir = tmp_path / "export_out"
    fake_result: dict = {"export_paths": {"dim_dataset": str(out_dir / "star/dim_dataset.csv")}}
    with patch("data_quality_toolkit.api.export_csv", return_value=fake_result) as mock_exp:
        result, err = _export_csv_to_dir("/data/test.csv", str(out_dir))
    assert err is None
    assert result == fake_result
    mock_exp.assert_called_once()
    assert out_dir.exists()


def test_export_csv_to_dir_export_error_returns_error(tmp_path: Path) -> None:
    out_dir = tmp_path / "export_err_dir"
    with patch(
        "data_quality_toolkit.api.export_csv",
        side_effect=RuntimeError("csv parse failed"),
    ):
        result, err = _export_csv_to_dir("/data/test.csv", str(out_dir))
    assert result is None
    assert err is not None
    assert "csv parse failed" in err
