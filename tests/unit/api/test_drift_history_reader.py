from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from data_quality_toolkit.api import detect_drift, read_drift_history
from data_quality_toolkit.domain.statistics import drift


class FakeStats:
    def ks_2samp(self, a: Any, b: Any) -> SimpleNamespace:
        return SimpleNamespace(statistic=0.42, pvalue=0.001)

    def chi2_contingency(self, table: Any) -> SimpleNamespace:
        arr = np.asarray(table, dtype=float)
        expected = arr.sum(axis=1, keepdims=True) * arr.sum(axis=0, keepdims=True) / arr.sum()
        return SimpleNamespace(statistic=1.23, pvalue=0.8, dof=1, expected_freq=expected)

    def wasserstein_distance(self, a: Any, b: Any) -> float:
        return 0.5


def _write_csv(path: Path, x_offset: float = 0.0) -> Path:
    lines = ["x,category"]
    for i in range(60):
        cat = "a" if i % 2 == 0 else "b"
        lines.append(f"{i + x_offset},{cat}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_read_drift_history_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_drift_history(tmp_path / "nonexistent.jsonl") == []


def test_read_drift_history_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drift, "_import_scipy_stats", lambda: FakeStats())
    baseline = _write_csv(tmp_path / "baseline.csv")
    current = _write_csv(tmp_path / "current.csv", x_offset=100.0)
    hist = tmp_path / "drift_history.jsonl"

    result = detect_drift(baseline, current, history_path=hist)
    records = read_drift_history(hist)

    assert len(records) == 1
    rec = records[0]
    assert rec["run_id"]  # non-empty uuid hex
    assert rec["status"] == "ok"
    assert rec["drift_detected"] == result["summary"]["drift_detected"]
    assert rec["columns_tested"] == result["summary"]["columns_tested"]
    assert rec["columns_drifted"] == result["summary"]["columns_drifted"]
    assert rec["columns_skipped"] == result["summary"]["columns_skipped"]


def test_read_drift_history_multiple_runs_accumulate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drift, "_import_scipy_stats", lambda: FakeStats())
    baseline = _write_csv(tmp_path / "baseline.csv")
    current = _write_csv(tmp_path / "current.csv")
    hist = tmp_path / "drift_history.jsonl"

    detect_drift(baseline, current, history_path=hist)
    detect_drift(baseline, current, history_path=hist)
    records = read_drift_history(hist)

    assert len(records) == 2
    assert records[0]["run_id"] != records[1]["run_id"]
