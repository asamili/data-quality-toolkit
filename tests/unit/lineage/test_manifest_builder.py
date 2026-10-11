"""Unit tests for lineage manifest builder."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

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


# ---------------------------------------------------------------------------
# build_manifest: a rebuild must not discard evidence the manifest records
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _populated_manifest(
    session_dir: Path,
    *,
    datasets: list[Dataset] | None = None,
    artifacts: list[Artifact] | None = None,
    gates: Gates | None = None,
) -> Path:
    """Write a populated manifest through the real producer; return its path."""
    from data_quality_toolkit.lineage.manifest.builder import build_and_write

    build_and_write(
        session_dir.name,
        session_dir,
        (
            datasets
            if datasets is not None
            else [Dataset(kind="bronze", path="raw/in.csv", rows=4, content_hash="")]
        ),
        artifacts if artifacts is not None else [Artifact(kind="star", path="star/d.csv", bytes=5)],
        rows_in=4,
        rows_out=4,
        health=0.83,
        gates=gates,
    )
    return session_dir / "artifacts.json"


def _lineage(*events: dict[str, Any]) -> str:
    return "\n".join(json.dumps(event) for event in events)


class TestRebuildEvidenceGuard:
    def test_lineage_less_rebuild_is_refused_and_manifest_is_byte_identical(
        self, tmp_path: Path
    ) -> None:
        from data_quality_toolkit.lineage.manifest.builder import (
            ManifestRebuildRefusedError,
            build_manifest,
        )

        session_dir = tmp_path / "run-guard"
        manifest_path = _populated_manifest(session_dir)
        before = _sha256(manifest_path)
        entries_before = sorted(p.name for p in session_dir.iterdir())

        with pytest.raises(ManifestRebuildRefusedError) as excinfo:
            build_manifest("run-guard", tmp_path)

        assert _sha256(manifest_path) == before
        # Refused before writing: no temp file was ever created next to it.
        assert sorted(p.name for p in session_dir.iterdir()) == entries_before
        data = json.loads(manifest_path.read_bytes())
        assert len(data["datasets"]) == 1
        assert len(data["artifacts"]) == 1
        assert data["summary"]["health"] == pytest.approx(0.83)
        assert excinfo.value.metadata == {"lost_evidence": ["datasets", "artifacts"]}

    def test_refusal_is_a_bounded_path_free_error(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import (
            ManifestRebuildRefusedError,
            build_manifest,
        )
        from data_quality_toolkit.shared.error_contract import to_error_info
        from data_quality_toolkit.shared.exceptions import DQTError

        _populated_manifest(tmp_path / "run-bounded")
        with pytest.raises(ManifestRebuildRefusedError) as excinfo:
            build_manifest("run-bounded", tmp_path)

        exc = excinfo.value
        assert isinstance(exc, DQTError)
        assert isinstance(exc, ValueError)  # CLI reports it via its ValueError handler
        info = to_error_info(exc)
        assert info["code"] == "MANIFESTREBUILDREFUSEDERROR"
        assert info["message"].startswith("Manifest rebuild refused:")
        assert "left unchanged" in info["message"]
        assert str(tmp_path) not in info["message"]
        assert str(tmp_path) not in (exc.hint or "")

    def test_empty_lineage_log_is_not_evidence(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import (
            ManifestRebuildRefusedError,
            build_manifest,
        )

        session_dir = _make_session(tmp_path, "run-empty-log")
        manifest_path = _populated_manifest(session_dir)
        before = _sha256(manifest_path)

        with pytest.raises(ManifestRebuildRefusedError):
            build_manifest("run-empty-log", tmp_path)
        assert _sha256(manifest_path) == before

    def test_rebuild_with_recorded_lineage_replaces_manifest(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_manifest

        run_id = "run-legit"
        session_dir = _make_session(
            tmp_path,
            run_id,
            lineage_content=_lineage(
                {"type": "DATASET", "path": f"{run_id}/data.csv", "kind": "gold"},
                {"type": "ARTIFACT", "path": f"{run_id}/star/fact.csv", "kind": "star"},
            ),
        )
        # Counts differ from the existing manifest; that alone is not a downgrade.
        manifest_path = _populated_manifest(
            session_dir,
            artifacts=[Artifact(kind="star", path=f"star/{n}.csv") for n in ("a", "b", "c")],
        )
        before = _sha256(manifest_path)

        result = build_manifest(run_id, tmp_path)

        assert _sha256(manifest_path) != before
        data = json.loads(manifest_path.read_bytes())
        assert [d["path"] for d in data["datasets"]] == ["data.csv"]
        assert [a["path"] for a in data["artifacts"]] == ["star/fact.csv"]
        assert result.datasets[0].kind == "gold"

    def test_first_creation_without_existing_manifest_succeeds(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_manifest

        (tmp_path / "run-first").mkdir()
        result = build_manifest("run-first", tmp_path)

        assert result.datasets == []
        assert result.artifacts == []
        assert (tmp_path / "run-first" / "artifacts.json").exists()

    def test_existing_empty_manifest_can_be_rebuilt_empty(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_manifest

        manifest_path = _populated_manifest(tmp_path / "run-was-empty", datasets=[], artifacts=[])

        result = build_manifest("run-was-empty", tmp_path)

        assert result.artifacts == []
        assert json.loads(manifest_path.read_bytes())["summary"]["health"] is None

    def test_dropping_gate_evidence_is_refused(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import (
            ManifestRebuildRefusedError,
            build_manifest,
        )

        run_id = "run-gates"
        session_dir = _make_session(
            tmp_path,
            run_id,
            lineage_content=_lineage(
                {"type": "DATASET", "path": f"{run_id}/raw/in.csv", "kind": "bronze"}
            ),
        )
        manifest_path = _populated_manifest(session_dir, artifacts=[], gates=Gates(status="failed"))
        before = _sha256(manifest_path)

        with pytest.raises(ManifestRebuildRefusedError) as excinfo:
            build_manifest(run_id, tmp_path)

        assert excinfo.value.metadata == {"lost_evidence": ["gates"]}
        assert _sha256(manifest_path) == before

    def test_dropping_artifact_provenance_is_refused(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import (
            ManifestRebuildRefusedError,
            build_manifest,
        )

        run_id = "run-prov"
        session_dir = _make_session(
            tmp_path,
            run_id,
            lineage_content=_lineage(
                {"type": "DATASET", "path": f"{run_id}/raw/in.csv", "kind": "bronze"},
                {"type": "ARTIFACT", "path": f"{run_id}/star/d.csv", "kind": "star"},
            ),
        )
        manifest_path = _populated_manifest(
            session_dir,
            artifacts=[Artifact(kind="star", path="star/d.csv", meta={"source_origin": "m"})],
        )
        before = _sha256(manifest_path)

        with pytest.raises(ManifestRebuildRefusedError) as excinfo:
            build_manifest(run_id, tmp_path)

        assert excinfo.value.metadata == {"lost_evidence": ["provenance"]}
        assert _sha256(manifest_path) == before

    def test_lineage_carrying_provenance_keeps_rebuild_available(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_manifest

        run_id = "run-prov-ok"
        session_dir = _make_session(
            tmp_path,
            run_id,
            lineage_content=_lineage(
                {"type": "DATASET", "path": f"{run_id}/raw/in.csv", "kind": "bronze"},
                {
                    "type": "ARTIFACT",
                    "path": f"{run_id}/star/d.csv",
                    "kind": "star",
                    "meta": {"source_origin": "m"},
                },
            ),
        )
        _populated_manifest(
            session_dir,
            artifacts=[Artifact(kind="star", path="star/d.csv", meta={"source_origin": "m"})],
        )

        result = build_manifest(run_id, tmp_path)

        assert result.artifacts[0].meta == {"source_origin": "m"}

    def test_invalid_existing_content_remains_repairable(self, tmp_path: Path) -> None:
        from data_quality_toolkit.lineage.manifest.builder import build_manifest

        session_dir = tmp_path / "run-corrupt"
        session_dir.mkdir()
        (session_dir / "artifacts.json").write_text("{not valid json", encoding="utf-8")

        build_manifest("run-corrupt", tmp_path)

        assert json.loads((session_dir / "artifacts.json").read_bytes())["run_id"] == "run-corrupt"

    def test_configured_manifest_file_is_written_and_protected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from data_quality_toolkit.lineage.manifest.builder import (
            ManifestRebuildRefusedError,
            build_manifest,
            resolve_manifest_path,
        )
        from data_quality_toolkit.shared.settings import settings

        monkeypatch.setattr(settings, "manifest_file", "lineage_index.json")
        session_dir = tmp_path / "run-custom"
        _populated_manifest(session_dir)
        manifest_path = session_dir / "lineage_index.json"
        assert resolve_manifest_path(session_dir) == manifest_path
        assert sorted(p.name for p in session_dir.iterdir()) == ["lineage_index.json"]
        before = _sha256(manifest_path)

        with pytest.raises(ManifestRebuildRefusedError):
            build_manifest("run-custom", tmp_path)

        assert _sha256(manifest_path) == before
        assert not (session_dir / "artifacts.json").exists()

    def test_real_export_manifest_is_protected_from_lineage_less_rebuild(
        self, tmp_path: Path
    ) -> None:
        from data_quality_toolkit.application.workflow.pipeline import run_export_star
        from data_quality_toolkit.lineage.manifest.builder import (
            ManifestRebuildRefusedError,
            build_manifest,
        )

        csv_path = tmp_path / "in.csv"
        csv_path.write_text("a,b\n1,x\n2,y\n3,\n", encoding="utf-8")
        out_dir = tmp_path / "sessions" / "run-export"
        run_export_star(str(csv_path), output_dir=str(out_dir), emit_manifest=True)
        manifest_path = out_dir / "artifacts.json"
        before = _sha256(manifest_path)
        exported = json.loads(manifest_path.read_bytes())
        assert exported["datasets"] and exported["artifacts"]

        with pytest.raises(ManifestRebuildRefusedError):
            build_manifest("run-export", tmp_path / "sessions")

        assert _sha256(manifest_path) == before
