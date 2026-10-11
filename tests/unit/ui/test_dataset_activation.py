"""Unit and state-transition tests for atomic dataset-context activation.

Covers validated legacy/managed construction, version-aware binding identity,
the atomic transition (invalidation + reporting), clear behavior, and — using a
fault-injecting ``MutableMapping`` — full snapshot rollback. No durable
lifecycle behavior is exercised here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.services import dataset_activation
from data_quality_toolkit.adapters.ui.services.dataset_activation import (
    ActivationStatus,
    DatasetActivationError,
    InvalidLegacyContextError,
    InvalidManagedContextError,
    ManagedActivationDisabledError,
    ManagedActivationOutcome,
    StateMutationError,
    activate_dataset_context,
    activate_managed_context,
    clear_dataset_context,
    make_legacy_context,
    make_managed_context,
    managed_activation_enabled,
    require_managed_activation_enabled,
    validate_dataset_context,
)
from data_quality_toolkit.adapters.ui.services.dataset_versions import (
    CreationMechanism,
    DatasetFormat,
    DatasetVersionRecord,
    ParentRef,
    RecipeRef,
    new_family_id,
    new_version_id,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    MANAGED_TRUST_STATE_KEY,
    SessionCapability,
    current_generation,
    get_valid_trust_root,
    peek_session_capability,
)
from data_quality_toolkit.adapters.ui.state.context import (
    DatasetContext,
    get_dataset_context,
)
from data_quality_toolkit.adapters.ui.state.keys import (
    BIV_COL1,
    BIV_COL2,
    DATASET_CONTEXT,
    DATASET_DERIVED_STATE_KEYS,
    EXPORT_CSV_PATH,
    PREP_CONFIRMED_VERSION,
    PREP_RECIPE_STEPS,
    SRC_DATASET_ID,
)

_CONTENT_A = "sha256:" + "a" * 64
_CONTENT_B = "sha256:" + "b" * 64
_ROOT = "sha256:" + "c" * 64


# --- Test fixtures / helpers ----------------------------------------------


def _legacy(
    path: str = "C:/safe/orders.csv", *, size: int = 2048, large: bool = False
) -> DatasetContext:
    return DatasetContext(
        source_path=path,
        display_name="orders.csv",
        size_bytes=size,
        modified_ns=10,
        large_file_mode=large,
    )


def _record(
    *,
    version_id: str | None = None,
    family_id: str | None = None,
    content_id: str = _CONTENT_A,
    root_content_id: str = _ROOT,
    parent: ParentRef | None = None,
    label: str = "cleaned v2",
) -> DatasetVersionRecord:
    return DatasetVersionRecord(
        schema_version=1,
        version_id=version_id or new_version_id(),
        family_id=family_id or new_family_id(),
        root_content_id=root_content_id,
        content_id=content_id,
        dataset_id="sha1:" + "d" * 40,
        label=label,
        file_relative_path="versions/v1/data.csv",
        format=DatasetFormat.CSV,
        size_bytes=2048,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        created_by=CreationMechanism.PREPROCESS_RECIPE,
        parent=parent if parent is not None else ParentRef(version_id=None, content_id=_CONTENT_B),
        recipe=RecipeRef(digest="sha256:" + "e" * 64, relative_path="recipes/v1.json"),
    )


def _managed(**overrides: Any) -> DatasetContext:
    record = _record(**overrides)
    return make_managed_context(
        record,
        source_path="C:/safe/orders.csv",
        display_name="orders.csv",
        size_bytes=2048,
        modified_ns=10,
    )


class _FaultMap(dict[str, Any]):
    """Dict that raises once on a targeted set/del, then heals.

    Initial contents pass through ``dict.__init__`` (which does not call the
    overridden ``__setitem__``), so a fault targeting ``DATASET_CONTEXT`` does
    not fire during setup. The single transient failure proves that rollback
    restores the complete prior snapshot.
    """

    def __init__(
        self,
        *args: Any,
        fail_set: str | None = None,
        fail_del: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._fail_set = fail_set
        self._fail_del = fail_del

    def __setitem__(self, key: str, value: Any) -> None:
        if key == self._fail_set:
            self._fail_set = None
            raise RuntimeError("injected __setitem__ failure")
        super().__setitem__(key, value)

    def __delitem__(self, key: str) -> None:
        if key == self._fail_del:
            self._fail_del = None
            raise RuntimeError("injected __delitem__ failure")
        super().__delitem__(key)


# --- A. Context construction ----------------------------------------------


def test_make_legacy_context_is_valid_and_unmanaged() -> None:
    context = make_legacy_context(
        source_path="C:/safe/orders.csv",
        display_name="orders.csv",
        size_bytes=2048,
        modified_ns=10,
        large_file_mode=True,
    )
    assert context.managed is False
    assert context.version_id is None
    assert context.content_id is None
    assert context.version_label is None
    assert context.large_file_mode is True


def test_legacy_context_with_lifecycle_ids_is_rejected() -> None:
    bad = DatasetContext(
        source_path="C:/safe/orders.csv",
        display_name="orders.csv",
        size_bytes=2048,
        modified_ns=10,
        managed=False,
        version_id=new_version_id(),
    )
    with pytest.raises(InvalidLegacyContextError):
        validate_dataset_context(bad)


def test_make_managed_context_maps_all_required_identities() -> None:
    record = _record(content_id=_CONTENT_A, root_content_id=_ROOT)
    context = make_managed_context(
        record,
        source_path="C:/active/orders.csv",
        display_name="orders.csv",
        size_bytes=4096,
        modified_ns=99,
        large_file_mode=True,
    )
    assert context.managed is True
    assert context.version_id == record.version_id
    assert context.family_id == record.family_id
    assert context.content_id == record.content_id
    assert context.root_content_id == record.root_content_id
    assert context.version_label == record.label
    # Active source path and current filesystem fingerprint are preserved.
    assert context.source_path == "C:/active/orders.csv"
    assert context.size_bytes == 4096
    assert context.modified_ns == 99
    assert context.large_file_mode is True


def test_first_managed_child_permits_unmanaged_parent() -> None:
    record = _record(parent=ParentRef(version_id=None, content_id=_CONTENT_B))
    context = _from_record(record)
    assert context.parent_version_id is None
    validate_dataset_context(context)


def test_descendant_maps_managed_parent_version_id() -> None:
    parent_id = new_version_id()
    record = _record(parent=ParentRef(version_id=parent_id, content_id=_CONTENT_B))
    context = _from_record(record)
    assert context.parent_version_id == parent_id


def test_malformed_managed_identity_is_rejected() -> None:
    bad = DatasetContext(
        source_path="C:/safe/orders.csv",
        display_name="orders.csv",
        size_bytes=2048,
        modified_ns=10,
        managed=True,
        version_id=new_version_id(),
        family_id=new_family_id(),
        content_id="not-a-sha256",
        root_content_id=_ROOT,
        version_label="v",
    )
    with pytest.raises(InvalidManagedContextError):
        validate_dataset_context(bad)


def test_managed_context_without_required_ids_is_rejected() -> None:
    bad = DatasetContext(
        source_path="C:/safe/orders.csv",
        display_name="orders.csv",
        size_bytes=2048,
        modified_ns=10,
        managed=True,
        version_id=new_version_id(),
        family_id=new_family_id(),
        content_id=None,  # missing required identity
        root_content_id=_ROOT,
        version_label="v",
    )
    with pytest.raises(InvalidManagedContextError):
        validate_dataset_context(bad)


def test_blank_lifecycle_identifier_is_invalid() -> None:
    bad = DatasetContext(
        source_path="C:/safe/orders.csv",
        display_name="orders.csv",
        size_bytes=2048,
        modified_ns=10,
        managed=True,
        version_id="   ",
        family_id=new_family_id(),
        content_id=_CONTENT_A,
        root_content_id=_ROOT,
        version_label="v",
    )
    with pytest.raises(InvalidManagedContextError):
        validate_dataset_context(bad)


def _from_record(record: DatasetVersionRecord) -> DatasetContext:
    return make_managed_context(
        record,
        source_path="C:/safe/orders.csv",
        display_name="orders.csv",
        size_bytes=2048,
        modified_ns=10,
    )


# --- B. Version-aware binding identity -------------------------------------


def test_identical_complete_binding_is_unchanged() -> None:
    assert _legacy().binding_identity == _legacy().binding_identity


def test_same_path_and_fingerprint_but_different_version_id_is_a_change() -> None:
    family = new_family_id()
    a = _managed(family_id=family)
    b = _managed(family_id=family)  # fresh version_id from _record default
    assert a.version_id != b.version_id
    assert a.binding_identity != b.binding_identity


def test_same_version_id_but_different_content_id_is_a_change() -> None:
    vid, fid = new_version_id(), new_family_id()
    a = _managed(version_id=vid, family_id=fid, content_id=_CONTENT_A)
    b = _managed(version_id=vid, family_id=fid, content_id=_CONTENT_B)
    assert a.binding_identity != b.binding_identity


def test_changed_path_size_mtime_or_large_mode_is_a_change() -> None:
    base = _legacy()
    assert base.binding_identity != _legacy("C:/safe/other.csv").binding_identity
    assert base.binding_identity != _legacy(size=9999).binding_identity
    assert base.binding_identity != _legacy(large=True).binding_identity
    mtime_changed = DatasetContext(
        source_path=base.source_path,
        display_name=base.display_name,
        size_bytes=base.size_bytes,
        modified_ns=base.modified_ns + 1,
    )
    assert base.binding_identity != mtime_changed.binding_identity


def test_legacy_and_managed_never_compare_as_same_binding() -> None:
    assert _legacy().binding_identity != _managed().binding_identity


# --- C. Atomic transition --------------------------------------------------


def test_first_activation_stores_target() -> None:
    state: dict[str, Any] = {}
    result = activate_dataset_context(state, _legacy())
    assert result.status is ActivationStatus.ACTIVATED
    assert get_dataset_context(state) is not None


def test_first_activation_preserves_operator_typed_dataset_id() -> None:
    state: dict[str, Any] = {SRC_DATASET_ID: "sha1:manual"}
    activate_dataset_context(state, _legacy())
    assert state[SRC_DATASET_ID] == "sha1:manual"


def test_first_activation_preserves_pre_entered_export_source() -> None:
    # Nothing was active before, so a hand-entered Export path cannot be stale
    # against a previous dataset — clearing it would only discard the operator's
    # own input.
    state: dict[str, Any] = {EXPORT_CSV_PATH: "C:/safe/typed_by_operator.csv"}

    result = activate_dataset_context(state, _legacy())

    assert result.status is ActivationStatus.ACTIVATED
    assert state[EXPORT_CSV_PATH] == "C:/safe/typed_by_operator.csv"
    assert EXPORT_CSV_PATH not in result.cleared_keys


def test_first_activation_preserves_both_compatibility_keys_together() -> None:
    state: dict[str, Any] = {
        SRC_DATASET_ID: "sha1:manual",
        EXPORT_CSV_PATH: "C:/safe/typed_by_operator.csv",
    }

    activate_dataset_context(state, _legacy())

    assert state[SRC_DATASET_ID] == "sha1:manual"
    assert state[EXPORT_CSV_PATH] == "C:/safe/typed_by_operator.csv"


def test_first_activation_still_clears_other_derived_state() -> None:
    # The exemption is narrow: only the operator-entered compatibility keys
    # survive. Everything genuinely derived from a dataset is still invalidated.
    state: dict[str, Any] = {}
    for key in DATASET_DERIVED_STATE_KEYS:
        state[key] = "seed"

    activate_dataset_context(state, _legacy())

    assert state[SRC_DATASET_ID] == "seed"
    assert state[EXPORT_CSV_PATH] == "seed"
    for key in (BIV_COL1, BIV_COL2, PREP_RECIPE_STEPS, PREP_CONFIRMED_VERSION):
        assert key not in state


def test_changed_activation_clears_every_derived_key() -> None:
    state: dict[str, Any] = {DATASET_CONTEXT: _legacy("C:/safe/a.csv")}
    for key in DATASET_DERIVED_STATE_KEYS:
        state[key] = "seed"

    result = activate_dataset_context(state, _legacy("C:/safe/b.csv"))

    assert result.changed is True
    for key in DATASET_DERIVED_STATE_KEYS:
        assert key not in state
    assert set(result.cleared_keys) == set(DATASET_DERIVED_STATE_KEYS)


def test_prep_recipe_steps_cleared_on_dataset_switch() -> None:
    state: dict[str, Any] = {
        DATASET_CONTEXT: _legacy("C:/safe/a.csv"),
        PREP_RECIPE_STEPS: [{"op": "dropna"}],
    }
    activate_dataset_context(state, _legacy("C:/safe/b.csv"))
    assert PREP_RECIPE_STEPS not in state


def test_unrelated_state_is_preserved_on_switch() -> None:
    state: dict[str, Any] = {
        DATASET_CONTEXT: _legacy("C:/safe/a.csv"),
        BIV_COL1: "x",
        "workspace_root": "./ws",
        "monitoring_db": "./m.db",
    }
    activate_dataset_context(state, _legacy("C:/safe/b.csv"))
    assert state["workspace_root"] == "./ws"
    assert state["monitoring_db"] == "./m.db"


def test_same_binding_activation_does_not_clear_derived_state() -> None:
    context = _legacy("C:/safe/a.csv")
    state: dict[str, Any] = {DATASET_CONTEXT: context, BIV_COL1: "keep"}

    result = activate_dataset_context(state, _legacy("C:/safe/a.csv"))

    assert result.status is ActivationStatus.UNCHANGED
    assert result.cleared_keys == ()
    assert state[BIV_COL1] == "keep"


def test_target_validation_failure_leaves_all_state_unchanged() -> None:
    original = _legacy("C:/safe/a.csv")
    state: dict[str, Any] = {DATASET_CONTEXT: original, BIV_COL1: "keep"}
    bad = DatasetContext(
        source_path="C:/safe/orders.csv",
        display_name="orders.csv",
        size_bytes=2048,
        modified_ns=10,
        managed=True,
        version_id=None,
        family_id=None,
        content_id=None,
        root_content_id=None,
    )

    with pytest.raises(InvalidManagedContextError):
        activate_dataset_context(state, bad)

    assert state[DATASET_CONTEXT] is original
    assert state[BIV_COL1] == "keep"


def test_transition_result_reports_cleared_keys_accurately() -> None:
    state: dict[str, Any] = {
        DATASET_CONTEXT: _legacy("C:/safe/a.csv"),
        BIV_COL1: "x",
        PREP_RECIPE_STEPS: [{"op": "dropna"}],
    }
    result = activate_dataset_context(state, _legacy("C:/safe/b.csv"))
    assert result.cleared_keys == (BIV_COL1, PREP_RECIPE_STEPS)


def test_managed_to_managed_switch_clears_export_source() -> None:
    family = new_family_id()
    state: dict[str, Any] = {
        DATASET_CONTEXT: _managed(family_id=family),
        EXPORT_CSV_PATH: "C:/safe/orders.csv",
    }

    result = activate_dataset_context(state, _managed(family_id=family))

    assert result.changed is True
    assert EXPORT_CSV_PATH not in state
    assert EXPORT_CSV_PATH in result.cleared_keys


def test_legacy_to_managed_switch_clears_export_source() -> None:
    state: dict[str, Any] = {
        DATASET_CONTEXT: _legacy(),
        EXPORT_CSV_PATH: "C:/safe/orders.csv",
    }

    result = activate_dataset_context(state, _managed())

    assert result.changed is True
    assert EXPORT_CSV_PATH not in state


def test_managed_to_legacy_switch_clears_export_source() -> None:
    state: dict[str, Any] = {
        DATASET_CONTEXT: _managed(),
        EXPORT_CSV_PATH: "C:/safe/orders.csv",
    }

    result = activate_dataset_context(state, _legacy())

    assert result.changed is True
    assert EXPORT_CSV_PATH not in state


def test_same_binding_activation_preserves_export_source() -> None:
    state: dict[str, Any] = {
        DATASET_CONTEXT: _legacy("C:/safe/a.csv"),
        EXPORT_CSV_PATH: "C:/safe/manual_override.csv",
    }

    result = activate_dataset_context(state, _legacy("C:/safe/a.csv"))

    assert result.status is ActivationStatus.UNCHANGED
    assert state[EXPORT_CSV_PATH] == "C:/safe/manual_override.csv"


def test_clear_context_removes_export_source() -> None:
    state: dict[str, Any] = {
        DATASET_CONTEXT: _legacy(),
        EXPORT_CSV_PATH: "C:/safe/orders.csv",
    }

    assert clear_dataset_context(state) is True
    assert EXPORT_CSV_PATH not in state


def test_activation_failure_preserves_previous_context_and_export_source() -> None:
    original = _legacy("C:/safe/a.csv")
    state: dict[str, Any] = {
        DATASET_CONTEXT: original,
        EXPORT_CSV_PATH: "C:/safe/a.csv",
    }
    bad = DatasetContext(
        source_path="C:/safe/orders.csv",
        display_name="orders.csv",
        size_bytes=2048,
        modified_ns=10,
        managed=True,
        version_id=None,
        family_id=None,
        content_id=None,
        root_content_id=None,
    )

    with pytest.raises(InvalidManagedContextError):
        activate_dataset_context(state, bad)

    assert state[DATASET_CONTEXT] is original
    assert state[EXPORT_CSV_PATH] == "C:/safe/a.csv"


def test_injected_failure_restores_export_source_exactly() -> None:
    ctx_a = _legacy("C:/safe/a.csv")
    state = _FaultMap(
        {
            DATASET_CONTEXT: ctx_a,
            EXPORT_CSV_PATH: "C:/safe/a.csv",
            BIV_COL1: "keep",
            "unrelated": "keep",
        },
        fail_set=DATASET_CONTEXT,
    )

    with pytest.raises(StateMutationError):
        activate_dataset_context(state, _legacy("C:/safe/b.csv"))

    assert state[DATASET_CONTEXT] is ctx_a
    assert state[EXPORT_CSV_PATH] == "C:/safe/a.csv"
    assert state[BIV_COL1] == "keep"
    assert state["unrelated"] == "keep"


def test_result_reports_managed_and_version_transition() -> None:
    managed = _managed()
    state: dict[str, Any] = {DATASET_CONTEXT: _legacy("C:/safe/a.csv")}
    result = activate_dataset_context(state, managed)
    assert result.previous_managed is False
    assert result.new_managed is True
    assert result.previous_version_id is None
    assert result.new_version_id == managed.version_id


# --- C(rollback). Injected-failure atomicity -------------------------------


def test_injected_failure_clearing_derived_key_restores_snapshot() -> None:
    ctx_a = _legacy("C:/safe/a.csv")
    state = _FaultMap(
        {
            DATASET_CONTEXT: ctx_a,
            BIV_COL1: "keep",
            PREP_RECIPE_STEPS: [{"op": "dropna"}],
            "unrelated": "keep",
        },
        fail_del=BIV_COL1,
    )

    with pytest.raises(StateMutationError):
        activate_dataset_context(state, _legacy("C:/safe/b.csv"))

    assert state[DATASET_CONTEXT] is ctx_a
    assert state[BIV_COL1] == "keep"
    assert state[PREP_RECIPE_STEPS] == [{"op": "dropna"}]
    assert state["unrelated"] == "keep"


def test_injected_failure_writing_context_restores_snapshot() -> None:
    ctx_a = _legacy("C:/safe/a.csv")
    state = _FaultMap(
        {
            DATASET_CONTEXT: ctx_a,
            BIV_COL1: "keep",
            SRC_DATASET_ID: "sha1:keep",
            "unrelated": "keep",
        },
        fail_set=DATASET_CONTEXT,
    )

    with pytest.raises(StateMutationError):
        activate_dataset_context(state, _legacy("C:/safe/b.csv"))

    assert state[DATASET_CONTEXT] is ctx_a
    assert state[BIV_COL1] == "keep"
    assert state[SRC_DATASET_ID] == "sha1:keep"
    assert state["unrelated"] == "keep"


def test_absent_keys_remain_absent_after_rollback() -> None:
    ctx_a = _legacy("C:/safe/a.csv")
    state = _FaultMap({DATASET_CONTEXT: ctx_a, BIV_COL1: "keep"}, fail_set=DATASET_CONTEXT)
    assert BIV_COL2 not in state
    assert PREP_RECIPE_STEPS not in state

    with pytest.raises(StateMutationError):
        activate_dataset_context(state, _legacy("C:/safe/b.csv"))

    assert BIV_COL2 not in state
    assert PREP_RECIPE_STEPS not in state


def test_present_falsey_derived_values_are_restored_exactly() -> None:
    ctx_a = _legacy("C:/safe/a.csv")
    state = _FaultMap(
        {
            DATASET_CONTEXT: ctx_a,
            BIV_COL1: None,
            BIV_COL2: "",
            PREP_RECIPE_STEPS: [],
        },
        fail_set=DATASET_CONTEXT,
    )

    with pytest.raises(StateMutationError):
        activate_dataset_context(state, _legacy("C:/safe/b.csv"))

    assert BIV_COL1 in state and state[BIV_COL1] is None
    assert BIV_COL2 in state and state[BIV_COL2] == ""
    assert PREP_RECIPE_STEPS in state and state[PREP_RECIPE_STEPS] == []


# --- D/E. Clear behavior ---------------------------------------------------


def test_clear_removes_context_and_all_declared_derived_keys() -> None:
    state: dict[str, Any] = {DATASET_CONTEXT: _legacy()}
    for key in DATASET_DERIVED_STATE_KEYS:
        state[key] = "seed"

    assert clear_dataset_context(state) is True
    assert get_dataset_context(state) is None
    for key in DATASET_DERIVED_STATE_KEYS:
        assert key not in state


def test_clear_preserves_unrelated_state() -> None:
    state: dict[str, Any] = {
        DATASET_CONTEXT: _legacy(),
        SRC_DATASET_ID: "sha1:x",
        "workspace_root": "./ws",
        "quality_history_db": "./q.db",
    }
    clear_dataset_context(state)
    assert state["workspace_root"] == "./ws"
    assert state["quality_history_db"] == "./q.db"
    assert SRC_DATASET_ID not in state


def test_clear_rollback_restores_context_and_derived_state() -> None:
    ctx = _legacy()
    state = _FaultMap(
        {
            DATASET_CONTEXT: ctx,
            BIV_COL1: "keep",
            PREP_RECIPE_STEPS: [{"op": "dropna"}],
            "unrelated": "keep",
        },
        fail_del=BIV_COL1,
    )

    with pytest.raises(StateMutationError):
        clear_dataset_context(state)

    assert state[DATASET_CONTEXT] is ctx
    assert state[BIV_COL1] == "keep"
    assert state[PREP_RECIPE_STEPS] == [{"op": "dropna"}]
    assert state["unrelated"] == "keep"


# --- F. Managed activation guard --------------------------------------------
#
# The production enable point is the single module literal
# ``_MANAGED_ACTIVATION_ENABLED``; these tests prove the guard's refusal
# semantics under both flag states so the suite holds before and after the
# byte-proven flag-only enable. The pre-enable/post-enable value of the literal
# itself is proven externally against the source text, not asserted here.


def test_guard_refuses_while_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dataset_activation, "_MANAGED_ACTIVATION_ENABLED", False)
    assert managed_activation_enabled() is False
    with pytest.raises(ManagedActivationDisabledError):
        require_managed_activation_enabled()


def test_guard_allows_only_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dataset_activation, "_MANAGED_ACTIVATION_ENABLED", True)
    assert managed_activation_enabled() is True
    require_managed_activation_enabled()  # must not raise


def test_guard_accessor_tracks_the_single_module_literal() -> None:
    # The accessor must report exactly the module literal — no second source of
    # enable authority may exist.
    assert managed_activation_enabled() is dataset_activation._MANAGED_ACTIVATION_ENABLED


def test_disabled_refusal_is_typed_and_privacy_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dataset_activation, "_MANAGED_ACTIVATION_ENABLED", False)
    with pytest.raises(ManagedActivationDisabledError) as excinfo:
        require_managed_activation_enabled()
    assert isinstance(excinfo.value, DatasetActivationError)
    text = str(excinfo.value)
    assert ":\\" not in text and "/" not in text  # no path material
    assert "C:" not in text


# --- G. Integrated trusted managed activation seam (R3, step 39/40) ---------
#
# The integrated transaction is fully wired while production activation stays
# disabled, so these tests exercise the real seam and prove both the disabled
# production default and the complete transaction semantics under an explicit
# local enable.

_REL_POSIX = "preprocessed/orders.csv"
# A native absolute path on every host: a Windows literal is not absolute on
# POSIX, where its backslashes never split into a bare file name.
_ABS_SOURCE = str(Path(Path.cwd().anchor, "private", "ws", "preprocessed", "orders.csv"))


def _managed_target(**overrides: Any) -> DatasetContext:
    record = _record(**overrides)
    return make_managed_context(
        record,
        source_path=_ABS_SOURCE,
        display_name="orders.csv",
        size_bytes=2048,
        modified_ns=10,
    )


@pytest.fixture
def activation_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dataset_activation, "_MANAGED_ACTIVATION_ENABLED", True)


@pytest.fixture
def activation_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the guard off.

    The flag's *production* value is proven externally against the source text
    (False before the flag-only enable, True after). These tests pin the
    behavior of the disabled branch itself, which must stay inert.
    """
    monkeypatch.setattr(dataset_activation, "_MANAGED_ACTIVATION_ENABLED", False)


