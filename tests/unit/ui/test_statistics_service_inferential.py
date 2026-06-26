"""Tests for the inferential wrappers in the Statistics Lab UI service.

The service stays streamlit-free and delegates to the domain helpers; these
tests pin the delegation, the scipy availability probe, the result shaping, and
the streamlit-free contract.
"""

from __future__ import annotations

import importlib.util
import inspect

import numpy as np
import pandas as pd

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


def test_normality_check_delegates() -> None:
    result = svc.normality_check(pd.Series(range(10)))
    assert "status" in result
    assert "method" in result


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
