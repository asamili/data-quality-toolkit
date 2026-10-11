"""Interruption and reconciliation semantics for trusted managed activation.

The activation transaction has exactly one trust-commit
point. These tests pin what happens on either side of it:

* a pre-commit failure leaves the previous valid authority exactly as it was;
* an interruption at or after the commit is reconciled *forward* — the stale
  authority is never restored and the session is left fail-closed;
* retirement is generation-driven, so a binding stays retired even when the
  physical mirror or marker is deliberately left behind;
* every generation change clears both managed caches.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.services import dataset_activation
from data_quality_toolkit.adapters.ui.services import managed_frame_loader as mfl
from data_quality_toolkit.adapters.ui.services.dataset_activation import (
    ManagedActivationOutcome,
    activate_managed_context,
    make_managed_context,
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
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT

_CONTENT_A = "sha256:" + "a" * 64
_CONTENT_B = "sha256:" + "b" * 64
_ROOT_CONTENT = "sha256:" + "c" * 64
_REL_POSIX = "preprocessed/orders.csv"
# A native absolute path on every host: a Windows literal is not absolute on
# POSIX, where its backslashes never split into a bare file name.
_ABS_SOURCE = str(Path(Path.cwd().anchor, "private", "ws", "preprocessed", "orders.csv"))


@pytest.fixture(autouse=True)
def _clean_caches() -> Iterator[None]:
    mfl.clear_managed_caches()
    yield
    mfl.clear_managed_caches()


@pytest.fixture(autouse=True)
def _enable_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the transaction directly; production stays flag-gated."""
    monkeypatch.setattr(dataset_activation, "_MANAGED_ACTIVATION_ENABLED", True)


def _record(**overrides: Any) -> DatasetVersionRecord:
    from datetime import UTC, datetime

    fields: dict[str, Any] = {
        "schema_version": 1,
        "version_id": new_version_id(),
        "family_id": new_family_id(),
        "root_content_id": _ROOT_CONTENT,
        "content_id": _CONTENT_A,
        "dataset_id": "sha1:" + "d" * 40,
        "label": "cleaned v2",
        "file_relative_path": _REL_POSIX,
        "format": DatasetFormat.CSV,
        "size_bytes": 2048,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "created_by": CreationMechanism.PREPROCESS_RECIPE,
    }
    fields.update(overrides)
    # A processed version must carry an immediate parent and a recipe. Neither is
    # read by the activation transaction under test (make_managed_context maps an
    # unmanaged parent to parent_version_id=None and ignores the recipe), so these
    # synthetic references satisfy the schema-1 invariant without altering behavior.
    if fields["created_by"] is CreationMechanism.PREPROCESS_RECIPE:
        fields.setdefault("parent", ParentRef(version_id=None, content_id=_CONTENT_A))
        fields.setdefault(
            "recipe", RecipeRef(digest="sha256:" + "e" * 64, relative_path="recipes/orders.json")
        )
    return DatasetVersionRecord(**fields)


def _target(csv: Path | None = None, **overrides: Any) -> DatasetContext:
    source = str(csv) if csv is not None else _ABS_SOURCE
    size = int(csv.stat().st_size) if csv is not None else 2048
    mtime = int(csv.stat().st_mtime_ns) if csv is not None else 10
    return make_managed_context(
        _record(**overrides),
        source_path=source,
        display_name="orders.csv",
        size_bytes=size,
        modified_ns=mtime,
    )


def _managed_csv(tmp_path: Path, name: str = "orders.csv") -> Path:
    target = tmp_path / "preprocessed" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("a,b\n1,2\n", encoding="utf-8")
    return target


