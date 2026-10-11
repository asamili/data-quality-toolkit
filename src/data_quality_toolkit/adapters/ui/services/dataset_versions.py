"""Pure, Streamlit-free dataset-lifecycle version contract.

This module defines the immutable typed contract for a processed dataset
*version*, plus deterministic identity helpers and strict validation /
serialization. It is intentionally free of side effects: no file writes, no
directory scans, no registry, no sidecar loading, and no UI. Only standard
library facilities are used.

Design decisions encoded here (accepted lifecycle architecture):

* ``DATASET_CONTEXT`` remains the single authoritative active pointer; a version
  record carries **no** ``active``/``is_active`` state.
* ``family_id`` is a generated UUID4 and is never derived from content.
* ``root_content_id`` separately identifies the root source bytes.
* ``content_id`` is a full-file SHA-256 (``sha256:<64 hex>``).
* The existing first-1-MB SHA-1 ``dataset_id`` (``sha1:<40 hex>``) is stored only
  as a compatibility identity; its algorithm is defined elsewhere and unchanged.
* Lineage is one-parent only.
* Durable file references are workspace-relative POSIX paths.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

__all__ = [
    "SCHEMA_VERSION",
    "PREPROCESS_PARENT_REQUIRED",
    "PREPROCESS_RECIPE_REQUIRED",
    "DatasetVersionError",
    "DatasetFormat",
    "CreationMechanism",
    "ParentRef",
    "RecipeRef",
    "DatasetVersionRecord",
    "content_id_from_bytes",
    "content_id_from_file",
    "recipe_digest",
    "new_version_id",
    "new_family_id",
    "to_mapping",
    "from_mapping",
]

# --- Schema ---------------------------------------------------------------

SCHEMA_VERSION = 1
_SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

# Creator-reference invariant codes (schema 1). A ``PREPROCESS_RECIPE`` version
# must carry both its immediate parent and the recipe that produced it; when both
# are absent the missing-parent failure is reported first. These are stable,
# value-free tokens surfaced on ``DatasetVersionError.code`` so a downstream
# reader can classify the failure without parsing the human-readable message.
PREPROCESS_PARENT_REQUIRED = "PREPROCESS_PARENT_REQUIRED"
PREPROCESS_RECIPE_REQUIRED = "PREPROCESS_RECIPE_REQUIRED"

# --- Identity prefixes / patterns ----------------------------------------

_SHA256_PREFIX = "sha256:"
_SHA1_PREFIX = "sha1:"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA1_RE = re.compile(r"^sha1:[0-9a-f]{40}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")

_READ_CHUNK_BYTES = 1024 * 1024


class DatasetVersionError(ValueError):
    """Raised when a lifecycle record is malformed or fails validation.

    ``code`` optionally carries a stable, value-free classification token so a
    caller (e.g. discovery) can distinguish a specific invariant failure without
    parsing the human-readable message. It defaults to ``None``, preserving the
    behavior of every pre-existing validation error.
    """

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class DatasetFormat(StrEnum):
    """Supported immutable-file formats for this schema version."""

    CSV = "csv"


class CreationMechanism(StrEnum):
    """How a dataset version came into being (``created_by``)."""

    ROOT_IMPORT = "root_import"
    PREPROCESS_RECIPE = "preprocess_recipe"


# --- Identity helpers -----------------------------------------------------


def content_id_from_bytes(data: bytes) -> str:
    """Return the full-content identity of ``data`` as ``sha256:<64 hex>``."""
    return f"{_SHA256_PREFIX}{hashlib.sha256(data).hexdigest()}"


def content_id_from_file(path: Path) -> str:
    """Return the full-content identity of a file (read-only, streamed).

    Hashes the complete byte sequence, so any change — including beyond the
    first megabyte — changes the result. File size never determines identity.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK_BYTES), b""):
            digest.update(chunk)
    return f"{_SHA256_PREFIX}{digest.hexdigest()}"


