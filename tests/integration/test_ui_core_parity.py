"""UI <-> core profiling parity guardrail.

Both the Streamlit dashboard (_run_assess_csv) and the core Python API
(api.assess_csv) route through the same hardened load_csv -> run_profiling ->
assess pipeline. This test pins that agreement on stable fields and confirms
assessment output (score, issues) matches between surfaces.

Assertions are limited to deterministic fields. Volatile fields (run_id, ts)
are intentionally excluded.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit.shared.result_types import AssessCsvResult

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


def _column_index(columns: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
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
    """Reproduce the dashboard's assessment path exactly (ui.services.assessment._run_assess_csv)."""
    from data_quality_toolkit.adapters.ui.services.assessment import _run_assess_csv

    out: dict[str, Any] | None
    err: str | None
    out, err = _run_assess_csv(str(csv))
    assert err is None and out is not None, f"UI _run_assess_csv failed: {err}"
    return out


def _core_assess(csv: Path) -> AssessCsvResult:
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


def test_compare_ui_service_matches_workflow(tmp_path: Path) -> None:
    """UI _run_compare service and workflow compare_last_two_runs agree on the same history."""
    import json

    star_dir = tmp_path / "star"
    star_dir.mkdir()
    history_path = star_dir / "quality_history.jsonl"

    run1 = {
        "run_id": "r1",
        "dataset_id": "sha1:abc",
        "score": 0.8,
        "issues_total": 5,
        "issues_by_severity": {"warn": 3, "error": 2},
        "issues_by_category": {"nulls": 5},
        "completeness_score": 0.8,
        "quality_score": 0.8,
        "ts": "2025-01-01T00:00:00",
    }
    run2 = {
        "run_id": "r2",
        "dataset_id": "sha1:abc",
        "score": 0.9,
        "issues_total": 2,
        "issues_by_severity": {"warn": 1, "error": 1},
        "issues_by_category": {"nulls": 2},
        "completeness_score": 0.9,
        "quality_score": 0.9,
        "ts": "2025-01-02T00:00:00",
    }
    history_path.write_text(json.dumps(run1) + "\n" + json.dumps(run2) + "\n", encoding="utf-8")

    # dqt.db does not exist — compare_last_two_runs falls back to JSONL
    fake_db = str(tmp_path / "dqt.db")

    from data_quality_toolkit.adapters.ui.services.compare import _run_compare
    from data_quality_toolkit.application.workflow.compare import compare_last_two_runs

    ui_result, ui_err = _run_compare(fake_db, "sha1:abc")
    core_result = compare_last_two_runs("sha1:abc", history_path)

    assert ui_err is None, f"UI compare failed: {ui_err}"
    assert ui_result is not None
    assert ui_result["score_delta"] == pytest.approx(core_result["score_delta"])
    assert ui_result["issues_delta"] == core_result["issues_delta"]
    assert ui_result["dataset_id"] == core_result["dataset_id"]
    assert ui_result["current_score"] == core_result["current_score"]
    assert ui_result["previous_score"] == core_result["previous_score"]