def test_integrated_activation_refuses_while_disabled(activation_disabled: None) -> None:
    state: dict[str, Any] = {}

    report = activate_managed_context(state, _managed_target(), relative_posix=_REL_POSIX)

    assert report.outcome is ManagedActivationOutcome.DISABLED
    assert report.trust_committed is False
    assert report.activated is False


def test_disabled_activation_mutates_nothing(activation_disabled: None) -> None:
    state: dict[str, Any] = {}

    activate_managed_context(state, _managed_target(), relative_posix=_REL_POSIX)

    assert state == {}
    assert get_valid_trust_root(state) is None
    assert peek_session_capability(state) is None
    assert MANAGED_TRUST_STATE_KEY not in state


def test_disabled_activation_never_touches_dataset_context(
    activation_disabled: None,
) -> None:
    original = _legacy()
    state: dict[str, Any] = {DATASET_CONTEXT: original}

    activate_managed_context(state, _managed_target(), relative_posix=_REL_POSIX)

    assert state[DATASET_CONTEXT] is original


def test_enabled_activation_commits_trust_and_publishes_mirror(
    activation_enabled: None,
) -> None:
    state: dict[str, Any] = {}
    target = _managed_target()

    report = activate_managed_context(state, target, relative_posix=_REL_POSIX)

    assert report.outcome is ManagedActivationOutcome.ACTIVATED
    assert report.trust_committed is True
    assert report.generation == 1
    trust_root = get_valid_trust_root(state)
    assert trust_root is not None
    assert trust_root.version_id == target.version_id
    assert trust_root.content_id == target.content_id
    assert get_dataset_context(state) == target


