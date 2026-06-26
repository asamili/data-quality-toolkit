"""Focused tests for the dependency-free P0 EDA summaries."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.eda import (
    _aggregate_iqr_outlier_summary,
    _correlation_matrix,
    _dataset_profile,
    _dtype_distribution,
    _duplicate_row_summary,
    _missingness_summary,
    _numeric_distribution,
)
from data_quality_toolkit.adapters.ui.pages.eda_explorer import (
    _render_correlation_matrix,
    _render_dataset_profile,
    _render_dtype_distribution,
    _render_duplicate_rows,
    _render_missingness,
    _render_outlier_summary,
)


def test_dataset_profile_reuses_supplied_profiler_facts() -> None:
    df = pd.DataFrame({"a": [1.0, None]})

    result = _dataset_profile(df, {"rows": 10, "cols": 4, "memory_mb": 1.234})

    assert result == {"rows": 10, "columns": 4, "missing_cells": 1, "memory_mb": 1.23}


def test_missingness_summary_is_sorted_and_bounded() -> None:
    df = pd.DataFrame({"complete": [1, 2], "missing": [None, 2], "later": [None, None]})

    result = _missingness_summary(df, max_columns=2)

    assert result["column"].tolist() == ["missing", "complete"]
    assert result["missing_pct"].tolist() == [50.0, 0.0]


def test_duplicate_summary_is_aggregate_only() -> None:
    df = pd.DataFrame({"id": [1, 1, 2], "label": ["a", "a", "b"]})

    result = _duplicate_row_summary(df)

    assert result == {
        "total_rows": 3,
        "duplicate_rows": 1,
        "unique_rows": 2,
        "duplicate_pct": pytest.approx(33.33),
    }


def test_dtype_distribution_counts_column_types() -> None:
    df = pd.DataFrame({"a": [1], "b": [2], "label": ["x"]})

    result = _dtype_distribution(df)

    assert result["column_count"].sum() == 3
    assert result.loc[result["dtype"] == "int64", "column_count"].iloc[0] == 2


def test_correlation_matrix_is_bounded_and_ignores_infinity() -> None:
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, float("inf")],
            "b": [2.0, 4.0, 6.0],
            "c": [3.0, 6.0, 9.0],
        }
    )

    result = _correlation_matrix(df, max_columns=2)

    assert result is not None
    assert result.columns.tolist() == ["a", "b"]
    assert result.loc["a", "b"] == pytest.approx(1.0)


def test_aggregate_iqr_summary_covers_numeric_columns_and_caps_width() -> None:
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 100.0],
            "b": [1.0, 1.0, 1.0, 1.0, 1.0],
        }
    )

    result = _aggregate_iqr_outlier_summary(df, max_columns=1)

    assert result["column"].tolist() == ["a"]
    assert result.loc[0, "outlier_count"] == 1


def test_numeric_distribution_handles_infinity_and_bounds_bins() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, float("inf")]})

    result = _numeric_distribution(df, "n", bins=1000)

    assert result is not None
    assert result["count"].sum() == 3
    assert len(result) <= 50


def test_p0_renderers_use_streamlit_native_tables_and_charts() -> None:
    st = MagicMock()
    st.columns.side_effect = lambda count: [st for _ in range(count)]
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 100.0],
            "b": [2.0, 4.0, 6.0, 8.0, 10.0],
            "label": ["x", "x", None, "y", "z"],
        }
    )

    _render_dataset_profile(st, df)
    _render_missingness(st, df)
    _render_duplicate_rows(st, df)
    _render_dtype_distribution(st, df)
    _render_correlation_matrix(st, df)
    _render_outlier_summary(st, df)

    headings = [call.args[0] for call in st.subheader.call_args_list]
    assert headings == [
        "Dataset profile",
        "Missingness",
        "Duplicate rows",
        "Data types",
        "Correlation matrix",
        "Outlier summary",
    ]
    assert st.metric.call_count == 7
    assert st.dataframe.call_count == 4
    st.bar_chart.assert_called_once()
