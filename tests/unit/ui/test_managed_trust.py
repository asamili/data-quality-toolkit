"""Unit tests for the UI-private managed trust authority.

Proves session-capability identity semantics, root-first authority, stale
mirror fail-closed behavior, missing/replaced capability fail-closed behavior,
generation-driven retirement, cache-invalidation hooks, marker-independent
reconciliation, privacy of every operator-visible surface, and that
validation accessors never create capability or trust state.
"""

from __future__ import annotations

import pickle
import uuid
from collections.abc import MutableMapping
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.services import managed_trust
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    MANAGED_TRUST_STATE_KEY,
    ManagedTrustError,
    ManagedTrustRoot,
    SessionCapability,
    TrustAuthority,
    commit_trust_root,
    current_generation,
    ensure_session_capability,
    get_valid_trust_root,
    make_source_locator,
    peek_session_capability,
    reconcile_managed_trust,
    resolve_trust_authority,
    retire_managed_trust,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT, EXPORT_CSV_PATH

_CONTENT = "sha256:" + "a" * 64
_CONTENT_OTHER = "sha256:" + "b" * 64
_ROOT_CONTENT = "sha256:" + "c" * 64
_ABS = "C:\\workspace\\versions\\v1\\data.csv"


def _locator() -> Any:
    return make_source_locator(
        display_name="data.csv",
        relative_posix="versions/v1/data.csv",
        absolute_path=_ABS,
    )


def _commit(
    state: dict[str, Any],
    capability: SessionCapability | None = None,
    *,
    version_id: str | None = None,
    content_id: str = _CONTENT,
) -> ManagedTrustRoot:
    cap = capability if capability is not None else ensure_session_capability(state)
    return commit_trust_root(
        state,
        cap,
        version_id=version_id or str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        content_id=content_id,
        root_content_id=_ROOT_CONTENT,
        parent_version_id=None,
        version_label="cleaned v2",
        locator=_locator(),
        size_bytes=2048,
        modified_ns=10,
        large_file_mode=False,
    )


def _managed_mirror(root: ManagedTrustRoot) -> DatasetContext:
    return DatasetContext(
        source_path=_ABS,
        display_name="data.csv",
        size_bytes=root.size_bytes,
        modified_ns=root.modified_ns,
        managed=True,
        version_id=root.version_id,
        family_id=root.family_id,
        content_id=root.content_id,
        root_content_id=root.root_content_id,
        version_label=root.version_label,
    )


# --- A. SessionCapability identity ------------------------------------------


def test_two_capabilities_are_never_equal() -> None:
    a, b = SessionCapability(), SessionCapability()
    assert a != b
    assert a is not b
    assert a == a


def test_capability_hash_is_identity_based() -> None:
    a, b = SessionCapability(), SessionCapability()
    assert len({a, b}) == 2
    assert hash(a) != hash(b) or a is b  # identity hashing, no value collision semantics


def test_pickled_capability_is_a_different_identity() -> None:
    # Serialization must never carry authority: the round-tripped instance is
    # a distinct identity and can never revalidate a prior binding.
    original = SessionCapability()
    clone = pickle.loads(pickle.dumps(original))  # noqa: S301 - proving non-authority
    assert clone is not original
    assert clone != original


# --- B. Capability lifecycle and no-implicit-creation ------------------------


def test_ensure_creates_once_and_is_stable() -> None:
    state: dict[str, Any] = {}
    first = ensure_session_capability(state)
    second = ensure_session_capability(state)
    assert first is second


def test_peek_never_creates_capability_or_state() -> None:
    state: dict[str, Any] = {}
    assert peek_session_capability(state) is None
    assert MANAGED_TRUST_STATE_KEY not in state


def test_get_valid_trust_root_never_creates_state() -> None:
    state: dict[str, Any] = {}
    assert get_valid_trust_root(state) is None
    assert MANAGED_TRUST_STATE_KEY not in state


def test_resolve_authority_never_creates_state() -> None:
    state: dict[str, Any] = {}
    decision = resolve_trust_authority(state)
    assert decision.authority is TrustAuthority.UNMANAGED
    assert MANAGED_TRUST_STATE_KEY not in state


def test_current_generation_defaults_to_zero_without_creating() -> None:
    state: dict[str, Any] = {}
    assert current_generation(state) == 0
    assert MANAGED_TRUST_STATE_KEY not in state


# --- C. Commit and generation semantics ---------------------------------------


def test_commit_requires_live_capability() -> None:
    state: dict[str, Any] = {}
    foreign = SessionCapability()
    with pytest.raises(ManagedTrustError):
        _commit(state, foreign)
    assert get_valid_trust_root(state) is None


