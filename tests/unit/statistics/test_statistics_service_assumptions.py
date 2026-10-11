"""Tests for the assumption-check wrappers in the Statistics Lab UI service.

The service stays streamlit-free and delegates to the domain helpers; these tests
pin the result structure, the pass/caution/not_applicable/unavailable mapping, the
graceful degradation paths, and the display-table shaping.
"""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.services import statistics as svc

_VALID_STATUSES = {"pass", "caution", "fail", "unavailable", "not_applicable"}
_CHECK_KEYS = {"name", "status", "statistic", "p_value", "alpha", "interpretation", "caveat"}
_CHECK_NORMALITY = "data_quality_toolkit.domain.statistics.inferential.check_normality"


def _grouped_df(n: int = 20) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "metric": np.concatenate([rng.normal(0, 1, n), rng.normal(1, 2, n)]),
            "group": ["a"] * n + ["b"] * n,
        }
    )


def _fake_normality(status: str, **fields: object):
    base = {
        "status": status,
        "reason": fields.get("reason"),
        "statistic": fields.get("statistic"),
        "p_value": fields.get("p_value"),
        "interpretation": fields.get("interpretation", ""),
    }
    return lambda *_a, **_k: base


# ── streamlit-free contract ──────────────────────────────────────────────────


def test_service_stays_streamlit_free() -> None:
    assert "import streamlit" not in inspect.getsource(svc)


# ── one-sample structure and mapping ─────────────────────────────────────────


def test_one_sample_structure() -> None:
    df = pd.DataFrame({"m": list(range(40))})
    result = svc.assumption_checks_one_sample(df, "m")
    assert result["status"] == "ok"
    assert result["metric"] == "m"
    assert "scipy_available" in result
    names = {c["name"] for c in result["checks"]}
    assert {"Normality (Shapiro-Wilk)", "Sample size", "Missing values"} <= names
    for check in result["checks"]:
        assert set(check) == _CHECK_KEYS
        assert check["status"] in _VALID_STATUSES


def test_one_sample_normality_pass_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_CHECK_NORMALITY, _fake_normality("ok", p_value=0.9, statistic=0.99))
    df = pd.DataFrame({"m": [float(x) for x in range(40)]})
    result = svc.assumption_checks_one_sample(df, "m", alpha=0.05)
    normality = next(c for c in result["checks"] if c["name"].startswith("Normality"))
    assert normality["status"] == "pass"
    assert normality["p_value"] == 0.9


def test_one_sample_normality_caution_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_CHECK_NORMALITY, _fake_normality("ok", p_value=0.001, statistic=0.5))
    df = pd.DataFrame({"m": [float(x) for x in range(40)]})
    result = svc.assumption_checks_one_sample(df, "m", alpha=0.05)
    normality = next(c for c in result["checks"] if c["name"].startswith("Normality"))
    assert normality["status"] == "caution"


def test_one_sample_constant_column_not_applicable() -> None:
    df = pd.DataFrame({"m": [5.0] * 10})
    result = svc.assumption_checks_one_sample(df, "m")
    normality = next(c for c in result["checks"] if c["name"].startswith("Normality"))
    assert normality["status"] == "not_applicable"
    assert "identical" in str(normality["caveat"])


def test_one_sample_too_small_sample_fails() -> None:
    df = pd.DataFrame({"m": [1.0, 2.0]})
    result = svc.assumption_checks_one_sample(df, "m")
    sample = next(c for c in result["checks"] if c["name"] == "Sample size")
    assert sample["status"] == "fail"


def test_one_sample_non_numeric_metric_invalid() -> None:
    df = pd.DataFrame({"m": ["x", "y", "z"]})
    result = svc.assumption_checks_one_sample(df, "m")
    assert result["status"] == "invalid_input"
    assert result["checks"] == []


