"""Focused tests for the dependency-free P0 EDA summaries."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.eda import (
    _aggregate_iqr_outlier_summary,
    _bounded_scatter_data,
    _categorical_top_frequency_data,
    _correlation_heatmap_data,
    _correlation_matrix,
    _dataset_profile,
    _datetime_trend_data,
    _dtype_distribution,
    _duplicate_row_summary,
    _missingness_bar_data,
    _missingness_summary,
    _numeric_by_category_summary_data,
    _numeric_distribution,
    _numeric_histogram_data,
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


def test_numeric_histogram_builder_returns_status_and_bins() -> None:
    df = pd.DataFrame({"n": [float(i) for i in range(1, 11)]})

    result = _numeric_histogram_data(df, "n", bins=4)

    assert result["status"] == "ok"
    data = result["data"]
    assert data.columns.tolist() == ["bin", "count", "left", "right"]
    assert data["count"].sum() == 10
    assert result["effective_bins"] == 4


def test_numeric_histogram_builder_invalid_type_status() -> None:
    result = _numeric_histogram_data(pd.DataFrame({"c": ["a", "b"]}), "c")

    assert result["status"] == "invalid_type"
    assert result["data"].empty


def test_categorical_top_frequency_builder_respects_top_n_and_missing_bucket() -> None:
    df = pd.DataFrame({"c": ["a", "a", "b", None, "c", "d"]})

    result = _categorical_top_frequency_data(df, "c", n=2, include_missing=True)

    assert result["status"] == "ok"
    assert result["top_n"] == 2
    assert result["data"]["category"].tolist() == ["a", "(missing)"]
    assert result["data"]["count"].tolist() == [2, 1]


def test_missingness_bar_builder_returns_percentages() -> None:
    df = pd.DataFrame({"full": [1, 2], "half": [None, 2]})

    result = _missingness_bar_data(df)

    assert result["status"] == "ok"
    data = result["data"]
    assert data.loc[data["column"] == "half", "missing_pct"].iloc[0] == 50.0


def test_correlation_heatmap_builder_returns_long_form_and_caps_columns() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": [2, 4, 6], "c": [3, 6, 9]})

    result = _correlation_heatmap_data(df, max_columns=2)

    assert result["status"] == "ok"
    assert result["truncated"] is True
    data = result["data"]
    assert data.columns.tolist() == ["x", "y", "correlation"]
    assert len(data) == 4


def test_bounded_scatter_builder_samples_deterministically() -> None:
    df = pd.DataFrame({"a": range(20), "b": range(20, 40)})

    first = _bounded_scatter_data(df, "a", "b", max_rows=5, seed=7)
    second = _bounded_scatter_data(df, "a", "b", max_rows=5, seed=7)

    assert first["status"] == "ok"
    assert first["sampled"] is True
    assert first["source_rows"] == 20
    assert len(first["data"]) == 5
    assert first["data"].equals(second["data"])


def test_numeric_by_category_summary_caps_high_cardinality_categories() -> None:
    df = pd.DataFrame({"n": range(30), "c": [f"cat-{i}" for i in range(30)]})

    result = _numeric_by_category_summary_data(df, "n", "c", max_categories=5)

    assert result["status"] == "ok"
    assert result["truncated"] is True
    assert len(result["data"]) == 5
    assert {"q1", "q3", "median"} <= set(result["data"].columns)


def test_datetime_trend_builder_requires_parse_confidence() -> None:
    df = pd.DataFrame(
        {
            "ts": ["2025-01-01", "not-a-date", "also-bad", "2025-01-02"],
            "n": [1.0, 2.0, 3.0, 4.0],
        }
    )

    result = _datetime_trend_data(df, "ts", "n", parse_threshold=0.75)

    assert result["status"] == "low_parse_confidence"
    assert result["data"].empty


def test_datetime_trend_builder_returns_daily_metric_when_confident() -> None:
    df = pd.DataFrame(
        {
            "ts": ["2025-01-01", "2025-01-01", "2025-01-02"],
            "n": [1.0, 3.0, 5.0],
        }
    )

    result = _datetime_trend_data(df, "ts", "n")

    assert result["status"] == "ok"
    assert result["metric"] == "n"
    assert result["data"]["value"].tolist() == [2.0, 5.0]


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
    assert st.bar_chart.call_count == 2
    st.vega_lite_chart.assert_called_once()


# ---------------------------------------------------------------------------
# Managed root-first dispatch: managed source and fail-closed behavior
# ---------------------------------------------------------------------------

from data_quality_toolkit.adapters.ui.pages.eda_explorer import (  # noqa: E402
    _MANAGED_FAIL_CLOSED_MESSAGE,
    _render_eda_explorer,
)
from data_quality_toolkit.adapters.ui.services import managed_frame_loader as _mfl  # noqa: E402
from data_quality_toolkit.adapters.ui.services.managed_trust import (  # noqa: E402
    commit_trust_root,
    ensure_session_capability,
    make_source_locator,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext  # noqa: E402
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT  # noqa: E402

_EDA_PAGE = "data_quality_toolkit.adapters.ui.pages.eda_explorer"
_MANAGED_ABS = "C:\\workspace\\versions\\v1\\data.csv"
_EDA_TAB_RENDERERS = (
    f"{_EDA_PAGE}.render_overview_tab",
    f"{_EDA_PAGE}.render_columns_tab",
    f"{_EDA_PAGE}.render_relationships_tab",
    f"{_EDA_PAGE}.render_time_tab",
    f"{_EDA_PAGE}.render_advanced_tab",
)


@pytest.fixture(autouse=True)
def _clean_managed_caches() -> Any:
    _mfl.clear_managed_caches()
    yield
    _mfl.clear_managed_caches()


def _trusted_eda_session(*, large: bool = False) -> dict[str, Any]:
    state: dict[str, Any] = {}
    capability = ensure_session_capability(state)
    commit_trust_root(
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
            absolute_path=_MANAGED_ABS,
        ),
        size_bytes=2048,
        modified_ns=10,
        large_file_mode=large,
    )
    return state


def _managed_mirror_only_session() -> dict[str, Any]:
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


def _eda_st() -> MagicMock:
    st = MagicMock()
    st.columns.side_effect = lambda count: [st for _ in range(count)]
    st.tabs.side_effect = lambda labels: [MagicMock() for _ in labels]
    st.text_input.return_value = ""
    return st


def test_managed_full_eda_dispatches_through_managed_loader() -> None:
    st = _eda_st()
    session = _trusted_eda_session()
    frame = pd.DataFrame({"a": [1, 2]})
    envelope = {"profile": {"rows": 2, "cols": 1, "memory_mb": 0.0, "columns": []}}
    with (
        patch(f"{_EDA_PAGE}.get_managed_frame", return_value=frame) as mock_frame,
        patch(f"{_EDA_PAGE}.get_managed_assessment", return_value=envelope) as mock_assess,
        patch(f"{_EDA_PAGE}._load_df_and_assess") as mock_legacy,
        patch(_EDA_TAB_RENDERERS[0]) as mock_overview,
        patch(_EDA_TAB_RENDERERS[1]),
        patch(_EDA_TAB_RENDERERS[2]),
        patch(_EDA_TAB_RENDERERS[3]),
        patch(_EDA_TAB_RENDERERS[4]),
    ):
        _render_eda_explorer(st, session)
    mock_frame.assert_called_once()
    mock_assess.assert_called_once()
    mock_legacy.assert_not_called()
    mock_overview.assert_called_once()
    assert mock_overview.call_args[0][1] is frame


def test_managed_mirror_without_trust_fails_closed_in_eda() -> None:
    st = _eda_st()
    session = _managed_mirror_only_session()
    with (
        patch(f"{_EDA_PAGE}.get_managed_frame") as mock_frame,
        patch(f"{_EDA_PAGE}._load_df_and_assess") as mock_legacy,
        patch(_EDA_TAB_RENDERERS[0]) as mock_overview,
    ):
        _render_eda_explorer(st, session)
    mock_frame.assert_not_called()
    mock_legacy.assert_not_called()
    mock_overview.assert_not_called()
    st.error.assert_called()
    error_text = " ".join(str(arg) for call in st.error.call_args_list for arg in call.args)
    assert _MANAGED_FAIL_CLOSED_MESSAGE in error_text


def test_managed_large_eda_refuses_frame_materialization() -> None:
    st = _eda_st()
    session = _trusted_eda_session(large=True)
    with (
        patch(f"{_EDA_PAGE}.get_managed_frame") as mock_frame,
        patch(f"{_EDA_PAGE}._load_df_and_assess") as mock_legacy,
    ):
        _render_eda_explorer(st, session)
    mock_frame.assert_not_called()
    mock_legacy.assert_not_called()
    st.warning.assert_called()
    st.tabs.assert_not_called()


def test_manual_path_cannot_override_valid_trust_in_eda() -> None:
    st = _eda_st()
    st.text_input.return_value = "C:/manual/other.csv"
    session = _trusted_eda_session()
    frame = pd.DataFrame({"a": [1]})
    with (
        patch(f"{_EDA_PAGE}.get_managed_frame", return_value=frame) as mock_frame,
        patch(f"{_EDA_PAGE}.get_managed_assessment", return_value={"profile": None}),
        patch(f"{_EDA_PAGE}._load_df_and_assess") as mock_legacy,
        patch(_EDA_TAB_RENDERERS[0]),
        patch(_EDA_TAB_RENDERERS[1]),
        patch(_EDA_TAB_RENDERERS[2]),
        patch(_EDA_TAB_RENDERERS[3]),
        patch(_EDA_TAB_RENDERERS[4]),
    ):
        _render_eda_explorer(st, session)
    mock_frame.assert_called_once()
    mock_legacy.assert_not_called()
    st.text_input.assert_not_called()  # manual override input never rendered


def test_managed_loader_refusal_shows_privacy_safe_error() -> None:
    st = _eda_st()
    session = _trusted_eda_session()
    refusal = _mfl.ManagedFrameLoadError("SOURCE_MISSING")
    with (
        patch(f"{_EDA_PAGE}.get_managed_frame", side_effect=refusal),
        patch(_EDA_TAB_RENDERERS[0]) as mock_overview,
    ):
        _render_eda_explorer(st, session)
    mock_overview.assert_not_called()
    st.error.assert_called()
    error_text = " ".join(str(arg) for call in st.error.call_args_list for arg in call.args)
    assert _MANAGED_ABS not in error_text
    assert "C:\\workspace" not in error_text


def test_unmanaged_eda_flow_unchanged_without_trust() -> None:
    st = _eda_st()
    st.text_input.return_value = "data.csv"
    frame = pd.DataFrame({"a": [1]})
    with (
        patch(
            f"{_EDA_PAGE}._load_df_and_assess", return_value=(frame, {"profile": None}, None)
        ) as mock_legacy,
        patch(f"{_EDA_PAGE}.get_managed_frame") as mock_frame,
        patch(_EDA_TAB_RENDERERS[0]) as mock_overview,
        patch(_EDA_TAB_RENDERERS[1]),
        patch(_EDA_TAB_RENDERERS[2]),
        patch(_EDA_TAB_RENDERERS[3]),
        patch(_EDA_TAB_RENDERERS[4]),
    ):
        _render_eda_explorer(st, {})
    mock_legacy.assert_called_once()
    mock_frame.assert_not_called()
    mock_overview.assert_called_once()
