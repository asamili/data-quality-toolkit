"""Contract tests for trusted managed-recipe reload/reprocessing.

Cover the four keyword-only callables' signatures and live provenance,
session-state containment, deep immutability, detached drafts, trusted and
hostile loading against real confirmed versions, complete atomic rollback,
immutable one-parent confirmation, reopen-only activation, and the absence of any
lineage-presentation surface. Every workspace is a pytest ``tmp_path``; no
real operator workspace, dataset, recipe, or export is read.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.services import managed_recipe_reprocessing as mrr
from data_quality_toolkit.adapters.ui.services.dataset_discovery import (
    DiscoveredVersion,
    DiscoveryResult,
    InternalLocator,
    RootStatus,
    VersionDisplay,
)
from data_quality_toolkit.adapters.ui.services.dataset_versions import (
    CreationMechanism,
    DatasetFormat,
    DatasetVersionRecord,
    ParentRef,
    RecipeRef,
    content_id_from_bytes,
    new_family_id,
    new_version_id,
    recipe_digest,
)
from data_quality_toolkit.adapters.ui.services.managed_recipe_reprocessing import (
    STATUS_CONFIRMED,
    STATUS_DRAFTED,
    STATUS_FAILED,
    STATUS_LOADED,
    LoadedRecipe,
    _resolve_unique,
    _restore_workspace,
    _snapshot_workspace,
    confirm_reprocessed_child,
    create_recipe_draft,
    derive_action_reference,
    load_confirmed_recipe,
    revalidate_durable_recipe,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    resolve_trust_authority,
)
from data_quality_toolkit.adapters.ui.services.preprocessing import (
    apply_recipe,
    deterministic_output_names,
)
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT
from data_quality_toolkit.application.workflow.preprocessing import (
    OUTPUT_COLLISION,
    STATUS_APPLIED,
    STATUS_ERROR,
    STATUS_SKIPPED,
    make_recipe_step,
)

_VALID_SHA1 = "sha1:" + "0" * 40
_ADMISSIBLE_STEPS = [
    {"operation": "scaling", "columns": ["n"], "parameters": {"strategy": "minmax"}}
]
_CHILD_CSV = b"n,c\n9,z\n"

# A frame whose one-hot expansion would land on the existing "c_a", so the
# encoding step refuses for real. No transform, and no part of the contract under
# test, is ever mocked away.
_REPLAY_FRAME = pd.DataFrame(
    {"n": [1.0, 2.0, 2.0, 3.0], "c": ["a", "a", "b", "b"], "c_a": [1, 2, 3, 4]}
)


def _replayed(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the execution evidence a real ``apply_recipe`` replay produced."""
    _transformed, executed = apply_recipe(_REPLAY_FRAME, steps)
    return executed


# --- A. Four-callable contract: keyword-only, no defaults, live provenance ----

_CALLABLES: dict[str, tuple[Any, tuple[str, ...]]] = {
    "load_confirmed_recipe": (
        load_confirmed_recipe,
        ("session_state", "workspace_root", "action_reference"),
    ),
    "create_recipe_draft": (
        create_recipe_draft,
        ("session_state", "workspace_root", "loaded_recipe"),
    ),
    "revalidate_durable_recipe": (
        revalidate_durable_recipe,
        ("session_state", "workspace_root", "steps"),
    ),
    "confirm_reprocessed_child": (
        confirm_reprocessed_child,
        (
            "session_state",
            "workspace_root",
            "parent_record",
            "steps",
            "executed_steps",
            "csv_bytes",
            "label",
        ),
    ),
}


@pytest.mark.parametrize("name", sorted(_CALLABLES))
def test_callable_is_keyword_only_without_defaults(name: str) -> None:
    func, expected = _CALLABLES[name]
    sig = inspect.signature(func)
    assert tuple(sig.parameters) == expected
    for param in sig.parameters.values():
        assert param.kind is inspect.Parameter.KEYWORD_ONLY, (name, param.name, param.kind)
        assert param.default is inspect.Parameter.empty, (name, param.name)


@pytest.mark.parametrize("name", sorted(_CALLABLES))
def test_callable_originates_in_the_live_module(name: str) -> None:
    func, _ = _CALLABLES[name]
    assert (
        func.__module__ == "data_quality_toolkit.adapters.ui.services.managed_recipe_reprocessing"
    )
    assert getattr(mrr, name) is func


# --- B. Session-state containment -------------------------------------------


def test_load_never_mutates_session_state(confirmed_recipe: Any) -> None:
    state: dict[str, Any] = {"unrelated": 1}
    load_confirmed_recipe(
        session_state=state,
        workspace_root=str(confirmed_recipe.root),
        action_reference=confirmed_recipe.action_reference,
    )
    assert state == {"unrelated": 1}


