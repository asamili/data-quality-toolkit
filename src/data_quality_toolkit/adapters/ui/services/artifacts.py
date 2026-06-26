"""Safe UI-facing artifact presentation helpers.

This module deliberately keeps full local paths out of display rows. Callers may
retain full paths internally for existing write/read behavior, but the rows
returned here contain only conservative, review-oriented metadata.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

CATEGORY_ORDER: tuple[str, ...] = (
    "data export",
    "quality report",
    "drift report",
    "dashboard/report",
    "visual evidence",
    "lineage/manifest",
    "other",
)

_CATEGORY_RANK = {name: idx for idx, name in enumerate(CATEGORY_ORDER)}

_STAR_EXPORT_KEYS = frozenset(
    {
        "dim_dataset",
        "dim_column",
        "fact_profile_runs",
        "fact_quality_metrics",
        "fact_issues",
    }
)

_TYPE_LABELS = {
    ".csv": "CSV",
    ".json": "JSON",
    ".jsonl": "JSONL",
    ".db": "SQLite database",
    ".sqlite": "SQLite database",
    ".html": "HTML",
    ".md": "Markdown",
    ".xlsx": "Excel workbook",
    ".duckdb": "DuckDB database",
    ".png": "PNG image",
    ".mmd": "Mermaid graph",
    ".dax": "DAX",
    ".zip": "ZIP package",
}


@dataclass(frozen=True, slots=True)
class ArtifactDisplayRow:
    """A path-redacted artifact row suitable for UI tables."""

    artifact: str
    basename: str
    artifact_type: str
    category: str
    status: str
    write_mode: str
    source: str

    def to_display_dict(self) -> dict[str, str]:
        """Return stable, UI-facing labels with no path fields."""
        return {
            "Category": self.category,
            "Artifact": self.artifact,
            "File": self.basename,
            "Type": self.artifact_type,
            "Status": self.status,
            "Write mode": self.write_mode,
            "Source": self.source,
        }


def redact_path_to_basename(value: object) -> str:
    """Return a host-independent basename, stripping POSIX and Windows paths."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    normalized = text.replace("\\", "/").rstrip("/")
    if not normalized:
        return ""
    return normalized.rsplit("/", 1)[-1]


def safe_artifact_label(value: object, fallback: str) -> str:
    """Return a stable label, stripping path separators if a path-like key appears."""
    text = str(value or "").strip()
    if not text:
        return fallback
    if "/" in text or "\\" in text:
        return redact_path_to_basename(text) or fallback
    return text


def infer_artifact_type(basename: str) -> str:
    """Infer a compact type label from a basename extension."""
    suffix = PurePosixPath(basename).suffix.lower()
    if not suffix:
        return "Directory or file"
    return _TYPE_LABELS.get(suffix, suffix.lstrip(".").upper() or "File")


def infer_artifact_category(key: object, basename: str) -> str:
    """Classify an artifact into the deterministic Artifact Center categories."""
    key_text = str(key or "").strip().lower()
    name = basename.lower()
    suffix = PurePosixPath(name).suffix.lower()
    haystack = f"{key_text} {name}"

    if key_text in _STAR_EXPORT_KEYS:
        return "data export"
    if "quality_report" in haystack or "quality_history" in haystack:
        return "quality report"
    if "drift" in haystack and (
        "report" in haystack or "history" in haystack or suffix in {".json", ".jsonl"}
    ):
        return "drift report"
    if "dashboard" in haystack or suffix in {".html", ".md"}:
        return "dashboard/report"
    if "plot" in haystack or "chart" in haystack or "graph" in haystack or suffix == ".png":
        return "visual evidence"
    if (
        "manifest" in haystack
        or name == "artifacts.json"
        or key_text == "relationships"
        or name == "relationships.json"
    ):
        return "lineage/manifest"
    if suffix == ".csv":
        return "data export"
    return "other"