def test_commit_refuses_non_live_capability_instance() -> None:
    state: dict[str, Any] = {}
    ensure_session_capability(state)
    foreign = SessionCapability()
    with pytest.raises(ManagedTrustError):
        _commit(state, foreign)
    assert get_valid_trust_root(state) is None


def test_precommit_failure_leaves_previous_authority_unchanged() -> None:
    state: dict[str, Any] = {}
    root = _commit(state)
    with pytest.raises(ManagedTrustError):
        commit_trust_root(
            state,
            peek_session_capability(state) or SessionCapability(),
            version_id="",  # blank id refused before commit
            family_id=str(uuid.uuid4()),
            content_id=_CONTENT,
            root_content_id=_ROOT_CONTENT,
            parent_version_id=None,
            version_label="x",
            locator=_locator(),
            size_bytes=1,
            modified_ns=1,
            large_file_mode=False,
        )
    assert get_valid_trust_root(state) is root


def test_commit_advances_generation_and_binds_root() -> None:
    state: dict[str, Any] = {}
    assert current_generation(state) == 0
    root = _commit(state)
    assert root.generation == 1
    assert current_generation(state) == 1
    assert get_valid_trust_root(state) is root


def test_version_switch_recommit_retires_previous_root() -> None:
    state: dict[str, Any] = {}
    first = _commit(state)
    second = _commit(state, content_id=_CONTENT_OTHER)
    assert second.generation == first.generation + 1
    assert get_valid_trust_root(state) is second


def test_retire_advances_generation_and_drops_root() -> None:
    state: dict[str, Any] = {}
    root = _commit(state)
    retire_managed_trust(state)
    assert get_valid_trust_root(state) is None
    assert current_generation(state) == root.generation + 1


# --- D. Fail-closed validation --------------------------------------------------


def test_missing_capability_fails_closed() -> None:
    state: dict[str, Any] = {}
    _commit(state)
    trust = managed_trust._peek_state(state)
    assert trust is not None
    trust.capability = None  # simulate lost session capability
    assert get_valid_trust_root(state) is None
    assert resolve_trust_authority(state).authority is not TrustAuthority.MANAGED_AUTHORITY


def test_replaced_capability_fails_closed() -> None:
    state: dict[str, Any] = {}
    _commit(state)
    trust = managed_trust._peek_state(state)
    assert trust is not None
    trust.capability = SessionCapability()  # replaced capability instance
    assert get_valid_trust_root(state) is None


def test_generation_mismatch_fails_closed() -> None:
    state: dict[str, Any] = {}
    _commit(state)
    trust = managed_trust._peek_state(state)
    assert trust is not None
    trust.generation += 1  # retired binding; root left in place on purpose
    assert get_valid_trust_root(state) is None


def test_root_copied_into_durable_state_carries_no_authority() -> None:
    state: dict[str, Any] = {}
    root = _commit(state)
    fresh: dict[str, Any] = {}
    trust = managed_trust._TrustState()
    trust.root = root  # rebuilt store without the commit-time capability
    fresh[MANAGED_TRUST_STATE_KEY] = trust
    assert get_valid_trust_root(fresh) is None


# --- E. Root-first authority ------------------------------------------------------


def test_valid_root_overrides_stale_dataset_context() -> None:
    state: dict[str, Any] = {}
    root = _commit(state)
    state[DATASET_CONTEXT] = DatasetContext(
        source_path="C:/elsewhere/old.csv",
        display_name="old.csv",
        size_bytes=1,
        modified_ns=1,
    )
    decision = resolve_trust_authority(state)
    assert decision.authority is TrustAuthority.MANAGED_AUTHORITY
    assert decision.root is root
    assert decision.mirror_stale is True


def test_valid_root_with_matching_mirror_is_not_stale() -> None:
    state: dict[str, Any] = {}
    root = _commit(state)
    state[DATASET_CONTEXT] = _managed_mirror(root)
    decision = resolve_trust_authority(state)
    assert decision.authority is TrustAuthority.MANAGED_AUTHORITY
    assert decision.mirror_stale is False


def test_managed_mirror_without_valid_trust_fails_closed() -> None:
    state: dict[str, Any] = {}
    root = _commit(state)
    mirror = _managed_mirror(root)
    retire_managed_trust(state)
    state[DATASET_CONTEXT] = mirror  # managed-looking, but trust retired
    decision = resolve_trust_authority(state)
    assert decision.authority is TrustAuthority.FAIL_CLOSED
    assert decision.root is None