def _boom(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("injected failure")


def _restore_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo the injected failure while keeping the transaction enabled.

    ``monkeypatch.undo()`` also reverts the autouse enable, so the flag is
    re-applied here rather than silently falling back to the disabled path.
    """
    monkeypatch.undo()
    monkeypatch.setattr(dataset_activation, "_MANAGED_ACTIVATION_ENABLED", True)


# --- A. Pre-commit failure ------------------------------------------------------


def test_pre_commit_failure_creates_no_trust_at_all() -> None:
    state: dict[str, Any] = {}

    report = activate_managed_context(
        state,
        DatasetContext(
            source_path="C:/x/orders.csv",
            display_name="orders.csv",
            size_bytes=1,
            modified_ns=1,
        ),
        relative_posix=_REL_POSIX,
    )

    assert report.outcome is ManagedActivationOutcome.REFUSED_PRE_COMMIT
    assert report.trust_committed is False
    assert get_valid_trust_root(state) is None


def test_pre_commit_failure_preserves_the_previous_root_object() -> None:
    state: dict[str, Any] = {}
    activate_managed_context(state, _target(), relative_posix=_REL_POSIX)
    original = get_valid_trust_root(state)
    assert original is not None
    generation_before = current_generation(state)

    report = activate_managed_context(state, _target(), relative_posix="C:/absolute/orders.csv")

    assert report.outcome is ManagedActivationOutcome.REFUSED_PRE_COMMIT
    assert get_valid_trust_root(state) is original
    assert current_generation(state) == generation_before


def test_pre_commit_failure_preserves_the_managed_caches(tmp_path: Path) -> None:
    csv = _managed_csv(tmp_path)
    state: dict[str, Any] = {}
    activate_managed_context(state, _target(csv), relative_posix=_REL_POSIX)
    mfl.get_managed_frame(state)
    assert mfl._managed_frame_cache

    activate_managed_context(state, _target(csv), relative_posix="C:/absolute/orders.csv")

    assert mfl._managed_frame_cache  # untouched: the commit was never reached


# --- B. Post-commit interruption ---------------------------------------------------


def test_post_commit_interruption_is_reported_as_such(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, Any] = {}
    monkeypatch.setattr(dataset_activation, "activate_dataset_context", _boom)

    report = activate_managed_context(state, _target(), relative_posix=_REL_POSIX)

    assert report.outcome is ManagedActivationOutcome.INTERRUPTED_POST_COMMIT
    assert report.trust_committed is True
    assert report.activated is False


def test_post_commit_interruption_leaves_the_session_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, Any] = {}
    monkeypatch.setattr(dataset_activation, "activate_dataset_context", _boom)

    activate_managed_context(state, _target(), relative_posix=_REL_POSIX)

    assert get_valid_trust_root(state) is None
    assert resolve_trust_authority(state).authority is not TrustAuthority.MANAGED_AUTHORITY


def test_post_commit_interruption_never_restores_stale_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, Any] = {}
    activate_managed_context(state, _target(content_id=_CONTENT_A), relative_posix=_REL_POSIX)
    stale = get_valid_trust_root(state)
    assert stale is not None

    monkeypatch.setattr(dataset_activation, "activate_dataset_context", _boom)
    activate_managed_context(state, _target(content_id=_CONTENT_B), relative_posix=_REL_POSIX)

    assert get_valid_trust_root(state) is None
    trust = state[MANAGED_TRUST_STATE_KEY]
    assert trust.root is None  # not the stale root, and not the new one either


def test_post_commit_interruption_only_advances_the_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, Any] = {}
    activate_managed_context(state, _target(), relative_posix=_REL_POSIX)
    before = current_generation(state)

    monkeypatch.setattr(dataset_activation, "activate_dataset_context", _boom)
    activate_managed_context(state, _target(), relative_posix=_REL_POSIX)

    assert current_generation(state) == before + 2
    assert current_generation(state) > before  # never decrements


def test_post_commit_interruption_clears_both_managed_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv = _managed_csv(tmp_path)
    state: dict[str, Any] = {}
    activate_managed_context(state, _target(csv), relative_posix=_REL_POSIX)
    mfl.get_managed_frame(state)
    mfl.get_managed_assessment(state, assessor=lambda frame: {"rows": int(len(frame))})
    assert mfl._managed_frame_cache and mfl._managed_assessment_cache

    monkeypatch.setattr(dataset_activation, "activate_dataset_context", _boom)
    activate_managed_context(state, _target(csv, content_id=_CONTENT_B), relative_posix=_REL_POSIX)

    assert len(mfl._managed_frame_cache) == 0
    assert len(mfl._managed_assessment_cache) == 0


def test_interrupted_session_refuses_managed_frame_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv = _managed_csv(tmp_path)
    state: dict[str, Any] = {}
    monkeypatch.setattr(dataset_activation, "activate_dataset_context", _boom)
    activate_managed_context(state, _target(csv), relative_posix=_REL_POSIX)

    with pytest.raises(mfl.ManagedFrameLoadError) as excinfo:
        mfl.get_managed_frame(state)

    assert excinfo.value.reason_code == "NO_VALID_TRUST"


# --- C. Generation-driven retirement is marker-independent ---------------------------


def test_retirement_survives_a_left_behind_mirror() -> None:
    state: dict[str, Any] = {}
    target = _target()
    activate_managed_context(state, target, relative_posix=_REL_POSIX)
    mirror = state[DATASET_CONTEXT]

    retire_managed_trust(state)
    state[DATASET_CONTEXT] = mirror  # physical marker deliberately not cleaned

    assert get_valid_trust_root(state) is None
    assert resolve_trust_authority(state).authority is TrustAuthority.FAIL_CLOSED


def test_retirement_survives_a_reinstated_root_object() -> None:
    """A retired root cannot be revived by putting the object back."""
    state: dict[str, Any] = {}
    activate_managed_context(state, _target(), relative_posix=_REL_POSIX)
    root = get_valid_trust_root(state)
    assert root is not None

    retire_managed_trust(state)
    state[MANAGED_TRUST_STATE_KEY].root = root  # reinstated by hand

    # The generation moved on, so the reinstated root is still invalid.
    assert get_valid_trust_root(state) is None


def test_reconciliation_drops_a_binding_invalidated_by_capability_replacement() -> None:
    state: dict[str, Any] = {}
    activate_managed_context(state, _target(), relative_posix=_REL_POSIX)
    state[MANAGED_TRUST_STATE_KEY].capability = SessionCapability()

    decision = reconcile_managed_trust(state)

    assert decision.authority is not TrustAuthority.MANAGED_AUTHORITY
    assert state[MANAGED_TRUST_STATE_KEY].root is None


def test_reconciliation_is_idempotent() -> None:
    state: dict[str, Any] = {}
    activate_managed_context(state, _target(), relative_posix=_REL_POSIX)
    state[MANAGED_TRUST_STATE_KEY].capability = None

    first = reconcile_managed_trust(state)
    second = reconcile_managed_trust(state)

    assert first.authority is second.authority
    assert state[MANAGED_TRUST_STATE_KEY].root is None


def test_reconciliation_keeps_a_valid_binding_intact() -> None:
    state: dict[str, Any] = {}
    activate_managed_context(state, _target(), relative_posix=_REL_POSIX)
    root = get_valid_trust_root(state)

    decision = reconcile_managed_trust(state)

    assert decision.authority is TrustAuthority.MANAGED_AUTHORITY
    assert decision.root is root


def test_capability_replacement_makes_prior_cache_entries_unreachable(
    tmp_path: Path,
) -> None:
    csv = _managed_csv(tmp_path)
    state: dict[str, Any] = {}
    activate_managed_context(state, _target(csv), relative_posix=_REL_POSIX)
    frame = mfl.get_managed_frame(state)
    assert isinstance(frame, pd.DataFrame)
    old_capability = peek_session_capability(state)

    state[MANAGED_TRUST_STATE_KEY].capability = SessionCapability()

    assert peek_session_capability(state) is not old_capability
    with pytest.raises(mfl.ManagedFrameLoadError):
        mfl.get_managed_frame(state)


# --- D. Recovery after interruption --------------------------------------------------


def test_a_fresh_activation_recovers_after_an_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv = _managed_csv(tmp_path)
    state: dict[str, Any] = {}
    monkeypatch.setattr(dataset_activation, "activate_dataset_context", _boom)
    activate_managed_context(state, _target(csv), relative_posix=_REL_POSIX)
    assert get_valid_trust_root(state) is None

    _restore_activation(monkeypatch)
    report = activate_managed_context(state, _target(csv), relative_posix=_REL_POSIX)

    assert report.outcome is ManagedActivationOutcome.ACTIVATED
    assert get_valid_trust_root(state) is not None
    assert isinstance(mfl.get_managed_frame(state), pd.DataFrame)


def test_recovery_reuses_the_same_session_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, Any] = {}
    monkeypatch.setattr(dataset_activation, "activate_dataset_context", _boom)
    activate_managed_context(state, _target(), relative_posix=_REL_POSIX)
    capability = peek_session_capability(state)
    assert capability is not None

    _restore_activation(monkeypatch)
    activate_managed_context(state, _target(), relative_posix=_REL_POSIX)

    # An interruption retires the binding, never the session identity itself.
    assert peek_session_capability(state) is capability


def test_interruption_reports_stay_privacy_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    state: dict[str, Any] = {}
    monkeypatch.setattr(dataset_activation, "activate_dataset_context", _boom)

    report = activate_managed_context(state, _target(), relative_posix=_REL_POSIX)

    text = repr(report) + str(report)
    assert _ABS_SOURCE not in text
    assert "C:\\" not in text
    assert "orders.csv" not in text
    assert "injected failure" not in text


def test_direct_commit_interruption_matches_the_service_contract() -> None:
    """A commit made directly is retired forward the same way."""
    state: dict[str, Any] = {}
    capability = ensure_session_capability(state)
    commit_trust_root(
        state,
        capability,
        version_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        content_id=_CONTENT_A,
        root_content_id=_ROOT_CONTENT,
        parent_version_id=None,
        version_label="cleaned v2",
        locator=make_source_locator(
            display_name="orders.csv",
            relative_posix=_REL_POSIX,
            absolute_path=_ABS_SOURCE,
        ),
        size_bytes=2048,
        modified_ns=10,
        large_file_mode=False,
    )
    generation = current_generation(state)

    retire_managed_trust(state)

    assert current_generation(state) == generation + 1
    assert get_valid_trust_root(state) is None
