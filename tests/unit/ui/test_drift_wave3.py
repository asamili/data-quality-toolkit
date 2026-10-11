"""Focused tests for the Wave 3 drift distribution-comparison download helper."""

from __future__ import annotations

from data_quality_toolkit.adapters.ui.services.monitoring import distribution_comparison_rows
from data_quality_toolkit.application.monitoring.view_model import DistributionBin


def _bin(index: int, label: str, ref: float | None, cur: float | None) -> DistributionBin:
    return DistributionBin(
        column_name="measure",
        kind="numeric",
        bin_index=index,
        bin_label=label,
        reference_prob=ref,
        current_prob=cur,
    )


def test_distribution_comparison_rows_keeps_raw_values() -> None:
    bins = [_bin(0, "low", 0.4, 0.3), _bin(1, "high", 0.6, 0.7)]
    rows = distribution_comparison_rows(bins)
    assert rows == [
        {"bin": "low", "reference_prob": 0.4, "current_prob": 0.3},
        {"bin": "high", "reference_prob": 0.6, "current_prob": 0.7},
    ]


def test_distribution_comparison_rows_preserve_missing_as_none() -> None:
    rows = distribution_comparison_rows([_bin(0, "b0", None, 0.25)])
    assert rows[0]["reference_prob"] is None
    assert rows[0]["current_prob"] == 0.25


def test_distribution_comparison_rows_empty() -> None:
    assert distribution_comparison_rows([]) == []
