from __future__ import annotations

import json
from pathlib import Path

from data_quality_toolkit.adapters.storage.jsonl import read_drift_history, read_jsonl_records


def _write_jsonl(path: Path, records: list) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _drift_record(**kwargs) -> dict:
    base = {
        "schema_version": "1",
        "kind": "drift_history_record",
        "run_id": "r1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "baseline_path": "b.csv",
        "current_path": "c.csv",
        "status": "ok",
        "alpha": 0.05,
        "columns_tested": 2,
        "columns_skipped": 0,
        "columns_drifted": 1,
        "drift_detected": True,
        "report_path": None,
    }
    base.update(kwargs)
    return base


# --- read_jsonl_records ---


def test_read_jsonl_records_missing_file(tmp_path: Path) -> None:
    assert read_jsonl_records(tmp_path / "nonexistent.jsonl") == []


def test_read_jsonl_records_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "h.jsonl"
    p.write_text("", encoding="utf-8")
    assert read_jsonl_records(p) == []


def test_read_jsonl_records_single_record(tmp_path: Path) -> None:
    p = tmp_path / "h.jsonl"
    rec = {"kind": "foo", "value": 1}
    _write_jsonl(p, [rec])
    assert read_jsonl_records(p) == [rec]


def test_read_jsonl_records_preserves_order(tmp_path: Path) -> None:
    p = tmp_path / "h.jsonl"
    records = [{"seq": i} for i in range(5)]
    _write_jsonl(p, records)
    assert read_jsonl_records(p) == records


def test_read_jsonl_records_skips_blank_lines(tmp_path: Path) -> None:
    p = tmp_path / "h.jsonl"
    p.write_text('{"a":1}\n\n{"b":2}\n', encoding="utf-8")
    assert read_jsonl_records(p) == [{"a": 1}, {"b": 2}]


def test_read_jsonl_records_skips_malformed_lines(tmp_path: Path) -> None:
    p = tmp_path / "h.jsonl"
    p.write_text('{"a":1}\nnot json\n{"b":2}\n', encoding="utf-8")
    assert read_jsonl_records(p) == [{"a": 1}, {"b": 2}]


# --- read_drift_history ---


def test_read_drift_history_missing_file(tmp_path: Path) -> None:
    assert read_drift_history(tmp_path / "nonexistent.jsonl") == []


def test_read_drift_history_single_record(tmp_path: Path) -> None:
    p = tmp_path / "h.jsonl"
    _write_jsonl(p, [_drift_record()])
    result = read_drift_history(p)
    assert len(result) == 1
    assert result[0]["kind"] == "drift_history_record"


def test_read_drift_history_preserves_order(tmp_path: Path) -> None:
    p = tmp_path / "h.jsonl"
    recs = [_drift_record(run_id=f"r{i}", columns_drifted=i) for i in range(3)]
    _write_jsonl(p, recs)
    result = read_drift_history(p)
    assert [r["run_id"] for r in result] == ["r0", "r1", "r2"]


def test_read_drift_history_filters_non_drift_kinds(tmp_path: Path) -> None:
    p = tmp_path / "h.jsonl"
    drift_rec = _drift_record(run_id="drift-run")
    other_rec = {"kind": "quality_history_record", "run_id": "other-run"}
    _write_jsonl(p, [other_rec, drift_rec, other_rec])
    result = read_drift_history(p)
    assert len(result) == 1
    assert result[0]["run_id"] == "drift-run"


def test_read_drift_history_skips_blank_and_malformed(tmp_path: Path) -> None:
    p = tmp_path / "h.jsonl"
    rec = _drift_record()
    p.write_text(f"\n{json.dumps(rec)}\nnot json\n", encoding="utf-8")
    result = read_drift_history(p)
    assert len(result) == 1
