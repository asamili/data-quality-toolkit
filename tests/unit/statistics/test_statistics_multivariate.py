"""Tests for the pure multivariate diagnostics helpers (pandas/numpy only)."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.domain.statistics import multivariate

_SCIPY_TARGET = "data_quality_toolkit.domain.statistics.multivariate.import_scipy_stats"


def _numeric_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 5.0],
            "b": [2.0, 4.0, 6.0, 8.0, 10.0],  # perfectly correlated with a
            "c": [5.0, 3.0, 4.0, 1.0, 2.0],
            "label": ["x", "y", "x", "y", "x"],  # ignored (non-numeric)
        }
    )


# ── covariance_matrix ─────────────────────────────────────────────────────────


def test_covariance_matrix_square_shape_and_values() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [2.0, 4.0, 6.0, 8.0]})
    cov = multivariate.covariance_matrix(df)
    assert list(cov.index) == ["x", "y"]
    assert list(cov.columns) == ["x", "y"]
    # var(x) for [1,2,3,4] with ddof=1 = 1.6666...
    assert cov.loc["x", "x"] == pytest.approx(1.666667, abs=1e-6)
    assert cov.loc["x", "y"] == pytest.approx(3.333333, abs=1e-6)


def test_covariance_matrix_ignores_non_numeric() -> None:
    cov = multivariate.covariance_matrix(_numeric_frame())
    assert list(cov.columns) == ["a", "b", "c"]
    assert "label" not in cov.columns


def test_covariance_matrix_empty_without_two_numeric() -> None:
    assert multivariate.covariance_matrix(pd.DataFrame({"c": ["a", "b"]})).empty
    assert multivariate.covariance_matrix(pd.DataFrame({"x": [1.0, 2.0]})).empty


def test_covariance_matrix_handles_nan_and_inf_without_raising() -> None:
    df = pd.DataFrame(
        {
            "x": [1.0, 2.0, np.nan, 4.0, 5.0],
            "y": [2.0, np.inf, 6.0, 8.0, 10.0],
        }
    )
    cov = multivariate.covariance_matrix(df)
    assert list(cov.columns) == ["x", "y"]
    assert np.isfinite(cov.loc["x", "x"])


def test_covariance_matrix_does_not_mutate_input() -> None:
    df = pd.DataFrame({"x": [1.0, np.inf, 3.0], "y": [1.0, 2.0, 3.0]})
    before = df.copy()
    multivariate.covariance_matrix(df)
    pd.testing.assert_frame_equal(df, before)


# ── variance_inflation_factors ────────────────────────────────────────────────


def test_vif_expected_columns() -> None:
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 5.0],
            "c": [5.0, 3.0, 4.0, 1.0, 2.0],
            "d": [2.0, 1.0, 5.0, 3.0, 9.0],
        }
    )
    vif = multivariate.variance_inflation_factors(df)
    assert list(vif.columns) == ["column", "vif"]
    assert set(vif["column"]) == {"a", "c", "d"}


def test_vif_duplicate_columns_no_raise() -> None:
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 5.0],
            "b": [1.0, 2.0, 3.0, 4.0, 5.0],  # exact duplicate → singular corr
            "c": [5.0, 3.0, 4.0, 1.0, 2.0],
        }
    )
    vif = multivariate.variance_inflation_factors(df)
    assert list(vif.columns) == ["column", "vif"]
    assert len(vif) == 3  # pinv fallback keeps all usable columns


def test_vif_perfectly_correlated_no_raise() -> None:
    vif = multivariate.variance_inflation_factors(_numeric_frame())
    assert not vif.empty
    assert vif["vif"].notna().all()


def test_vif_sorted_descending() -> None:
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "b": [1.1, 2.0, 3.1, 3.9, 5.2, 5.8],  # near-collinear with a → high VIF
            "c": [9.0, 1.0, 4.0, 2.0, 7.0, 3.0],  # unrelated → low VIF
        }
    )
    vif = multivariate.variance_inflation_factors(df)
    assert list(vif["vif"]) == sorted(vif["vif"], reverse=True)


def test_vif_drops_constant_columns() -> None:
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 5.0],
            "const": [7.0, 7.0, 7.0, 7.0, 7.0],  # constant → dropped
            "c": [5.0, 3.0, 4.0, 1.0, 2.0],
        }
    )
    vif = multivariate.variance_inflation_factors(df)
    assert "const" not in set(vif["column"])
    assert set(vif["column"]) == {"a", "c"}


def test_vif_empty_without_two_usable_columns() -> None:
    single = multivariate.variance_inflation_factors(pd.DataFrame({"x": [1.0, 2.0, 3.0]}))
    assert single.empty
    assert list(single.columns) == ["column", "vif"]
    # One numeric varies, the other constant → only one usable → empty.
    one_usable = pd.DataFrame({"x": [1.0, 2.0, 3.0], "const": [4.0, 4.0, 4.0]})
    assert multivariate.variance_inflation_factors(one_usable).empty


def test_vif_handles_inf_without_raising() -> None:
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, np.inf, 4.0, 5.0],
            "c": [5.0, 3.0, 4.0, 1.0, 2.0],
            "d": [2.0, 1.0, 5.0, 3.0, 9.0],
        }
    )
    vif = multivariate.variance_inflation_factors(df)
    assert list(vif.columns) == ["column", "vif"]


# ── top_correlations ──────────────────────────────────────────────────────────


def test_top_correlations_excludes_self_and_mirrors() -> None:
    top = multivariate.top_correlations(_numeric_frame())
    # 3 numeric columns → C(3, 2) = 3 unordered pairs, no self, no mirror.
    assert len(top) == 3
    assert list(top.columns) == [
        "feature_x",
        "feature_y",
        "correlation",
        "abs_correlation",
        "method",
        "n",
    ]
    pairs = {frozenset((row.feature_x, row.feature_y)) for row in top.itertuples()}
    assert len(pairs) == 3
    assert all(row.feature_x != row.feature_y for row in top.itertuples())


def test_top_correlations_sorted_by_abs_descending() -> None:
    top = multivariate.top_correlations(_numeric_frame())
    assert list(top["abs_correlation"]) == sorted(top["abs_correlation"], reverse=True)
    # a and b are perfectly correlated → strongest pair first.
    assert top.iloc[0]["abs_correlation"] == pytest.approx(1.0)
    assert {top.iloc[0]["feature_x"], top.iloc[0]["feature_y"]} == {"a", "b"}


def test_top_correlations_includes_method_and_n() -> None:
    top = multivariate.top_correlations(_numeric_frame(), method="spearman")
    assert (top["method"] == "spearman").all()
    assert (top["n"] == 5).all()


def test_top_correlations_unknown_method_falls_back_to_pearson() -> None:
    top = multivariate.top_correlations(_numeric_frame(), method="bogus")
    assert (top["method"] == "pearson").all()


def test_top_correlations_respects_top_k() -> None:
    top = multivariate.top_correlations(_numeric_frame(), top_k=1)
    assert len(top) == 1


def test_top_correlations_empty_without_two_numeric() -> None:
    single = multivariate.top_correlations(pd.DataFrame({"x": [1.0, 2.0, 3.0]}))
    assert single.empty
    assert list(single.columns) == [
        "feature_x",
        "feature_y",
        "correlation",
        "abs_correlation",
        "method",
        "n",
    ]


def test_top_correlations_handles_nan_and_inf_pairwise_n() -> None:
    df = pd.DataFrame(
        {
            "x": [1.0, 2.0, np.nan, 4.0, 5.0],
            "y": [2.0, np.inf, 6.0, 8.0, 10.0],
        }
    )
    top = multivariate.top_correlations(df)
    assert len(top) == 1
    # x row 2 is NaN, y row 1 is inf→NaN → 3 overlapping complete observations.
    assert int(top.iloc[0]["n"]) == 3


def test_top_correlations_does_not_mutate_input() -> None:
    df = _numeric_frame()
    before = df.copy()
    multivariate.top_correlations(df)
    pd.testing.assert_frame_equal(df, before)


# ── categorical_associations ──────────────────────────────────────────────────


def _associated_frame() -> pd.DataFrame:
    # x and y are perfectly associated → Cramér's V == 1.0.
    return pd.DataFrame(
        {
            "x": ["a", "a", "b", "b", "c", "c"],
            "y": ["p", "p", "q", "q", "r", "r"],
            "num": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],  # numeric → ignored
        }
    )


def test_categorical_associations_expected_columns() -> None:
    assoc = multivariate.categorical_associations(_associated_frame())
    assert list(assoc.columns) == [
        "feature_x",
        "feature_y",
        "cramers_v",
        "chi2",
        "dof",
        "n",
        "p_value",
        "warning",
    ]


def test_categorical_associations_high_cramers_v_for_clear_association() -> None:
    assoc = multivariate.categorical_associations(_associated_frame())
    assert len(assoc) == 1
    assert assoc.iloc[0]["cramers_v"] == pytest.approx(1.0)
    assert {assoc.iloc[0]["feature_x"], assoc.iloc[0]["feature_y"]} == {"x", "y"}


def test_categorical_associations_excludes_self_and_mirrors() -> None:
    df = pd.DataFrame(
        {
            "x": ["a", "a", "b", "b"],
            "y": ["p", "q", "p", "q"],
            "z": ["m", "n", "m", "n"],
        }
    )
    assoc = multivariate.categorical_associations(df)
    assert len(assoc) == 3  # C(3, 2) unordered pairs, no self, no mirror
    pairs = {frozenset((row.feature_x, row.feature_y)) for row in assoc.itertuples()}
    assert len(pairs) == 3
    assert all(row.feature_x != row.feature_y for row in assoc.itertuples())


def test_categorical_associations_p_value_present_when_scipy_available() -> None:
    pytest.importorskip("scipy")
    assoc = multivariate.categorical_associations(_associated_frame())
    assert "p_value" in assoc.columns
    assert assoc.iloc[0]["p_value"] is not None


def test_categorical_associations_p_value_none_when_scipy_unavailable() -> None:
    with patch(_SCIPY_TARGET, return_value=None):
        assoc = multivariate.categorical_associations(_associated_frame())
    assert assoc.iloc[0]["p_value"] is None
    assert "scipy_unavailable" in str(assoc.iloc[0]["warning"])


def test_categorical_associations_never_raises_without_scipy() -> None:
    with patch(_SCIPY_TARGET, return_value=None):
        assoc = multivariate.categorical_associations(_associated_frame())
    assert not assoc.empty  # completed without raising


def test_categorical_associations_no_categorical_columns() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
    result = multivariate.categorical_associations(df)
    assert result.empty
    assert list(result.columns) == [
        "feature_x",
        "feature_y",
        "cramers_v",
        "chi2",
        "dof",
        "n",
        "p_value",
        "warning",
    ]


def test_categorical_associations_one_categorical_column() -> None:
    df = pd.DataFrame({"x": ["a", "b", "a"], "num": [1.0, 2.0, 3.0]})
    assert multivariate.categorical_associations(df).empty


def test_categorical_associations_handles_missing_values() -> None:
    df = pd.DataFrame(
        {
            "x": ["a", "a", None, "b", "b"],
            "y": ["p", "q", "p", None, "q"],
        }
    )
    assoc = multivariate.categorical_associations(df)
    assert len(assoc) == 1
    assert int(assoc.iloc[0]["n"]) == 3  # two rows dropped for missing values


def test_categorical_associations_single_level_flags_insufficient() -> None:
    df = pd.DataFrame({"x": ["a", "a", "a", "a"], "y": ["p", "q", "p", "q"]})
    assoc = multivariate.categorical_associations(df)
    assert len(assoc) == 1
    assert assoc.iloc[0]["cramers_v"] is None
    assert "insufficient_categories" in str(assoc.iloc[0]["warning"])


def test_categorical_associations_high_cardinality_capped_warning() -> None:
    df = pd.DataFrame(
        {
            "x": ["a", "b", "c", "d", "e", "a", "b", "c", "d", "e"],
            "y": ["p", "q", "p", "q", "p", "q", "p", "q", "p", "q"],
        }
    )
    assoc = multivariate.categorical_associations(df, max_categories=2)
    assert "high_cardinality_capped" in str(assoc.iloc[0]["warning"])


def test_categorical_associations_sparse_expected_counts_warning() -> None:
    df = pd.DataFrame({"x": ["a", "a", "b", "b"], "y": ["p", "q", "p", "q"]})
    assoc = multivariate.categorical_associations(df)
    assert "sparse_expected_counts" in str(assoc.iloc[0]["warning"])


def test_categorical_associations_does_not_mutate_input() -> None:
    df = _associated_frame()
    before = df.copy()
    multivariate.categorical_associations(df)
    pd.testing.assert_frame_equal(df, before)


# ── grouped_numeric_by_category_summary ───────────────────────────────────────


def _mixed_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "cat": ["a", "a", "b", "b"],
            "grp": ["x", "y", "x", "y"],
            "num": [1.0, 2.0, 3.0, 4.0],
            "num2": [10.0, 20.0, 30.0, 40.0],
        }
    )


def test_grouped_summary_expected_columns() -> None:
    grouped = multivariate.grouped_numeric_by_category_summary(_mixed_frame())
    assert list(grouped.columns) == [
        "category_column",
        "category_value",
        "numeric_column",
        "count",
        "missing",
        "mean",
        "median",
        "std",
        "min",
        "max",
    ]


def test_grouped_summary_uses_first_categorical_when_none() -> None:
    grouped = multivariate.grouped_numeric_by_category_summary(_mixed_frame())
    assert (grouped["category_column"] == "cat").all()


def test_grouped_summary_respects_explicit_category() -> None:
    grouped = multivariate.grouped_numeric_by_category_summary(_mixed_frame(), category="grp")
    assert (grouped["category_column"] == "grp").all()


def test_grouped_summary_computes_aggregates() -> None:
    grouped = multivariate.grouped_numeric_by_category_summary(_mixed_frame())
    row = grouped[(grouped["category_value"] == "a") & (grouped["numeric_column"] == "num")].iloc[0]
    assert int(row["count"]) == 2
    assert int(row["missing"]) == 0
    assert row["mean"] == pytest.approx(1.5)
    assert row["median"] == pytest.approx(1.5)
    assert row["min"] == 1.0
    assert row["max"] == 2.0


def test_grouped_summary_no_categorical_columns() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
    result = multivariate.grouped_numeric_by_category_summary(df)
    assert result.empty
    assert list(result.columns) == [
        "category_column",
        "category_value",
        "numeric_column",
        "count",
        "missing",
        "mean",
        "median",
        "std",
        "min",
        "max",
    ]


def test_grouped_summary_no_numeric_columns() -> None:
    df = pd.DataFrame({"cat": ["a", "b"], "grp": ["x", "y"]})
    assert multivariate.grouped_numeric_by_category_summary(df).empty


def test_grouped_summary_explicit_non_categorical_is_empty() -> None:
    assert multivariate.grouped_numeric_by_category_summary(_mixed_frame(), category="num").empty


def test_grouped_summary_handles_missing_numeric_values() -> None:
    df = pd.DataFrame(
        {
            "cat": ["a", "a", "b", "b"],
            "num": [1.0, np.nan, 3.0, 4.0],
        }
    )
    grouped = multivariate.grouped_numeric_by_category_summary(df)
    row = grouped[grouped["category_value"] == "a"].iloc[0]
    assert int(row["count"]) == 1
    assert int(row["missing"]) == 1


def test_grouped_summary_high_cardinality_capping() -> None:
    df = pd.DataFrame(
        {
            "cat": ["a", "b", "c", "d", "e", "f"],
            "num": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        }
    )
    grouped = multivariate.grouped_numeric_by_category_summary(df, max_categories=2)
    assert "__other__" in set(grouped["category_value"])


def test_grouped_summary_does_not_mutate_input() -> None:
    df = _mixed_frame()
    before = df.copy()
    multivariate.grouped_numeric_by_category_summary(df)
    pd.testing.assert_frame_equal(df, before)
