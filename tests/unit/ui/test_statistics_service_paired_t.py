"""Tests for the paired t-test wrapper in the Statistics Lab service.

The service stays streamlit-free, validates the paired column selection, applies
pairwise missing-value exclusion while preserving row alignment, and routes the
computation through the existing ``run_statistical_test`` public-API seam with
``PAIRED_T``. Includes a non-mocked kernel execution and the structured
scipy-unavailable degradation path.
"""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.services import statistics as svc


def _paired_df(n: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    before = rng.normal(10, 2, n)
    after = before + rng.normal(2, 1, n)
    return pd.DataFrame({"before": before, "after": after, "label": ["x"] * n})


def test_service_stays_streamlit_free() -> None:
    assert "import streamlit" not in inspect.getsource(svc)


def test_paired_t_success_through_real_public_api() -> None:
    pytest.importorskip("scipy")
    result = svc.run_paired_t_test(_paired_df(), "before", "after")
    assert result["status"] == "ok"
    assert result["test_key"] == "PAIRED_T"
    assert result["method"] == "paired_t"
    assert result["reject_null"] is True
    assert result["column_a"] == "before"
    assert result["column_b"] == "after"
    assert result["n_pairs"] == 30
    assert result["n_excluded_rows"] == 0
    assert result["assumptions"]["n"] == 30
    assert result["scipy_available"] is True


def test_missing_column_invalid() -> None:
    result = svc.run_paired_t_test(_paired_df(), "before", "nope")
    assert result["status"] == "invalid_input"
    assert result["test_key"] == "PAIRED_T"
    assert "not found" in str(result["reason"])


def test_identical_columns_rejected_with_actionable_message() -> None:
    result = svc.run_paired_t_test(_paired_df(), "before", "before")
    assert result["status"] == "invalid_input"
    assert "two different numeric columns" in str(result["reason"])


def test_non_numeric_column_invalid() -> None:
    result = svc.run_paired_t_test(_paired_df(), "before", "label")
    assert result["status"] == "invalid_input"
    assert "numeric" in str(result["reason"])


def test_pairwise_exclusion_counts_and_alignment() -> None:
    scipy_stats = pytest.importorskip("scipy.stats")
    df = pd.DataFrame(
        {
            "a": [1.0, np.nan, 3.0, 4.0, 5.0, np.nan],
            "b": [1.5, 2.5, np.nan, 4.2, 5.9, np.nan],
        }
    )
    result = svc.run_paired_t_test(df, "a", "b")
    assert result["status"] == "ok"
    # A row is dropped only when either member is missing; the row missing in
    # both columns counts once.
    assert result["n_pairs"] == 3
    assert result["n_excluded_rows"] == 3
    # Row-level alignment: matches scipy's paired t-test on the complete pairs.
    expected = scipy_stats.ttest_rel([1.0, 4.0, 5.0], [1.5, 4.2, 5.9])
    assert result["statistic"] == pytest.approx(float(expected.statistic))
    assert result["p_value"] == pytest.approx(float(expected.pvalue))


def test_non_finite_values_excluded_as_incomplete_pairs() -> None:
    pytest.importorskip("scipy")
    df = _paired_df()
    df.loc[0, "before"] = np.inf
    df.loc[1, "after"] = -np.inf
    result = svc.run_paired_t_test(df, "before", "after")
    assert result["status"] == "ok"
    assert result["n_pairs"] == 28
    assert result["n_excluded_rows"] == 2


def test_insufficient_complete_pairs_actionable() -> None:
    df = pd.DataFrame({"a": [1.0, np.nan, 3.0], "b": [1.5, 2.5, np.nan]})
    result = svc.run_paired_t_test(df, "a", "b")
    assert result["status"] == "insufficient_data"
    assert "complete pairs" in str(result["reason"])
    assert result["n_pairs"] == 1
    assert result["n_excluded_rows"] == 2


def test_constant_differences_surface_kernel_invalid_input() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [2.0, 3.0, 4.0, 5.0]})
    result = svc.run_paired_t_test(df, "a", "b")
    assert result["status"] == "invalid_input"
    assert "standard deviation" in str(result["reason"])


def test_invalid_alpha_returns_structured_invalid_input() -> None:
    result = svc.run_paired_t_test(_paired_df(), "before", "after", alpha=1.5)
    assert result["status"] == "invalid_input"


def test_invalid_alternative_returns_structured_invalid_input() -> None:
    result = svc.run_paired_t_test(_paired_df(), "before", "after", alternative="up")
    assert result["status"] == "invalid_input"


def test_scipy_unavailable_structured_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from data_quality_toolkit.domain.statistics import inference

    monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)
    result = svc.run_paired_t_test(_paired_df(), "before", "after")
    assert result["status"] == "unavailable"
    assert result["scipy_available"] is False
    assert "scipy" in str(result["reason"]).lower()
    assert result["n_pairs"] == 30
    assert result["n_excluded_rows"] == 0
