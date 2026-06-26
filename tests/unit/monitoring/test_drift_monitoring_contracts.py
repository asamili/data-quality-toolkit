"""Focused G27H-A drift-monitoring contract tests.

Covers the additive ``RunRow.alpha`` projection and the contract-level
missing-probability formatting helper. No database, no Streamlit.
"""

from __future__ import annotations

import data_quality_toolkit.adapters.ui.services.monitoring as svc
from data_quality_toolkit.application.monitoring import view_model as vm

# --- RunRow.alpha additive projection ----------------------------------------


def test_alpha_projected_when_authoritative():
    row = vm.RunRow.from_row({"run_id": "r1", "alpha": 0.05})
    assert row.alpha == 0.05


def test_alpha_none_when_key_absent():
    row = vm.RunRow.from_row({"run_id": "r1"})
    assert row.alpha is None


def test_alpha_none_when_explicit_null():
    row = vm.RunRow.from_row({"run_id": "r1", "alpha": None})
    assert row.alpha is None


def test_alpha_none_when_invalid_not_fabricated():
    row = vm.RunRow.from_row({"run_id": "r1", "alpha": "oops"})
    assert row.alpha is None


def test_alpha_included_additively_in_to_dict():
    d = vm.RunRow.from_row({"run_id": "r1", "alpha": 0.01}).to_dict()
    assert d["alpha"] == 0.01
    # Additive only — original fields remain present and paths excluded.
    assert "run_id" in d
    assert "baseline_path" not in d
    assert "current_path" not in d
    assert "report_path" not in d


# --- Missing-probability semantics (no zero coercion) ------------------------


def test_missing_probability_is_unavailable_not_zero():
    assert svc.format_probability(None) == "unavailable"


def test_present_probability_formatted():
    assert svc.format_probability(0.0) == "0.0000"  # a real zero is distinct from missing
    assert svc.format_probability(0.25) == "0.2500"
