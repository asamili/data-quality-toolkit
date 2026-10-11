"""Tests for the shared lifecycle short-version formatter (H2).

One formatter serves every equivalent managed-version surface, so the active
dataset and a newly confirmed version can never spell one identity two ways.
Cover the canonical label contract (prefix, width, casing, determinism), the
byte-identical agreement of the two surfaces, safe degradation for missing or
unmanaged identities, and the purity guarantee that formatting mutates nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.components import active_dataset_identity
from data_quality_toolkit.adapters.ui.components.active_dataset_identity import (
    LEGACY_STATUS,
    MANAGED_STATUS,
    build_active_dataset_identity,
)
from data_quality_toolkit.adapters.ui.services.dataset_confirmation import (
    ConfirmationStatus,
    ConfirmedVersionHandoff,
    confirm_processed_version,
)
from data_quality_toolkit.adapters.ui.services.dataset_versions import (
    SCHEMA_VERSION,
    CreationMechanism,
    DatasetFormat,
    DatasetVersionRecord,
    ParentRef,
    RecipeRef,
    from_mapping,
    to_mapping,
)
from data_quality_toolkit.adapters.ui.services.version_presentation import (
    SHORT_VERSION_HEX_CHARS,
    SHORT_VERSION_PREFIX,
    format_short_version,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext

# The representative identity named by the presentation contract: its canonical
# short token is ``3f1c9a2e``, so every surface must render ``v-3f1c9a2e``.
_VERSION_ID = "3f1c9a2e-1b4d-4c6a-8e2f-7a9b0c1d2e3f"
_EXPECTED_LABEL = "v-3f1c9a2e"

_FAMILY_ID = "9f8e7d6c-5b4a-4938-8271-605f4e3d2c1b"
_CONTENT_ID = "sha256:" + "a" * 64
_ROOT_CONTENT_ID = "sha256:" + "b" * 64
_RECIPE_DIGEST = "sha256:" + "c" * 64
_DATASET_ID = "sha1:" + "d" * 40
_PARENT_CONTENT_ID = "sha256:" + "e" * 64


def _record() -> DatasetVersionRecord:
    """A valid, fully populated confirmed-version record."""
    return DatasetVersionRecord(
        schema_version=SCHEMA_VERSION,
        version_id=_VERSION_ID,
        family_id=_FAMILY_ID,
        root_content_id=_ROOT_CONTENT_ID,
        content_id=_CONTENT_ID,
        dataset_id=_DATASET_ID,
        label="cleaned v2",
        file_relative_path="preprocessed/customers.csv",
        format=DatasetFormat.CSV,
        size_bytes=19,
        created_at=datetime(2026, 7, 24, 12, 0, tzinfo=UTC),
        created_by=CreationMechanism.PREPROCESS_RECIPE,
        parent=ParentRef(version_id=None, content_id=_PARENT_CONTENT_ID),
        recipe=RecipeRef(digest=_RECIPE_DIGEST, relative_path="recipes/customers.json"),
    )


def _handoff() -> ConfirmedVersionHandoff:
    return ConfirmedVersionHandoff(
        record=_record(),
        csv_path=r"C:\ws\preprocessed\customers.csv",
        csv_relative_path="preprocessed/customers.csv",
    )


def _managed_context(version_id: str = _VERSION_ID) -> DatasetContext:
    return DatasetContext(
        source_path=r"C:\ws\preprocessed\customers.csv",
        display_name="customers.csv",
        size_bytes=19,
        modified_ns=1,
        managed=True,
        version_id=version_id,
        family_id=_FAMILY_ID,
        content_id=_CONTENT_ID,
        root_content_id=_ROOT_CONTENT_ID,
        version_label="cleaned v2",
    )


# --- canonical label contract ---------------------------------------------


def test_representative_identity_formats_as_the_contracted_label() -> None:
    assert format_short_version(_VERSION_ID) == _EXPECTED_LABEL


def test_label_is_the_prefix_followed_by_the_canonical_short_token() -> None:
    label = format_short_version(_VERSION_ID)
    token = label.removeprefix(SHORT_VERSION_PREFIX)

    assert label == f"{SHORT_VERSION_PREFIX}{token}"
    assert token == _VERSION_ID.replace("-", "")[:SHORT_VERSION_HEX_CHARS]


def test_prefix_appears_exactly_once() -> None:
    label = format_short_version(_VERSION_ID)

    assert label.startswith(SHORT_VERSION_PREFIX)
    assert label.count(SHORT_VERSION_PREFIX) == 1
    assert not label.startswith(SHORT_VERSION_PREFIX * 2)


def test_short_token_width_and_lowercase_hex_casing_are_unchanged() -> None:
    token = format_short_version(_VERSION_ID).removeprefix(SHORT_VERSION_PREFIX)

    assert SHORT_VERSION_HEX_CHARS == 8
    assert len(token) == SHORT_VERSION_HEX_CHARS
    assert len(format_short_version(_VERSION_ID)) == len(SHORT_VERSION_PREFIX) + 8
    assert token == token.lower()
    assert all(char in "0123456789abcdef" for char in token)


def test_equivalent_spellings_of_one_identity_yield_one_label() -> None:
    hyphenless = _VERSION_ID.replace("-", "")
    braced = "{" + _VERSION_ID + "}"

    assert format_short_version(_VERSION_ID.upper()) == _EXPECTED_LABEL
    assert format_short_version(hyphenless) == _EXPECTED_LABEL
    assert format_short_version(braced) == _EXPECTED_LABEL
    assert format_short_version(f"  {_VERSION_ID}  ") == _EXPECTED_LABEL


def test_formatter_is_deterministic_across_repeated_calls() -> None:
    assert format_short_version(_VERSION_ID) == format_short_version(_VERSION_ID)


# --- one shared formatter --------------------------------------------------


def test_active_surface_reuses_the_one_shared_formatter_object() -> None:
    assert active_dataset_identity.short_version_id is format_short_version


def test_active_and_newly_confirmed_surfaces_produce_byte_identical_labels() -> None:
    active = build_active_dataset_identity(_managed_context()).short_version_id
    confirmed = _handoff().short_version_id

    assert active == confirmed == _EXPECTED_LABEL


def test_active_descriptor_embeds_the_shared_label_exactly_once() -> None:
    descriptor = build_active_dataset_identity(_managed_context()).descriptor

    assert descriptor == f"{MANAGED_STATUS} {_EXPECTED_LABEL}"
    assert descriptor.count(SHORT_VERSION_PREFIX) == 1


# --- safe degradation ------------------------------------------------------


@pytest.mark.parametrize(
    "unusable",
    [
        None,
        "",
        "   ",
        "not-a-uuid",
        "3f1c9a2e",
        "v-3f1c9a2e",
        "preprocessed/customers.csv",
        "0" * 8,
    ],
)
def test_unusable_identity_degrades_to_an_empty_label(unusable: str | None) -> None:
    assert format_short_version(unusable) == ""


def test_an_already_formatted_label_is_never_prefixed_twice() -> None:
    assert format_short_version(format_short_version(_VERSION_ID)) == ""


def test_unmanaged_context_presents_no_short_version() -> None:
    legacy = DatasetContext(
        source_path=r"C:\data\customers.csv",
        display_name="customers.csv",
        size_bytes=19,
        modified_ns=1,
    )
    identity = build_active_dataset_identity(legacy)

    assert identity.short_version_id == ""
    assert identity.descriptor == LEGACY_STATUS
    assert SHORT_VERSION_PREFIX not in identity.descriptor


def test_managed_context_with_malformed_identity_degrades_to_bare_status() -> None:
    identity = build_active_dataset_identity(_managed_context(version_id="not-a-uuid"))

    assert identity.managed is True
    assert identity.short_version_id == ""
    assert identity.descriptor == MANAGED_STATUS


# --- purity ----------------------------------------------------------------


def test_formatting_mutates_neither_the_record_nor_its_serialized_form() -> None:
    handoff = _handoff()
    before = to_mapping(handoff.record)

    label = handoff.short_version_id

    assert label == _EXPECTED_LABEL
    assert handoff.record.version_id == _VERSION_ID
    assert handoff.version_id == _VERSION_ID
    assert handoff.record == _record()
    assert to_mapping(handoff.record) == before


def test_formatting_mutates_neither_the_context_nor_the_derived_identity() -> None:
    context = _managed_context()
    before = (context.version_id, context.family_id, context.content_id, context.managed)

    first = build_active_dataset_identity(context)
    second = build_active_dataset_identity(context)

    assert (context.version_id, context.family_id, context.content_id, context.managed) == before
    assert first == second


# --- end-to-end confirmation flow ------------------------------------------
#
# The unit tests above pin the formatter. These drive a real confirmation so the
# label the operator actually sees, the durable sidecar, and the full identity
# carried forward to activation are all checked against one another.

_CSV_BYTES = b"id,value\n1,10\n2,20\n"
_RECIPE: dict[str, Any] = {
    "schema_version": 1,
    "steps": [{"operation": "drop_duplicates", "columns": [], "parameters": {}}],
    "summary": {"before": {"row_count": 4}, "after": {"row_count": 3}},
}


def _confirm(tmp_path: Path) -> Any:
    """Confirm one version from an unmanaged parent inside a fresh workspace."""
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "src" / "customers.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"id,value\n1,10\n1,10\n2,20\n")
    stat = source.stat()
    parent = DatasetContext(
        source_path=str(source),
        display_name="customers.csv",
        size_bytes=int(stat.st_size),
        modified_ns=int(stat.st_mtime_ns),
    )
    return root, confirm_processed_version(
        workspace_root=str(root),
        csv_bytes=_CSV_BYTES,
        recipe=_RECIPE,
        parent=parent,
        label="cleaned v2",
        filename_stem=parent.display_name,
    )


def _context_from(result: Any) -> DatasetContext:
    """The managed context a later Set-active builds from a confirmed result."""
    record = result.record
    return DatasetContext(
        source_path=result.csv_path,
        display_name=Path(result.csv_relative_path).name,
        size_bytes=record.size_bytes,
        modified_ns=1,
        managed=True,
        version_id=record.version_id,
        family_id=record.family_id,
        content_id=record.content_id,
        root_content_id=record.root_content_id,
        version_label=record.label,
    )


def test_confirmation_message_uses_the_shared_short_version_label(tmp_path: Path) -> None:
    _root, result = _confirm(tmp_path)

    assert result.status is ConfirmationStatus.CONFIRMED
    assert result.record is not None
    label = format_short_version(result.record.version_id)
    assert label.startswith(SHORT_VERSION_PREFIX)
    assert result.message == f"Confirmed version {result.record.label} ({label})."
    assert result.message.count(SHORT_VERSION_PREFIX) == 1


def test_confirmation_message_never_leaks_the_full_version_identity(tmp_path: Path) -> None:
    _root, result = _confirm(tmp_path)

    assert result.record is not None
    assert result.record.version_id not in result.message
    assert result.record.family_id not in result.message
    assert result.record.content_id not in result.message


def test_confirmed_and_active_surfaces_of_one_version_agree(tmp_path: Path) -> None:
    _root, result = _confirm(tmp_path)
    assert result.record is not None

    handoff = ConfirmedVersionHandoff(
        record=result.record,
        csv_path=result.csv_path,
        csv_relative_path=result.csv_relative_path,
    )
    active = build_active_dataset_identity(_context_from(result))

    assert handoff.short_version_id == format_short_version(result.record.version_id)
    assert active.short_version_id == handoff.short_version_id
    assert handoff.short_version_id.count(SHORT_VERSION_PREFIX) == 1
    assert active.descriptor == f"{MANAGED_STATUS} {handoff.short_version_id}"
    # The handoff still carries the untouched full identity for activation.
    assert handoff.version_id == result.record.version_id


def test_reading_a_short_label_leaves_record_and_sidecar_untouched(tmp_path: Path) -> None:
    root, result = _confirm(tmp_path)
    assert result.record is not None

    sidecar = root / result.sidecar_relative_path
    before_bytes = sidecar.read_bytes()
    before_record = to_mapping(result.record)
    handoff = ConfirmedVersionHandoff(
        record=result.record,
        csv_path=result.csv_path,
        csv_relative_path=result.csv_relative_path,
    )

    assert handoff.short_version_id
    assert build_active_dataset_identity(_context_from(result)).short_version_id

    assert sidecar.read_bytes() == before_bytes
    assert to_mapping(result.record) == before_record
    assert result.status is ConfirmationStatus.CONFIRMED


def test_the_durable_record_stores_identity_never_a_presentation_label(tmp_path: Path) -> None:
    root, result = _confirm(tmp_path)
    assert result.record is not None

    stored = json.loads((root / result.sidecar_relative_path).read_bytes().decode("utf-8"))

    assert stored["version_id"] == result.record.version_id
    assert not stored["version_id"].startswith(SHORT_VERSION_PREFIX)
    assert from_mapping(stored).version_id == result.record.version_id
    assert format_short_version(stored["version_id"]) == format_short_version(
        result.record.version_id
    )
