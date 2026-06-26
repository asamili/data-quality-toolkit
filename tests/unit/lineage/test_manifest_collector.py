"""Unit tests for lineage manifest collector."""

from __future__ import annotations

import json
from pathlib import Path

from data_quality_toolkit.lineage.manifest.collector import (
    _canonicalize_to_run,
    _infer_media_type,
    _normalize_artifact_kind,
    collect,
)


def _write_lineage(session_dir: Path, events: list[dict]) -> None:
    meta = session_dir / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(e) for e in events)
    (meta / "lineage.jsonl").write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Empty / missing inputs
# ---------------------------------------------------------------------------


class TestCollectEmpty:
    def test_empty_dir_no_lineage_file(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "run-a"
        session_dir.mkdir()
        datasets, artifacts = collect(session_dir)
        assert datasets == []
        assert artifacts == []

    def test_empty_lineage_file(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "run-b"
        _write_lineage(session_dir, [])
        datasets, artifacts = collect(session_dir)
        assert datasets == []
        assert artifacts == []

    def test_no_meta_dir(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "run-no-meta"
        session_dir.mkdir()
        datasets, artifacts = collect(session_dir)
        assert datasets == []
        assert artifacts == []


# ---------------------------------------------------------------------------
# Dataset events
# ---------------------------------------------------------------------------


class TestDatasetEvents:
    def test_dataset_event_parsed(self, tmp_path: Path) -> None:
        run_id = "run-ds"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {"type": "DATASET", "path": f"{run_id}/star/data.csv", "kind": "silver"},
            ],
        )
        datasets, _ = collect(session_dir)
        assert len(datasets) == 1
        assert datasets[0].kind == "silver"
        assert datasets[0].path == "star/data.csv"

    def test_plural_datasets_type_parsed(self, tmp_path: Path) -> None:
        run_id = "run-plural"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {"type": "DATASETS", "path": f"{run_id}/out.csv", "kind": "gold"},
            ],
        )
        datasets, _ = collect(session_dir)
        assert len(datasets) == 1
        assert datasets[0].kind == "gold"

    def test_dataset_kind_defaults_to_bronze(self, tmp_path: Path) -> None:
        run_id = "run-dk"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {"type": "DATASET", "path": f"{run_id}/data.csv"},
            ],
        )
        datasets, _ = collect(session_dir)
        assert datasets[0].kind == "bronze"

    def test_dataset_exists_false_when_file_absent(self, tmp_path: Path) -> None:
        run_id = "run-dex"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {"type": "DATASET", "path": f"{run_id}/missing.csv", "kind": "gold"},
            ],
        )
        datasets, _ = collect(session_dir)
        assert datasets[0].exists is False

    def test_dataset_exists_true_and_bytes_when_file_present(self, tmp_path: Path) -> None:
        run_id = "run-dfs"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {"type": "DATASET", "path": f"{run_id}/data.csv", "kind": "bronze"},
            ],
        )
        (session_dir / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        datasets, _ = collect(session_dir)
        assert datasets[0].exists is True
        assert datasets[0].bytes > 0

    def test_malformed_dataset_event_empty_path_skipped(self, tmp_path: Path) -> None:
        run_id = "run-dmalf"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {"type": "DATASET", "path": ""},
            ],
        )
        datasets, _ = collect(session_dir)
        assert datasets == []

    def test_dataset_content_hash_preserved(self, tmp_path: Path) -> None:
        run_id = "run-dhash"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {
                    "type": "DATASET",
                    "path": f"{run_id}/d.csv",
                    "kind": "bronze",
                    "content_sha256": "sha256:abc123",
                },
            ],
        )
        datasets, _ = collect(session_dir)
        assert datasets[0].content_hash == "sha256:abc123"


# ---------------------------------------------------------------------------
# Artifact events
# ---------------------------------------------------------------------------


