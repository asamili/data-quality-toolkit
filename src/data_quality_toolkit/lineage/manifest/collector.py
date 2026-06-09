# cspell:ignore openxmlformats officedocument spreadsheetml pbix etype apath

"""Collect datasets and artifacts from lineage and filesystem."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeGuard

from data_quality_toolkit.lineage.manifest.schemas import (
    Artifact,
    ArtifactKind,
    Dataset,
    Schema,
)


@dataclass(frozen=True)
class FSItem:
    """Filesystem item metadata."""

    rel_path: str
    bytes: int
    exists: bool


_MEDIA_TYPES: dict[str, str] = {
    ".csv": "text/csv",
    ".parquet": "application/parquet",
    ".json": "application/json",
    ".md": "text/markdown",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pbix": "application/vnd.ms-powerbi",
    ".zip": "application/zip",
}

# Use Literal-typed container + a set for fast membership
_ALLOWED_ARTIFACT_KINDS: Final[tuple[ArtifactKind, ...]] = (
    "star",
    "pbi_package",
    "report",  # verifier expects 'report'
    "dax",
    "roles",
    "parameters",
    "sanity_report",
    "manifest",
)
_ALLOWED_ARTIFACT_KINDS_SET: Final[set[str]] = set(_ALLOWED_ARTIFACT_KINDS)


def _is_artifact_kind(s: str) -> TypeGuard[ArtifactKind]:
    return s in _ALLOWED_ARTIFACT_KINDS_SET


def _infer_media_type(path: str) -> str:
    """Infer media type from file extension."""
    return _MEDIA_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


def _normalize_artifact_kind(kind: str | None, path: str) -> ArtifactKind:
    """
    Coerce external/unknown lineage kinds to the allowed Literal set.
    Also accepts common synonyms & infers from extension.
    """
    k = (kind or "").lower()
    if _is_artifact_kind(k):
        return k
    if Path(path).suffix.lower() == ".pbix":
        return "pbi_package"
    # default to manifest if unknown
    return "manifest"


def _scan_fs(session_dir: Path) -> dict[str, FSItem]:
    """Scan filesystem for all files in session directory."""
    out: dict[str, FSItem] = {}
    for p in session_dir.rglob("*"):
        if p.is_file():
            rel = p.relative_to(session_dir).as_posix()
            out[rel] = FSItem(rel_path=rel, bytes=p.stat().st_size, exists=True)
    return out


def _event_payload(evt: dict) -> dict:
    """Support both flat events and shape { 'type': ..., 'data': {...} }."""
    data = evt.get("data")
    return data if isinstance(data, dict) else evt


def _to_fwd(s: str) -> str:
    return s.replace("\\", "/")


def _canonicalize_to_run(path_str: str, run_id: str) -> tuple[str, str]:
    """
    Return (canonical_path_for_manifest, relative_path_for_fs)
      canonical: '<run_id>/...'
      relative:  path relative to session_dir (no leading slash)
    """
    s = _to_fwd(path_str.strip())
    # already <run_id>/...
    if s.startswith(f"{run_id}/"):
        rel = s[len(run_id) + 1 :]
        return f"{run_id}/{rel}", rel
    # tolerate 'sessions/<run_id>/...'
    if s.startswith(f"sessions/{run_id}/"):
        rel = s[len(f"sessions/{run_id}/") :]
        return f"{run_id}/{rel}", rel
    # fallback: locate run_id anywhere in the string
    idx = s.find(run_id)
    if idx != -1:
        tail = s[idx + len(run_id) :].lstrip("/\\")
        return f"{run_id}/{tail}", tail
    # assume already relative to session_dir
    rel = s.lstrip("/\\")
    return f"{run_id}/{rel}", rel


def _maybe_with_csv(session_dir: Path, rel_path: str) -> str:
    """If a dataset path under star/ has no suffix and <rel>.csv exists, use <rel>.csv."""
    p = session_dir / rel_path
    return f"{rel_path}.csv" if p.suffix == "" and (p.with_suffix(".csv")).exists() else rel_path


def _parse_lineage(lineage_path: Path, session_dir: Path) -> tuple[list[Dataset], list[Artifact]]:
    """Parse lineage JSONL for dataset and artifact events."""
    datasets: list[Dataset] = []
    artifacts: list[Artifact] = []

    if not lineage_path.exists():
        return datasets, artifacts

    with lineage_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = (evt.get("type") or "").upper()
            payload = _event_payload(evt)

            if etype in {"DATASETS", "DATASET"}:
                raw_path = (payload.get("path") or "").strip()
                if not raw_path:
                    continue  # skip malformed dataset events
                # Use path *relative* to session_dir in the manifest
                _canonical, rel = _canonicalize_to_run(raw_path, run_id=session_dir.name)
                rel = _maybe_with_csv(session_dir, rel)
                datasets.append(
                    Dataset(
                        kind=payload.get("kind", "bronze"),
                        path=rel,
                        content_hash=payload.get("content_sha256", ""),
                        bytes=payload.get("bytes", 0),
                        rows=payload.get("rows", 0),
                        # NOTE: Pydantic v2: field is schema_ (alias 'schema')
                        schema_=Schema(
                            columns=payload.get("columns", []),
                            dtypes=payload.get("dtypes", {}),
                        ),
                        exists=True,
                    )
                )

            elif etype in {"ARTIFACTS", "ARTIFACT"}:
                raw_path = (payload.get("path") or "").strip()
                if not raw_path:
                    continue  # skip malformed artifact events
                _canonical, rel = _canonicalize_to_run(raw_path, run_id=session_dir.name)
                apath = rel  # artifacts also stored relative to session_dir

                artifacts.append(
                    Artifact(
                        kind=_normalize_artifact_kind(payload.get("kind"), apath),
                        path=apath,
                        media_type=payload.get("mime", _infer_media_type(apath)),
                        bytes=payload.get("bytes", 0),
                        meta=payload.get("meta", {}),
                        exists=True,
                    )
                )

    return datasets, artifacts


def _normalize_rel_path(p: str, run_id: str) -> str:
    """Strip prefix '<run_id>/' during FS matching."""
    p = p[2:] if p.startswith("./") else p
    p = _to_fwd(p)
    prefix = f"{run_id}/"
    return p[len(prefix) :] if p.startswith(prefix) else p


def _apply_fs_datasets(
    items: Iterable[Dataset], fs_map: dict[str, FSItem], run_id: str
) -> list[Dataset]:
    """Apply filesystem stats to datasets."""
    out: list[Dataset] = []
    for item in items:
        rel_path = _normalize_rel_path(item.path, run_id)
        fs_item = fs_map.get(rel_path)
        exists = fs_item is not None
        bytes_val = fs_item.bytes if fs_item else item.bytes
        out.append(item.model_copy(update={"exists": exists, "bytes": bytes_val}))
    return out


def _apply_fs_artifacts(
    items: Iterable[Artifact], fs_map: dict[str, FSItem], run_id: str
) -> list[Artifact]:
    """Apply filesystem stats (and media type inference) to artifacts."""
    out: list[Artifact] = []
    for item in items:
        rel_path = _normalize_rel_path(item.path, run_id)
        fs_item = fs_map.get(rel_path)
        exists = fs_item is not None
        bytes_val = fs_item.bytes if fs_item else item.bytes

        updated = item.model_copy(update={"exists": exists, "bytes": bytes_val})

        # Infer media type if it looks generic
        if updated.media_type == "application/octet-stream":
            updated = updated.model_copy(update={"media_type": _infer_media_type(rel_path)})

        out.append(updated)
    return out


def collect(session_dir: Path) -> tuple[list[Dataset], list[Artifact]]:
    """Collect normalized datasets/artifacts from lineage + filesystem."""
    fs_map = _scan_fs(session_dir)
    lineage_file = session_dir / "meta" / "lineage.jsonl"
    datasets, artifacts = _parse_lineage(lineage_file, session_dir)
    run_id = session_dir.name

    # --- Ensure Power BI package ZIP is present as 'report' even if lineage missed it ---
    # Preferred (current) location:
    zip_top = session_dir / "powerbi_package.zip"
    # Legacy fallback:
    zip_old = session_dir / "powerbi_package" / "powerbi_package.zip"

    already_listed = any(
        a.kind == "report" and a.path.endswith("/powerbi_package.zip") for a in artifacts
    )

    zip_path: Path | None = None
    if zip_top.exists():
        zip_path = zip_top
    elif zip_old.exists():
        zip_path = zip_old

    if not already_listed and zip_path is not None:
        rel = zip_path.relative_to(session_dir).as_posix()  # relative path in manifest
        artifacts.append(
            Artifact(
                kind="report",
                path=rel,
                media_type="application/vnd.ms-powerbi",
                bytes=zip_path.stat().st_size,
                exists=True,
            )
        )

    # Apply FS stats & media type inference
    return _apply_fs_datasets(datasets, fs_map, run_id), _apply_fs_artifacts(
        artifacts, fs_map, run_id
    )