def test_draft_never_mutates_session_state(confirmed_recipe: Any) -> None:
    loaded = _load(confirmed_recipe)
    state: dict[str, Any] = {"unrelated": 2}
    create_recipe_draft(
        session_state=state, workspace_root=str(confirmed_recipe.root), loaded_recipe=loaded
    )
    assert state == {"unrelated": 2}


def test_confirm_never_mutates_session_state(confirmed_recipe: Any) -> None:
    state: dict[str, Any] = {"unrelated": 3}
    confirm_reprocessed_child(
        session_state=state,
        workspace_root=str(confirmed_recipe.root),
        parent_record=confirmed_recipe.record,
        steps=_ADMISSIBLE_STEPS,
        executed_steps=_replayed(_ADMISSIBLE_STEPS),
        csv_bytes=_CHILD_CSV,
        label="child",
    )
    assert state == {"unrelated": 3}
    assert DATASET_CONTEXT not in state


# --- C. Trusted loading + deep immutability + detached drafts ----------------


def _load(fixture: Any) -> LoadedRecipe:
    return load_confirmed_recipe(
        session_state={},
        workspace_root=str(fixture.root),
        action_reference=fixture.action_reference,
    )


def test_trusted_load_succeeds(confirmed_recipe: Any) -> None:
    loaded = _load(confirmed_recipe)
    assert loaded.status == STATUS_LOADED
    assert loaded.loaded
    assert loaded.record is not None
    assert loaded.record.version_id == confirmed_recipe.record.version_id


def test_loaded_steps_are_deeply_immutable(confirmed_recipe: Any) -> None:
    loaded = _load(confirmed_recipe)
    assert isinstance(loaded.steps, tuple)
    step = loaded.steps[0]
    assert isinstance(step, Mapping)
    with pytest.raises(TypeError):
        step["operation"] = "hacked"  # type: ignore[index]
    assert isinstance(step["columns"], tuple)


def test_frozen_arrays_and_objects_stay_distinct_including_empty(
    confirmed_recipe: Any,
) -> None:
    loaded = _load(confirmed_recipe)
    # The second default step (drop_duplicates) carries empty columns and params.
    drop_step = next(s for s in loaded.steps if s["operation"] == "drop_duplicates")
    assert isinstance(drop_step["columns"], tuple)  # empty array stays a tuple
    assert drop_step["columns"] == ()
    assert isinstance(drop_step["parameters"], Mapping)  # empty object stays a mapping
    assert not isinstance(drop_step["parameters"], tuple)


def test_draft_is_detached_from_load_and_durable_bytes(
    confirmed_recipe: Any,
) -> None:
    loaded = _load(confirmed_recipe)
    before_recipe = confirmed_recipe.recipe_bytes()
    draft = create_recipe_draft(
        session_state={}, workspace_root=str(confirmed_recipe.root), loaded_recipe=loaded
    )
    assert draft.status == STATUS_DRAFTED
    assert isinstance(draft.steps, list)
    # Deeply mutate the draft at every level.
    draft.steps[0]["operation"] = "MUTATED"
    draft.steps[0]["parameters"]["strategy"] = "MUTATED"
    draft.steps[0]["columns"].append("MUTATED")
    draft.steps.append({"operation": "new"})
    # The immutable load and the durable recipe bytes are untouched.
    assert loaded.steps[0]["operation"] != "MUTATED"
    assert confirmed_recipe.recipe_bytes() == before_recipe


def test_load_writes_nothing_durable(confirmed_recipe: Any) -> None:
    before = {
        confirmed_recipe.csv_path: confirmed_recipe.csv_path.read_bytes(),
        confirmed_recipe.recipe_path: confirmed_recipe.recipe_path.read_bytes(),
        confirmed_recipe.sidecar_path: confirmed_recipe.sidecar_path.read_bytes(),
    }
    _load(confirmed_recipe)
    for path, data in before.items():
        assert path.read_bytes() == data


# --- D. Hostile loading ------------------------------------------------------


def test_blank_workspace_root_fails_closed() -> None:
    loaded = load_confirmed_recipe(
        session_state={}, workspace_root="  ", action_reference="v-1a2b3c4d"
    )
    assert loaded.status == STATUS_FAILED
    assert loaded.reason_code == "WORKSPACE_ROOT_BLANK"


def test_malformed_reference_fails_before_any_scan(tmp_path: Path) -> None:
    loaded = load_confirmed_recipe(
        session_state={}, workspace_root=str(tmp_path), action_reference="../etc/passwd"
    )
    assert loaded.reason_code == "REFERENCE_MALFORMED"


def test_missing_reference_is_unavailable(confirmed_recipe: Any) -> None:
    loaded = load_confirmed_recipe(
        session_state={},
        workspace_root=str(confirmed_recipe.root),
        action_reference="v-00000000",
    )
    assert loaded.reason_code == "REFERENCE_NOT_FOUND"