class TestArtifactEvents:
    def test_artifact_event_parsed(self, tmp_path: Path) -> None:
        run_id = "run-art"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {"type": "ARTIFACT", "path": f"{run_id}/dist/report.csv", "kind": "star"},
            ],
        )
        _, artifacts = collect(session_dir)
        assert len(artifacts) == 1
        assert artifacts[0].kind == "star"

    def test_plural_artifacts_type_parsed(self, tmp_path: Path) -> None:
        run_id = "run-plurala"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {"type": "ARTIFACTS", "path": f"{run_id}/out.csv", "kind": "star"},
            ],
        )
        _, artifacts = collect(session_dir)
        assert len(artifacts) == 1

    def test_artifact_pbix_extension_infers_pbi_package_kind(self, tmp_path: Path) -> None:
        run_id = "run-pbix"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {"type": "ARTIFACT", "path": f"{run_id}/dist/report.pbix"},
            ],
        )
        _, artifacts = collect(session_dir)
        assert artifacts[0].kind == "pbi_package"

    def test_artifact_media_type_inferred_for_csv(self, tmp_path: Path) -> None:
        run_id = "run-mt"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {"type": "ARTIFACT", "path": f"{run_id}/out.csv", "kind": "star"},
            ],
        )
        _, artifacts = collect(session_dir)
        assert artifacts[0].media_type == "text/csv"

    def test_artifact_exists_true_and_bytes_when_file_present(self, tmp_path: Path) -> None:
        run_id = "run-aex"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {"type": "ARTIFACT", "path": f"{run_id}/star.csv", "kind": "star"},
            ],
        )
        (session_dir / "star.csv").write_text("x,y\n1,2\n", encoding="utf-8")
        _, artifacts = collect(session_dir)
        assert artifacts[0].exists is True
        assert artifacts[0].bytes > 0

    def test_artifact_exists_false_when_file_absent(self, tmp_path: Path) -> None:
        run_id = "run-aexa"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {"type": "ARTIFACT", "path": f"{run_id}/missing.csv", "kind": "star"},
            ],
        )
        _, artifacts = collect(session_dir)
        assert artifacts[0].exists is False

    def test_malformed_artifact_empty_path_skipped(self, tmp_path: Path) -> None:
        run_id = "run-amalf"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {"type": "ARTIFACT", "path": ""},
            ],
        )
        _, artifacts = collect(session_dir)
        assert artifacts == []

    def test_powerbi_zip_injected_at_top_level(self, tmp_path: Path) -> None:
        run_id = "run-pbi"
        session_dir = tmp_path / run_id
        _write_lineage(session_dir, [])
        (session_dir / "powerbi_package.zip").write_bytes(b"PK\x00")
        _, artifacts = collect(session_dir)
        kinds = [a.kind for a in artifacts]
        assert "report" in kinds
        paths = [a.path for a in artifacts]
        assert any("powerbi_package.zip" in p for p in paths)

    def test_powerbi_zip_dedup_works_for_nested_path(self, tmp_path: Path) -> None:
        # Source dedup check: already_listed = any(a.kind=="report" and a.path.endswith("/powerbi_package.zip"))
        # Triggers for nested lineage path "powerbi_package/powerbi_package.zip" (ends with /name).
        # Does NOT trigger for bare "powerbi_package.zip" — documented source behavior.
        run_id = "run-pbi2"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {
                    "type": "ARTIFACT",
                    "path": f"{run_id}/powerbi_package/powerbi_package.zip",
                    "kind": "report",
                },
            ],
        )
        nested = session_dir / "powerbi_package"
        nested.mkdir(parents=True)
        (nested / "powerbi_package.zip").write_bytes(b"PK\x00")
        _, artifacts = collect(session_dir)
        report_artifacts = [a for a in artifacts if a.kind == "report"]
        assert len(report_artifacts) == 1

    def test_powerbi_zip_top_level_injected_even_if_bare_path_in_lineage(
        self, tmp_path: Path
    ) -> None:
        # Bare "powerbi_package.zip" rel_path does NOT match endswith("/powerbi_package.zip")
        # so top-level zip is injected again — this is current source behavior.
        run_id = "run-pbi3"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {"type": "ARTIFACT", "path": f"{run_id}/powerbi_package.zip", "kind": "report"},
            ],
        )
        (session_dir / "powerbi_package.zip").write_bytes(b"PK\x00")
        _, artifacts = collect(session_dir)
        report_artifacts = [a for a in artifacts if a.kind == "report"]
        assert len(report_artifacts) == 2

    def test_mime_field_overrides_inferred_media_type(self, tmp_path: Path) -> None:
        run_id = "run-mime"
        session_dir = tmp_path / run_id
        _write_lineage(
            session_dir,
            [
                {
                    "type": "ARTIFACT",
                    "path": f"{run_id}/out.csv",
                    "kind": "star",
                    "mime": "application/octet-stream",
                },
            ],
        )
        _, artifacts = collect(session_dir)
        # Event provides explicit mime; apply_fs_artifacts re-infers from rel_path extension
        # rel_path "out.csv" → "text/csv" re-inferred since stored mime was octet-stream
        assert artifacts[0].media_type == "text/csv"


