"""Tests for the paired Wilcoxon signed-rank wrapper in the Statistics Lab service.

The service stays streamlit-free and delegates to the domain helper; these tests
pin the delegation, the column validation, the result shaping, and the scipy
graceful-degradation path.
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


def test_paired_wilcoxon_structure_and_echo() -> None:
    result = svc.paired_wilcoxon_test(_paired_df(), "before", "after")
    assert result["status"] in {"ok", "unavailable"}
    assert result["test_name"] == "Wilcoxon signed-rank"
    assert result["method"] == "wilcoxon_signed_rank"
    assert result["column_a"] == "before"
    assert result["column_b"] == "after"
    for key in ("n_pairs", "n_nonzero_differences", "alpha", "alternative", "caveat"):
        assert key in result


def test_paired_wilcoxon_detects_shift_with_scipy() -> None:
    pytest.importorskip("scipy")
    result = svc.paired_wilcoxon_test(_paired_df(), "before", "after")
    assert result["status"] == "ok"
    assert result["significant"] is True
    assert result["n_pairs"] == 30


def test_paired_wilcoxon_missing_column_invalid() -> None:
    result = svc.paired_wilcoxon_test(_paired_df(), "before", "nope")
    assert result["status"] == "invalid_input"
    assert "not found" in str(result["reason"])


def test_paired_wilcoxon_same_column_invalid() -> None:
    result = svc.paired_wilcoxon_test(_paired_df(), "before", "before")
    assert result["status"] == "invalid_input"
    assert "different" in str(result["reason"])


def test_paired_wilcoxon_non_numeric_invalid() -> None:
    result = svc.paired_wilcoxon_test(_paired_df(), "before", "label")
    assert result["status"] == "invalid_input"
    assert "numeric" in str(result["reason"])


def test_paired_wilcoxon_invalid_alternative() -> None:
    result = svc.paired_wilcoxon_test(_paired_df(), "before", "after", alternative="up")
    assert result["status"] == "invalid_input"


def test_paired_wilcoxon_scipy_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from data_quality_toolkit.domain.statistics import inferential

    monkeypatch.setattr(inferential, "_import_scipy_stats", lambda: None)
    result = svc.paired_wilcoxon_test(_paired_df(), "before", "after")
    assert result["status"] == "unavailable"
    assert result["scipy_available"] is False


@pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1])
def test_paired_wilcoxon_invalid_alpha_raises(alpha: float) -> None:
    with pytest.raises(ValueError, match="alpha"):
        svc.paired_wilcoxon_test(_paired_df(), "before", "after", alpha=alpha)
