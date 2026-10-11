"""Tests for the statistics kernel core helpers (guards + critical-value conversions).

Real-scipy correctness behind importorskip plus the scipy-unavailable degradation
path (monkeypatched), mirroring the guarding style of ``test_inferential.py``.
"""

from __future__ import annotations

import numpy as np
import pytest

from data_quality_toolkit.domain.statistics import core

# ── validation ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1, 1.5])
def test_validate_alpha_rejects_out_of_range(alpha: float) -> None:
    with pytest.raises(ValueError, match="alpha"):
        core.validate_alpha(alpha)


def test_validate_alpha_accepts_valid() -> None:
    core.validate_alpha(0.05)  # no raise


@pytest.mark.parametrize("confidence", [0.0, 1.0, -0.2, 2.0])
def test_validate_confidence_rejects_out_of_range(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        core.validate_confidence(confidence)


# ── clean_numeric / has_enough_observations ──────────────────────────────────


def test_clean_numeric_drops_non_finite() -> None:
    arr = core.clean_numeric([1.0, 2.0, np.nan, np.inf, -np.inf, 3.0])
    assert arr.tolist() == [1.0, 2.0, 3.0]


def test_clean_numeric_keeps_non_finite_when_dropna_false() -> None:
    arr = core.clean_numeric([1.0, np.nan, 3.0], dropna=False)
    assert arr.size == 3
    assert np.isnan(arr[1])


def test_clean_numeric_max_rows_is_bounded_and_deterministic() -> None:
    a = core.clean_numeric(range(100), max_rows=10, seed=0)
    b = core.clean_numeric(range(100), max_rows=10, seed=0)
    assert a.size == 10
    assert np.array_equal(a, b)  # deterministic for a fixed seed
    assert np.array_equal(a, np.sort(a))  # order preserved


def test_has_enough_observations() -> None:
    assert core.has_enough_observations([1, 2, 3], min_n=3) is True
    assert core.has_enough_observations([1, 2], min_n=3) is False


# ── conversions: real scipy ──────────────────────────────────────────────────


class TestConversionsRealScipy:
    def test_confidence_to_z_95(self) -> None:
        pytest.importorskip("scipy")
        assert core.confidence_level_to_z(0.95) == pytest.approx(1.959964, abs=1e-5)

    def test_confidence_to_t_exceeds_z_for_small_df(self) -> None:
        pytest.importorskip("scipy")
        t10 = core.confidence_level_to_t(0.95, df=10)
        z95 = core.confidence_level_to_z(0.95)
        assert t10 is not None
        assert z95 is not None
        assert t10 > z95

    def test_confidence_to_t_falls_back_to_z_for_large_df(self) -> None:
        pytest.importorskip("scipy")
        assert core.confidence_level_to_t(0.95, df=5000) == pytest.approx(
            core.confidence_level_to_z(0.95), abs=1e-9
        )

    def test_z_to_confidence_roundtrip(self) -> None:
        pytest.importorskip("scipy")
        z = core.confidence_level_to_z(0.95)
        assert z is not None
        assert core.z_to_confidence_level(z) == pytest.approx(0.95, abs=1e-6)

    def test_confidence_to_t_rejects_nonpositive_df(self) -> None:
        with pytest.raises(ValueError, match="df"):
            core.confidence_level_to_t(0.95, df=0)


# ── conversions: scipy unavailable ───────────────────────────────────────────


class TestConversionsUnavailable:
    def test_all_conversions_return_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(core, "import_scipy_stats", lambda: None)
        assert core.confidence_level_to_z(0.95) is None
        assert core.confidence_level_to_t(0.95, df=10) is None
        assert core.z_to_confidence_level(1.96) is None