def test_enabled_activation_creates_the_capability(activation_enabled: None) -> None:
    state: dict[str, Any] = {}
    assert peek_session_capability(state) is None

    activate_managed_context(state, _managed_target(), relative_posix=_REL_POSIX)

    assert peek_session_capability(state) is not None


def test_repeat_activation_reports_unchanged_but_rebinds_trust(
    activation_enabled: None,
) -> None:
    state: dict[str, Any] = {}
    target = _managed_target()
    activate_managed_context(state, target, relative_posix=_REL_POSIX)

    report = activate_managed_context(state, target, relative_posix=_REL_POSIX)

    assert report.outcome is ManagedActivationOutcome.UNCHANGED
    assert report.activated is True
    assert report.generation == 2  # generation only ever advances


def test_unmanaged_target_is_refused_pre_commit(activation_enabled: None) -> None:
    state: dict[str, Any] = {}

    report = activate_managed_context(state, _legacy(), relative_posix=_REL_POSIX)

    assert report.outcome is ManagedActivationOutcome.REFUSED_PRE_COMMIT
    assert report.trust_committed is False
    assert get_valid_trust_root(state) is None


def test_absolute_relative_posix_is_refused_pre_commit(activation_enabled: None) -> None:
    state: dict[str, Any] = {}

    report = activate_managed_context(
        state, _managed_target(), relative_posix="C:/private/ws/orders.csv"
    )

    assert report.outcome is ManagedActivationOutcome.REFUSED_PRE_COMMIT
    assert report.trust_committed is False


