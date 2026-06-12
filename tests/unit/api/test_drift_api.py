"""Tests for the detect_drift public API wrapper."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

import data_quality_toolkit
from data_quality_toolkit.api import detect_drift
from data_quality_toolkit.domain.statistics import drift


class FakeStats:
    def ks_2samp(self, a: Any, b: Any) -> SimpleNamespace:
        return SimpleNamespace(statistic=0.42, pvalue=0.001)

    def chi2_contingency(self, table: Any) -> SimpleNamespace:
        arr = np.asarray(table, dtype=float)
        expected = arr.sum(axis=1, keepdims=True) * arr.sum(axis=0, keepdims=True) / arr.sum()
        return SimpleNamespace(statistic=1.23, pvalue=0.8, dof=1, expected_freq=expected)


def _write_csv(path: Path, x_offset: float = 0.0) -> Path:
    lines = ["x,category"]
    for i in range(60):
        cat = "a" if i % 2 == 0 else "b"
        lines.append(f"{i + x_offset},{cat}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_detect_drift_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drift, "_import_scipy_stats", lambda: FakeStats())
    baseline = _write_csv(tmp_path / "baseline.csv")
    current = _write_csv(tmp_path / "current.csv", x_offset=100.0)

    result = detect_drift(baseline, current)

    assert result["status"] == "ok"
    assert result["reference_rows"] == 60
    assert result["current_rows"] == 60
    assert result["baseline_dataset_id"]
    assert result["current_dataset_id"]
    by_name = {c["column"]: c for c in result["columns"]}
    assert by_name["x"]["test"] == "ks"
    assert by_name["x"]["drift_detected"] is True
    assert by_name["category"]["test"] == "chi_square"
    assert by_name["category"]["drift_detected"] is False
    assert result["summary"]["columns_tested"] == 2


def test_detect_drift_unavailable_without_scipy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drift, "_import_scipy_stats", lambda: None)
    baseline = _write_csv(tmp_path / "baseline.csv")
    current = _write_csv(tmp_path / "current.csv")

    result = detect_drift(baseline, current)

    assert result["status"] == "unavailable"
    assert result["scipy_available"] is False
    assert "data-quality-toolkit[stats]" in result["reason"]
    assert result["columns"] == []


def test_detect_drift_alpha_passthrough(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drift, "_import_scipy_stats", lambda: FakeStats())
    baseline = _write_csv(tmp_path / "baseline.csv")
    current = _write_csv(tmp_path / "current.csv")

    result = detect_drift(baseline, current, alpha=0.0005)
    by_name = {c["column"]: c for c in result["columns"]}
    assert result["alpha"] == 0.0005
    assert by_name["x"]["drift_detected"] is False  # fake p=0.001 >= alpha


def test_detect_drift_exported_from_package() -> None:
    assert hasattr(data_quality_toolkit, "detect_drift")
    assert "detect_drift" in data_quality_toolkit.__all__


def test_detect_drift_no_output_path_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drift, "_import_scipy_stats", lambda: FakeStats())
    baseline = _write_csv(tmp_path / "baseline.csv")
    current = _write_csv(tmp_path / "current.csv")

    result = detect_drift(baseline, current)

    assert "output_path" not in result
    assert sorted(p.name for p in tmp_path.iterdir()) == ["baseline.csv", "current.csv"]


def test_detect_drift_output_path_writes_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    monkeypatch.setattr(drift, "_import_scipy_stats", lambda: FakeStats())
    baseline = _write_csv(tmp_path / "baseline.csv")
    current = _write_csv(tmp_path / "current.csv", x_offset=100.0)
    out = tmp_path / "reports" / "drift_report.json"

    result = detect_drift(baseline, current, output_path=out)

    assert result["output_path"] == str(out)
    assert out.exists()
    envelope = json.loads(out.read_text(encoding="utf-8"))
    assert envelope["schema_version"] == "1"
    assert envelope["kind"] == "drift_report"
    assert envelope["run_id"]
    assert envelope["created_at"]
    assert envelope["baseline_path"] == str(baseline)
    assert envelope["current_path"] == str(current)
    # File holds the pure result (no output_path key inside the envelope)
    assert "output_path" not in envelope["result"]
    expected = {k: v for k, v in result.items() if k != "output_path"}
    assert envelope["result"] == expected


def test_detect_drift_output_path_written_when_scipy_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    monkeypatch.setattr(drift, "_import_scipy_stats", lambda: None)
    baseline = _write_csv(tmp_path / "baseline.csv")
    current = _write_csv(tmp_path / "current.csv")
    out = tmp_path / "drift_report.json"

    result = detect_drift(baseline, current, output_path=out)

    assert result["status"] == "unavailable"
    assert out.exists()
    envelope = json.loads(out.read_text(encoding="utf-8"))
    assert envelope["result"]["status"] == "unavailable"
    assert envelope["result"]["scipy_available"] is False


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    import json

    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_detect_drift_no_history_path_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drift, "_import_scipy_stats", lambda: FakeStats())
    baseline = _write_csv(tmp_path / "baseline.csv")
    current = _write_csv(tmp_path / "current.csv")

    result = detect_drift(baseline, current)

    assert "history_path" not in result
    assert sorted(p.name for p in tmp_path.iterdir()) == ["baseline.csv", "current.csv"]


def test_detect_drift_history_path_appends_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drift, "_import_scipy_stats", lambda: FakeStats())
    baseline = _write_csv(tmp_path / "baseline.csv")
    current = _write_csv(tmp_path / "current.csv", x_offset=100.0)
    hist = tmp_path / "history" / "drift_history.jsonl"

    result = detect_drift(baseline, current, history_path=hist)

    assert result["history_path"] == str(hist)
    records = _read_jsonl(hist)
    assert len(records) == 1
    rec = records[0]
    assert rec["schema_version"] == "1"
    assert rec["kind"] == "drift_history_record"
    assert rec["run_id"]
    assert rec["created_at"]
    assert rec["baseline_path"] == str(baseline)
    assert rec["current_path"] == str(current)
    assert rec["baseline_dataset_id"] == result["baseline_dataset_id"]
    assert rec["current_dataset_id"] == result["current_dataset_id"]
    assert rec["status"] == "ok"
    assert rec["alpha"] == result["alpha"]
    assert rec["columns_tested"] == result["summary"]["columns_tested"]
    assert rec["columns_skipped"] == result["summary"]["columns_skipped"]
    assert rec["columns_drifted"] == result["summary"]["columns_drifted"]
    assert rec["drift_detected"] == result["summary"]["drift_detected"]
    assert rec["report_path"] is None


def test_detect_drift_history_appends_one_record_per_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drift, "_import_scipy_stats", lambda: FakeStats())
    baseline = _write_csv(tmp_path / "baseline.csv")
    current = _write_csv(tmp_path / "current.csv")
    hist = tmp_path / "drift_history.jsonl"

    detect_drift(baseline, current, history_path=hist)
    detect_drift(baseline, current, history_path=hist)

    records = _read_jsonl(hist)
    assert len(records) == 2
    assert records[0]["run_id"] != records[1]["run_id"]


def test_detect_drift_history_run_id_matches_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    monkeypatch.setattr(drift, "_import_scipy_stats", lambda: FakeStats())
    baseline = _write_csv(tmp_path / "baseline.csv")
    current = _write_csv(tmp_path / "current.csv")
    out = tmp_path / "drift_report.json"
    hist = tmp_path / "drift_history.jsonl"

    detect_drift(baseline, current, output_path=out, history_path=hist)

    envelope = json.loads(out.read_text(encoding="utf-8"))
    rec = _read_jsonl(hist)[0]
    assert rec["run_id"] == envelope["run_id"]
    assert rec["created_at"] == envelope["created_at"]
    assert rec["report_path"] == str(out)


def test_detect_drift_history_appended_when_scipy_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drift, "_import_scipy_stats", lambda: None)
    baseline = _write_csv(tmp_path / "baseline.csv")
    current = _write_csv(tmp_path / "current.csv")
    hist = tmp_path / "drift_history.jsonl"

    result = detect_drift(baseline, current, history_path=hist)

    assert result["status"] == "unavailable"
    rec = _read_jsonl(hist)[0]
    assert rec["status"] == "unavailable"
    assert rec["columns_tested"] == 0
    assert rec["drift_detected"] is False
