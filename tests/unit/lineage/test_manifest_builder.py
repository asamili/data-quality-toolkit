"""Unit tests for lineage manifest builder."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from data_quality_toolkit.lineage.manifest.schemas import (
    Artifact,
    Dataset,
    Gates,
    StepSummary,
)


def _make_session(tmp_path: Path, run_id: str, lineage_content: str = "") -> Path:
    """Create minimal session directory with meta/lineage.jsonl."""
    session_dir = tmp_path / run_id
    meta = session_dir / "meta"
    meta.mkdir(parents=True)
    (meta / "lineage.jsonl").write_text(lineage_content, encoding="utf-8")
    return session_dir


def _write_gates(session_dir: Path, events: list[dict]) -> None:
    text = "\n".join(json.dumps(e) for e in events)
    (session_dir / "meta" / "gates.jsonl").write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# build_manifest (public entry point)
# ---------------------------------------------------------------------------


class TestBuildManifest:
    def test_returns_manifest_with_correct_run_id(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_manifest

        _make_session(tmp_path, "run-001")
        result = build_manifest("run-001", tmp_path)
        assert result.run_id == "run-001"

    def test_schema_version_populated(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_manifest

        _make_session(tmp_path, "run-002")
        result = build_manifest("run-002", tmp_path)
        assert result.schema_version is not None
        assert len(result.schema_version) > 0

    def test_created_at_is_aware_datetime(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_manifest

        _make_session(tmp_path, "run-003")
        result = build_manifest("run-003", tmp_path)
        assert isinstance(result.created_at, datetime)
        assert result.created_at.tzinfo is not None

    def test_creates_artifacts_json_file(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_manifest

        _make_session(tmp_path, "run-004")
        build_manifest("run-004", tmp_path)
        assert (tmp_path / "run-004" / "artifacts.json").exists()

    def test_artifacts_json_is_valid_json(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_manifest

        _make_session(tmp_path, "run-005")
        build_manifest("run-005", tmp_path)
        data = json.loads((tmp_path / "run-005" / "artifacts.json").read_bytes())
        for key in ("run_id", "schema_version", "datasets", "artifacts", "summary", "gates"):
            assert key in data

    def test_empty_session_has_no_datasets_or_artifacts(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_manifest

        _make_session(tmp_path, "run-006")
        result = build_manifest("run-006", tmp_path)
        assert result.datasets == []
        assert result.artifacts == []

    def test_gates_skipped_when_no_gates_file(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_manifest

        _make_session(tmp_path, "run-007")
        result = build_manifest("run-007", tmp_path)
        assert result.gates.status == "skipped"
        assert result.gates.failures == []

    def test_gates_failed_from_error_event(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_manifest

        run_id = "run-008"
        session_dir = _make_session(tmp_path, run_id)
        _write_gates(
            session_dir,
            [
                {
                    "gate": "post",
                    "status": "failed",
                    "severity": "error",
                    "code": "E001",
                    "timestamp": "2025-01-01T00:00:00Z",
                }
            ],
        )
        result = build_manifest(run_id, tmp_path)
        assert result.gates.status == "failed"
        assert result.gates.failures[0].code == "E001"

    def test_datasets_collected_from_lineage(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_manifest

        run_id = "run-009"
        event = json.dumps({"type": "DATASET", "path": f"{run_id}/data.csv", "kind": "gold"})
        _make_session(tmp_path, run_id, lineage_content=event)
        result = build_manifest(run_id, tmp_path)
        assert len(result.datasets) == 1
        assert result.datasets[0].kind == "gold"

    def test_accepts_sessions_root_as_string(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_manifest

        _make_session(tmp_path, "run-010")
        result = build_manifest("run-010", str(tmp_path))
        assert result.run_id == "run-010"


# ---------------------------------------------------------------------------
# build_and_write (direct)
# ---------------------------------------------------------------------------


class TestBuildAndWrite:
    def test_minimal_call_returns_manifest(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_and_write

        session_dir = tmp_path / "run-baw"
        session_dir.mkdir()
        result = build_and_write(
            run_id="run-baw", session_dir=session_dir, datasets=[], artifacts=[]
        )
        assert result.run_id == "run-baw"

    def test_creates_artifacts_json(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_and_write

        session_dir = tmp_path / "run-baw2"
        session_dir.mkdir()
        build_and_write(run_id="run-baw2", session_dir=session_dir, datasets=[], artifacts=[])
        assert (session_dir / "artifacts.json").exists()

    def test_datasets_and_artifacts_in_result(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_and_write

        session_dir = tmp_path / "run-rich"
        session_dir.mkdir()
        ds = [Dataset(kind="silver", path="data/clean.csv")]
        art = [Artifact(kind="star", path="dist/star.csv")]
        result = build_and_write("run-rich", session_dir, ds, art)
        assert result.datasets[0].kind == "silver"
        assert result.artifacts[0].kind == "star"

    def test_bytes_total_computed_from_items_when_zero(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_and_write

        session_dir = tmp_path / "run-bt"
        session_dir.mkdir()
        ds = [Dataset(kind="bronze", path="d.csv", bytes=100)]
        art = [Artifact(kind="star", path="a.csv", bytes=200)]
        result = build_and_write("run-bt", session_dir, ds, art, bytes_total=0)
        assert result.summary.bytes_total == 300

    def test_explicit_bytes_total_used_when_nonzero(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_and_write

        session_dir = tmp_path / "run-bt2"
        session_dir.mkdir()
        result = build_and_write("run-bt2", session_dir, [], [], bytes_total=999)
        assert result.summary.bytes_total == 999

    def test_steps_summary_populated(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_and_write

        session_dir = tmp_path / "run-steps"
        session_dir.mkdir()
        steps = StepSummary(total=5, succeeded=4, failed=1)
        result = build_and_write("run-steps", session_dir, [], [], steps_summary=steps)
        assert result.summary.steps.total == 5
        assert result.summary.steps.failed == 1

    def test_explicit_gates_used(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_and_write

        session_dir = tmp_path / "run-gp"
        session_dir.mkdir()
        gates = Gates(status="passed")
        result = build_and_write("run-gp", session_dir, [], [], gates=gates)
        assert result.gates.status == "passed"

    def test_rows_in_out_populated(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_and_write

        session_dir = tmp_path / "run-rows"
        session_dir.mkdir()
        result = build_and_write("run-rows", session_dir, [], [], rows_in=100, rows_out=80)
        assert result.summary.rows_in == 100
        assert result.summary.rows_out == 80

    def test_health_populated(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_and_write

        session_dir = tmp_path / "run-health"
        session_dir.mkdir()
        result = build_and_write("run-health", session_dir, [], [], health=0.95)
        assert result.summary.health == pytest.approx(0.95)

    def test_output_json_uses_schema_alias(self, tmp_path: Path) -> None:
        """artifacts.json must use 'schema' alias not 'schema_' for Dataset."""
        from data_quality_toolkit.lineage.manifest.builder import build_and_write

        session_dir = tmp_path / "run-alias"
        session_dir.mkdir()
        ds = [Dataset(kind="bronze", path="raw.csv")]
        build_and_write("run-alias", session_dir, ds, [])
        data = json.loads((session_dir / "artifacts.json").read_bytes())
        assert "schema" in data["datasets"][0]
        assert "schema_" not in data["datasets"][0]

    def test_datasets_sorted_by_kind_then_path(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_and_write

        session_dir = tmp_path / "run-sort"
        session_dir.mkdir()
        ds = [
            Dataset(kind="gold", path="b.csv"),
            Dataset(kind="bronze", path="a.csv"),
            Dataset(kind="gold", path="a.csv"),
        ]
        result = build_and_write("run-sort", session_dir, ds, [])
        kinds = [d.kind for d in result.datasets]
        paths = [d.path for d in result.datasets]
        assert kinds == ["bronze", "gold", "gold"]
        assert paths == ["a.csv", "a.csv", "b.csv"]


# ---------------------------------------------------------------------------
# _atomic_write_json
# ---------------------------------------------------------------------------


class TestAtomicWriteJson:
    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _atomic_write_json

        deep = tmp_path / "a" / "b" / "c" / "out.json"
        _atomic_write_json(deep, {"key": "value"})
        assert deep.exists()
        assert json.loads(deep.read_bytes())["key"] == "value"

    def test_output_is_valid_sorted_json(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _atomic_write_json

        out = tmp_path / "sorted.json"
        _atomic_write_json(out, {"z": 1, "a": 2, "m": 3})
        data = json.loads(out.read_bytes())
        assert data == {"z": 1, "a": 2, "m": 3}

    def test_overwrite_existing_file(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _atomic_write_json

        out = tmp_path / "existing.json"
        _atomic_write_json(out, {"v": 1})
        _atomic_write_json(out, {"v": 2})
        assert json.loads(out.read_bytes())["v"] == 2

    def test_orjson_path_if_available(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        orjson = pytest.importorskip("orjson")
        import data_quality_toolkit.lineage.manifest.builder as builder_mod

        monkeypatch.setattr(builder_mod.settings, "json_writer", "orjson")
        monkeypatch.setattr(builder_mod, "orjson", orjson)
        from data_quality_toolkit.lineage.manifest.builder import _atomic_write_json

        out = tmp_path / "orjson.json"
        _atomic_write_json(out, {"key": "val"})
        assert out.exists()
        assert json.loads(out.read_bytes())["key"] == "val"


# ---------------------------------------------------------------------------
# _read_gates
# ---------------------------------------------------------------------------


class TestReadGates:
    def test_no_gates_file_returns_skipped(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _read_gates

        session_dir = tmp_path / "rg-001"
        session_dir.mkdir()
        assert _read_gates(session_dir).status == "skipped"

    def test_empty_gates_file_returns_passed(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _read_gates

        session_dir = tmp_path / "rg-002"
        meta = session_dir / "meta"
        meta.mkdir(parents=True)
        (meta / "gates.jsonl").write_text("", encoding="utf-8")
        assert _read_gates(session_dir).status == "passed"

    def test_error_failed_event_returns_failed(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _read_gates

        session_dir = tmp_path / "rg-003"
        meta = session_dir / "meta"
        meta.mkdir(parents=True)
        (meta / "gates.jsonl").write_text(
            json.dumps(
                {
                    "gate": "pre",
                    "status": "failed",
                    "severity": "error",
                    "code": "G001",
                    "timestamp": "2025-01-01T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        gates = _read_gates(session_dir)
        assert gates.status == "failed"
        assert len(gates.failures) == 1
        assert gates.failures[0].code == "G001"

    def test_warn_failed_event_not_counted_as_error(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _read_gates

        session_dir = tmp_path / "rg-004"
        meta = session_dir / "meta"
        meta.mkdir(parents=True)
        (meta / "gates.jsonl").write_text(
            json.dumps(
                {
                    "gate": "pre",
                    "status": "failed",
                    "severity": "warn",
                    "code": "W001",
                    "timestamp": "2025-01-01T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        # warn+failed is NOT error+failed → no error_failed flag
        assert _read_gates(session_dir).status == "passed"

    def test_malformed_json_line_skipped(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _read_gates

        session_dir = tmp_path / "rg-005"
        meta = session_dir / "meta"
        meta.mkdir(parents=True)
        (meta / "gates.jsonl").write_text("not-json\n", encoding="utf-8")
        assert _read_gates(session_dir).status == "passed"

    def test_unknown_phase_error_failed_sets_status_failed_no_failure_object(
        self, tmp_path: Path
    ) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _read_gates

        session_dir = tmp_path / "rg-006"
        meta = session_dir / "meta"
        meta.mkdir(parents=True)
        # gate="unknown" → _coerce_phase returns None → is_failed=True, failure=None
        (meta / "gates.jsonl").write_text(
            json.dumps(
                {
                    "gate": "unknown_phase",
                    "status": "failed",
                    "severity": "error",
                    "code": "E002",
                    "timestamp": "2025-01-01T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        gates = _read_gates(session_dir)
        assert gates.status == "failed"
        # failure object not created for unknown phase
        assert gates.failures == []

    def test_multiple_events_mixed(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _read_gates

        session_dir = tmp_path / "rg-007"
        meta = session_dir / "meta"
        meta.mkdir(parents=True)
        events = [
            {
                "gate": "pre",
                "status": "passed",
                "severity": "warn",
                "code": "OK",
                "timestamp": "2025-01-01T00:00:00Z",
            },
            {
                "gate": "post",
                "status": "failed",
                "severity": "error",
                "code": "E999",
                "timestamp": "2025-01-01T00:01:00Z",
            },
        ]
        (meta / "gates.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events), encoding="utf-8"
        )
        gates = _read_gates(session_dir)
        assert gates.status == "failed"
        assert any(f.code == "E999" for f in gates.failures)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


class TestParseIsoUtc:
    def test_z_suffix_parsed(self) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _parse_iso_utc

        dt = _parse_iso_utc("2025-01-01T00:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_offset_suffix_parsed(self) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _parse_iso_utc

        dt = _parse_iso_utc("2025-01-01T00:00:00+00:00")
        assert dt is not None

    def test_empty_returns_none(self) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _parse_iso_utc

        assert _parse_iso_utc("") is None

    def test_invalid_returns_none(self) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _parse_iso_utc

        assert _parse_iso_utc("not-a-date") is None


class TestCoercePhase:
    def test_valid_phases(self) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _coerce_phase

        assert _coerce_phase("pre") == "pre"
        assert _coerce_phase("post") == "post"
        assert _coerce_phase("publish") == "publish"

    def test_case_insensitive(self) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _coerce_phase

        assert _coerce_phase("PRE") == "pre"

    def test_unknown_returns_none(self) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _coerce_phase

        assert _coerce_phase("invalid") is None


class TestCoerceSeverity:
    def test_error(self) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _coerce_severity

        assert _coerce_severity("error") == "error"

    def test_warn(self) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _coerce_severity

        assert _coerce_severity("warn") == "warn"

    def test_warning_normalized_to_warn(self) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _coerce_severity

        assert _coerce_severity("warning") == "warn"

    def test_unknown_returns_none(self) -> None:
        from data_quality_toolkit.lineage.manifest.builder import _coerce_severity

        assert _coerce_severity("critical") is None