def test_one_sample_missing_metric_invalid() -> None:
    result = svc.assumption_checks_one_sample(pd.DataFrame({"other": [1.0]}), "m")
    assert result["status"] == "invalid_input"
    assert "not found" in str(result["reason"])


def test_one_sample_empty_df_is_structured() -> None:
    df = pd.DataFrame({"m": pd.Series([], dtype=float)})
    result = svc.assumption_checks_one_sample(df, "m")
    assert result["status"] == "ok"  # never raises
    sample = next(c for c in result["checks"] if c["name"] == "Sample size")
    assert sample["status"] == "fail"


def test_one_sample_missing_values_flagged() -> None:
    df = pd.DataFrame({"m": [1.0, 2.0, np.nan, 4.0, 5.0]})
    result = svc.assumption_checks_one_sample(df, "m")
    missing = next(c for c in result["checks"] if c["name"] == "Missing values")
    assert missing["status"] == "caution"
    assert "dropped" in missing["interpretation"]


# ── grouped structure and mapping ────────────────────────────────────────────


def test_grouped_structure_has_variance_check() -> None:
    result = svc.assumption_checks_grouped(_grouped_df(), "metric", "group")
    assert result["status"] == "ok"
    assert result["group_col"] == "group"
    names = {c["name"] for c in result["checks"]}
    assert "Equal variance (Levene)" in names
    assert "Minimum group size" in names
    assert any(n.startswith("Normality — ") for n in names)
    for check in result["checks"]:
        assert check["status"] in _VALID_STATUSES


def test_grouped_non_numeric_metric_invalid() -> None:
    df = pd.DataFrame({"metric": ["x", "y"], "group": ["a", "b"]})
    result = svc.assumption_checks_grouped(df, "metric", "group")
    assert result["status"] == "invalid_input"


def test_grouped_metric_equals_group_invalid() -> None:
    result = svc.assumption_checks_grouped(_grouped_df(), "group", "group")
    assert result["status"] == "invalid_input"


def test_grouped_truncates_many_groups() -> None:
    rng = np.random.default_rng(1)
    groups = [f"g{i}" for i in range(25) for _ in range(4)]
    df = pd.DataFrame({"metric": rng.normal(size=len(groups)), "group": groups})
    result = svc.assumption_checks_grouped(df, "metric", "group")
    assert result["warnings"]
    normality_checks = [c for c in result["checks"] if c["name"].startswith("Normality — ")]
    assert len(normality_checks) == svc.ASSUMPTION_MAX_GROUPS


# ── graceful degradation when scipy is absent ────────────────────────────────


def test_scipy_unavailable_degrades_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    from data_quality_toolkit.domain.statistics import assumptions, inferential

    monkeypatch.setattr(inferential, "_import_scipy_stats", lambda: None)
    monkeypatch.setattr(assumptions, "import_scipy_stats", lambda: None)

    result = svc.assumption_checks_grouped(_grouped_df(), "metric", "group")
    assert result["status"] == "ok"  # envelope still ok; individual checks degrade
    variance = next(c for c in result["checks"] if c["name"] == "Equal variance (Levene)")
    assert variance["status"] == "unavailable"
    normality = next(c for c in result["checks"] if c["name"].startswith("Normality — "))
    assert normality["status"] == "unavailable"
    # Pure-pandas checks still compute.
    assert any(c["name"] == "Missing values" for c in result["checks"])


# ── display table ────────────────────────────────────────────────────────────


def test_dataframe_shape() -> None:
    result = svc.assumption_checks_one_sample(pd.DataFrame({"m": list(range(40))}), "m")
    table = svc.assumption_checks_dataframe(result)
    assert table is not None
    assert list(table.columns) == [
        "check",
        "status",
        "statistic",
        "p_value",
        "alpha",
        "interpretation",
        "caveat",
    ]
    assert len(table) == len(result["checks"])


def test_dataframe_none_without_checks() -> None:
    assert svc.assumption_checks_dataframe({"checks": []}) is None