def recipe_digest(recipe: Mapping[str, Any]) -> str:
    """Return a deterministic ``sha256:`` digest of a recipe mapping.

    Uses a canonical JSON representation (recursively key-sorted) so that
    semantically identical mappings hash equally regardless of insertion order.
    No ``repr``, timestamps, or environment values participate.
    """
    canonical = json.dumps(recipe, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{_SHA256_PREFIX}{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def new_version_id() -> str:
    """Return a fresh, normalized UUID4 string for a version identity."""
    return str(uuid.uuid4())


def new_family_id() -> str:
    """Return a fresh, normalized UUID4 string for a family identity.

    Independent of any content; descendants will later inherit their family id.
    """
    return str(uuid.uuid4())


# --- Predicate helpers ----------------------------------------------------


def _is_uuid(value: object) -> bool:
    """True if ``value`` is a normalized UUID string (canonical lowercase)."""
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.match(value) is not None


def _is_sha1(value: object) -> bool:
    return isinstance(value, str) and _SHA1_RE.match(value) is not None


def _is_tz_aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.tzinfo.utcoffset(value) is not None
    )


def _is_valid_relative_path(path: object) -> bool:
    """True if ``path`` is a safe, workspace-relative POSIX path.

    Rejects empty/whitespace, ``.`` as the whole path, any ``..`` segment,
    backslashes, absolute POSIX paths, Windows drive-qualified paths, and UNC
    paths. Pure — never touches the real filesystem.
    """
    if not isinstance(path, str) or not path.strip() or path.strip() != path:
        return False
    if "\\" in path or path == "." or path.startswith("//"):
        return False
    if _DRIVE_RE.match(path):
        return False
    pure = PurePosixPath(path)
    if pure.is_absolute():
        return False
    return ".." not in pure.parts


# --- Typed contracts ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParentRef:
    """Reference to the single immediate parent (one-parent lineage).

    ``content_id`` is always the exact full-content identity of the parent.
    ``version_id`` is the parent's lifecycle version id when the parent is a
    managed version, or ``None`` when the immediate parent is an unmanaged
    source (a legacy/unversioned CSV). ``root_content_id`` on the record remains
    the family-root identity and does not replace this immediate-parent link.
    """

    version_id: str | None
    content_id: str

    def __post_init__(self) -> None:
        if self.version_id is not None and not _is_uuid(self.version_id):
            raise DatasetVersionError(f"parent version_id is not a UUID: {self.version_id!r}")
        if not _is_sha256(self.content_id):
            raise DatasetVersionError(f"parent content_id is not sha256: {self.content_id!r}")


@dataclass(frozen=True, slots=True)
class RecipeRef:
    """Reference to the recipe that produced a derived version."""

    digest: str
    relative_path: str

    def __post_init__(self) -> None:
        if not _is_sha256(self.digest):
            raise DatasetVersionError(f"recipe digest is not sha256: {self.digest!r}")
        if not _is_valid_relative_path(self.relative_path):
            raise DatasetVersionError(
                f"recipe relative_path is not workspace-relative: {self.relative_path!r}"
            )


@dataclass(frozen=True, slots=True)
class DatasetVersionRecord:
    """Immutable metadata identifying one processed dataset version.

    Carries no active-pointer, graph, registry, or collaboration state.
    """

    schema_version: int
    version_id: str
    family_id: str
    root_content_id: str
    content_id: str
    dataset_id: str
    label: str
    file_relative_path: str
    format: DatasetFormat
    size_bytes: int
    created_at: datetime
    created_by: CreationMechanism
    mtime_ns: int | None = None
    parent: ParentRef | None = None
    recipe: RecipeRef | None = None

    def __post_init__(self) -> None:
        _validate_identity(self)
        _validate_scalars(self)
        _validate_time(self)
        _validate_paths_and_refs(self)
        _validate_creator_refs(self)


# --- Record validation (split to respect complexity ceiling) --------------


def _validate_identity(record: DatasetVersionRecord) -> None:
    if not _is_uuid(record.version_id):
        raise DatasetVersionError(f"version_id is not a UUID: {record.version_id!r}")
    if not _is_uuid(record.family_id):
        raise DatasetVersionError(f"family_id is not a UUID: {record.family_id!r}")
    if not _is_sha256(record.root_content_id):
        raise DatasetVersionError(f"root_content_id is not sha256: {record.root_content_id!r}")
    if not _is_sha256(record.content_id):
        raise DatasetVersionError(f"content_id is not sha256: {record.content_id!r}")
    if not _is_sha1(record.dataset_id):
        raise DatasetVersionError(f"dataset_id is not sha1: {record.dataset_id!r}")


def _validate_scalars(record: DatasetVersionRecord) -> None:
    if record.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise DatasetVersionError(f"unsupported schema_version: {record.schema_version!r}")
    if not isinstance(record.label, str) or not record.label.strip():
        raise DatasetVersionError("label must be a non-empty string")
    if record.format is not DatasetFormat.CSV:
        raise DatasetVersionError(
            f"unsupported format for schema {SCHEMA_VERSION}: {record.format!r}"
        )
    if not isinstance(record.size_bytes, int) or isinstance(record.size_bytes, bool):
        raise DatasetVersionError("size_bytes must be an int")
    if record.size_bytes < 0:
        raise DatasetVersionError("size_bytes must be non-negative")
    _validate_mtime(record.mtime_ns)


def _validate_mtime(mtime_ns: int | None) -> None:
    if mtime_ns is None:
        return
    if not isinstance(mtime_ns, int) or isinstance(mtime_ns, bool):
        raise DatasetVersionError("mtime_ns must be an int or None")
    if mtime_ns < 0:
        raise DatasetVersionError("mtime_ns must be non-negative")


def _validate_time(record: DatasetVersionRecord) -> None:
    if not _is_tz_aware(record.created_at):
        raise DatasetVersionError("created_at must be a timezone-aware datetime")
    if not isinstance(record.created_by, CreationMechanism):
        raise DatasetVersionError(f"unsupported creation mechanism: {record.created_by!r}")


def _validate_paths_and_refs(record: DatasetVersionRecord) -> None:
    if not _is_valid_relative_path(record.file_relative_path):
        raise DatasetVersionError(
            f"file_relative_path is not workspace-relative: {record.file_relative_path!r}"
        )
    if record.parent is not None and not isinstance(record.parent, ParentRef):
        raise DatasetVersionError("parent must be a ParentRef or None")
    if record.recipe is not None and not isinstance(record.recipe, RecipeRef):
        raise DatasetVersionError("recipe must be a RecipeRef or None")


def _validate_creator_refs(record: DatasetVersionRecord) -> None:
    """Enforce the schema-1 creator-reference invariant.

    A ``PREPROCESS_RECIPE`` version is only well-formed when it records both the
    immediate parent it descends from and the recipe that produced it. When both
    references are missing the missing-parent failure wins. ``ROOT_IMPORT``
    records are untouched: they legitimately carry neither reference. Pure — it
    only inspects the record and raises; it never mutates or performs I/O.
    """
    if record.created_by is not CreationMechanism.PREPROCESS_RECIPE:
        return
    if record.parent is None:
        raise DatasetVersionError(
            "preprocess_recipe record requires a parent reference",
            code=PREPROCESS_PARENT_REQUIRED,
        )
    if record.recipe is None:
        raise DatasetVersionError(
            "preprocess_recipe record requires a recipe reference",
            code=PREPROCESS_RECIPE_REQUIRED,
        )


# --- Serialization --------------------------------------------------------


def to_mapping(record: DatasetVersionRecord) -> dict[str, Any]:
    """Serialize a record to a deterministic JSON-compatible mapping.

    Optional fields are omitted when unset. The output contains no
    active-state field.
    """
    result: dict[str, Any] = {
        "schema_version": record.schema_version,
        "version_id": record.version_id,
        "family_id": record.family_id,
        "root_content_id": record.root_content_id,
        "content_id": record.content_id,
        "dataset_id": record.dataset_id,
        "label": record.label,
        "file_relative_path": record.file_relative_path,
        "format": record.format.value,
        "size_bytes": record.size_bytes,
        "created_at": record.created_at.isoformat(),
        "created_by": record.created_by.value,
    }
    if record.mtime_ns is not None:
        result["mtime_ns"] = record.mtime_ns
    if record.parent is not None:
        result["parent"] = {
            "version_id": record.parent.version_id,
            "content_id": record.parent.content_id,
        }
    if record.recipe is not None:
        result["recipe"] = {
            "digest": record.recipe.digest,
            "relative_path": record.recipe.relative_path,
        }
    return result


def from_mapping(data: Mapping[str, Any]) -> DatasetVersionRecord:
    """Build a validated record from a mapping, failing explicitly on error.

    An unknown schema major version or any missing/malformed field raises
    :class:`DatasetVersionError`.
    """
    if not isinstance(data, Mapping):
        raise DatasetVersionError("record must be a mapping")
    schema_version = data.get("schema_version")
    if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise DatasetVersionError(f"unsupported schema_version: {schema_version!r}")
    try:
        return DatasetVersionRecord(
            schema_version=schema_version,
            version_id=_require(data, "version_id"),
            family_id=_require(data, "family_id"),
            root_content_id=_require(data, "root_content_id"),
            content_id=_require(data, "content_id"),
            dataset_id=_require(data, "dataset_id"),
            label=_require(data, "label"),
            file_relative_path=_require(data, "file_relative_path"),
            format=_parse_enum(DatasetFormat, _require(data, "format"), "format"),
            size_bytes=_require(data, "size_bytes"),
            created_at=_parse_created_at(_require(data, "created_at")),
            created_by=_parse_enum(CreationMechanism, _require(data, "created_by"), "created_by"),
            mtime_ns=data.get("mtime_ns"),
            parent=_parse_parent(data.get("parent")),
            recipe=_parse_recipe(data.get("recipe")),
        )
    except DatasetVersionError:
        raise
    except (KeyError, TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise DatasetVersionError(f"malformed record: {exc}") from exc


def _require(data: Mapping[str, Any], key: str) -> Any:
    if key not in data:
        raise DatasetVersionError(f"missing required field: {key!r}")
    return data[key]


def _parse_enum(enum_cls: type[Enum], raw: Any, field: str) -> Any:
    try:
        return enum_cls(raw)
    except ValueError as exc:
        raise DatasetVersionError(f"unsupported {field}: {raw!r}") from exc


def _parse_created_at(raw: Any) -> datetime:
    if not isinstance(raw, str):
        raise DatasetVersionError("created_at must be an ISO 8601 string")
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise DatasetVersionError(f"created_at is not ISO 8601: {raw!r}") from exc


def _parse_parent(raw: Any) -> ParentRef | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise DatasetVersionError("parent must be a mapping")
    return ParentRef(
        version_id=_require(raw, "version_id"),
        content_id=_require(raw, "content_id"),
    )


def _parse_recipe(raw: Any) -> RecipeRef | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise DatasetVersionError("recipe must be a mapping")
    return RecipeRef(
        digest=_require(raw, "digest"),
        relative_path=_require(raw, "relative_path"),
    )
