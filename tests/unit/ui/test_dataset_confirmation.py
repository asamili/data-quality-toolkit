"""Tests for explicit processed-version confirmation.

Cover identity/lineage construction, workspace-relative durable paths, the
sidecar-last registration boundary, no-overwrite linkage, and the partial-failure
contract (a durable CSV without registration is never reported as confirmed).
Fault injection on ``os.replace`` proves the registration boundary.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit.adapters.loaders.file.csv_loader import dataset_id_from_file
from data_quality_toolkit.adapters.ui.services import dataset_confirmation
from data_quality_toolkit.adapters.ui.services.dataset_confirmation import (
    SIDECAR_SUFFIX,
    ConfirmationStatus,
    confirm_processed_version,
)
from data_quality_toolkit.adapters.ui.services.dataset_versions import (
    CreationMechanism,
    DatasetFormat,
    content_id_from_bytes,
    content_id_from_file,
    from_mapping,
    new_family_id,
    new_version_id,
    recipe_digest,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    ManagedTrustRoot,
    commit_trust_root,
    ensure_session_capability,
    make_source_locator,
    retire_managed_trust,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT

_CSV_BYTES = b"id,value\n1,10\n2,20\n"
_RECIPE: dict[str, Any] = {
    "schema_version": 1,
    "steps": [{"operation": "drop_duplicates", "columns": [], "parameters": {}}],
    "summary": {"before": {"row_count": 4}, "after": {"row_count": 3}},
}
_LABEL = "cleaned v2"

# Content owned by a competing writer. Every byte must survive a collision.
_COMPETITOR = b"competing output that must never be overwritten\n"
_RIVAL_SIDECAR = b'{"not":"ours"}\n'

# Final-target suffixes, used to aim fault injection at one publish step.
_CSV_TARGET = "customers.csv"
_RECIPE_TARGET = os.path.join("recipes", "customers.json")


# --- fixtures / helpers ---------------------------------------------------


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _source_csv(tmp_path: Path, payload: bytes = b"id,value\n1,10\n1,10\n2,20\n") -> Path:
    src = tmp_path / "src" / "customers.csv"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


def _legacy_parent(tmp_path: Path) -> DatasetContext:
    src = _source_csv(tmp_path)
    stat = src.stat()
    return DatasetContext(
        source_path=str(src),
        display_name="customers.csv",
        size_bytes=int(stat.st_size),
        modified_ns=int(stat.st_mtime_ns),
    )


def _managed_parent(tmp_path: Path, *, family_id: str, root_content_id: str) -> DatasetContext:
    src = _source_csv(tmp_path)
    stat = src.stat()
    return DatasetContext(
        source_path=str(src),
        display_name="customers.csv",
        size_bytes=int(stat.st_size),
        modified_ns=int(stat.st_mtime_ns),
        managed=True,
        version_id=new_version_id(),
        family_id=family_id,
        content_id="sha256:" + "e" * 64,
        root_content_id=root_content_id,
        version_label="parent v1",
    )


def _confirm(
    root: Path,
    parent: DatasetContext,
    *,
    csv_bytes: bytes = _CSV_BYTES,
    recipe: dict[str, Any] | None = None,
    label: str = _LABEL,
) -> Any:
    return confirm_processed_version(
        workspace_root=str(root),
        csv_bytes=csv_bytes,
        recipe=_RECIPE if recipe is None else recipe,
        parent=parent,
        label=label,
        filename_stem=parent.display_name,
    )


def _patch_publish(
    monkeypatch: pytest.MonkeyPatch, *, fail_on_suffix: str | None = None
) -> list[str]:
    """Record every publish destination; optionally fail one by suffix."""
    calls: list[str] = []
    real = os.link

    def fake(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        name = os.fspath(dst)
        calls.append(str(name))
        if fail_on_suffix is not None and str(name).endswith(fail_on_suffix):
            raise OSError("injected publish failure")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(dataset_confirmation.os, "link", fake)
    return calls


def _patch_collision(
    monkeypatch: pytest.MonkeyPatch,
    *,
    collide_on_suffix: str,
    payload: bytes = _COMPETITOR,
    also_claim: tuple[tuple[str, bytes], ...] = (),
) -> list[str]:
    """Let a competitor claim a final target in the instant before it is published.

    Reproduces the reservation-to-finalization race exactly: reservation saw the
    path free, then another writer created it before this confirmation could.
    ``also_claim`` lets the competitor claim further paths (workspace-relative) in
    the same instant.
    """
    calls: list[str] = []
    real = os.link

    def claim(target: Path, content: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def fake(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        name = str(os.fspath(dst))
        calls.append(name)
        if name.endswith(collide_on_suffix):
            root = Path(name).parent.parent
            claim(Path(name), payload)
            for relative, content in also_claim:
                claim(root / relative, content)
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(dataset_confirmation.os, "link", fake)
    return calls


def _tmp_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file() and p.name.endswith(".tmp")]


# --- identity and lineage -------------------------------------------------


def test_legacy_parent_confirmation_starts_new_family_from_source_content(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    parent = _legacy_parent(tmp_path)
    expected_parent_content = content_id_from_file(Path(parent.source_path))

    result = _confirm(root, parent)

    assert result.status is ConfirmationStatus.CONFIRMED
    record = result.record
    assert record is not None
    # A brand-new family, rooted at the exact unmanaged source content.
    assert str(uuid.UUID(record.family_id)) == record.family_id
    assert record.root_content_id == expected_parent_content
    assert record.parent is not None
    assert record.parent.version_id is None
    assert record.parent.content_id == expected_parent_content
    assert record.created_by is CreationMechanism.PREPROCESS_RECIPE
    assert record.format is DatasetFormat.CSV
    assert record.created_at.tzinfo is not None


def test_managed_parent_confirmation_inherits_family_and_root(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    family = new_family_id()
    root_content = "sha256:" + "f" * 64
    parent = _managed_parent(tmp_path, family_id=family, root_content_id=root_content)

    result = _confirm(root, parent)

    record = result.record
    assert record is not None
    assert record.family_id == family
    assert record.root_content_id == root_content
    assert record.parent is not None
    assert record.parent.version_id == parent.version_id
    assert record.parent.content_id == parent.content_id


def test_processed_content_id_hashes_all_bytes(tmp_path: Path) -> None:
    # Two payloads identical through the first megabyte, differing only after it:
    # the full-content SHA-256 must differ while the first-1-MB SHA-1 matches.
    head = b"a" * (1024 * 1024)
    first = _confirm(_workspace(tmp_path / "one"), _legacy_parent(tmp_path), csv_bytes=head + b"x")
    second = _confirm(_workspace(tmp_path / "two"), _legacy_parent(tmp_path), csv_bytes=head + b"y")

    assert first.record is not None and second.record is not None
    assert first.record.content_id == content_id_from_bytes(head + b"x")
    assert first.record.content_id != second.record.content_id
    assert first.record.dataset_id == second.record.dataset_id


def test_compatibility_dataset_id_matches_existing_algorithm(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    result = _confirm(root, _legacy_parent(tmp_path))

    assert result.record is not None
    written = root / result.csv_relative_path
    assert result.record.dataset_id == dataset_id_from_file(written)


def test_recipe_digest_matches_canonical_recipe_mapping(tmp_path: Path) -> None:
    result = _confirm(_workspace(tmp_path), _legacy_parent(tmp_path))

    assert result.record is not None
    assert result.record.recipe is not None
    assert result.record.recipe.digest == recipe_digest(_RECIPE)


def test_confirmation_emits_workspace_relative_paths(tmp_path: Path) -> None:
    result = _confirm(_workspace(tmp_path), _legacy_parent(tmp_path))

    assert result.record is not None
    assert result.record.file_relative_path == "preprocessed/customers.csv"
    assert result.record.recipe is not None
    assert result.record.recipe.relative_path == "recipes/customers.json"
    assert result.csv_relative_path == "preprocessed/customers.csv"
    assert result.sidecar_relative_path == "preprocessed/customers.csv.dqtv.json"


# --- durable output -------------------------------------------------------


def test_confirmation_creates_csv_recipe_and_sidecar(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    result = _confirm(root, _legacy_parent(tmp_path))

    assert (root / "preprocessed" / "customers.csv").read_bytes() == _CSV_BYTES
    assert (root / "recipes" / "customers.json").is_file()
    assert (root / "preprocessed" / "customers.csv.dqtv.json").is_file()
    assert result.status is ConfirmationStatus.CONFIRMED


def test_sidecar_round_trips_through_lifecycle_parser(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    result = _confirm(root, _legacy_parent(tmp_path))

    sidecar = (root / "preprocessed" / "customers.csv.dqtv.json").read_text(encoding="utf-8")
    parsed = from_mapping(json.loads(sidecar))

    assert parsed == result.record


def test_sidecar_is_written_last_as_the_registration_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_publish(monkeypatch)

    _confirm(_workspace(tmp_path), _legacy_parent(tmp_path))

    assert len(calls) == 3
    assert calls[0].endswith(_CSV_TARGET)
    assert calls[1].endswith(_RECIPE_TARGET)
    assert calls[2].endswith(SIDECAR_SUFFIX)


def test_existing_targets_are_never_overwritten_and_stay_linked(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    parent = _legacy_parent(tmp_path)

    first = _confirm(root, parent)
    second = _confirm(root, parent)

    assert first.csv_relative_path == "preprocessed/customers.csv"
    # A collision suffixes every target together, keeping the trio linked.
    assert second.csv_relative_path == "preprocessed/customers-1.csv"
    assert second.recipe_relative_path == "recipes/customers-1.json"
    assert second.sidecar_relative_path == "preprocessed/customers-1.csv.dqtv.json"
    assert (root / "preprocessed" / "customers.csv").is_file()
    assert (root / "preprocessed" / "customers-1.csv").is_file()


def test_temporary_files_are_cleaned_up(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _confirm(root, _legacy_parent(tmp_path))

    assert _tmp_files(root) == []


# --- partial failure ------------------------------------------------------


def test_sidecar_registration_failure_returns_saved_unmanaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _patch_publish(monkeypatch, fail_on_suffix=SIDECAR_SUFFIX)

    result = _confirm(root, _legacy_parent(tmp_path))

    assert result.status is ConfirmationStatus.SAVED_UNMANAGED
    # No authoritative record, and nothing may be treated as confirmed.
    assert result.record is None
    assert result.confirmed is False
    # The CSV is durable but unregistered; no final sidecar may exist.
    assert (root / "preprocessed" / "customers.csv").is_file()
    assert not (root / "preprocessed" / "customers.csv.dqtv.json").exists()
    assert "not a confirmed version" in result.message


def test_failed_registration_leaves_no_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _patch_publish(monkeypatch, fail_on_suffix=SIDECAR_SUFFIX)

    _confirm(root, _legacy_parent(tmp_path))

    assert _tmp_files(root) == []


# --- finalization collisions (target claimed after reservation) -----------


def test_csv_collision_at_finalization_confirms_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    calls = _patch_collision(monkeypatch, collide_on_suffix=_CSV_TARGET)

    result = _confirm(root, _legacy_parent(tmp_path))

    assert result.status is ConfirmationStatus.FAILED
    assert result.record is None
    assert result.confirmed is False
    # Specifically the exclusive-create collision path, not an incidental error.
    assert "already occupies" in result.message
    # The competing CSV survives byte-for-byte; nothing else was published.
    assert (root / "preprocessed" / "customers.csv").read_bytes() == _COMPETITOR
    assert not (root / "recipes" / "customers.json").exists()
    assert not (root / "preprocessed" / f"customers.csv{SIDECAR_SUFFIX}").exists()
    assert calls == [str(root / "preprocessed" / "customers.csv")]


def test_recipe_collision_returns_saved_unmanaged_without_a_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _patch_collision(monkeypatch, collide_on_suffix=_RECIPE_TARGET)

    result = _confirm(root, _legacy_parent(tmp_path))

    assert result.status is ConfirmationStatus.SAVED_UNMANAGED
    assert result.record is None
    assert result.confirmed is False
    # The CSV is durable but unregistered, the competing recipe is untouched, and
    # registration never happened.
    assert (root / "preprocessed" / "customers.csv").read_bytes() == _CSV_BYTES
    assert (root / "recipes" / "customers.json").read_bytes() == _COMPETITOR
    assert not (root / "preprocessed" / f"customers.csv{SIDECAR_SUFFIX}").exists()


def test_sidecar_collision_preserves_the_competing_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _patch_collision(monkeypatch, collide_on_suffix=SIDECAR_SUFFIX)

    result = _confirm(root, _legacy_parent(tmp_path))

    assert result.status is ConfirmationStatus.SAVED_UNMANAGED
    assert result.record is None
    assert result.confirmed is False
    assert (root / "preprocessed" / "customers.csv").read_bytes() == _CSV_BYTES
    assert (root / "recipes" / "customers.json").is_file()
    # Someone else's registration must not be clobbered by ours.
    assert (root / "preprocessed" / f"customers.csv{SIDECAR_SUFFIX}").read_bytes() == _COMPETITOR


def test_recipe_collision_never_deletes_a_competing_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A competitor claims the recipe and the sidecar in the same instant. Cleaning
    # the sidecar path on failure would destroy a rival's registration, so the
    # failure path must not touch it at all.
    root = _workspace(tmp_path)
    _patch_collision(
        monkeypatch,
        collide_on_suffix=_RECIPE_TARGET,
        also_claim=((f"preprocessed/customers.csv{SIDECAR_SUFFIX}", _RIVAL_SIDECAR),),
    )

    result = _confirm(root, _legacy_parent(tmp_path))

    assert result.status is ConfirmationStatus.SAVED_UNMANAGED
    assert result.record is None
    assert (root / "recipes" / "customers.json").read_bytes() == _COMPETITOR
    assert (root / "preprocessed" / f"customers.csv{SIDECAR_SUFFIX}").read_bytes() == _RIVAL_SIDECAR


@pytest.mark.parametrize("suffix", [_CSV_TARGET, _RECIPE_TARGET, SIDECAR_SUFFIX])
def test_collision_leaves_no_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    root = _workspace(tmp_path)
    _patch_collision(monkeypatch, collide_on_suffix=suffix)

    _confirm(root, _legacy_parent(tmp_path))

    assert _tmp_files(root) == []


@pytest.mark.parametrize("suffix", [_CSV_TARGET, _RECIPE_TARGET, SIDECAR_SUFFIX])
def test_collision_never_truncates_or_removes_the_competing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    root = _workspace(tmp_path)
    _patch_collision(monkeypatch, collide_on_suffix=suffix)

    _confirm(root, _legacy_parent(tmp_path))

    competitor = next(p for p in root.rglob("*") if p.is_file() and str(p).endswith(suffix))
    assert competitor.read_bytes() == _COMPETITOR


# --- validation writes nothing --------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"label": "   "},
        {"csv_bytes": b""},
        {"recipe": {}},
    ],
)
def test_validation_failure_writes_nothing(tmp_path: Path, kwargs: dict[str, Any]) -> None:
    root = _workspace(tmp_path)

    result = _confirm(root, _legacy_parent(tmp_path), **kwargs)

    assert result.status is ConfirmationStatus.FAILED
    assert result.record is None
    assert not (root / "preprocessed").exists()
    assert not (root / "recipes").exists()


def test_missing_parent_context_is_rejected_before_writing(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    result = confirm_processed_version(
        workspace_root=str(root),
        csv_bytes=_CSV_BYTES,
        recipe=_RECIPE,
        parent=None,
        label=_LABEL,
    )

    assert result.status is ConfirmationStatus.FAILED
    assert not (root / "preprocessed").exists()


def test_blank_workspace_root_is_rejected_before_writing(tmp_path: Path) -> None:
    result = confirm_processed_version(
        workspace_root="   ",
        csv_bytes=_CSV_BYTES,
        recipe=_RECIPE,
        parent=_legacy_parent(tmp_path),
        label=_LABEL,
    )

    assert result.status is ConfirmationStatus.FAILED
    assert result.record is None


def test_unreadable_legacy_parent_is_rejected_before_writing(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    parent = DatasetContext(
        source_path=str(tmp_path / "src" / "missing.csv"),
        display_name="missing.csv",
        size_bytes=1,
        modified_ns=1,
    )

    result = _confirm(root, parent)

    assert result.status is ConfirmationStatus.FAILED
    assert not (root / "preprocessed").exists()


def test_managed_parent_missing_identities_is_rejected(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    src = _source_csv(tmp_path)
    parent = DatasetContext(
        source_path=str(src),
        display_name="customers.csv",
        size_bytes=1,
        modified_ns=1,
        managed=True,
        version_id=new_version_id(),
        family_id=None,  # missing required lifecycle identity
        content_id="sha256:" + "e" * 64,
        root_content_id="sha256:" + "f" * 64,
        version_label="parent v1",
    )

    result = _confirm(root, parent)

    assert result.status is ConfirmationStatus.FAILED
    assert not (root / "preprocessed").exists()


# --- display safety -------------------------------------------------------


def test_messages_and_display_fields_expose_no_absolute_paths(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    parent = _legacy_parent(tmp_path)

    confirmed = _confirm(root, parent)
    failed = _confirm(root, parent, label="")

    for result in (confirmed, failed):
        for field in (
            result.message,
            result.csv_relative_path,
            result.recipe_relative_path,
            result.sidecar_relative_path,
        ):
            assert str(root) not in field
            assert str(tmp_path) not in field
    assert confirmed.record is not None
    assert str(root) not in confirmed.record.file_relative_path


# --- root-first confirmation authority ------------------------------------


def _trusted_confirmation_session(
    tmp_path: Path, *, family_id: str | None = None, root_content_id: str | None = None
) -> tuple[dict[str, Any], ManagedTrustRoot]:
    src = _source_csv(tmp_path)
    stat = src.stat()
    state: dict[str, Any] = {}
    capability = ensure_session_capability(state)
    root = commit_trust_root(
        state,
        capability,
        version_id=new_version_id(),
        family_id=family_id or new_family_id(),
        content_id="sha256:" + "e" * 64,
        root_content_id=root_content_id or ("sha256:" + "f" * 64),
        parent_version_id=None,
        version_label="trusted parent v1",
        locator=make_source_locator(
            display_name="customers.csv",
            relative_posix="preprocessed/customers.csv",
            absolute_path=str(src),
        ),
        size_bytes=int(stat.st_size),
        modified_ns=int(stat.st_mtime_ns),
        large_file_mode=False,
    )
    return state, root


def test_valid_trust_root_overrides_stale_passed_parent(tmp_path: Path) -> None:
    """A valid trust root is the confirmation parent even when `parent` is stale."""
    root_dir = _workspace(tmp_path)
    session, trust_root = _trusted_confirmation_session(tmp_path)
    stale = _legacy_parent(tmp_path)  # unmanaged, would start a NEW family

    result = confirm_processed_version(
        workspace_root=str(root_dir),
        csv_bytes=_CSV_BYTES,
        recipe=_RECIPE,
        parent=stale,
        label=_LABEL,
        filename_stem="customers.csv",
        session_state=session,
    )

    assert result.status is ConfirmationStatus.CONFIRMED
    assert result.record is not None
    # Lineage descends from the trust root, not from the stale unmanaged parent.
    assert result.record.family_id == trust_root.family_id
    assert result.record.root_content_id == trust_root.root_content_id
    assert result.record.parent is not None
    assert result.record.parent.version_id == trust_root.version_id
    assert result.record.parent.content_id == trust_root.content_id


def test_managed_mirror_without_valid_trust_is_refused(tmp_path: Path) -> None:
    root_dir = _workspace(tmp_path)
    mirror = _managed_parent(
        tmp_path, family_id=new_family_id(), root_content_id="sha256:" + "a" * 64
    )
    session: dict[str, Any] = {DATASET_CONTEXT: mirror}  # managed-looking, no trust

    result = confirm_processed_version(
        workspace_root=str(root_dir),
        csv_bytes=_CSV_BYTES,
        recipe=_RECIPE,
        parent=mirror,
        label=_LABEL,
        filename_stem="customers.csv",
        session_state=session,
    )

    assert result.status is ConfirmationStatus.FAILED
    assert result.record is None
    assert "valid managed trust root" in result.message
    # Fails closed before any durable write.
    assert not (root_dir / "preprocessed").exists()


def test_manual_parent_cannot_override_valid_trust(tmp_path: Path) -> None:
    root_dir = _workspace(tmp_path)
    session, trust_root = _trusted_confirmation_session(tmp_path)
    manual = _managed_parent(
        tmp_path, family_id=new_family_id(), root_content_id="sha256:" + "9" * 64
    )

    result = confirm_processed_version(
        workspace_root=str(root_dir),
        csv_bytes=_CSV_BYTES,
        recipe=_RECIPE,
        parent=manual,
        label=_LABEL,
        filename_stem="customers.csv",
        session_state=session,
    )

    assert result.status is ConfirmationStatus.CONFIRMED
    assert result.record is not None
    assert result.record.family_id == trust_root.family_id
    assert result.record.family_id != manual.family_id


def test_retired_trust_fails_closed_for_confirmation(tmp_path: Path) -> None:
    root_dir = _workspace(tmp_path)
    session, trust_root = _trusted_confirmation_session(tmp_path)
    mirror = DatasetContext(
        source_path=trust_root.locator.absolute_path,
        display_name=trust_root.locator.display_name,
        size_bytes=trust_root.size_bytes,
        modified_ns=trust_root.modified_ns,
        managed=True,
        version_id=trust_root.version_id,
        family_id=trust_root.family_id,
        content_id=trust_root.content_id,
        root_content_id=trust_root.root_content_id,
        version_label=trust_root.version_label,
    )
    retire_managed_trust(session)
    session[DATASET_CONTEXT] = mirror  # physical marker deliberately left behind

    result = confirm_processed_version(
        workspace_root=str(root_dir),
        csv_bytes=_CSV_BYTES,
        recipe=_RECIPE,
        parent=mirror,
        label=_LABEL,
        filename_stem="customers.csv",
        session_state=session,
    )

    assert result.status is ConfirmationStatus.FAILED
    assert result.record is None


def test_unmanaged_confirmation_preserved_with_session_state(tmp_path: Path) -> None:
    """No managed trust and no managed mirror -> legacy lineage is unchanged."""
    root_dir = _workspace(tmp_path)
    parent = _legacy_parent(tmp_path)
    session: dict[str, Any] = {DATASET_CONTEXT: parent}

    with_session = confirm_processed_version(
        workspace_root=str(root_dir),
        csv_bytes=_CSV_BYTES,
        recipe=_RECIPE,
        parent=parent,
        label=_LABEL,
        filename_stem="customers.csv",
        session_state=session,
    )

    assert with_session.status is ConfirmationStatus.CONFIRMED
    assert with_session.record is not None
    assert with_session.record.parent is not None
    assert with_session.record.parent.version_id is None  # unmanaged parent by content
    assert with_session.record.root_content_id == content_id_from_file(Path(parent.source_path))


def test_omitting_session_state_preserves_legacy_contract(tmp_path: Path) -> None:
    root_dir = _workspace(tmp_path)
    parent = _legacy_parent(tmp_path)

    result = _confirm(root_dir, parent)

    assert result.status is ConfirmationStatus.CONFIRMED
    assert result.record is not None
    assert result.record.parent is not None
    assert result.record.parent.version_id is None


def test_trust_refusal_message_is_privacy_safe(tmp_path: Path) -> None:
    root_dir = _workspace(tmp_path)
    mirror = _managed_parent(
        tmp_path, family_id=new_family_id(), root_content_id="sha256:" + "a" * 64
    )
    session: dict[str, Any] = {DATASET_CONTEXT: mirror}

    result = confirm_processed_version(
        workspace_root=str(root_dir),
        csv_bytes=_CSV_BYTES,
        recipe=_RECIPE,
        parent=mirror,
        label=_LABEL,
        filename_stem="customers.csv",
        session_state=session,
    )

    assert str(tmp_path) not in result.message
    assert mirror.source_path not in result.message
