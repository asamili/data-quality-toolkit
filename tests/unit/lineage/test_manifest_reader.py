"""Focused tests for the pure read-only manifest loader."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from data_quality_toolkit.lineage.manifest import load_manifest
from data_quality_toolkit.lineage.manifest.builder import build_and_write
from data_quality_toolkit.lineage.manifest.schemas import Artifact, Dataset, Manifest


def _write_fixture_manifest(session_dir: Path) -> Path:
    """Write a real manifest with the existing producer and return its path."""
    build_and_write(
        run_id="run-reader-1",
        session_dir=session_dir,
        datasets=[Dataset(kind="bronze", path="raw/input.csv", rows=3, bytes=10, content_hash="")],
        artifacts=[Artifact(kind="star", path="star/dim_dataset.csv", bytes=5)],
    )
    return session_dir / "artifacts.json"


def _tree_snapshot(root: Path) -> set[tuple[str, int]]:
    return {
        (str(path.relative_to(root)), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_load_manifest_round_trips_existing_file_without_writing(tmp_path: Path) -> None:
    session_dir = tmp_path / "sessions" / "run-reader-1"
    manifest_path = _write_fixture_manifest(session_dir)
    before = _tree_snapshot(tmp_path)

    manifest = load_manifest(manifest_path)

    assert isinstance(manifest, Manifest)
    assert manifest.run_id == "run-reader-1"
    assert [artifact.path for artifact in manifest.artifacts] == ["star/dim_dataset.csv"]
    assert [dataset.path for dataset in manifest.datasets] == ["raw/input.csv"]
    # Pure read: no file was created, removed, or touched.
    assert _tree_snapshot(tmp_path) == before


def test_load_manifest_missing_file_raises_and_creates_nothing(tmp_path: Path) -> None:
    missing = tmp_path / "sessions" / "run-none" / "artifacts.json"

    with pytest.raises(FileNotFoundError):
        load_manifest(missing)

    assert not missing.parent.exists()
    assert list(tmp_path.iterdir()) == []


def test_load_manifest_validates_through_existing_schema(tmp_path: Path) -> None:
    bad = tmp_path / "artifacts.json"
    bad.write_text('{"artifacts": []}', encoding="utf-8")

    # Missing required schema fields (schema_version/run_id/created_at) must fail
    # validation (pydantic ValidationError is a ValueError) rather than yield a
    # partially populated manifest.
    with pytest.raises(ValueError):
        load_manifest(bad)


def test_load_manifest_rejects_invalid_json(tmp_path: Path) -> None:
    corrupt = tmp_path / "artifacts.json"
    corrupt.write_text("{not json", encoding="utf-8")

    # Both serializer implementations surface invalid JSON as a ValueError
    # (json.JSONDecodeError / msgspec.DecodeError subclass it).
    with pytest.raises(ValueError):
        load_manifest(corrupt)


def test_load_manifest_accepts_str_and_path_inputs(tmp_path: Path) -> None:
    session_dir = tmp_path / "run-reader-2"
    manifest_path = _write_fixture_manifest(session_dir)

    from_path = load_manifest(manifest_path)
    from_str = load_manifest(str(manifest_path))

    assert from_path.run_id == from_str.run_id == "run-reader-1"


def test_load_manifest_performs_no_directory_scan(tmp_path: Path) -> None:
    """A stray sibling file must not influence the loaded manifest."""
    session_dir = tmp_path / "run-reader-3"
    manifest_path = _write_fixture_manifest(session_dir)
    (session_dir / "unrelated.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    manifest = load_manifest(manifest_path)

    assert [artifact.path for artifact in manifest.artifacts] == ["star/dim_dataset.csv"]
    assert os.path.exists(manifest_path)
