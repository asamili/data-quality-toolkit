"""Unit tests for domain.statistics.drift.

Orchestration tests use a deterministic fake scipy.stats (monkeypatched via
drift._import_scipy_stats) so they run without scipy installed. Tests that
exercise real statistics are guarded by pytest.importorskip("scipy").
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.domain.statistics import drift
from data_quality_toolkit.domain.statistics.drift import OTHER_BUCKET, detect_drift_frames

RESULT_KEYS = {
    "status",
    "reason",
    "alpha",
    "scipy_available",
    "reference_rows",
    "current_rows",
    "columns",
    "summary",
}
COLUMN_KEYS = {
    "column",
    "kind",
    "test",
    "statistic",
    "p_value",
    "drift_detected",
    "reference_n",
    "current_n",
    "status",
    "skip_reason",
    "interpretation",
}


class FakeStats:
    """Deterministic stand-in for scipy.stats."""

    def __init__(self, ks_p: float = 0.5, chi2_p: float = 0.5) -> None:
        self.ks_p = ks_p
        self.chi2_p = chi2_p
        self.last_chi2_table: np.ndarray | None = None

    def ks_2samp(self, a: Any, b: Any) -> SimpleNamespace:
        return SimpleNamespace(statistic=0.42, pvalue=self.ks_p)

    def chi2_contingency(self, table: Any) -> SimpleNamespace:
        arr = np.asarray(table, dtype=float)
        self.last_chi2_table = arr
        # Expected counts under homogeneity (same formula scipy uses)
        expected = arr.sum(axis=1, keepdims=True) * arr.sum(axis=0, keepdims=True) / arr.sum()
        return SimpleNamespace(
            statistic=1.23, pvalue=self.chi2_p, dof=arr.shape[1] - 1, expected_freq=expected
        )


def _patch(monkeypatch: pytest.MonkeyPatch, fake: FakeStats | None) -> None:
    monkeypatch.setattr(drift, "_import_scipy_stats", lambda: fake)


def _numeric_frames(shift: float = 0.0, n: int = 100) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(42)
    ref = pd.DataFrame({"x": rng.normal(0, 1, n)})
    cur = pd.DataFrame({"x": rng.normal(shift, 1, n)})
    return ref, cur


def _col(result: dict[str, Any], name: str) -> dict[str, Any]:
    return next(c for c in result["columns"] if c["column"] == name)


class TestUnavailable:
    def test_no_scipy_returns_unavailable_without_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, None)
        ref, cur = _numeric_frames()
        result = detect_drift_frames(ref, cur)
        assert result["status"] == "unavailable"
        assert result["scipy_available"] is False
        assert "data-quality-toolkit[stats]" in result["reason"]
        assert result["columns"] == []
        assert result["summary"]["drift_detected"] is False
        assert set(result) >= RESULT_KEYS

    def test_unavailable_schema_matches_ok_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ref, cur = _numeric_frames()
        _patch(monkeypatch, None)
        unavailable = detect_drift_frames(ref, cur)
        _patch(monkeypatch, FakeStats())
        ok = detect_drift_frames(ref, cur)
        assert set(unavailable) == set(ok)


class TestNumericDrift:
    def test_low_p_flags_drift(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(ks_p=0.001))
        ref, cur = _numeric_frames()
        result = detect_drift_frames(ref, cur)
        col = _col(result, "x")
        assert col["status"] == "tested"
        assert col["test"] == "ks"
        assert col["kind"] == "numeric"
        assert col["drift_detected"] is True
        assert col["p_value"] == pytest.approx(0.001)
        assert "drift detected" in col["interpretation"]
        assert result["summary"]["drift_detected"] is True
        assert result["summary"]["columns_drifted"] == 1

    def test_high_p_no_drift(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(ks_p=0.9))
        ref, cur = _numeric_frames()
        result = detect_drift_frames(ref, cur)
        col = _col(result, "x")
        assert col["drift_detected"] is False
        assert "no significant drift" in col["interpretation"]
        assert result["summary"]["drift_detected"] is False

    def test_alpha_boundary_changes_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(ks_p=0.04))
        ref, cur = _numeric_frames()
        assert _col(detect_drift_frames(ref, cur, alpha=0.05), "x")["drift_detected"] is True
        assert _col(detect_drift_frames(ref, cur, alpha=0.01), "x")["drift_detected"] is False


class TestCategoricalDrift:
    def test_low_p_flags_drift(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(chi2_p=0.001))
        ref = pd.DataFrame({"c": ["a"] * 50 + ["b"] * 50})
        cur = pd.DataFrame({"c": ["a"] * 80 + ["b"] * 20})
        result = detect_drift_frames(ref, cur)
        col = _col(result, "c")
        assert col["status"] == "tested"
        assert col["test"] == "chi_square"
        assert col["kind"] == "categorical"
        assert col["drift_detected"] is True

    def test_high_cardinality_bucketed_into_other(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeStats(chi2_p=0.5)
        _patch(monkeypatch, fake)
        # 3 dominant categories + 30 rare ones; max_categories=3 buckets the rest
        values = ["a"] * 100 + ["b"] * 100 + ["c"] * 100 + [f"rare_{i}" for i in range(30)] * 2
        ref = pd.DataFrame({"c": values})
        cur = pd.DataFrame({"c": values})
        result = detect_drift_frames(ref, cur, max_categories=3)
        col = _col(result, "c")
        assert col["status"] == "tested"
        assert fake.last_chi2_table is not None
        assert fake.last_chi2_table.shape[1] <= 4  # 3 kept + OTHER_BUCKET

    def test_other_bucket_name(self) -> None:
        ref = pd.Series(["a"] * 50 + ["b"] * 30 + ["z1", "z2", "z3"])
        cur = pd.Series(["a"] * 50 + ["b"] * 30)
        table = drift._contingency_table(ref, cur, max_categories=2)
        assert OTHER_BUCKET in table.columns

    def test_expected_frequency_too_low_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(chi2_p=0.001))
        # "b" is so rare its expected cell count is < 5
        ref = pd.DataFrame({"c": ["a"] * 98 + ["b"] * 2})
        cur = pd.DataFrame({"c": ["a"] * 99 + ["b"] * 1})
        col = _col(detect_drift_frames(ref, cur), "c")
        assert col["status"] == "skipped"
        assert col["skip_reason"] == "expected_frequency_too_low"

    def test_single_category_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats())
        ref = pd.DataFrame({"c": ["a"] * 50})
        cur = pd.DataFrame({"c": ["a"] * 50})
        col = _col(detect_drift_frames(ref, cur), "c")
        assert col["skip_reason"] == "single_category"

    def test_bool_column_is_categorical(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(chi2_p=0.2))
        ref = pd.DataFrame({"b": [True] * 50 + [False] * 50})
        cur = pd.DataFrame({"b": [True] * 30 + [False] * 70})
        col = _col(detect_drift_frames(ref, cur), "b")
        assert col["kind"] == "categorical"
        assert col["test"] == "chi_square"


class TestSkips:
    def test_insufficient_samples(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats())
        ref = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        cur = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        col = _col(detect_drift_frames(ref, cur, min_samples=30), "x")
        assert col["status"] == "skipped"
        assert col["skip_reason"] == "insufficient_samples"
        assert col["reference_n"] == 3

    def test_column_missing_each_side(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats())
        ref = pd.DataFrame({"only_ref": range(50), "shared": range(50)})
        cur = pd.DataFrame({"only_cur": range(50), "shared": range(50)})
        result = detect_drift_frames(ref, cur)
        assert _col(result, "only_ref")["skip_reason"] == "column_missing"
        assert _col(result, "only_cur")["skip_reason"] == "column_missing"
        assert _col(result, "shared")["status"] == "tested"

    def test_all_null_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats())
        ref = pd.DataFrame({"x": [None] * 50}, dtype="float64")
        cur = pd.DataFrame({"x": [1.0] * 50})
        col = _col(detect_drift_frames(ref, cur), "x")
        assert col["skip_reason"] == "all_null"

    def test_datetime_unsupported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats())
        ts = pd.date_range("2024-01-01", periods=50)
        ref = pd.DataFrame({"t": ts})
        cur = pd.DataFrame({"t": ts})
        col = _col(detect_drift_frames(ref, cur), "t")
        assert col["skip_reason"] == "unsupported_dtype"

    def test_dtype_mismatch_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats())
        ref = pd.DataFrame({"x": [1.0] * 50})
        cur = pd.DataFrame({"x": ["a"] * 50})
        col = _col(detect_drift_frames(ref, cur), "x")
        assert col["skip_reason"] == "dtype_mismatch"

    def test_nulls_dropped_and_counted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(ks_p=0.5))
        ref = pd.DataFrame({"x": [1.0] * 40 + [None] * 10})
        cur = pd.DataFrame({"x": [2.0] * 50})
        col = _col(detect_drift_frames(ref, cur), "x")
        assert col["reference_n"] == 40
        assert col["current_n"] == 50


class TestValidationAndSchema:
    @pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1, 1.5])
    def test_invalid_alpha_raises(self, alpha: float) -> None:
        ref, cur = _numeric_frames()
        with pytest.raises(ValueError, match="alpha"):
            detect_drift_frames(ref, cur, alpha=alpha)

    def test_invalid_min_samples_raises(self) -> None:
        ref, cur = _numeric_frames()
        with pytest.raises(ValueError, match="min_samples"):
            detect_drift_frames(ref, cur, min_samples=1)

    def test_invalid_max_categories_raises(self) -> None:
        ref, cur = _numeric_frames()
        with pytest.raises(ValueError, match="max_categories"):
            detect_drift_frames(ref, cur, max_categories=1)

    def test_column_entry_keys_stable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats())
        ref = pd.DataFrame({"x": range(50), "only_ref": range(50)})
        cur = pd.DataFrame({"x": range(50)})
        result = detect_drift_frames(ref, cur)
        for col in result["columns"]:
            assert set(col) == COLUMN_KEYS

    def test_summary_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, FakeStats(ks_p=0.001))
        ref = pd.DataFrame({"x": np.arange(50.0), "only_ref": range(50)})
        cur = pd.DataFrame({"x": np.arange(50.0) + 10})
        summary = detect_drift_frames(ref, cur)["summary"]
        assert summary["columns_tested"] == 1
        assert summary["columns_skipped"] == 1
        assert summary["columns_drifted"] == 1
        assert "uncorrected" in summary["note"]


class TestRealScipy:
    """End-to-end statistical correctness; runs only where scipy is installed."""

    def test_shifted_numeric_detected(self) -> None:
        pytest.importorskip("scipy")
        rng = np.random.default_rng(7)
        ref = pd.DataFrame({"x": rng.normal(0, 1, 500)})
        cur = pd.DataFrame({"x": rng.normal(2, 1, 500)})
        col = _col(detect_drift_frames(ref, cur), "x")
        assert col["drift_detected"] is True
        assert col["p_value"] < 0.05

    def test_identical_numeric_not_detected(self) -> None:
        pytest.importorskip("scipy")
        rng = np.random.default_rng(7)
        values = rng.normal(0, 1, 500)
        col = _col(
            detect_drift_frames(pd.DataFrame({"x": values}), pd.DataFrame({"x": values})), "x"
        )
        assert col["drift_detected"] is False

    def test_categorical_shift_detected(self) -> None:
        pytest.importorskip("scipy")
        ref = pd.DataFrame({"c": ["a"] * 400 + ["b"] * 100})
        cur = pd.DataFrame({"c": ["a"] * 100 + ["b"] * 400})
        col = _col(detect_drift_frames(ref, cur), "c")
        assert col["drift_detected"] is True
        assert col["test"] == "chi_square"
