"""DQT-UX-G8C2C-BT: exact-shape contracts for drift-history SQLite row APIs.

Proves the exported row TypedDicts (DriftRunRow, DriftColumnRow,
DriftDistributionRow) are importable from both the package root and the
``data_quality_toolkit.api`` seam, are listed in both ``__all__`` collections,
and that the three read APIs return rows whose key sets exactly match the
TypedDict contracts. Also pins ``drift_detected`` as int 0/1 (or None), not bool.

These are export-only contracts: the read functions still return
``list[dict[str, Any]]`` at the public seam.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit import (
    DriftColumnRow,
    DriftDistributionRow,
    DriftRunRow,
    import_drift_history_sqlite,
    read_drift_columns_sqlite,
    read_drift_distributions_sqlite,
    read_drift_runs_sqlite,
)
from data_quality_toolkit.adapters.storage.schema import ensure_db

_ROW_TYPES = ["DriftRunRow", "DriftColumnRow", "DriftDistributionRow"]


# --------------------------------------------------------------------------
# Export-surface checks: importable + in __all__ from both paths.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", _ROW_TYPES)
def test_row_type_importable_from_root(name: str) -> None:
    root = importlib.import_module("data_quality_toolkit")
    assert hasattr(root, name), f"{name} missing from data_quality_toolkit"
    assert name in root.__all__, f"{name} missing from data_quality_toolkit.__all__"


@pytest.mark.parametrize("name", _ROW_TYPES)
def test_row_type_importable_from_api_seam(name: str) -> None:
    api = importlib.import_module("data_quality_toolkit.api")
    assert hasattr(api, name), f"{name} missing from data_quality_toolkit.api"
    assert name in api.__all__, f"{name} missing from data_quality_toolkit.api.__all__"


@pytest.mark.parametrize("name", _ROW_TYPES)
def test_row_type_same_object_from_both_paths(name: str) -> None:
    root = importlib.import_module("data_quality_toolkit")
    api = importlib.import_module("data_quality_toolkit.api")
    assert getattr(root, name) is getattr(api, name)


# --------------------------------------------------------------------------
# Fixtures: build a temporary SQLite drift-history DB under tmp_path.
# --------------------------------------------------------------------------
def _column(column: str, *, drift_detected: bool) -> dict[str, Any]:
    return {
        "column": column,
        "kind": "numeric",
        "test": "ks",
        "statistic": 0.4,
        "p_value": 0.001,
        "drift_detected": drift_detected,
        "reference_n": 60,
        "current_n": 60,
        "status": "tested",
        "skip_reason": None,
        "interpretation": "drift",
        "psi": 0.3,
        "js_distance": 0.2,
        "wasserstein": 1.1,
        "distribution": {
            "kind": "numeric",
            "bins": [
                {"label": "[-inf, 1.5)", "reference": 0.6, "current": 0.4},
                {"label": "[1.5, inf)", "reference": 0.4, "current": 0.6},
            ],
        },
    }


def _write_report(path: Path, columns: list[dict[str, Any]], *, run_id: str) -> None:
    envelope = {
        "schema_version": "3",
        "kind": "drift_report",
        "run_id": run_id,
        "created_at": "2026-06-13T00:00:00+00:00",
        "baseline_path": "a",
        "current_path": "b",
        "result": {"status": "ok", "columns": columns},
    }
    path.write_text(json.dumps(envelope), encoding="utf-8")


def _drift_record(report_path: str, *, run_id: str, drift_detected: bool | None) -> str:
    record = {
        "schema_version": "1",
        "kind": "drift_history_record",
        "run_id": run_id,
        "created_at": "2026-06-13T00:00:00+00:00",
        "baseline_path": "a",
        "current_path": "b",
        "baseline_dataset_id": "1",
        "current_dataset_id": "2",
        "status": "detected",
        "alpha": 0.05,
        "columns_tested": 1,
        "columns_skipped": 0,
        "columns_drifted": 1,
        "drift_detected": drift_detected,
        "report_path": report_path,
    }
    return json.dumps(record) + "\n"


def _build_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "drift.db"
    ensure_db(db_path)
    report = tmp_path / "r1.json"
    _write_report(report, [_column("age", drift_detected=True)], run_id="r1")
    history = tmp_path / "history.jsonl"
    history.write_text(
        _drift_record(str(report), run_id="r1", drift_detected=True),
        encoding="utf-8",
    )
    import_drift_history_sqlite(db_path, history)
    return db_path


# --------------------------------------------------------------------------
# Exact key-set contracts: row dict keys == TypedDict annotations.
# --------------------------------------------------------------------------
def test_drift_runs_row_key_set(tmp_path: Path) -> None:
    db_path = _build_db(tmp_path)
    rows = read_drift_runs_sqlite(db_path)
    assert len(rows) == 1
    assert set(rows[0].keys()) == set(DriftRunRow.__annotations__)


def test_drift_columns_row_key_set(tmp_path: Path) -> None:
    db_path = _build_db(tmp_path)
    rows = read_drift_columns_sqlite(db_path)
    assert len(rows) == 1
    assert set(rows[0].keys()) == set(DriftColumnRow.__annotations__)


def test_drift_distributions_row_key_set(tmp_path: Path) -> None:
    db_path = _build_db(tmp_path)
    rows = read_drift_distributions_sqlite(db_path)
    assert len(rows) == 2
    assert set(rows[0].keys()) == set(DriftDistributionRow.__annotations__)


# --------------------------------------------------------------------------
# drift_detected is int 0/1 (or None), NOT bool.
# (bool is a subclass of int, so isinstance(..., int) is not enough.)
# --------------------------------------------------------------------------
def test_drift_runs_drift_detected_is_int_not_bool(tmp_path: Path) -> None:
    db_path = _build_db(tmp_path)
    value = read_drift_runs_sqlite(db_path)[0]["drift_detected"]
    assert isinstance(value, int) and not isinstance(value, bool)
    assert value == 1


def test_drift_columns_drift_detected_is_int_not_bool(tmp_path: Path) -> None:
    db_path = _build_db(tmp_path)
    value = read_drift_columns_sqlite(db_path)[0]["drift_detected"]
    assert isinstance(value, int) and not isinstance(value, bool)
    assert value in (0, 1)


def test_drift_runs_drift_detected_none_preserved(tmp_path: Path) -> None:
    db_path = tmp_path / "drift.db"
    ensure_db(db_path)
    report = tmp_path / "rn.json"
    _write_report(report, [_column("age", drift_detected=True)], run_id="rn")
    history = tmp_path / "history.jsonl"
    history.write_text(
        _drift_record(str(report), run_id="rn", drift_detected=None),
        encoding="utf-8",
    )
    import_drift_history_sqlite(db_path, history)

    assert read_drift_runs_sqlite(db_path)[0]["drift_detected"] is None