def conservative_status(category: str, write_mode: str) -> str:
    """Return a conservative local/shareability label for display."""
    mode = write_mode.strip().lower()
    if mode == "browser download":
        return "browser download - review before sharing"
    if category == "lineage/manifest":
        return "private evidence / local-only"
    if category in {"quality report", "drift report", "dashboard/report"}:
        return "generated report - review before sharing"
    return "local file - review before sharing"


def artifact_rows_from_mapping(
    artifacts: Mapping[str, object] | None,
    *,
    source: str,
    write_mode: str,
) -> list[ArtifactDisplayRow]:
    """Build deterministic, path-redacted artifact rows from a key->path mapping."""
    if not artifacts:
        return []
    rows: list[ArtifactDisplayRow] = []
    for key, raw_path in sorted(artifacts.items(), key=lambda item: str(item[0])):
        basename = redact_path_to_basename(raw_path)
        if not basename:
            continue
        category = infer_artifact_category(key, basename)
        rows.append(
            ArtifactDisplayRow(
                artifact=safe_artifact_label(key, basename),
                basename=basename,
                artifact_type=infer_artifact_type(basename),
                category=category,
                status=conservative_status(category, write_mode),
                write_mode=write_mode,
                source=source,
            )
        )
    return sort_artifact_rows(rows)


def artifact_rows_from_manifest(manifest: Mapping[str, Any]) -> list[ArtifactDisplayRow]:
    """Build safe rows from a lineage manifest's artifact entries."""
    raw_items = manifest.get("artifacts") or []
    if not isinstance(raw_items, list):
        return []
    rows: list[ArtifactDisplayRow] = []
    for idx, item in enumerate(raw_items, start=1):
        if not isinstance(item, Mapping):
            continue
        basename = redact_path_to_basename(item.get("path"))
        if not basename:
            continue
        kind = safe_artifact_label(item.get("kind"), f"artifact_{idx}")
        category = infer_artifact_category(kind, basename)
        status = "private evidence / local-only"
        rows.append(
            ArtifactDisplayRow(
                artifact=kind,
                basename=basename,
                artifact_type=infer_artifact_type(basename),
                category=category,
                status=status,
                write_mode="manifest evidence",
                source="Manifest Viewer",
            )
        )
    return sort_artifact_rows(rows)


def dataset_rows_from_manifest(manifest: Mapping[str, Any]) -> list[dict[str, str]]:
    """Build a safe basename-only dataset projection for the Manifest Viewer."""
    raw_items = manifest.get("datasets") or []
    if not isinstance(raw_items, list):
        return []
    rows: list[dict[str, str]] = []
    for idx, item in enumerate(raw_items, start=1):
        if not isinstance(item, Mapping):
            continue
        basename = redact_path_to_basename(item.get("path"))
        if not basename:
            continue
        rows.append(
            {
                "Dataset": safe_artifact_label(item.get("kind"), f"dataset_{idx}"),
                "File": basename,
                "Status": "private evidence / local-only",
                "Source": "Manifest Viewer",
            }
        )
    return sorted(rows, key=lambda row: (row["Dataset"], row["File"]))


def sort_artifact_rows(rows: Iterable[ArtifactDisplayRow]) -> list[ArtifactDisplayRow]:
    """Sort rows by category order, artifact label, and basename."""
    return sorted(
        rows,
        key=lambda row: (
            _CATEGORY_RANK.get(row.category, len(_CATEGORY_RANK)),
            row.artifact,
            row.basename,
        ),
    )


def group_artifact_rows(
    rows: Iterable[ArtifactDisplayRow],
) -> list[tuple[str, list[ArtifactDisplayRow]]]:
    """Group rows by deterministic category order."""
    sorted_rows = sort_artifact_rows(rows)
    grouped: list[tuple[str, list[ArtifactDisplayRow]]] = []
    for row in sorted_rows:
        if not grouped or grouped[-1][0] != row.category:
            grouped.append((row.category, [row]))
        else:
            grouped[-1][1].append(row)
    return grouped