def test_manual_path_cannot_override_valid_trust() -> None:
    state: dict[str, Any] = {}
    root = _commit(state)
    state[EXPORT_CSV_PATH] = "C:/manual/other.csv"
    state[DATASET_CONTEXT] = DatasetContext(
        source_path="C:/manual/other.csv",
        display_name="other.csv",
        size_bytes=7,
        modified_ns=7,
    )
    decision = resolve_trust_authority(state)
    assert decision.authority is TrustAuthority.MANAGED_AUTHORITY
    assert decision.root is root


def test_unmanaged_behavior_unchanged_without_trust() -> None:
    state: dict[str, Any] = {
        DATASET_CONTEXT: DatasetContext(
            source_path="C:/safe/orders.csv",
            display_name="orders.csv",
            size_bytes=10,
            modified_ns=10,
        )
    }
    decision = resolve_trust_authority(state)
    assert decision.authority is TrustAuthority.UNMANAGED
    assert decision.root is None


# --- F. Reconciliation (marker-independent, forward-only) --------------------------


def test_reconcile_drops_invalid_binding_without_restoring_stale_authority() -> None:
    state: dict[str, Any] = {}
    _commit(state)
    trust = managed_trust._peek_state(state)
    assert trust is not None
    trust.capability = SessionCapability()  # invalidate by replacement
    decision = reconcile_managed_trust(state)
    assert decision.authority is not TrustAuthority.MANAGED_AUTHORITY
    assert trust.root is None  # retired forward, never restored


def test_reconcile_is_marker_independent() -> None:
    # No filesystem marker, mirror, or cleanup is consulted: validity flows
    # from generation + capability alone.
    state: dict[str, Any] = {}
    root = _commit(state)
    state[DATASET_CONTEXT] = _managed_mirror(root)  # physical mirror left behind
    retire_managed_trust(state)  # marker (mirror) deliberately NOT cleaned
    decision = reconcile_managed_trust(state)
    assert decision.authority is TrustAuthority.FAIL_CLOSED


def test_reconcile_keeps_valid_root() -> None:
    state: dict[str, Any] = {}
    root = _commit(state)
    decision = reconcile_managed_trust(state)
    assert decision.authority is TrustAuthority.MANAGED_AUTHORITY
    assert decision.root is root


# --- G. Invalidation hooks -----------------------------------------------------------


def test_hooks_run_on_commit_and_retire(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(managed_trust, "_INVALIDATION_HOOKS", [])

    def hook(_state: MutableMapping[str, Any]) -> None:
        calls.append("hit")

    managed_trust.register_cache_invalidation_hook(hook)
    state: dict[str, Any] = {}
    _commit(state)
    assert calls == ["hit"]
    retire_managed_trust(state)
    assert calls == ["hit", "hit"]


def test_hook_failure_never_rolls_back_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(managed_trust, "_INVALIDATION_HOOKS", [])

    def bad_hook(_state: MutableMapping[str, Any]) -> None:
        raise RuntimeError("cleanup failed")

    managed_trust.register_cache_invalidation_hook(bad_hook)
    state: dict[str, Any] = {}
    root = _commit(state)  # must not raise, must not roll back
    assert get_valid_trust_root(state) is root


def test_hook_registration_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(managed_trust, "_INVALIDATION_HOOKS", [])
    calls: list[str] = []

    def hook(_state: MutableMapping[str, Any]) -> None:
        calls.append("hit")

    managed_trust.register_cache_invalidation_hook(hook)
    managed_trust.register_cache_invalidation_hook(hook)
    state: dict[str, Any] = {}
    _commit(state)
    assert calls == ["hit"]


# --- H. Privacy ------------------------------------------------------------------------


def test_locator_repr_hides_absolute_path() -> None:
    locator = _locator()
    for text in (repr(locator), str(locator)):
        assert _ABS not in text
        assert "C:\\" not in text
    assert locator.absolute_path == _ABS  # machine-side access still works


def test_locator_refuses_absolute_or_pathlike_public_fields() -> None:
    with pytest.raises(ManagedTrustError):
        make_source_locator(
            display_name="C:\\data.csv", relative_posix="v/d.csv", absolute_path=_ABS
        )
    with pytest.raises(ManagedTrustError):
        make_source_locator(
            display_name="data.csv", relative_posix="/abs/d.csv", absolute_path=_ABS
        )
    with pytest.raises(ManagedTrustError):
        make_source_locator(
            display_name="data.csv", relative_posix="C:/abs/d.csv", absolute_path=_ABS
        )


def test_trust_root_repr_hides_absolute_path() -> None:
    state: dict[str, Any] = {}
    root = _commit(state)
    assert _ABS not in repr(root)


def test_trust_errors_never_carry_paths() -> None:
    state: dict[str, Any] = {}
    with pytest.raises(ManagedTrustError) as excinfo:
        _commit(state, SessionCapability())
    text = str(excinfo.value)
    assert "\\" not in text and "C:" not in text
