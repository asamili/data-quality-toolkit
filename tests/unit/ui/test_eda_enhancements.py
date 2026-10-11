"""Focused tests for the Wave 2 EDA additions (shape, boxplot, density, corr methods)."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.eda import (
    CORRELATION_METHODS,
    DEFAULT_DENSITY_BINS,
    DEFAULT_HISTOGRAM_BINS,
    MAX_DENSITY_BINS,
    MAX_HISTOGRAM_BINS,
    MAX_PLOT_ROWS,
    MIN_DENSITY_BINS,
    MIN_HISTOGRAM_BINS,
    _auto_histogram_bins,
    _bounded_density_heatmap_data,
    _bounded_scatter_data,
    _boxplot_data,
    _categorical_crosstab_data,
    _categorical_crosstab_heatmap_data,
    _categorical_top_frequency_data,
    _correlation_heatmap_data,
    _correlation_matrix,
    _datetime_categorical_counts_data,
    _datetime_numeric_aggregation_data,
    _datetime_trend_data,
    _density_curve_data,
    _linear_trendline_data,
    _numeric_ecdf_data,
    _numeric_histogram_data,
    _percentile_domain,
    _skew_kurtosis_summary,
)

# ── skewness / kurtosis ──────────────────────────────────────────────────────


def test_skew_kurtosis_summary_reports_numeric_columns_only() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0, 4.0, 5.0], "c": ["a", "b", "c", "d", "e"]})
    summary = _skew_kurtosis_summary(df)
    assert summary["column"].tolist() == ["n"]
    assert summary.columns.tolist() == ["column", "count", "skewness", "kurtosis"]
    assert summary.loc[0, "skewness"] is not None


def test_skew_kurtosis_kurtosis_none_when_too_few_values() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0]})  # 3 values: skew ok, kurtosis undefined
    summary = _skew_kurtosis_summary(df)
    assert summary.loc[0, "kurtosis"] is None


def test_skew_kurtosis_empty_for_no_numeric_columns() -> None:
    df = pd.DataFrame({"c": ["a", "b"]})
    assert _skew_kurtosis_summary(df).empty


# ── boxplot ──────────────────────────────────────────────────────────────────


def test_boxplot_data_returns_bounded_values() -> None:
    df = pd.DataFrame({"n": [float(i) for i in range(10)]})
    result = _boxplot_data(df, "n", max_rows=5)
    assert result["status"] == "ok"
    assert result["sampled"] is True
    assert result["source_rows"] == 10
    assert list(result["data"].columns) == ["value"]
    assert len(result["data"]) == 5


def test_boxplot_data_rejects_non_numeric() -> None:
    df = pd.DataFrame({"c": ["a", "b"]})
    assert _boxplot_data(df, "c")["status"] == "invalid_type"


# ── density curve ────────────────────────────────────────────────────────────


def test_density_curve_returns_value_and_density_columns() -> None:
    df = pd.DataFrame({"n": [float(i) for i in range(1, 21)]})
    result = _density_curve_data(df, "n", bins=5)
    assert result["status"] == "ok"
    assert list(result["data"].columns) == ["value", "density"]
    assert (result["data"]["density"] >= 0).all()


def test_density_curve_insufficient_for_constant_column() -> None:
    df = pd.DataFrame({"n": [3.0, 3.0, 3.0, 3.0]})
    assert _density_curve_data(df, "n")["status"] != "ok"


# ── correlation methods ──────────────────────────────────────────────────────


def test_correlation_methods_constant_lists_three() -> None:
    assert CORRELATION_METHODS == ("pearson", "spearman", "kendall")


def test_spearman_and_kendall_detect_monotonic_nonlinear() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [1.0, 4.0, 9.0, 16.0]})
    spearman = _correlation_matrix(df, method="spearman")
    kendall = _correlation_matrix(df, method="kendall")
    assert spearman is not None and kendall is not None
    assert spearman.loc["a", "b"] == pytest.approx(1.0)
    assert kendall.loc["a", "b"] == pytest.approx(1.0)


def test_kendall_falls_back_without_scipy_and_matches_native() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [1.0, 4.0, 9.0, 16.0]})
    native = _correlation_matrix(df, method="kendall")
    with patch("data_quality_toolkit.adapters.ui.eda._scipy_available", return_value=False):
        fallback = _correlation_matrix(df, method="kendall")
    assert native is not None and fallback is not None
    assert fallback.loc["a", "b"] == pytest.approx(1.0)
    assert fallback.loc["a", "b"] == pytest.approx(native.loc["a", "b"])


def test_unknown_method_falls_back_to_pearson() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [1.0, 4.0, 9.0, 16.0]})
    fallback = _correlation_matrix(df, method="bogus")
    pearson = _correlation_matrix(df, method="pearson")
    assert fallback is not None and pearson is not None
    assert fallback.loc["a", "b"] == pearson.loc["a", "b"]


def test_correlation_heatmap_echoes_selected_method() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": [2, 4, 6], "c": [3, 6, 9]})
    result = _correlation_heatmap_data(df, method="spearman")
    assert result["status"] == "ok"
    assert result["method"] == "spearman"


# ── correlation column selection and ranked pairs (P2) ───────────────────────


def test_correlation_default_selection_matches_legacy_first_n_behavior() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0], "c": [1.0, 4.0, 9.0]})
    legacy = _correlation_matrix(df, max_columns=2)
    with_default = _correlation_matrix(df, max_columns=2, columns=None)
    assert legacy is not None and with_default is not None
    pd.testing.assert_frame_equal(legacy, with_default)


def test_correlation_matrix_narrows_to_an_explicit_column_selection() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0], "c": [1.0, 4.0, 9.0]})
    matrix = _correlation_matrix(df, columns=["a", "c"])
    assert matrix is not None
    assert list(matrix.columns) == ["a", "c"]


def test_correlation_heatmap_long_form_columns_are_unchanged() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": [2, 4, 6]})
    result = _correlation_heatmap_data(df)
    assert list(result["data"].columns) == ["x", "y", "correlation"]
    assert len(result["data"]) == 4  # 2x2 matrix in long form


def test_correlation_heatmap_handles_columns_literally_named_x_and_y() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [3.0, 2.0, 1.0]})
    result = _correlation_heatmap_data(df)
    assert result["status"] == "ok"
    assert set(result["data"]["x"]) == {"x", "y"}


def test_correlation_heatmap_exposes_ranked_pairs_without_diagonal() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0], "c": [1.0, 4.0, 9.0]})
    pairs = _correlation_heatmap_data(df)["pairs"]
    assert list(pairs.columns) == ["column_x", "column_y", "correlation", "abs_correlation"]
    assert len(pairs) == 3
    assert (pairs["column_x"] != pairs["column_y"]).all()
    assert pairs["abs_correlation"].tolist() == sorted(
        pairs["abs_correlation"].tolist(), reverse=True
    )


def test_correlation_ranked_pairs_survive_a_constant_column() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "flat": [5.0, 5.0, 5.0]})
    result = _correlation_heatmap_data(df)
    assert result["status"] == "ok"
    assert result["pairs"].empty  # the only pair is undefined, not fabricated


# ── auto histogram bins ─────────────────────────────────────────────────────


def test_auto_histogram_bins_fd_path_returns_bounded_count() -> None:
    series = pd.Series([float(i) for i in range(100)])
    bins = _auto_histogram_bins(series)
    assert isinstance(bins, int)
    assert MIN_HISTOGRAM_BINS <= bins <= MAX_HISTOGRAM_BINS


def test_auto_histogram_bins_zero_iqr_falls_back_to_sqrt() -> None:
    # q1 == q3 == 1 → IQR 0 → sqrt fallback: ceil(sqrt(9)) == 3.
    series = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0])
    assert _auto_histogram_bins(series) == 3


def test_auto_histogram_bins_clamps_to_max() -> None:
    # Dense cluster + far outlier → tiny FD bin width over a huge span → clamp.
    series = pd.Series([i / 1000 for i in range(1000)] + [100000.0])
    assert _auto_histogram_bins(series) == MAX_HISTOGRAM_BINS


def test_auto_histogram_bins_fewer_than_two_values_returns_default() -> None:
    assert _auto_histogram_bins(pd.Series([1.0])) == DEFAULT_HISTOGRAM_BINS
    assert _auto_histogram_bins(pd.Series([], dtype="float64")) == DEFAULT_HISTOGRAM_BINS


def test_auto_histogram_bins_ignores_inf_and_nan() -> None:
    series = pd.Series([1.0, 2.0, 3.0, 4.0, float("inf"), float("nan")])
    bins = _auto_histogram_bins(series)
    assert MIN_HISTOGRAM_BINS <= bins <= MAX_HISTOGRAM_BINS


def test_numeric_histogram_auto_path_returns_data_and_metadata() -> None:
    df = pd.DataFrame({"n": [float(i) for i in range(50)]})
    result = _numeric_histogram_data(df, "n", bins=None)
    assert result["status"] == "ok"
    assert result["auto"] is True
    assert result["requested_bins"] is None
    assert MIN_HISTOGRAM_BINS <= result["effective_bins"] <= MAX_HISTOGRAM_BINS
    assert result["data"]["count"].sum() == 50


def test_numeric_histogram_explicit_path_unchanged() -> None:
    df = pd.DataFrame({"n": [float(i) for i in range(1, 11)]})
    result = _numeric_histogram_data(df, "n", bins=4)
    assert result["auto"] is False
    assert result["requested_bins"] == 4
    assert result["effective_bins"] == 4


# ── categorical Other bucket ────────────────────────────────────────────────


def _cat_frame() -> pd.DataFrame:
    return pd.DataFrame({"c": ["a"] * 5 + ["b"] * 4 + ["c"] * 3 + ["d"] * 2 + ["e"] * 1})


def test_categorical_other_bucket_aggregates_remainder() -> None:
    result = _categorical_top_frequency_data(_cat_frame(), "c", n=2, other_bucket=True)
    assert result["status"] == "ok"
    assert result["data"]["category"].tolist() == ["a", "b", "(other)"]
    assert result["data"]["count"].tolist() == [5, 4, 6]  # other = 3 + 2 + 1
    assert result["other_count"] == 6
    assert result["data"]["count"].sum() == 15


def test_categorical_other_bucket_disabled_preserves_legacy() -> None:
    result = _categorical_top_frequency_data(_cat_frame(), "c", n=2, other_bucket=False)
    assert result["data"]["category"].tolist() == ["a", "b"]
    assert "(other)" not in result["data"]["category"].tolist()


def test_categorical_other_bucket_pct_sums_near_100() -> None:
    result = _categorical_top_frequency_data(_cat_frame(), "c", n=2, other_bucket=True)
    assert abs(float(result["data"]["pct"].sum()) - 100.0) < 0.5


def test_categorical_other_bucket_absent_when_not_truncated() -> None:
    df = pd.DataFrame({"c": ["a", "a", "b"]})
    result = _categorical_top_frequency_data(df, "c", n=5, other_bucket=True)
    assert "(other)" not in result["data"]["category"].tolist()
    assert result["other_count"] == 0


# ── datetime granularity + missing count ────────────────────────────────────


def _dt_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": ["2025-01-01", "2025-01-02", "2025-01-08", "2025-02-01"],
            "n": [1.0, 2.0, 3.0, 4.0],
        }
    )


def test_datetime_granularity_day_week_month_group_correctly() -> None:
    df = _dt_frame()
    day = _datetime_trend_data(df, "ts", "n", granularity="day")
    week = _datetime_trend_data(df, "ts", "n", granularity="week")
    month = _datetime_trend_data(df, "ts", "n", granularity="month")
    assert day["status"] == "ok" and len(day["data"]) == 4
    assert week["status"] == "ok" and len(week["data"]) == 3
    assert month["status"] == "ok" and len(month["data"]) == 2
    assert month["granularity"] == "month"


def test_datetime_missing_count_metadata_surfaced() -> None:
    df = pd.DataFrame(
        {"ts": ["2025-01-01", "bad", "2025-01-02", "2025-01-03"], "n": [1.0, 2.0, 3.0, 4.0]}
    )
    result = _datetime_trend_data(df, "ts", "n", parse_threshold=0.5)
    assert result["status"] == "ok"
    assert result["missing_datetime"] == 1


def test_datetime_invalid_granularity_falls_back_to_day() -> None:
    result = _datetime_trend_data(_dt_frame(), "ts", "n", granularity="bogus")
    assert result["status"] == "ok"
    assert result["granularity"] == "day"
    assert len(result["data"]) == 4


# ── percentile domain ───────────────────────────────────────────────────────


def test_percentile_domain_normal_case() -> None:
    domain = _percentile_domain(pd.Series([float(i) for i in range(1, 101)]))
    assert domain is not None
    low, high = domain
    assert low < high
    assert 0.0 < low < 5.0
    assert 95.0 < high < 100.0


def test_percentile_domain_handles_missing_and_inf() -> None:
    domain = _percentile_domain(pd.Series([1.0, 2.0, 3.0, 4.0, float("inf"), float("nan")]))
    assert domain is not None
    assert domain[0] < domain[1]


def test_percentile_domain_degenerate_returns_none() -> None:
    assert _percentile_domain(pd.Series([5.0] * 10)) is None  # low == high
    assert _percentile_domain(pd.Series([5.0])) is None  # < 2 usable
    assert _percentile_domain(pd.Series([], dtype="float64")) is None


# ── linear trend line ───────────────────────────────────────────────────────


def test_linear_trendline_returns_two_endpoints_for_linear_data() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [2.0, 4.0, 6.0, 8.0]})
    line = _linear_trendline_data(df, "x", "y")
    assert list(line.columns) == ["x", "y"]
    assert len(line) == 2
    assert line["x"].tolist() == [1.0, 4.0]
    assert line["y"].tolist() == [pytest.approx(2.0), pytest.approx(8.0)]


def test_linear_trendline_empty_on_insufficient_points() -> None:
    assert _linear_trendline_data(pd.DataFrame({"x": [1.0], "y": [2.0]}), "x", "y").empty


def test_linear_trendline_empty_on_constant_x() -> None:
    df = pd.DataFrame({"x": [3.0, 3.0, 3.0], "y": [1.0, 2.0, 3.0]})
    assert _linear_trendline_data(df, "x", "y").empty


def test_bounded_scatter_clip_and_trend_metadata() -> None:
    df = pd.DataFrame(
        {"a": [float(i) for i in range(1, 21)], "b": [float(i) * 2 for i in range(1, 21)]}
    )
    result = _bounded_scatter_data(df, "a", "b", clip=True, trend=True)
    assert result["status"] == "ok"
    assert result["x_domain"] is not None and result["x_domain"][0] < result["x_domain"][1]
    assert result["trendline_status"] == "ok"
    assert len(result["trendline"]) == 2


def test_bounded_scatter_default_has_no_clip_or_trend_keys() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [2.0, 4.0, 6.0, 8.0]})
    result = _bounded_scatter_data(df, "a", "b")
    assert "x_domain" not in result
    assert "trendline" not in result


# ── 2D binned-density heatmap ───────────────────────────────────────────────


def _density_df(n: int = 40) -> pd.DataFrame:
    return pd.DataFrame({"a": [float(i) for i in range(n)], "b": [float(i) * 2 for i in range(n)]})


def test_density_heatmap_long_form_columns_and_count_conservation() -> None:
    result = _bounded_density_heatmap_data(_density_df(), "a", "b", bins=10)
    assert result["status"] == "ok"
    assert list(result["data"].columns) == [
        "x_left",
        "x_right",
        "y_left",
        "y_right",
        "count",
        "density",
    ]
    # No sampling: every finite row is counted into the grid.
    assert int(result["data"]["count"].sum()) == result["source_rows"] == 40
    assert result["total_count"] == 40


def test_density_heatmap_density_is_share_summing_to_one() -> None:
    result = _bounded_density_heatmap_data(_density_df(), "a", "b", bins=10)
    assert result["data"]["density"].sum() == pytest.approx(1.0, abs=1e-3)


def test_density_heatmap_bins_clamped_and_cells_bounded() -> None:
    low = _bounded_density_heatmap_data(_density_df(), "a", "b", bins=1)
    high = _bounded_density_heatmap_data(_density_df(), "a", "b", bins=9999)
    assert low["bins_x"] == MIN_DENSITY_BINS
    assert high["bins_x"] == MAX_DENSITY_BINS
    assert high["cells"] == MAX_DENSITY_BINS * MAX_DENSITY_BINS
    assert high["nonzero_cells"] <= high["cells"]


def test_density_heatmap_is_deterministic() -> None:
    first = _bounded_density_heatmap_data(_density_df(), "a", "b", bins=12)
    second = _bounded_density_heatmap_data(_density_df(), "a", "b", bins=12)
    assert first["data"].equals(second["data"])


def test_density_heatmap_invalid_column_status() -> None:
    result = _bounded_density_heatmap_data(_density_df(), "a", "missing", bins=10)
    assert result["status"] == "invalid_column"
    assert result["data"].empty


def test_density_heatmap_invalid_type_status() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "c": ["x", "y", "z"]})
    result = _bounded_density_heatmap_data(df, "a", "c", bins=10)
    assert result["status"] == "invalid_type"
    assert result["data"].empty


def test_density_heatmap_constant_column_is_insufficient() -> None:
    df = pd.DataFrame({"a": [1.0, 1.0, 1.0, 1.0], "b": [2.0, 4.0, 6.0, 8.0]})
    result = _bounded_density_heatmap_data(df, "a", "b", bins=10)
    assert result["status"] == "insufficient_data"


def test_density_heatmap_ignores_nan_and_inf() -> None:
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, float("nan"), float("inf")],
            "b": [2.0, 4.0, 6.0, 8.0, 10.0, 12.0],
        }
    )
    result = _bounded_density_heatmap_data(df, "a", "b", bins=5)
    assert result["status"] == "ok"
    # NaN and inf rows are dropped before binning.
    assert result["source_rows"] == 4
    assert int(result["data"]["count"].sum()) == 4


def test_density_heatmap_clip_restricts_range_and_reports_domain() -> None:
    df = pd.DataFrame(
        {
            "a": [float(i) for i in range(100)] + [10_000.0],
            "b": [float(i) for i in range(100)] + [10_000.0],
        }
    )
    unclipped = _bounded_density_heatmap_data(df, "a", "b", bins=10)
    clipped = _bounded_density_heatmap_data(df, "a", "b", bins=10, clip=True)
    assert clipped["x_domain"] is not None and clipped["x_domain"][1] < 10_000.0
    # Clipping drops the far outlier from the counted total.
    assert clipped["total_count"] < unclipped["total_count"]


def test_density_heatmap_large_data_output_bounded_and_lossless() -> None:
    n = 50_000
    df = pd.DataFrame({"a": range(n), "b": range(n)})
    result = _bounded_density_heatmap_data(df, "a", "b", bins=MAX_DENSITY_BINS)
    assert result["status"] == "ok"
    assert result["cells"] == MAX_DENSITY_BINS * MAX_DENSITY_BINS
    assert result["nonzero_cells"] <= result["cells"]
    assert int(result["data"]["count"].sum()) == n


def test_density_heatmap_default_bins_constant() -> None:
    result = _bounded_density_heatmap_data(_density_df(), "a", "b")
    assert result["bins_x"] == DEFAULT_DENSITY_BINS


# ── categorical crosstab normalization ──────────────────────────────────────


def _crosstab_frame() -> pd.DataFrame:
    return pd.DataFrame({"x": ["a", "a", "b", "b"], "y": ["p", "q", "p", "q"]})


def test_crosstab_raw_default_unchanged() -> None:
    result = _categorical_crosstab_data(_crosstab_frame(), "x", "y")
    assert result["status"] == "ok"
    assert result["normalize"] == "none"
    assert int(result["data"].to_numpy().sum()) == 4  # raw counts


def test_crosstab_overall_normalization_sums_to_100() -> None:
    result = _categorical_crosstab_data(_crosstab_frame(), "x", "y", normalize="overall")
    assert result["normalize"] == "overall"
    assert float(result["data"].to_numpy().sum()) == pytest.approx(100.0)


def test_crosstab_row_normalization_rows_sum_to_100() -> None:
    result = _categorical_crosstab_data(_crosstab_frame(), "x", "y", normalize="row")
    row_sums = result["data"].sum(axis=1)
    assert all(v == pytest.approx(100.0) for v in row_sums)


def test_crosstab_column_normalization_columns_sum_to_100() -> None:
    result = _categorical_crosstab_data(_crosstab_frame(), "x", "y", normalize="column")
    col_sums = result["data"].sum(axis=0)
    assert all(v == pytest.approx(100.0) for v in col_sums)


# ── categorical crosstab heatmap ────────────────────────────────────────────


def test_crosstab_heatmap_long_form_columns_and_counts() -> None:
    result = _categorical_crosstab_heatmap_data(_crosstab_frame(), "x", "y")
    assert result["status"] == "ok"
    assert list(result["data"].columns) == ["feature_x", "feature_y", "value", "count"]
    assert len(result["data"]) == 4  # 2x2 cells
    assert int(result["data"]["count"].sum()) == 4
    # raw mode: value equals count.
    assert result["data"]["value"].tolist() == [1.0, 1.0, 1.0, 1.0]


def test_crosstab_heatmap_honors_normalization() -> None:
    result = _categorical_crosstab_heatmap_data(_crosstab_frame(), "x", "y", normalize="overall")
    assert result["normalize"] == "overall"
    assert float(result["data"]["value"].sum()) == pytest.approx(100.0)
    assert int(result["data"]["count"].sum()) == 4  # counts preserved alongside %


def test_crosstab_heatmap_no_raise_on_insufficient_data() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0], "c": ["a", "b", "c"]})
    result = _categorical_crosstab_heatmap_data(df, "n", "c")  # numeric x → invalid_type
    assert result["status"] != "ok"
    assert result["data"].empty


# ── datetime × numeric aggregation ──────────────────────────────────────────


def _dt_num_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": ["2025-01-01", "2025-01-01", "2025-01-02", "2025-02-01"],
            "n": [2.0, 4.0, 6.0, 8.0],
        }
    )


def test_dt_numeric_day_mean() -> None:
    result = _datetime_numeric_aggregation_data(_dt_num_frame(), "ts", "n", granularity="day")
    assert result["status"] == "ok"
    assert list(result["data"].columns) == ["period", "value", "aggregation", "count"]
    assert len(result["data"]) == 3  # 01-01, 01-02, 02-01
    assert result["data"]["value"].tolist() == [3.0, 6.0, 8.0]  # mean(2,4)=3
    assert (result["data"]["aggregation"] == "mean").all()


def test_dt_numeric_week_sum() -> None:
    result = _datetime_numeric_aggregation_data(
        _dt_num_frame(), "ts", "n", granularity="week", aggregation="sum"
    )
    assert result["status"] == "ok"
    assert result["aggregation"] == "sum"
    # 01-01,01-01,01-02 share one week (sum 12); 02-01 alone (8).
    assert result["data"]["value"].tolist() == [12.0, 8.0]


def test_dt_numeric_month_count() -> None:
    result = _datetime_numeric_aggregation_data(
        _dt_num_frame(), "ts", "n", granularity="month", aggregation="count"
    )
    assert result["status"] == "ok"
    assert result["data"]["count"].tolist() == [3, 1]  # Jan 3 obs, Feb 1
    assert result["data"]["value"].tolist() == [3.0, 1.0]  # count agg mirrors count


def test_dt_numeric_explicit_columns_direction() -> None:
    # Builder takes named columns; datetime is always the first positional regardless of df order.
    df = pd.DataFrame({"n": [2.0, 4.0, 6.0, 8.0], "ts": _dt_num_frame()["ts"]})
    result = _datetime_numeric_aggregation_data(df, "ts", "n", granularity="day")
    assert result["status"] == "ok"
    assert len(result["data"]) == 3


def test_dt_numeric_missing_datetime_metadata() -> None:
    df = pd.DataFrame(
        {"ts": ["2025-01-01", "bad", "2025-01-02", "2025-01-03"], "n": [1.0, 2.0, 3.0, 4.0]}
    )
    result = _datetime_numeric_aggregation_data(df, "ts", "n", parse_threshold=0.5)
    assert result["status"] == "ok"
    assert result["missing_datetime"] == 1


def test_dt_numeric_low_parse_confidence_safe() -> None:
    df = pd.DataFrame({"ts": ["2025-01-01", "bad", "nope", "x"], "n": [1.0, 2.0, 3.0, 4.0]})
    result = _datetime_numeric_aggregation_data(df, "ts", "n")
    assert result["status"] == "low_parse_confidence"
    assert result["data"].empty


def test_dt_numeric_unsupported_aggregation_safe() -> None:
    result = _datetime_numeric_aggregation_data(_dt_num_frame(), "ts", "n", aggregation="bogus")
    assert result["status"] == "invalid_aggregation"
    assert result["data"].empty


def test_dt_numeric_insufficient_single_bucket() -> None:
    df = pd.DataFrame({"ts": ["2025-01-01"] * 4, "n": [1.0, 2.0, 3.0, 4.0]})
    result = _datetime_numeric_aggregation_data(df, "ts", "n")
    assert result["status"] == "insufficient_data"


# ── datetime × categorical counts ───────────────────────────────────────────


def _dt_cat_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": ["2025-01-01", "2025-01-01", "2025-01-02", "2025-02-01"],
            "c": ["a", "b", "a", "b"],
        }
    )


def test_dt_categorical_day_counts() -> None:
    result = _datetime_categorical_counts_data(_dt_cat_frame(), "ts", "c", granularity="day")
    assert result["status"] == "ok"
    assert list(result["data"].columns) == ["period", "category", "count"]
    assert int(result["data"]["count"].sum()) == 4
    assert result["rows_used"] == 4


def test_dt_categorical_month_grouping() -> None:
    result = _datetime_categorical_counts_data(_dt_cat_frame(), "ts", "c", granularity="month")
    # Jan: a=2, b=1; Feb: b=1 → 3 long-form rows.
    assert result["status"] == "ok"
    assert len(result["data"]) == 3


def test_dt_categorical_top_n_other_bucket() -> None:
    df = pd.DataFrame(
        {
            "ts": ["2025-01-01"] * 5,
            "c": ["a", "b", "c", "d", "e"],
        }
    )
    result = _datetime_categorical_counts_data(df, "ts", "c", top_n=2)
    assert result["status"] == "ok"
    assert result["other_count"] == 3  # c, d, e rolled into (other)
    assert "(other)" in set(result["data"]["category"])


def test_dt_categorical_preserves_missing_bucket() -> None:
    df = pd.DataFrame({"ts": ["2025-01-01", "2025-01-02"], "c": ["a", None]})
    result = _datetime_categorical_counts_data(df, "ts", "c")
    assert "(missing)" in set(result["data"]["category"])


def test_dt_categorical_missing_datetime_metadata() -> None:
    df = pd.DataFrame({"ts": ["2025-01-01", "bad", "2025-01-02"], "c": ["a", "b", "a"]})
    result = _datetime_categorical_counts_data(df, "ts", "c", parse_threshold=0.5)
    assert result["status"] == "ok"
    assert result["missing_datetime"] == 1


def test_dt_categorical_low_parse_confidence_safe() -> None:
    df = pd.DataFrame({"ts": ["nope", "bad", "x", "2025-01-01"], "c": ["a", "b", "a", "b"]})
    result = _datetime_categorical_counts_data(df, "ts", "c")
    assert result["status"] == "low_parse_confidence"
    assert result["data"].empty


# ── numeric ECDF ────────────────────────────────────────────────────────────


def test_numeric_ecdf_simple_series_is_sorted_and_reaches_one() -> None:
    df = pd.DataFrame({"n": [float(i) for i in range(1, 6)]})
    result = _numeric_ecdf_data(df, "n")
    assert result["status"] == "ok"
    assert list(result["data"].columns) == ["value", "cumulative_probability", "count"]
    values = result["data"]["value"].tolist()
    probs = result["data"]["cumulative_probability"].tolist()
    assert values == sorted(values)
    assert probs == sorted(probs)  # monotonically non-decreasing
    assert probs[-1] == pytest.approx(1.0)
    assert result["non_null_count"] == 5


def test_numeric_ecdf_duplicates_aggregate_deterministically() -> None:
    df = pd.DataFrame({"n": [1.0, 1.0, 2.0, 3.0, 3.0, 3.0]})
    result = _numeric_ecdf_data(df, "n")
    assert result["data"]["value"].tolist() == [1.0, 2.0, 3.0]
    assert result["data"]["count"].tolist() == [2, 1, 3]
    assert result["data"]["cumulative_probability"].tolist() == [
        pytest.approx(2 / 6),
        pytest.approx(3 / 6),
        pytest.approx(6 / 6),
    ]
    assert result["unique_values"] == 3


def test_numeric_ecdf_ignores_nulls() -> None:
    df = pd.DataFrame({"n": [1.0, float("nan"), 2.0, float("nan"), 3.0]})
    result = _numeric_ecdf_data(df, "n")
    assert result["status"] == "ok"
    assert result["non_null_count"] == 3
    assert result["data"]["cumulative_probability"].iloc[-1] == pytest.approx(1.0)


def test_numeric_ecdf_handles_infinities_safely() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, float("inf"), float("-inf"), 3.0]})
    result = _numeric_ecdf_data(df, "n")
    assert result["status"] == "ok"
    assert result["non_null_count"] == 3
    assert result["data"]["value"].tolist() == [1.0, 2.0, 3.0]


def test_numeric_ecdf_constant_column_returns_single_valid_point() -> None:
    df = pd.DataFrame({"n": [5.0, 5.0, 5.0]})
    result = _numeric_ecdf_data(df, "n")
    assert result["status"] == "ok"
    assert result["points"] == 1
    assert result["data"]["value"].tolist() == [5.0]
    assert result["data"]["cumulative_probability"].tolist() == [pytest.approx(1.0)]


def test_numeric_ecdf_empty_and_all_null_return_safe_empty() -> None:
    empty = _numeric_ecdf_data(pd.DataFrame({"n": pd.Series([], dtype="float64")}), "n")
    assert empty["status"] == "insufficient_data"
    assert empty["data"].empty
    all_null = _numeric_ecdf_data(
        pd.DataFrame({"n": pd.Series([float("nan"), float("nan")], dtype="float64")}), "n"
    )
    assert all_null["status"] == "insufficient_data"
    assert all_null["data"].empty


def test_numeric_ecdf_rejects_non_numeric_and_missing_column() -> None:
    df = pd.DataFrame({"c": ["a", "b"]})
    assert _numeric_ecdf_data(df, "c")["status"] == "invalid_type"
    assert _numeric_ecdf_data(df, "missing")["status"] == "invalid_column"


def test_numeric_ecdf_large_series_output_is_bounded() -> None:
    df = pd.DataFrame({"n": [float(i) for i in range(MAX_PLOT_ROWS * 4)]})
    result = _numeric_ecdf_data(df, "n")
    assert result["status"] == "ok"
    assert result["sampled"] is True
    assert result["points"] <= MAX_PLOT_ROWS
    assert result["unique_values"] == MAX_PLOT_ROWS * 4
    # first and last points preserved
    assert result["data"]["value"].iloc[0] == pytest.approx(0.0)
    assert result["data"]["cumulative_probability"].iloc[-1] == pytest.approx(1.0)


def test_numeric_ecdf_does_not_mutate_input() -> None:
    df = pd.DataFrame({"n": [3.0, 1.0, float("nan"), 2.0, float("inf")]})
    before = df.copy(deep=True)
    _numeric_ecdf_data(df, "n")
    pd.testing.assert_frame_equal(df, before)


def test_numeric_ecdf_is_deterministic() -> None:
    df = pd.DataFrame({"n": [float(i % 97) for i in range(1000)]})
    first = _numeric_ecdf_data(df, "n")["data"]
    second = _numeric_ecdf_data(df, "n")["data"]
    pd.testing.assert_frame_equal(first, second)
