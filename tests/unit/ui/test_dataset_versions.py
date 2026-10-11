"""Tests for the pure dataset-lifecycle version contract."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit.adapters.loaders.file.csv_loader import dataset_id_from_file
from data_quality_toolkit.adapters.ui.services.dataset_versions import (
    CreationMechanism,
    DatasetFormat,
    DatasetVersionError,
    DatasetVersionRecord,
    ParentRef,
    RecipeRef,
    content_id_from_bytes,
    content_id_from_file,
    from_mapping,
    new_family_id,
    new_version_id,
    recipe_digest,
    to_mapping,
)

_VALID_SHA1 = "sha1:" + "0" * 40
_VALID_CONTENT = content_id_from_bytes(b"data")
_VALID_ROOT = content_id_from_bytes(b"root")


def _record(**overrides: Any) -> DatasetVersionRecord:
    fields: dict[str, Any] = {
        "schema_version": 1,
        "version_id": new_version_id(),
        "family_id": new_family_id(),
        "root_content_id": _VALID_ROOT,
        "content_id": _VALID_CONTENT,
        "dataset_id": _VALID_SHA1,
        "label": "orders v1",
        "file_relative_path": "datasets/orders.csv",
        "format": DatasetFormat.CSV,
        "size_bytes": 2048,
        "created_at": datetime(2026, 7, 16, 12, 30, 15, tzinfo=UTC),
        "created_by": CreationMechanism.ROOT_IMPORT,
    }
    fields.update(overrides)
    return DatasetVersionRecord(**fields)


# --- Construction & serialization ----------------------------------------


def test_valid_record_construction() -> None:
    record = _record()
    assert record.schema_version == 1
    assert record.format is DatasetFormat.CSV
    assert record.created_by is CreationMechanism.ROOT_IMPORT
    assert record.parent is None
    assert record.recipe is None
    assert record.mtime_ns is None


def test_mapping_round_trip_minimal() -> None:
    record = _record()
    assert from_mapping(to_mapping(record)) == record


def test_mapping_round_trip_full() -> None:
    parent = ParentRef(version_id=new_version_id(), content_id=content_id_from_bytes(b"parent"))
    recipe = RecipeRef(digest=recipe_digest({"op": "dropna"}), relative_path="recipes/r1.json")
    record = _record(
        created_by=CreationMechanism.PREPROCESS_RECIPE,
        mtime_ns=1_726_000_000_000_000_000,
        parent=parent,
        recipe=recipe,
    )
    restored = from_mapping(to_mapping(record))
    assert restored == record
    assert restored.parent == parent
    assert restored.recipe == recipe
    assert restored.mtime_ns == record.mtime_ns


def test_to_mapping_omits_unset_optionals() -> None:
    mapping = to_mapping(_record())
    assert "mtime_ns" not in mapping
    assert "parent" not in mapping
    assert "recipe" not in mapping


# --- Explicit failure on malformed / unknown input -----------------------


def test_missing_required_field_fails() -> None:
    mapping = to_mapping(_record())
    del mapping["label"]
    with pytest.raises(DatasetVersionError):
        from_mapping(mapping)


def test_malformed_content_id_fails() -> None:
    mapping = to_mapping(_record())
    mapping["content_id"] = "sha1:" + "0" * 40
    with pytest.raises(DatasetVersionError):
        from_mapping(mapping)


def test_unknown_schema_version_fails() -> None:
    mapping = to_mapping(_record())
    mapping["schema_version"] = 2
    with pytest.raises(DatasetVersionError):
        from_mapping(mapping)


def test_non_mapping_input_fails() -> None:
    with pytest.raises(DatasetVersionError):
        from_mapping(["not", "a", "mapping"])  # type: ignore[arg-type]


def test_uuid_validation() -> None:
    with pytest.raises(DatasetVersionError):
        _record(version_id="not-a-uuid")
    with pytest.raises(DatasetVersionError):
        _record(family_id="1234")
    # Uppercase (non-normalized) UUID is rejected.
    with pytest.raises(DatasetVersionError):
        _record(version_id=new_version_id().upper())


def test_non_tz_aware_created_at_fails() -> None:
    with pytest.raises(DatasetVersionError):
        _record(created_at=datetime(2026, 7, 16, 12, 30, 15))


def test_negative_size_and_mtime_fail() -> None:
    with pytest.raises(DatasetVersionError):
        _record(size_bytes=-1)
    with pytest.raises(DatasetVersionError):
        _record(mtime_ns=-1)


def test_empty_label_fails() -> None:
    with pytest.raises(DatasetVersionError):
        _record(label="   ")


# --- Identity semantics ---------------------------------------------------


def test_full_file_sha256_identity(tmp_path: Path) -> None:
    assert content_id_from_bytes(b"hello") == (
        "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )
    path = tmp_path / "blob.bin"
    payload = b"the quick brown fox" * 100
    path.write_bytes(payload)
    assert content_id_from_file(path) == content_id_from_bytes(payload)
    assert content_id_from_bytes(payload) == f"sha256:{hashlib.sha256(payload).hexdigest()}"


def test_byte_change_beyond_1mb_changes_content_id(tmp_path: Path) -> None:
    head = b"x" * (1024 * 1024)
    a_bytes = head + b"A"
    b_bytes = head + b"B"

    assert content_id_from_bytes(a_bytes) != content_id_from_bytes(b_bytes)

    a_file = tmp_path / "a.csv"
    b_file = tmp_path / "b.csv"
    a_file.write_bytes(a_bytes)
    b_file.write_bytes(b_bytes)
    # Full-file content_id diverges...
    assert content_id_from_file(a_file) != content_id_from_file(b_file)
    # ...while the legacy first-1-MB compatibility identity does not.
    assert dataset_id_from_file(a_file) == dataset_id_from_file(b_file)


def test_recipe_digest_order_independent() -> None:
    left = {"a": 1, "b": {"x": 1, "y": 2}}
    right = {"b": {"y": 2, "x": 1}, "a": 1}
    assert recipe_digest(left) == recipe_digest(right)


def test_recipe_digest_changes_with_content() -> None:
    assert recipe_digest({"op": "dropna"}) != recipe_digest({"op": "fillna"})


def test_identical_content_can_have_distinct_version_id() -> None:
    a = _record(content_id=_VALID_CONTENT)
    b = _record(content_id=_VALID_CONTENT)
    assert a.content_id == b.content_id
    assert a.version_id != b.version_id


def test_identical_root_content_can_have_distinct_family_id() -> None:
    a = _record(root_content_id=_VALID_ROOT)
    b = _record(root_content_id=_VALID_ROOT)
    assert a.root_content_id == b.root_content_id
    assert a.family_id != b.family_id


def test_family_id_not_derived_from_root_content_id() -> None:
    # Same root bytes, two independent generations -> different family ids, and
    # the family id is not any digest of the root content.
    first = new_family_id()
    second = new_family_id()
    assert first != second
    assert first != recipe_digest({"root": _VALID_ROOT})
    assert first != _VALID_ROOT


def test_compatibility_dataset_id_validation() -> None:
    good = _record(dataset_id="sha1:" + "a" * 40)
    assert good.dataset_id.startswith("sha1:")
    with pytest.raises(DatasetVersionError):
        _record(dataset_id=_VALID_CONTENT)  # sha256 is not a valid dataset_id
    with pytest.raises(DatasetVersionError):
        _record(dataset_id="sha1:" + "A" * 40)  # uppercase hex rejected


@pytest.mark.parametrize(
    "bad_content_id",
    [
        "md5:" + "0" * 32,
        "sha256:" + "0" * 63,  # too short
        "sha256:" + "0" * 65,  # too long
        "sha256:" + "G" * 64,  # non-hex
        "sha256:" + "A" * 64,  # uppercase
        "0" * 64,  # no prefix
    ],
)
def test_reject_invalid_content_id_prefixes(bad_content_id: str) -> None:
    with pytest.raises(DatasetVersionError):
        _record(content_id=bad_content_id)


# --- Path safety ----------------------------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    [
        "",
        "   ",
        ".",
        "/abs/orders.csv",  # absolute POSIX
        "C:/data/orders.csv",  # Windows drive (forward slash)
        "C:\\data\\orders.csv",  # Windows drive (backslash)
        "\\\\host\\share\\orders.csv",  # UNC (backslash)
        "//host/share/orders.csv",  # UNC (forward slash)
        "../escape.csv",  # traversal
        "a/../../b.csv",  # embedded traversal
        "a\\b.csv",  # backslash separator trick
        " datasets/orders.csv",  # leading whitespace
    ],
)
def test_reject_unsafe_relative_paths(bad_path: str) -> None:
    with pytest.raises(DatasetVersionError):
        _record(file_relative_path=bad_path)


def test_accepts_nested_relative_path() -> None:
    record = _record(file_relative_path="datasets/2026/orders.csv")
    assert record.file_relative_path == "datasets/2026/orders.csv"


# --- Reference structures -------------------------------------------------


def test_parent_reference_validation() -> None:
    ParentRef(version_id=new_version_id(), content_id=_VALID_CONTENT)  # valid managed
    with pytest.raises(DatasetVersionError):
        ParentRef(version_id="nope", content_id=_VALID_CONTENT)
    with pytest.raises(DatasetVersionError):
        ParentRef(version_id=new_version_id(), content_id="sha1:" + "0" * 40)


def test_managed_parent_accepts_normalized_uuid() -> None:
    version_id = new_version_id()
    parent = ParentRef(version_id=version_id, content_id=_VALID_CONTENT)
    assert parent.version_id == version_id
    # Non-normalized (uppercase) UUID is rejected for a managed parent.
    with pytest.raises(DatasetVersionError):
        ParentRef(version_id=version_id.upper(), content_id=_VALID_CONTENT)


def test_unmanaged_parent_accepts_none_version_id() -> None:
    parent = ParentRef(version_id=None, content_id=_VALID_CONTENT)
    assert parent.version_id is None
    assert parent.content_id == _VALID_CONTENT


@pytest.mark.parametrize("bad_version_id", ["", "   ", "not-a-uuid", "1234"])
def test_non_null_parent_version_id_must_be_valid_uuid(bad_version_id: str) -> None:
    with pytest.raises(DatasetVersionError):
        ParentRef(version_id=bad_version_id, content_id=_VALID_CONTENT)


def test_parent_content_id_always_required_and_sha256() -> None:
    # content_id must be a valid sha256 even for an unmanaged (None) parent.
    with pytest.raises(DatasetVersionError):
        ParentRef(version_id=None, content_id="sha1:" + "0" * 40)


def test_unmanaged_parent_round_trips() -> None:
    source_content = content_id_from_bytes(b"legacy-source")
    record = _record(parent=ParentRef(version_id=None, content_id=source_content))
    mapping = to_mapping(record)

    assert "version_id" in mapping["parent"]  # not omitted
    assert mapping["parent"]["version_id"] is None  # explicit null
    assert mapping["parent"]["content_id"] == source_content

    restored = from_mapping(mapping)
    assert restored == record
    assert restored.parent is not None
    assert restored.parent.version_id is None
    assert restored.parent.content_id == source_content


def test_managed_parent_round_trips() -> None:
    parent_version = new_version_id()
    parent_content = content_id_from_bytes(b"managed-parent")
    record = _record(
        created_by=CreationMechanism.PREPROCESS_RECIPE,
        parent=ParentRef(version_id=parent_version, content_id=parent_content),
        recipe=RecipeRef(digest=recipe_digest({"op": "x"}), relative_path="recipes/r.json"),
    )
    restored = from_mapping(to_mapping(record))
    assert restored == record
    assert restored.parent is not None
    assert restored.parent.version_id == parent_version
    assert restored.parent.content_id == parent_content


def test_parent_mapping_missing_version_id_fails() -> None:
    mapping = to_mapping(_record(parent=ParentRef(version_id=None, content_id=_VALID_CONTENT)))
    del mapping["parent"]["version_id"]
    with pytest.raises(DatasetVersionError):
        from_mapping(mapping)


def test_first_managed_child_preserves_unmanaged_source_parent() -> None:
    # A first confirmed managed child of a legacy/unmanaged CSV: the immediate
    # parent carries the source content_id with version_id=None, while the
    # record keeps its own separate root_content_id and content_id.
    source_content = content_id_from_bytes(b"unmanaged-source-bytes")
    child_content = content_id_from_bytes(b"processed-child-bytes")
    root_content = content_id_from_bytes(b"family-root-bytes")

    record = _record(
        created_by=CreationMechanism.PREPROCESS_RECIPE,
        content_id=child_content,
        root_content_id=root_content,
        parent=ParentRef(version_id=None, content_id=source_content),
        recipe=RecipeRef(digest=recipe_digest({"op": "x"}), relative_path="recipes/r.json"),
    )
    restored = from_mapping(to_mapping(record))

    assert restored.parent is not None
    assert restored.parent.version_id is None
    assert restored.parent.content_id == source_content
    assert restored.root_content_id == root_content
    assert restored.content_id == child_content
    assert restored.parent.content_id != restored.root_content_id


def test_child_of_managed_version_preserves_parent_version_id() -> None:
    parent_version = new_version_id()
    record = _record(
        created_by=CreationMechanism.PREPROCESS_RECIPE,
        parent=ParentRef(version_id=parent_version, content_id=content_id_from_bytes(b"pv")),
        recipe=RecipeRef(digest=recipe_digest({"op": "x"}), relative_path="recipes/r.json"),
    )
    restored = from_mapping(to_mapping(record))
    assert restored.parent is not None
    assert restored.parent.version_id == parent_version


def test_optional_recipe_reference_validation() -> None:
    RecipeRef(digest=recipe_digest({"op": "x"}), relative_path="recipes/r.json")  # valid
    with pytest.raises(DatasetVersionError):
        RecipeRef(digest="not-a-digest", relative_path="recipes/r.json")
    with pytest.raises(DatasetVersionError):
        RecipeRef(digest=recipe_digest({"op": "x"}), relative_path="/etc/passwd")


def test_recipe_optional_on_record() -> None:
    record = _record(recipe=None)
    assert record.recipe is None


# --- No active state ------------------------------------------------------


def test_no_active_field_in_serialized_output() -> None:
    parent = ParentRef(version_id=new_version_id(), content_id=content_id_from_bytes(b"p"))
    recipe = RecipeRef(digest=recipe_digest({"op": "x"}), relative_path="recipes/r.json")
    mapping = to_mapping(
        _record(
            created_by=CreationMechanism.PREPROCESS_RECIPE,
            mtime_ns=1,
            parent=parent,
            recipe=recipe,
        )
    )
    flat = str(mapping)
    assert "active" not in flat
    assert "is_active" not in mapping
    assert "is_active" not in mapping.get("parent", {})