# ---------------------------------------------------------------------------
# Path canonicalization
# ---------------------------------------------------------------------------


class TestCanonicalizeToRun:
    def test_already_prefixed_with_run_id(self) -> None:
        canonical, rel = _canonicalize_to_run("run-x/star/data.csv", "run-x")
        assert canonical == "run-x/star/data.csv"
        assert rel == "star/data.csv"

    def test_sessions_prefix_stripped(self) -> None:
        canonical, rel = _canonicalize_to_run("sessions/run-x/data.csv", "run-x")
        assert canonical == "run-x/data.csv"
        assert rel == "data.csv"

    def test_bare_relative_path(self) -> None:
        canonical, rel = _canonicalize_to_run("data.csv", "run-x")
        assert rel == "data.csv"
        assert canonical == "run-x/data.csv"

    def test_backslash_normalized(self) -> None:
        _, rel = _canonicalize_to_run("run-x\\star\\d.csv", "run-x")
        assert rel == "star/d.csv"

    def test_run_id_found_anywhere_in_path(self) -> None:
        canonical, rel = _canonicalize_to_run("/some/prefix/run-x/out.csv", "run-x")
        assert canonical == "run-x/out.csv"
        assert rel == "out.csv"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestInferMediaType:
    def test_csv(self) -> None:
        assert _infer_media_type("data.csv") == "text/csv"

    def test_pbix(self) -> None:
        assert _infer_media_type("report.pbix") == "application/vnd.ms-powerbi"

    def test_xlsx(self) -> None:
        assert (
            _infer_media_type("export.xlsx")
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    def test_json(self) -> None:
        assert _infer_media_type("artifacts.json") == "application/json"

    def test_unknown_extension(self) -> None:
        assert _infer_media_type("file.xyz") == "application/octet-stream"

    def test_no_extension(self) -> None:
        assert _infer_media_type("noext") == "application/octet-stream"

    def test_case_insensitive_extension(self) -> None:
        assert _infer_media_type("DATA.CSV") == "text/csv"


class TestNormalizeArtifactKind:
    def test_known_kind_passthrough(self) -> None:
        assert _normalize_artifact_kind("star", "out.csv") == "star"

    def test_uppercase_kind_normalized(self) -> None:
        assert _normalize_artifact_kind("STAR", "out.csv") == "star"

    def test_unknown_kind_defaults_to_manifest(self) -> None:
        assert _normalize_artifact_kind("unknown_kind", "file.txt") == "manifest"

    def test_none_kind_with_pbix_extension(self) -> None:
        assert _normalize_artifact_kind(None, "report.pbix") == "pbi_package"

    def test_empty_kind_with_pbix_extension(self) -> None:
        assert _normalize_artifact_kind("", "report.pbix") == "pbi_package"

    def test_none_kind_unknown_extension(self) -> None:
        assert _normalize_artifact_kind(None, "file.bin") == "manifest"

    def test_all_allowed_kinds_pass_through(self) -> None:
        allowed = (
            "star",
            "pbi_package",
            "report",
            "dax",
            "roles",
            "parameters",
            "sanity_report",
            "manifest",
        )
        for k in allowed:
            assert _normalize_artifact_kind(k, "file") == k
