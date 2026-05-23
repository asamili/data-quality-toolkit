"""UI <-> core profiling parity guardrail.

The Streamlit dashboard profiles a CSV via:
    ui.app._load_csv (raw pandas.read_csv) -> profiling_orchestrator.run_profiling

The core pipeline profiles the same CSV via:
    workflow.pipeline.run_profile (loaders.load_csv -> run_profiling)

Both ultimately call run_profiling, so for a plain, well-formed CSV their
profile MATH must agree. This test pins that agreement on stable fields, and
documents the known by-design differences (dataset_id, input-option handling,
and the absence of an assessment/score on the UI path) without touching
production code.

Assertions are limited to deterministic fields. Volatile fields (run_id, ts)
and loader-policy fields (dataset_id) are intentionally excluded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration


def _sample_csv(tmp_path: Path) -> Path:
    """Plain, well-formed CSV with mixed dtypes and nulls in two columns."""
    p = tmp_path / "ui_core.csv"
    p.write_text(
        "id,name,amount,region\n"
        "1,Alice,100.0,North\n"
        "2,Bob,,South\n"
        "3,,200.0,East\n"
        "4,Diana,150.0,\n"
        "5,Eve,175.0,West\n",
        encoding="utf-8",
    )
    return p


def _column_index(columns: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map column name -> {dtype, nulls, unique} for order-independent comparison."""
    return {
        str(c.get("name")): {
            "dtype": str(c.get("dtype")),
            "nulls": c.get("nulls"),
            "unique": c.get("unique"),
        }
        for c in columns
    }


def _ui_assess(csv: Path) -> dict[str, Any]:
    """Reproduce the dashboard's assessment path exactly (ui.app._run_assess_csv)."""
    from data_quality_toolkit.ui.app import _run_assess_csv

    out, err = _run_assess_csv(str(csv))
    assert err is None and out is not None, f"UI _run_assess_csv failed: {err}"
    return out


def _core_assess(csv: Path) -> dict[str, Any]:
    """Core pipeline assessment path (api.assess_csv -> load_csv -> run_profiling -> assess)."""
    from data_quality_toolkit import assess_csv

    return assess_csv(str(csv))


def test_ui_core_profiling_parity(tmp_path: Path) -> None:
    csv = _sample_csv(tmp_path)

    ui_out = _ui_assess(csv)
    core_out = _core_assess(csv)

    ui_prof = ui_out["profile"]
    core_prof = core_out["profile"]

    # --- shape parity ---
    assert ui_prof["rows"] == core_prof["rows"] == 5
    assert ui_prof["cols"] == core_prof["cols"] == 4

    # --- per-column parity: names, dtype, nulls, unique ---
    ui_cols = _column_index(ui_prof["columns"])
    core_cols = _column_index(core_prof["columns"])

    assert set(ui_cols) == set(core_cols), "column name set differs between UI and core"

    for name in core_cols:
        assert ui_cols[name]["dtype"] == core_cols[name]["dtype"], f"dtype mismatch: {name}"
        assert ui_cols[name]["nulls"] == core_cols[name]["nulls"], f"nulls mismatch: {name}"
        assert ui_cols[name]["unique"] == core_cols[name]["unique"], f"unique mismatch: {name}"

    # --- fixture must actually exercise the null path (guard a vacuous pass) ---
    assert ui_cols["name"]["nulls"] == 1
    assert ui_cols["region"]["nulls"] == 1
    assert ui_cols["amount"]["nulls"] == 1

    # --- STRENGTHENED: assessment parity (gap closed) ---
    # Both UI and core now route through api.assess_csv → same pipeline.
    assert "assessment" in ui_out
    assert "assessment" in core_out
    assert ui_out["assessment"]["score"] == pytest.approx(core_out["assessment"]["score"])
    assert len(ui_out["assessment"]["issues"]) == len(core_out["assessment"]["issues"])

    # --- dataset_id now matches: both use sha1 hash from load_csv ---
    assert ui_out["dataset_id"] == core_out["dataset_id"]
    assert ui_out["dataset_id"].startswith("sha1:")
