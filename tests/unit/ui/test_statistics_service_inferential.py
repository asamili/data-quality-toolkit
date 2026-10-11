"""Tests for the inferential wrappers in the Statistics Lab UI service.

The service stays streamlit-free and delegates to the domain helpers; these
tests pin the delegation, the scipy availability probe, the result shaping, and
the streamlit-free contract.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.services import statistics as svc


def _df(n: int = 20) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "metric": np.concatenate([rng.normal(0, 1, n), rng.normal(1, 1, n)]),
            "group": ["a"] * n + ["b"] * n,
        }
    )


def test_service_stays_streamlit_free() -> None:
    src = inspect.getsource(svc)
    assert "import streamlit" not in src


def test_inferential_available_matches_find_spec() -> None:
    expected = importlib.util.find_spec("scipy") is not None
    assert svc.inferential_available() is expected


def test_statistics_profile_wraps_public_api(tmp_path: Path) -> None:
    csv = tmp_path / "stats.csv"
    csv.write_text("group,metric\na,1\na,2\nb,3\nb,4\n", encoding="utf-8")

    result = svc.statistics_profile(csv)
    table = svc.profile_numeric_summary_dataframe(result)

    assert result["status"] == "ok"
    assert result["profile"]["n_rows"] == 4
    assert table is not None
    assert table.loc[0, "column"] == "metric"


def test_select_hypothesis_test_wraps_public_api() -> None:
    result = svc.select_hypothesis_test(
        "numeric",
        "two_independent",
        sigma_known=False,
        equal_variance_assumed=False,
    )

    assert result["status"] == "ok"
    assert result["test_key"] == "TWO_T_WELCH"


def test_normality_check_delegates() -> None:
    result = svc.normality_check(pd.Series(range(10)))
    assert "status" in result
    assert "method" in result


def test_run_one_sample_numeric_test_wraps_public_api() -> None:
    result = svc.run_one_sample_numeric_test(_df(), "metric", null_mean=0.0)
    assert result["status"] in {"ok", "unavailable"}
    assert result["test_key"] == "ONE_T"


def test_run_one_sample_numeric_test_invalid_metric_is_structured() -> None:
    result = svc.run_one_sample_numeric_test(pd.DataFrame({"name": ["a", "b"]}), "name")
    assert result["status"] == "invalid_input"
    assert result["test_key"] == "ONE_T"
    assert "not numeric" in str(result["reason"])


def test_run_two_sample_numeric_test_insufficient_data() -> None:
    pytest.importorskip("scipy")
    tiny = pd.DataFrame({"metric": [1.0, 2.0], "group": ["a", "b"]})
    result = svc.run_two_sample_numeric_test(tiny, "metric", "group", "a", "b")
    assert result["status"] == "insufficient_data"
    assert result["test_key"] == "TWO_T_WELCH"


def test_run_one_sample_missing_scipy_returns_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from data_quality_toolkit.domain.statistics import inference

    monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)

    result = svc.run_one_sample_numeric_test(_df(), "metric")
    assert result["status"] == "unavailable"
    assert result["scipy_available"] is False


def test_two_group_comparison_delegates() -> None:
    result = svc.two_group_comparison(_df(), "metric", "group")
    assert result["status"] in {"ok", "unavailable"}
    assert result["group_col"] == "group"
    assert result["metric"] == "metric"


def test_multi_group_comparison_delegates() -> None:
    result = svc.multi_group_comparison(_df(), "metric", "group")
    assert "groups" in result


def test_ab_comparison_delegates() -> None:
    result = svc.ab_comparison(_df(), "group", "a", "b", "metric")
    assert result["status"] in {"ok", "unavailable", "invalid_type", "insufficient_data"}


def test_compare_numeric_ab_wraps_public_api() -> None:
    result = svc.compare_numeric_ab(_df(), "group", "a", "b", "metric")
    assert result["status"] in {"ok", "unavailable"}
    assert result["test_key"] == "TWO_T_WELCH"
    assert result["group_a"] == "a"
    assert result["group_b"] == "b"


def test_group_summary_dataframe_shape() -> None:
    result = {
        "groups": [
            {"group": "a", "n": 3, "mean": 1.0, "median": 1.0, "std": 0.0},
            {"group": "b", "n": 3, "mean": 2.0, "median": 2.0, "std": 0.0},
        ]
    }
    table = svc.group_summary_dataframe(result)
    assert table is not None
    assert list(table.columns) == ["group", "n", "mean", "median", "std"]
    assert len(table) == 2


def test_group_summary_dataframe_none_without_groups() -> None:
    assert svc.group_summary_dataframe({"status": "unavailable"}) is None