def test_source_mismatch_leaves_the_mismatched_recipe_untouched(
    confirmed_recipe: Any,
) -> None:
    recipe_before = confirmed_recipe.recipe_bytes()
    data = bytearray(confirmed_recipe.csv_path.read_bytes())
    data[0] = data[0] ^ 0x01  # same length, different content
    confirmed_recipe.csv_path.write_bytes(bytes(data))
    loaded = _load(confirmed_recipe)
    assert loaded.status == STATUS_FAILED
    assert loaded.reason_code == "SOURCE_MISMATCH"
    # The recipe was never read/rewritten on a source-identity failure.
    assert confirmed_recipe.recipe_bytes() == recipe_before


def test_ambiguity_uses_genuinely_colliding_selectable_references(
    confirmed_recipe: Any,
) -> None:
    # A second sidecar claiming the identical version_id is a genuine collision:
    # discovery quarantines the pair, so the shared reference resolves to no
    # single selectable record.
    duplicate = confirmed_recipe.sidecar_path.parent / "orders_dup.csv.dqtv.json"
    duplicate.write_bytes(confirmed_recipe.sidecar_path.read_bytes())
    loaded = _load(confirmed_recipe)
    assert loaded.status == STATUS_FAILED
    assert loaded.reason_code == "REFERENCE_AMBIGUOUS"


def test_resolve_unique_rejects_two_valid_matches() -> None:
    # Directly exercise the >1-valid-match guard with genuinely colliding
    # selectable references (two distinct valid versions sharing a short id).
    version = _synthetic_version("v-1a2b3c4d")
    other = _synthetic_version("v-1a2b3c4d")
    result = _synthetic_result(versions=(version, other))
    resolved, code = _resolve_unique(result, "v-1a2b3c4d")
    assert resolved is None
    assert code == "REFERENCE_AMBIGUOUS"


def test_unsupported_envelope_fails_independently_of_digest(
    make_confirmed: Any,
) -> None:
    # The registered digest matches the on-disk recipe exactly, yet the envelope
    # is schema_version "2": the refusal is the envelope, not a digest mismatch.
    unsupported = {"schema_version": "2", "steps": []}
    fixture = make_confirmed(recipe=unsupported, label="bad-envelope")
    assert fixture.record.recipe is not None
    assert recipe_digest(unsupported) == fixture.record.recipe.digest  # digest DOES match
    loaded = _load(fixture)
    assert loaded.status == STATUS_FAILED
    assert loaded.reason_code == "RECIPE_ENVELOPE_UNSUPPORTED"


def test_digest_mismatch_fails_independently_of_envelope(make_confirmed: Any) -> None:
    fixture = make_confirmed(label="tampered")
    # Overwrite with a *supported* envelope whose bytes differ from the registered
    # digest: the envelope passes, so the refusal is squarely the digest.
    tampered = json.dumps({"schema_version": "1", "steps": [], "summary": None})
    fixture.recipe_path.write_text(tampered, encoding="utf-8")
    loaded = _load(fixture)
    assert loaded.status == STATUS_FAILED
    assert loaded.reason_code == "RECIPE_DIGEST_MISMATCH"


# --- E. Immutable one-parent confirmation + reopen-only activation -----------


def test_confirm_creates_one_immutable_child_with_one_parent(
    confirmed_recipe: Any,
) -> None:
    parent = confirmed_recipe.record
    child = confirm_reprocessed_child(
        session_state={},
        workspace_root=str(confirmed_recipe.root),
        parent_record=parent,
        steps=_ADMISSIBLE_STEPS,
        executed_steps=_replayed(_ADMISSIBLE_STEPS),
        csv_bytes=_CHILD_CSV,
        label="child v1",
    )
    assert child.status == STATUS_CONFIRMED
    assert child.record is not None
    record = child.record
    # Exactly one parent, equal to parent_record.
    assert record.parent is not None
    assert record.parent.version_id == parent.version_id
    # Family and root identity preserved; new version and content identity.
    assert record.family_id == parent.family_id
    assert record.root_content_id == parent.root_content_id
    assert record.version_id != parent.version_id
    assert record.content_id == content_id_from_bytes(_CHILD_CSV)
    assert record.content_id != parent.content_id
    # The child artifacts exist on disk.
    assert (confirmed_recipe.root / Path(child.csv_relative_path)).is_file()
    assert (confirmed_recipe.root / Path(child.recipe_relative_path)).is_file()
    assert (confirmed_recipe.root / Path(child.sidecar_relative_path)).is_file()