def test_pre_commit_refusal_leaves_previous_authority_unchanged(
    activation_enabled: None,
) -> None:
    state: dict[str, Any] = {}
    first = _managed_target()
    activate_managed_context(state, first, relative_posix=_REL_POSIX)
    original_root = get_valid_trust_root(state)
    assert original_root is not None

    report = activate_managed_context(state, _legacy(), relative_posix=_REL_POSIX)

    assert report.outcome is ManagedActivationOutcome.REFUSED_PRE_COMMIT
    assert get_valid_trust_root(state) is original_root


def test_post_commit_interruption_never_restores_stale_trust(
    activation_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state: dict[str, Any] = {}
    activate_managed_context(state, _managed_target(), relative_posix=_REL_POSIX)
    stale_root = get_valid_trust_root(state)
    assert stale_root is not None

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("injected post-commit failure")

    monkeypatch.setattr(dataset_activation, "activate_dataset_context", boom)
    report = activate_managed_context(state, _managed_target(), relative_posix=_REL_POSIX)

    assert report.outcome is ManagedActivationOutcome.INTERRUPTED_POST_COMMIT
    assert report.trust_committed is True
    # Forward reconciliation: fail closed, never restore the previous root.
    assert get_valid_trust_root(state) is None
    assert get_valid_trust_root(state) is not stale_root


def test_post_commit_interruption_advances_generation_forward(
    activation_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state: dict[str, Any] = {}
    activate_managed_context(state, _managed_target(), relative_posix=_REL_POSIX)
    before = current_generation(state)

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("injected post-commit failure")

    monkeypatch.setattr(dataset_activation, "activate_dataset_context", boom)
    activate_managed_context(state, _managed_target(), relative_posix=_REL_POSIX)

    # commit (+1) then forward retirement (+1); never a decrement.
    assert current_generation(state) == before + 2


def test_report_is_privacy_safe(activation_enabled: None) -> None:
    state: dict[str, Any] = {}

    report = activate_managed_context(state, _managed_target(), relative_posix=_REL_POSIX)

    text = repr(report) + str(report)
    assert _ABS_SOURCE not in text
    assert "C:\\" not in text
    assert "ManagedTrustRoot(" not in text


def test_activation_reconciles_an_invalid_binding_forward(activation_enabled: None) -> None:
    state: dict[str, Any] = {}
    activate_managed_context(state, _managed_target(), relative_posix=_REL_POSIX)
    # Invalidate by capability replacement; the mirror is deliberately left.
    state[MANAGED_TRUST_STATE_KEY].capability = SessionCapability()

    report = activate_managed_context(state, _legacy(), relative_posix=_REL_POSIX)

    assert report.outcome is ManagedActivationOutcome.REFUSED_PRE_COMMIT
    # Reconciliation dropped the stale binding without marker cleanup.
    assert state[MANAGED_TRUST_STATE_KEY].root is None


def test_flag_gates_the_integrated_path_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flipping the flag changes only whether the trusted path runs."""
    state_off: dict[str, Any] = {}
    monkeypatch.setattr(dataset_activation, "_MANAGED_ACTIVATION_ENABLED", False)
    off = activate_managed_context(state_off, _managed_target(), relative_posix=_REL_POSIX)

    state_on: dict[str, Any] = {}
    monkeypatch.setattr(dataset_activation, "_MANAGED_ACTIVATION_ENABLED", True)
    on = activate_managed_context(state_on, _managed_target(), relative_posix=_REL_POSIX)

    assert off.outcome is ManagedActivationOutcome.DISABLED
    assert on.outcome is ManagedActivationOutcome.ACTIVATED
    # Legacy unmanaged activation is identical under both flag states.
    legacy_off: dict[str, Any] = {}
    legacy_on: dict[str, Any] = {}
    monkeypatch.setattr(dataset_activation, "_MANAGED_ACTIVATION_ENABLED", False)
    result_off = activate_dataset_context(legacy_off, _legacy())
    monkeypatch.setattr(dataset_activation, "_MANAGED_ACTIVATION_ENABLED", True)
    result_on = activate_dataset_context(legacy_on, _legacy())
    assert result_off.status is result_on.status
    assert get_dataset_context(legacy_off) == get_dataset_context(legacy_on)
