"""Tests for the pure descriptive-statistics helpers (pandas/numpy only)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.domain.statistics import descriptive


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, np.nan],
            "b": [10.0, 20.0, 30.0, 40.0, 50.0],
            "label": ["x", "y", "x", "y", "x"],
        }
    )


def test_numeric_summary_fields_and_missing() -> None:
    summary = descriptive.numeric_summary(_frame())
    assert set(summary.index) == {"a", "b"}  # non-numeric column excluded
    assert summary.loc["a", "count"] == 4
    assert summary.loc["a", "missing"] == 1
    assert summary.loc["a", "missing_pct"] == pytest.approx(20.0)
    assert summary.loc["b", "mean"] == pytest.approx(30.0)
    assert summary.loc["b", "median"] == pytest.approx(30.0)
    assert summary.loc["b", "min"] == 10.0
    assert summary.loc["b", "max"] == 50.0


def test_numeric_summary_empty_when_no_numeric() -> None:
    df = pd.DataFrame({"label": ["x", "y"]})
    assert descriptive.numeric_summary(df).empty


def test_numeric_summary_accepts_series() -> None:
    summary = descriptive.numeric_summary(pd.Series([1.0, 2.0, 3.0], name="v"))
    assert summary.loc["v", "count"] == 3


def test_quick_profile_keys() -> None:
    profile = descriptive.quick_profile(_frame())
    assert profile["n_rows"] == 5
    assert profile["n_columns"] == 3
    assert profile["missing"] == {"a": 1}
    assert profile["memory_mb"] >= 0
    assert isinstance(profile["dtypes"], dict)


def test_correlation_matrix_perfect_linear() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [2.0, 4.0, 6.0, 8.0]})
    corr = descriptive.correlation_matrix(df)
    assert corr.loc["x", "y"] == pytest.approx(1.0)


def test_correlation_matrix_empty_when_single_numeric() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0], "label": ["a", "b"]})
    assert descriptive.correlation_matrix(df).empty


def test_correlation_matrix_rejects_unknown_method() -> None:
    with pytest.raises(ValueError, match="method"):
        descriptive.correlation_matrix(_frame(), method="bogus")