def test_confirm_preserves_step_ordering(confirmed_recipe: Any) -> None:
    steps = [
        {"operation": "type_cast", "columns": ["n"], "parameters": {"target_type": "numeric"}},
        {"operation": "scaling", "columns": ["n"], "parameters": {"strategy": "zscore"}},
        {"operation": "drop_duplicates", "columns": [], "parameters": {}},
    ]
    child = confirm_reprocessed_child(
        session_state={},
        workspace_root=str(confirmed_recipe.root),
        parent_record=confirmed_recipe.record,
        steps=steps,
        executed_steps=_replayed(steps),
        csv_bytes=_CHILD_CSV,
        label="ordered",
    )
    assert child.confirmed and child.recipe is not None
    written = [s["operation"] for s in child.recipe["steps"]]
    assert written == ["type_cast", "scaling", "drop_duplicates"]


def test_confirm_does_not_activate_the_child(confirmed_recipe: Any) -> None:
    state: dict[str, Any] = {}
    confirm_reprocessed_child(
        session_state=state,
        workspace_root=str(confirmed_recipe.root),
        parent_record=confirmed_recipe.record,
        steps=_ADMISSIBLE_STEPS,
        executed_steps=_replayed(_ADMISSIBLE_STEPS),
        csv_bytes=_CHILD_CSV,
        label="child",
    )
    # No trust root committed, no active context: activation stays a later, explicit
    # reopen action.
    assert resolve_trust_authority(state).authority.name == "UNMANAGED"
    assert DATASET_CONTEXT not in state


def test_confirm_refuses_a_rejected_recipe_without_writing(
    confirmed_recipe: Any,
) -> None:
    before = sorted(p.name for p in (confirmed_recipe.root / "preprocessed").iterdir())
    rejected = [{"operation": "scaling", "columns": [], "parameters": {"strategy": "minmax"}}]
    child = confirm_reprocessed_child(
        session_state={},
        workspace_root=str(confirmed_recipe.root),
        parent_record=confirmed_recipe.record,
        steps=rejected,
        executed_steps=_replayed(rejected),
        csv_bytes=_CHILD_CSV,
        label="child",
    )
    assert child.status == STATUS_FAILED
    assert child.reason_code == "COLUMNS_REQUIRED"
    after = sorted(p.name for p in (confirmed_recipe.root / "preprocessed").iterdir())
    assert after == before  # nothing durable written on a rejected recipe


# --- F. Complete atomic rollback --------------------------------------------


