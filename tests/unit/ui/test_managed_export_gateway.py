"""Tests for the UI-private managed export gateway.

Proves exact provenance transfer, fail-closed trust, the FULL size ceiling at
and above the boundary, LARGE refusal, privacy of every refusal surface, and
that provenance crosses the boundary as one undecomposed object.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import uuid
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.services import managed_export_gateway as gateway
from data_quality_toolkit.adapters.ui.services.managed_export_gateway import (
    ManagedExportRefusedError,
    build_verified_managed_export_source,
    managed_export_available,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    MANAGED_TRUST_STATE_KEY,
    ManagedTrustRoot,
    SessionCapability,
    commit_trust_root,
    ensure_session_capability,
    make_source_locator,
    retire_managed_trust,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT
from data_quality_toolkit.shared.managed_export_source import (
    MANAGED_FULL_MAX_SOURCE_BYTES,
    VerifiedManagedExportSource,
)

_MANAGED_ABS = "C:\\private\\workspace\\preprocessed\\customers.csv"
_VERSION_ID = str(uuid.uuid4())
_FAMILY_ID = str(uuid.uuid4())
_PARENT_VERSION_ID = str(uuid.uuid4())
_CONTENT_ID = "sha256:" + "a" * 64
_ROOT_CONTENT_ID = "sha256:" + "b" * 64


def _trusted_state(
    *, large: bool = False, size: int = 2048
) -> tuple[dict[str, Any], ManagedTrustRoot]:
    state: dict[str, Any] = {}
    capability = ensure_session_capability(state)
    root = commit_trust_root(
        state,
        capability,
        version_id=_VERSION_ID,
        family_id=_FAMILY_ID,
        content_id=_CONTENT_ID,
        root_content_id=_ROOT_CONTENT_ID,
        parent_version_id=_PARENT_VERSION_ID,
        version_label="cleaned v2",
        locator=make_source_locator(
            display_name="customers.csv",
            relative_posix="preprocessed/customers.csv",
            absolute_path=_MANAGED_ABS,
        ),
        size_bytes=size,
        modified_ns=10,
        large_file_mode=large,
    )
    return state, root


def _managed_mirror() -> DatasetContext:
    return DatasetContext(
        source_path=_MANAGED_ABS,
        display_name="customers.csv",
        size_bytes=2048,
        modified_ns=10,
        managed=True,
        version_id=_VERSION_ID,
        family_id=_FAMILY_ID,
        content_id=_CONTENT_ID,
        root_content_id=_ROOT_CONTENT_ID,
        version_label="cleaned v2",
    )


# --- A. Exact provenance -------------------------------------------------------


def test_gateway_transfers_every_verified_identity() -> None:
    state, root = _trusted_state()

    source = build_verified_managed_export_source(state)

    assert isinstance(source, VerifiedManagedExportSource)
    assert source.version_id == root.version_id
    assert source.family_id == root.family_id
    assert source.content_id == root.content_id
    assert source.root_content_id == root.root_content_id
    assert source.parent_version_id == root.parent_version_id
    assert source.version_label == root.version_label
    assert source.display_name == root.locator.display_name
    assert source.relative_posix == root.locator.relative_posix
    assert source.size_bytes == root.size_bytes
    assert source.modified_ns == root.modified_ns
    assert source.large_file_mode is False
    assert source.source_path == root.locator.absolute_path


def test_provenance_is_immutable_after_minting() -> None:
    state, _root = _trusted_state()

    source = build_verified_managed_export_source(state)

    with pytest.raises(dataclasses.FrozenInstanceError):
        source.version_id = "tampered"  # type: ignore[misc]


def test_gateway_returns_one_object_not_decomposed_parts() -> None:
    state, _root = _trusted_state()

    result = build_verified_managed_export_source(state)

    assert not isinstance(result, tuple)
    assert isinstance(result, VerifiedManagedExportSource)
    signature = inspect.signature(build_verified_managed_export_source)
    assert list(signature.parameters) == ["state"]
    assert signature.return_annotation == "VerifiedManagedExportSource"


def test_gateway_never_returns_a_trust_type() -> None:
    state, _root = _trusted_state()

    source = build_verified_managed_export_source(state)

    assert not isinstance(source, ManagedTrustRoot)
    for value in dataclasses.astuple(source):
        assert not isinstance(value, ManagedTrustRoot | SessionCapability)


# --- B. Fail-closed trust ---------------------------------------------------------


def test_no_trust_is_refused() -> None:
    with pytest.raises(ManagedExportRefusedError) as excinfo:
        build_verified_managed_export_source({})
    assert excinfo.value.reason_code == "NO_VALID_TRUST"


def test_managed_mirror_without_trust_is_refused() -> None:
    state: dict[str, Any] = {DATASET_CONTEXT: _managed_mirror()}

    with pytest.raises(ManagedExportRefusedError) as excinfo:
        build_verified_managed_export_source(state)

    assert excinfo.value.reason_code == "MANAGED_MIRROR_WITHOUT_TRUST"


def test_retired_trust_is_refused_even_with_mirror_left_behind() -> None:
    state, _root = _trusted_state()
    mirror = _managed_mirror()
    retire_managed_trust(state)
    state[DATASET_CONTEXT] = mirror  # physical marker deliberately not cleaned

    with pytest.raises(ManagedExportRefusedError) as excinfo:
        build_verified_managed_export_source(state)

    assert excinfo.value.reason_code == "MANAGED_MIRROR_WITHOUT_TRUST"


def test_replaced_capability_is_refused() -> None:
    state, _root = _trusted_state()
    trust = state[MANAGED_TRUST_STATE_KEY]
    trust.capability = SessionCapability()  # replaced session capability

    with pytest.raises(ManagedExportRefusedError) as excinfo:
        build_verified_managed_export_source(state)

    assert excinfo.value.reason_code == "NO_VALID_TRUST"


def test_missing_capability_is_refused() -> None:
    state, _root = _trusted_state()
    trust = state[MANAGED_TRUST_STATE_KEY]
    trust.capability = None

    with pytest.raises(ManagedExportRefusedError) as excinfo:
        build_verified_managed_export_source(state)

    assert excinfo.value.reason_code == "NO_VALID_TRUST"


def test_gateway_never_creates_trust_or_capability_state() -> None:
    state: dict[str, Any] = {}

    with pytest.raises(ManagedExportRefusedError):
        build_verified_managed_export_source(state)

    assert MANAGED_TRUST_STATE_KEY not in state


def test_availability_probe_never_creates_state_and_never_raises() -> None:
    state: dict[str, Any] = {}

    assert managed_export_available(state) is False
    assert MANAGED_TRUST_STATE_KEY not in state


# --- C. FULL size ceiling and LARGE refusal ------------------------------------------


def test_full_exactly_at_boundary_is_permitted() -> None:
    state, _root = _trusted_state(size=MANAGED_FULL_MAX_SOURCE_BYTES)

    source = build_verified_managed_export_source(state)

    assert source.size_bytes == 134_217_728
    assert managed_export_available(state) is True


def test_full_above_boundary_is_refused() -> None:
    state, _root = _trusted_state(size=MANAGED_FULL_MAX_SOURCE_BYTES + 1)

    with pytest.raises(ManagedExportRefusedError) as excinfo:
        build_verified_managed_export_source(state)

    assert excinfo.value.reason_code == "FULL_SIZE_EXCEEDED"
    assert managed_export_available(state) is False


def test_large_mode_export_is_refused() -> None:
    state, _root = _trusted_state(large=True)

    with pytest.raises(ManagedExportRefusedError) as excinfo:
        build_verified_managed_export_source(state)

    assert excinfo.value.reason_code == "LARGE_MODE_REFUSED"
    assert managed_export_available(state) is False


def test_gateway_imports_the_shared_ceiling_and_does_not_redefine_it() -> None:
    tree = ast.parse(inspect.getsource(gateway))
    assigned = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert "MANAGED_FULL_MAX_SOURCE_BYTES" not in assigned
    assert gateway.MANAGED_FULL_MAX_SOURCE_BYTES is MANAGED_FULL_MAX_SOURCE_BYTES


# --- D. Privacy ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ({}, None),
        lambda: ({DATASET_CONTEXT: _managed_mirror()}, None),
    ],
)
def test_refusal_messages_never_carry_paths_or_identifiers(factory: Any) -> None:
    state, _ = factory()

    with pytest.raises(ManagedExportRefusedError) as excinfo:
        build_verified_managed_export_source(state)

    text = str(excinfo.value) + repr(excinfo.value)
    for secret in (_MANAGED_ABS, _VERSION_ID, _FAMILY_ID, _CONTENT_ID, _ROOT_CONTENT_ID):
        assert secret not in text
    assert "C:\\" not in text
    assert "ManagedTrustRoot(" not in text


def test_size_refusal_message_is_privacy_safe() -> None:
    state, _root = _trusted_state(size=MANAGED_FULL_MAX_SOURCE_BYTES + 1)

    with pytest.raises(ManagedExportRefusedError) as excinfo:
        build_verified_managed_export_source(state)

    text = str(excinfo.value)
    assert _MANAGED_ABS not in text
    assert "C:\\" not in text


def test_minted_source_repr_hides_the_absolute_path() -> None:
    state, _root = _trusted_state()

    source = build_verified_managed_export_source(state)

    for text in (repr(source), str(source)):
        assert _MANAGED_ABS not in text
        assert "C:\\private" not in text
    assert source.source_path == _MANAGED_ABS  # machine-side access still works


# --- E. Containment --------------------------------------------------------------------


def test_gateway_is_the_only_ui_module_importing_the_shared_contract() -> None:
    """The gateway sits on the boundary: UI trust in, shared provenance out."""
    tree = ast.parse(inspect.getsource(gateway))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "data_quality_toolkit.shared.managed_export_source" in modules
    assert "data_quality_toolkit.adapters.ui.services.managed_trust" in modules
    # It must not reach into workflow or API layers itself.
    assert not any(
        m.startswith(("data_quality_toolkit.application", "data_quality_toolkit.api"))
        for m in modules
    )
