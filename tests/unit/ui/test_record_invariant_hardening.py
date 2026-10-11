"""Hardening tests for the schema-1 creator-reference invariant.

A ``PREPROCESS_RECIPE`` version is well-formed only when it records both the
immediate parent it descends from and the recipe that produced it. These tests
pin that invariant at its single enforcement point — record construction — and
prove it also holds through the ``from_mapping`` deserialization path, that the
missing-parent failure is reported before the missing-recipe failure, that the
two failures carry distinct value-free codes, and that ``ROOT_IMPORT`` records
(which legitimately carry neither reference) are entirely unaffected.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.services.dataset_versions import (
    PREPROCESS_PARENT_REQUIRED,
    PREPROCESS_RECIPE_REQUIRED,
    CreationMechanism,
    DatasetFormat,
    DatasetVersionError,
    DatasetVersionRecord,
    ParentRef,
    RecipeRef,
    content_id_from_bytes,
    from_mapping,
    new_family_id,
    new_version_id,
    recipe_digest,
    to_mapping,
)

_VALID_SHA1 = "sha1:" + "0" * 40
_VALID_CONTENT = content_id_from_bytes(b"data")
_VALID_ROOT = content_id_from_bytes(b"root")


def _managed_parent() -> ParentRef:
    return ParentRef(version_id=new_version_id(), content_id=content_id_from_bytes(b"parent"))


def _unmanaged_parent() -> ParentRef:
    return ParentRef(version_id=None, content_id=content_id_from_bytes(b"source"))


def _recipe() -> RecipeRef:
    return RecipeRef(digest=recipe_digest({"op": "dropna"}), relative_path="recipes/r1.json")


def _record(**overrides: Any) -> DatasetVersionRecord:
    fields: dict[str, Any] = {
        "schema_version": 1,
        "version_id": new_version_id(),
        "family_id": new_family_id(),
        "root_content_id": _VALID_ROOT,
        "content_id": _VALID_CONTENT,
        "dataset_id": _VALID_SHA1,
        "label": "orders v1",
        "file_relative_path": "preprocessed/orders.csv",
        "format": DatasetFormat.CSV,
        "size_bytes": 2048,
        "created_at": datetime(2026, 7, 16, 12, 30, 15, tzinfo=UTC),
        "created_by": CreationMechanism.ROOT_IMPORT,
    }
    fields.update(overrides)
    return DatasetVersionRecord(**fields)


# --- Code identity --------------------------------------------------------


def test_exactly_two_distinct_invariant_codes() -> None:
    assert PREPROCESS_PARENT_REQUIRED == "PREPROCESS_PARENT_REQUIRED"
    assert PREPROCESS_RECIPE_REQUIRED == "PREPROCESS_RECIPE_REQUIRED"
    assert PREPROCESS_PARENT_REQUIRED != PREPROCESS_RECIPE_REQUIRED


# --- ROOT_IMPORT is unaffected --------------------------------------------


def test_root_import_needs_neither_reference() -> None:
    record = _record(created_by=CreationMechanism.ROOT_IMPORT)
    assert record.parent is None
    assert record.recipe is None


def test_root_import_may_carry_parent_without_recipe() -> None:
    # A root import legitimately references an unmanaged source parent and no
    # recipe; the invariant must not touch it.
    record = _record(created_by=CreationMechanism.ROOT_IMPORT, parent=_unmanaged_parent())
    assert record.recipe is None
    assert record.parent is not None


def test_root_import_may_carry_both_references() -> None:
    record = _record(
        created_by=CreationMechanism.ROOT_IMPORT, parent=_unmanaged_parent(), recipe=_recipe()
    )
    assert record.parent is not None
    assert record.recipe is not None


# --- PREPROCESS_RECIPE: valid case ----------------------------------------


def test_preprocess_recipe_with_both_references_is_valid() -> None:
    record = _record(
        created_by=CreationMechanism.PREPROCESS_RECIPE, parent=_managed_parent(), recipe=_recipe()
    )
    assert record.created_by is CreationMechanism.PREPROCESS_RECIPE
    assert record.parent is not None
    assert record.recipe is not None


def test_preprocess_recipe_accepts_unmanaged_source_parent() -> None:
    # First managed child of a legacy/unmanaged CSV: parent version_id is None.
    record = _record(
        created_by=CreationMechanism.PREPROCESS_RECIPE, parent=_unmanaged_parent(), recipe=_recipe()
    )
    assert record.parent is not None and record.parent.version_id is None


# --- PREPROCESS_RECIPE: enforced at construction --------------------------


def test_missing_parent_is_rejected_at_construction() -> None:
    with pytest.raises(DatasetVersionError) as exc_info:
        _record(created_by=CreationMechanism.PREPROCESS_RECIPE, recipe=_recipe())
    assert exc_info.value.code == PREPROCESS_PARENT_REQUIRED


def test_missing_recipe_is_rejected_at_construction() -> None:
    with pytest.raises(DatasetVersionError) as exc_info:
        _record(created_by=CreationMechanism.PREPROCESS_RECIPE, parent=_managed_parent())
    assert exc_info.value.code == PREPROCESS_RECIPE_REQUIRED


def test_missing_both_reports_parent_first() -> None:
    with pytest.raises(DatasetVersionError) as exc_info:
        _record(created_by=CreationMechanism.PREPROCESS_RECIPE)
    assert exc_info.value.code == PREPROCESS_PARENT_REQUIRED


# --- from_mapping enforces the same invariant with the same codes ----------


def _valid_preprocess_mapping() -> dict[str, Any]:
    record = _record(
        created_by=CreationMechanism.PREPROCESS_RECIPE, parent=_managed_parent(), recipe=_recipe()
    )
    return to_mapping(record)


def test_from_mapping_round_trips_a_valid_preprocess_record() -> None:
    mapping = _valid_preprocess_mapping()
    restored = from_mapping(mapping)
    assert restored.created_by is CreationMechanism.PREPROCESS_RECIPE
    assert restored.parent is not None
    assert restored.recipe is not None


def test_from_mapping_rejects_missing_parent() -> None:
    mapping = _valid_preprocess_mapping()
    del mapping["parent"]
    with pytest.raises(DatasetVersionError) as exc_info:
        from_mapping(mapping)
    assert exc_info.value.code == PREPROCESS_PARENT_REQUIRED


def test_from_mapping_rejects_missing_recipe() -> None:
    mapping = _valid_preprocess_mapping()
    del mapping["recipe"]
    with pytest.raises(DatasetVersionError) as exc_info:
        from_mapping(mapping)
    assert exc_info.value.code == PREPROCESS_RECIPE_REQUIRED


def test_from_mapping_rejects_missing_both_parent_first() -> None:
    mapping = _valid_preprocess_mapping()
    del mapping["parent"]
    del mapping["recipe"]
    with pytest.raises(DatasetVersionError) as exc_info:
        from_mapping(mapping)
    assert exc_info.value.code == PREPROCESS_PARENT_REQUIRED


# --- Pre-existing validation errors keep a value-free (None) code ----------


def test_unrelated_validation_error_has_no_invariant_code() -> None:
    # A malformed content_id fails an older check; its code stays None so the
    # two new invariant codes remain the only ones a reader must distinguish.
    with pytest.raises(DatasetVersionError) as exc_info:
        _record(content_id="sha1:" + "0" * 40)
    assert exc_info.value.code is None