def test_reachable_durable_failure_restores_workspace(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    (root / "preprocessed").mkdir(parents=True)
    parent_csv = root / "preprocessed" / "parent.csv"
    parent_csv.write_bytes(b"n\n1\n")
    # Make the recipes destination a *file* so the child's recipe staging fails
    # for real (no mocking of the durable stage).
    (root / "recipes").write_bytes(b"not a directory")
    parent = _managed_parent_record()

    before_pp = sorted(p.name for p in (root / "preprocessed").iterdir())
    child = confirm_reprocessed_child(
        session_state={},
        workspace_root=str(root),
        parent_record=parent,
        steps=_ADMISSIBLE_STEPS,
        executed_steps=_replayed(_ADMISSIBLE_STEPS),
        csv_bytes=_CHILD_CSV,
        label="child",
    )
    assert child.status == STATUS_FAILED
    assert child.record is None
    # Exact pre-call workspace state: no managed artifacts, no temp files, and the
    # recipes file left exactly as it was.
    assert sorted(p.name for p in (root / "preprocessed").iterdir()) == before_pp
    assert (root / "recipes").is_file()


def test_restore_sweeps_only_reserved_names_and_orphan_dirs(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    pp = root / "preprocessed"
    pp.mkdir(parents=True)
    (pp / "parent.csv").write_bytes(b"n\n1\n")
    (pp / "keep.csv").write_bytes(b"unrelated\n")  # unrelated, must survive
    snapshot = _snapshot_workspace(root, "orders")
    # Simulate a partial publish: reserved CSV, sidecar, a temp, and an orphan
    # recipes/ directory with the reserved recipe.
    (pp / "orders.csv").write_bytes(b"child\n")
    (pp / "orders.csv.dqtv.json").write_bytes(b"{}")
    (pp / ".orders.csv.abc123.tmp").write_bytes(b"tmp")
    (root / "recipes").mkdir()
    (root / "recipes" / "orders.json").write_bytes(b"{}")

    assert _restore_workspace(snapshot) is True
    assert sorted(p.name for p in pp.iterdir()) == ["keep.csv", "parent.csv"]
    assert not (root / "recipes").exists()  # orphan directory removed


# --- G. No lineage-presentation surface -------------------------------------

_LINEAGE_PRESENTATION_TOKENS = (
    "family_tree",
    "family tree",
    "parent_chain",
    "parent chain",
    "parent-chain",
    "ancestor",
    "descendant",
    "lineage graph",
    "lineage_graph",
    "lineage-graph",
    "version tree",
    "version_tree",
)

_RECIPE_RELOAD_SRC_PATHS = (
    "src/data_quality_toolkit/adapters/ui/services/managed_recipe_reprocessing.py",
    "src/data_quality_toolkit/adapters/ui/pages/preprocess_studio.py",
)


@pytest.mark.parametrize("relpath", _RECIPE_RELOAD_SRC_PATHS)
def test_no_lineage_presentation_surface(relpath: str) -> None:
    root = Path(__file__).resolve().parents[3]
    source = (root / relpath).read_text(encoding="utf-8").lower()
    offenders = [token for token in _LINEAGE_PRESENTATION_TOKENS if token in source]
    assert offenders == [], offenders


# --- H. Replay evidence integrity -------------------------------------------

# PASS -> ERROR -> PASS: the one-hot expansion of "c" would write a second "c_a",
# so it refuses before touching the frame, while the steps around it succeed.
# Exactly one middle operation never happened, so the recipe was never fully
# replayed - and the surviving "c_a" is what the cast then reads.
_PARTIAL_REPLAY_STEPS = [
    make_recipe_step("scaling", ["n"], {"strategy": "minmax"}),
    make_recipe_step("encoding", ["c"], {"strategy": "one_hot"}),
    make_recipe_step("type_cast", ["c_a"], {"target_type": "numeric"}),
]

# All three run to completion. The middle one is skipped on its own terms (an IQR
# strategy cannot apply to a text column), which the engine records truthfully and
# the durable step vocabulary admits - unlike an error, the step did complete.
_COMPLETE_REPLAY_STEPS = [
    make_recipe_step("scaling", ["n"], {"strategy": "minmax"}),
    make_recipe_step("iqr_outlier", ["c"], {"strategy": "flag"}),
    make_recipe_step("drop_duplicates", [], {}),
]


def _partial_replay() -> tuple[bytes, list[dict[str, Any]]]:
    """Return real replay output and evidence for the PASS/ERROR/PASS scenario."""
    transformed, executed = apply_recipe(_REPLAY_FRAME, _PARTIAL_REPLAY_STEPS)
    assert [step["status"] for step in executed] == [
        STATUS_APPLIED,
        STATUS_ERROR,
        STATUS_APPLIED,
    ]
    # The refused expansion is an output collision, not an incidental failure.
    assert OUTPUT_COLLISION in (executed[1]["warning"] or "")
    return transformed.to_csv(index=False).encode("utf-8"), executed


def _entries(root: Path) -> list[str]:
    return sorted(p.name for p in (root / "preprocessed").iterdir())


def test_partial_replay_is_refused_by_the_service_itself(confirmed_recipe: Any) -> None:
    """CASE B/F: a direct service call with failed evidence writes nothing."""
    csv_bytes, executed = _partial_replay()
    before = _entries(confirmed_recipe.root)

    child = confirm_reprocessed_child(
        session_state={},
        workspace_root=str(confirmed_recipe.root),
        parent_record=confirmed_recipe.record,
        steps=_PARTIAL_REPLAY_STEPS,
        executed_steps=executed,
        csv_bytes=csv_bytes,
        label="partial",
    )

    assert child.status == STATUS_FAILED
    assert not child.confirmed
    assert child.reason_code == "REPLAY_FAILED"
    assert child.record is None
    assert child.recipe is None
    assert child.csv_relative_path == ""
    assert child.sidecar_relative_path == ""
    # No confirmed child, no recipe, and no sidecar: the workspace is untouched.
    assert _entries(confirmed_recipe.root) == before
    assert not (confirmed_recipe.root / "recipes" / "orders-1.json").exists()


def test_authored_steps_alone_cannot_confirm_a_child(confirmed_recipe: Any) -> None:
    """Evidence is required: the authored recipe is never self-certifying."""
    csv_bytes, _executed = _partial_replay()
    before = _entries(confirmed_recipe.root)

    child = confirm_reprocessed_child(
        session_state={},
        workspace_root=str(confirmed_recipe.root),
        parent_record=confirmed_recipe.record,
        steps=_PARTIAL_REPLAY_STEPS,
        executed_steps=[],
        csv_bytes=csv_bytes,
        label="no evidence",
    )

    assert child.reason_code == "REPLAY_EVIDENCE_INVALID"
    assert _entries(confirmed_recipe.root) == before


def test_missing_execution_record_is_refused(confirmed_recipe: Any) -> None:
    """CASE E: N authored steps with N-1 execution records cannot be complete."""
    transformed, executed = apply_recipe(_REPLAY_FRAME, _COMPLETE_REPLAY_STEPS)
    before = _entries(confirmed_recipe.root)

    child = confirm_reprocessed_child(
        session_state={},
        workspace_root=str(confirmed_recipe.root),
        parent_record=confirmed_recipe.record,
        steps=_COMPLETE_REPLAY_STEPS,
        executed_steps=executed[:-1],
        csv_bytes=transformed.to_csv(index=False).encode("utf-8"),
        label="short",
    )

    assert child.reason_code == "REPLAY_INCOMPLETE"
    assert _entries(confirmed_recipe.root) == before


def test_substituted_execution_record_is_refused(confirmed_recipe: Any) -> None:
    """CASE E: an execution record naming a different step proves nothing."""
    transformed, executed = apply_recipe(_REPLAY_FRAME, _COMPLETE_REPLAY_STEPS)
    swapped = [executed[0], executed[2], executed[1]]
    before = _entries(confirmed_recipe.root)

    child = confirm_reprocessed_child(
        session_state={},
        workspace_root=str(confirmed_recipe.root),
        parent_record=confirmed_recipe.record,
        steps=_COMPLETE_REPLAY_STEPS,
        executed_steps=swapped,
        csv_bytes=transformed.to_csv(index=False).encode("utf-8"),
        label="reordered",
    )

    assert child.reason_code == "REPLAY_INCOMPLETE"
    assert _entries(confirmed_recipe.root) == before


def test_complete_replay_confirms_and_persists_executed_evidence(
    confirmed_recipe: Any,
) -> None:
    """CASE C/D: success still confirms, and the durable recipe is the replay."""
    transformed, executed = apply_recipe(_REPLAY_FRAME, _COMPLETE_REPLAY_STEPS)
    assert [step["status"] for step in executed] == [
        STATUS_APPLIED,
        STATUS_SKIPPED,
        STATUS_APPLIED,
    ]

    child = confirm_reprocessed_child(
        session_state={},
        workspace_root=str(confirmed_recipe.root),
        parent_record=confirmed_recipe.record,
        steps=_COMPLETE_REPLAY_STEPS,
        executed_steps=executed,
        csv_bytes=transformed.to_csv(index=False).encode("utf-8"),
        label="complete",
    )

    assert child.confirmed
    assert child.recipe is not None
    written = child.recipe["steps"]
    assert [step["operation"] for step in written] == [step["operation"] for step in executed]
    # The durable child states what the replay did, not what the draft intended:
    # the authored "pending" placeholders are gone and the skip is recorded as one.
    assert [step["status"] for step in written] == [
        STATUS_APPLIED,
        STATUS_SKIPPED,
        STATUS_APPLIED,
    ]
    assert all(step["before"] is not None and step["after"] is not None for step in written)
    # The same truth is on disk, not only in the returned value.
    durable = json.loads(
        (confirmed_recipe.root / Path(child.recipe_relative_path)).read_text(encoding="utf-8")
    )
    assert [step["status"] for step in durable["steps"]] == [
        STATUS_APPLIED,
        STATUS_SKIPPED,
        STATUS_APPLIED,
    ]
    assert durable["steps"][1]["warning"]  # the skip carries its real reason


def test_child_written_from_evidence_stays_reloadable(confirmed_recipe: Any) -> None:
    """A post-fix child round-trips through discovery, reload, and re-admission."""
    transformed, executed = apply_recipe(_REPLAY_FRAME, _COMPLETE_REPLAY_STEPS)
    child = confirm_reprocessed_child(
        session_state={},
        workspace_root=str(confirmed_recipe.root),
        parent_record=confirmed_recipe.record,
        steps=_COMPLETE_REPLAY_STEPS,
        executed_steps=executed,
        csv_bytes=transformed.to_csv(index=False).encode("utf-8"),
        label="reloadable",
    )
    assert child.confirmed and child.record is not None

    reloaded = load_confirmed_recipe(
        session_state={},
        workspace_root=str(confirmed_recipe.root),
        action_reference=derive_action_reference(version_id=child.record.version_id),
    )
    assert reloaded.loaded  # envelope, digest, and source identity all still hold
    assert [step["operation"] for step in reloaded.steps] == [
        step["operation"] for step in executed
    ]

    draft = create_recipe_draft(
        session_state={}, workspace_root=str(confirmed_recipe.root), loaded_recipe=reloaded
    )
    assert draft.drafted
    admission = revalidate_durable_recipe(
        session_state={}, workspace_root=str(confirmed_recipe.root), steps=draft.steps
    )
    assert admission.admitted


def test_replay_refusal_leaks_no_path_or_authored_value(confirmed_recipe: Any) -> None:
    """CASE G: the refusal names no workspace path, column, or parameter value."""
    csv_bytes, executed = _partial_replay()

    child = confirm_reprocessed_child(
        session_state={},
        workspace_root=str(confirmed_recipe.root),
        parent_record=confirmed_recipe.record,
        steps=_PARTIAL_REPLAY_STEPS,
        executed_steps=executed,
        csv_bytes=csv_bytes,
        label="partial",
    )

    surfaced = f"{child.reason_code} {child.message}"
    for secret in (
        str(confirmed_recipe.root),
        "c_a",
        "one_hot",
        "numeric",
        "TypeError",
    ):
        assert secret not in surfaced
    assert child.message == mrr._STATUS_MESSAGES[STATUS_FAILED]


# --- Synthetic helpers (unreachable-through-real-discovery branches only) -----


def _synthetic_locator(record: DatasetVersionRecord) -> InternalLocator:
    return InternalLocator(
        sidecar_relative_posix="preprocessed/orders.dqtv.json",
        sidecar_resolved_path="/ws/preprocessed/orders.dqtv.json",
        csv_resolved_path="/ws/preprocessed/orders.csv",
        recipe_resolved_path="/ws/recipes/orders.json",
        version_id=record.version_id,
        family_id=record.family_id,
        content_id=record.content_id,
        st_dev=1,
        st_ino=2,
    )


def _synthetic_record() -> DatasetVersionRecord:
    return DatasetVersionRecord(
        schema_version=1,
        version_id=new_version_id(),
        family_id=new_family_id(),
        root_content_id=content_id_from_bytes(b"root"),
        content_id=content_id_from_bytes(b"data"),
        dataset_id=_VALID_SHA1,
        label="orders",
        file_relative_path="preprocessed/orders.csv",
        format=DatasetFormat.CSV,
        size_bytes=4,
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
        created_by=CreationMechanism.PREPROCESS_RECIPE,
        parent=ParentRef(version_id=None, content_id=content_id_from_bytes(b"parent")),
        recipe=RecipeRef(digest="sha256:" + "0" * 64, relative_path="recipes/orders.json"),
    )


def _synthetic_version(short_id: str) -> DiscoveredVersion:
    record = _synthetic_record()
    return DiscoveredVersion(
        record=record,
        display=VersionDisplay(
            label="orders",
            short_version_id=short_id,
            status_label="Managed version",
            kind_label="Processed version",
        ),
        csv_status="ARTIFACT_OK",
        recipe_status="ARTIFACT_OK",
        locator=_synthetic_locator(record),
    )


def _synthetic_result(*, versions: tuple[DiscoveredVersion, ...]) -> DiscoveryResult:
    return DiscoveryResult(
        root_status=RootStatus.OK,
        root_reason="",
        enumeration_complete=True,
        result_complete=True,
        reopen_safe=True,
        entries_observed=len(versions),
        candidates_retained=len(versions),
        sidecars_parsed=len(versions),
        records_returned=len(versions),
        duplicate_group_count=0,
        duplicate_member_count=0,
        versions=versions,
        issues=(),
        duplicates=(),
        omitted_count=0,
        reason_codes=(),
    )


def _managed_parent_record() -> DatasetVersionRecord:
    return DatasetVersionRecord(
        schema_version=1,
        version_id=new_version_id(),
        family_id=new_family_id(),
        root_content_id=content_id_from_bytes(b"root"),
        content_id=content_id_from_bytes(b"parent"),
        dataset_id=_VALID_SHA1,
        label="parent",
        file_relative_path="preprocessed/parent.csv",
        format=DatasetFormat.CSV,
        size_bytes=4,
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
        created_by=CreationMechanism.ROOT_IMPORT,
    )


# --- I. Output-collision admission and trusted-activation interaction ---------

_ADMISSION_ROOT = "C:/nonexistent-workspace-root-never-read"


def _admit_steps(steps: list[dict[str, Any]]) -> Any:
    return revalidate_durable_recipe(session_state={}, workspace_root=_ADMISSION_ROOT, steps=steps)


def _plain(operation: str, columns: list[str], parameters: dict[str, Any]) -> dict[str, Any]:
    return {"operation": operation, "columns": columns, "parameters": parameters}


@pytest.mark.parametrize(
    ("first", "second"),
    [
        # Two steps generating the same deterministic create-only destination.
        (
            _plain("iqr_outlier", ["age"], {"strategy": "flag"}),
            _plain("iqr_outlier", ["age"], {"strategy": "flag"}),
        ),
        (
            _plain("encoding", ["city"], {"strategy": "frequency"}),
            _plain("encoding", ["city"], {"strategy": "frequency"}),
        ),
        (
            _plain("encoding", ["city"], {"strategy": "label"}),
            _plain("encoding", ["city"], {"strategy": "label"}),
        ),
        (
            _plain("derived_column", [], {"source_column": "d", "derived_kind": "year"}),
            _plain("derived_column", [], {"source_column": "d", "derived_kind": "year"}),
        ),
        # A generated destination and an explicit calculated destination.
        (
            _plain("iqr_outlier", ["age"], {"strategy": "flag"}),
            _plain(
                "calc_scalar",
                [],
                {
                    "source_column": "age",
                    "operator": "add",
                    "scalar": 1.0,
                    "output_column": "age__outlier",
                },
            ),
        ),
        # ...and the same pair in the other order.
        (
            _plain(
                "calc_scalar",
                [],
                {
                    "source_column": "age",
                    "operator": "add",
                    "scalar": 1.0,
                    "output_column": "city__freq",
                },
            ),
            _plain("encoding", ["city"], {"strategy": "frequency"}),
        ),
    ],
)
def test_admission_refuses_a_reserved_generated_destination(
    first: dict[str, Any], second: dict[str, Any]
) -> None:
    result = _admit_steps([first, second])
    assert result.reason_code == OUTPUT_COLLISION
    assert result.step_index == 1


def test_admission_admits_distinct_generated_destinations() -> None:
    result = _admit_steps(
        [
            _plain("iqr_outlier", ["age"], {"strategy": "flag"}),
            _plain("encoding", ["city"], {"strategy": "frequency"}),
            _plain("encoding", ["city"], {"strategy": "label"}),
            _plain("derived_column", [], {"source_column": "d", "derived_kind": "year"}),
        ]
    )
    assert result.admitted


def test_admission_does_not_reserve_for_in_place_or_row_only_operations() -> None:
    # Repeating an in-place transform on one column is not an output collision:
    # rewriting the selected source is the operation's own contract.
    result = _admit_steps(
        [
            _plain("type_cast", ["age"], {"target_type": "numeric"}),
            _plain("scaling", ["age"], {"strategy": "minmax"}),
            _plain("scaling", ["age"], {"strategy": "zscore"}),
            _plain("iqr_outlier", ["age"], {"strategy": "clip"}),
            _plain("iqr_outlier", ["age"], {"strategy": "remove"}),
            _plain("drop_duplicates", [], {}),
            _plain("missing_value", ["age"], {"strategy": "median"}),
        ]
    )
    assert result.admitted


def test_admission_does_not_claim_to_have_validated_one_hot_destinations() -> None:
    # Two one-hot steps on the same column would collide at execution, but their
    # names depend on the values present, so admission proves nothing about them.
    result = _admit_steps(
        [
            _plain("encoding", ["c"], {"strategy": "one_hot"}),
            _plain("encoding", ["c"], {"strategy": "one_hot"}),
        ]
    )
    assert result.admitted
    assert deterministic_output_names("encoding", ["c"], {"strategy": "one_hot"}) == []


def test_admission_refusal_names_no_column_or_value() -> None:
    result = _admit_steps(
        [
            _plain("iqr_outlier", ["age"], {"strategy": "flag"}),
            _plain("iqr_outlier", ["age"], {"strategy": "flag"}),
        ]
    )
    surfaced = f"{result.reason_code} {result.message}"
    assert "age" not in surfaced
    assert "__outlier" not in surfaced


def test_collision_error_cannot_confirm_a_child(confirmed_recipe: Any) -> None:
    """The whole R4 -> R3 path: collision, error evidence, refusal, no child."""
    steps = [
        make_recipe_step("scaling", ["n"], {"strategy": "minmax"}),
        make_recipe_step("encoding", ["c"], {"strategy": "one_hot"}),
    ]
    transformed, executed = apply_recipe(_REPLAY_FRAME, steps)
    assert [step["status"] for step in executed] == [STATUS_APPLIED, STATUS_ERROR]
    assert OUTPUT_COLLISION in (executed[1]["warning"] or "")
    # The refused expansion left the protected column exactly as it was.
    assert transformed["c_a"].tolist() == _REPLAY_FRAME["c_a"].tolist()
    assert list(transformed.columns).count("c_a") == 1

    # The authored recipe itself is admissible: only execution can know this.
    assert _admit_steps([dict(step) for step in steps]).admitted

    before = _entries(confirmed_recipe.root)
    child = confirm_reprocessed_child(
        session_state={},
        workspace_root=str(confirmed_recipe.root),
        parent_record=confirmed_recipe.record,
        steps=steps,
        executed_steps=executed,
        csv_bytes=transformed.to_csv(index=False).encode("utf-8"),
        label="collision",
    )

    assert child.status == STATUS_FAILED
    assert not child.confirmed
    assert child.reason_code == "REPLAY_FAILED"
    assert child.record is None
    assert child.recipe is None
    # No durable child, recipe, or sidecar was written.
    assert _entries(confirmed_recipe.root) == before
    assert not (confirmed_recipe.root / "recipes" / "orders-1.json").exists()
