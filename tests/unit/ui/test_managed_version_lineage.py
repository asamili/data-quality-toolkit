"""Tests for the pure direct-only managed-version lineage projection.

Cover :mod:`...services.managed_version_lineage`: exact callable signatures and
live provenance, immutable frozen/slots results, deterministic selected / root /
direct-parent / direct-child projection, independent selected-versus-active
state, zero-parent root, unavailable parent/root, exact duplicate quarantine from
the live discovery representation, ambiguous selection, self-parent, two-node and longer
cycles, cross-family edges, safely proven root-content mismatch, missing-root
evidence that must not be misread as corruption, ``max_nodes`` validation,
deterministic truncation, the absence of ancestry/descendant traversal beyond
direct relations, purity (no filesystem/session/durable access), privacy
redaction, and the normalized text alternative.

Assertions are semantic: presence of safe meaning and absence of every sensitive
value (paths, filenames, full UUIDs, content hashes, family UUIDs, raw discovery
issues, and exceptions). Records are constructed directly so every sensitive
field is under test control.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.services import managed_version_lineage as lineage_mod
from data_quality_toolkit.adapters.ui.services.dataset_discovery import (
    DiscoveredVersion,
    DiscoveryIssue,
    DiscoveryResult,
    DuplicateGroup,
    InternalLocator,
    RecordStatus,
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
)
from data_quality_toolkit.adapters.ui.services.managed_version_lineage import (
    MAX_LINEAGE_NODES,
    LineageNode,
    LineageRelationship,
    LineageState,
    LineageView,
    empty_lineage,
    project_lineage,
)

_VALID_SHA1 = "sha1:" + "0" * 40
_PRIVATE_DIR = r"C:\Users\example_user\private"
_DEFAULT_TIME = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)


# --- direct-construction helpers (full control over sensitive fields) ------


def _cid(tag: bytes) -> str:
    return content_id_from_bytes(tag)


def _ver(
    short_id: str,
    *,
    vid: str,
    fid: str,
    content: str,
    root_content: str,
    parent: ParentRef | None = None,
    created_at: datetime = _DEFAULT_TIME,
    label: str = "version",
    created_by: CreationMechanism = CreationMechanism.PREPROCESS_RECIPE,
    csv_status: str = "ARTIFACT_OK",
    recipe_status: str = "RECIPE_ABSENT",
) -> DiscoveredVersion:
    # A processed version must carry the recipe that produced it; a true root
    # (ROOT_IMPORT) carries none. The recipe is never probed here — lineage is a
    # pure projection — so a synthetic reference keeps the record valid.
    recipe = (
        RecipeRef(digest="sha256:" + "0" * 64, relative_path="recipes/data.json")
        if created_by is CreationMechanism.PREPROCESS_RECIPE
        else None
    )
    record = DatasetVersionRecord(
        schema_version=1,
        version_id=vid,
        family_id=fid,
        root_content_id=root_content,
        content_id=content,
        dataset_id=_VALID_SHA1,
        label=label,
        file_relative_path="preprocessed/data.csv",
        format=DatasetFormat.CSV,
        size_bytes=16,
        created_at=created_at,
        created_by=created_by,
        parent=parent,
        recipe=recipe,
    )
    display = VersionDisplay(
        label=label,
        short_version_id=short_id,
        status_label="Managed version",
        kind_label="Processed version",
    )
    locator = InternalLocator(
        sidecar_relative_posix="preprocessed/orders.dqtv.json",
        sidecar_resolved_path=rf"{_PRIVATE_DIR}\preprocessed\orders.dqtv.json",
        csv_resolved_path=rf"{_PRIVATE_DIR}\preprocessed\orders.csv",
        recipe_resolved_path=None,
        version_id=vid,
        family_id=fid,
        content_id=content,
        st_dev=1,
        st_ino=2,
    )
    return DiscoveredVersion(
        record=record,
        display=display,
        csv_status=csv_status,
        recipe_status=recipe_status,
        locator=locator,
    )


def _duplicate(
    *,
    short_version_id: str,
    member_references: tuple[str, ...] = ("duplicate-0001", "duplicate-0002"),
) -> DuplicateGroup:
    vid = new_version_id()
    fid = new_family_id()
    member = InternalLocator(
        sidecar_relative_posix="preprocessed/dupe.dqtv.json",
        sidecar_resolved_path=rf"{_PRIVATE_DIR}\preprocessed\dupe.dqtv.json",
        csv_resolved_path=None,
        recipe_resolved_path=None,
        version_id=vid,
        family_id=fid,
        content_id=_cid(b"dupe"),
        st_dev=1,
        st_ino=2,
    )
    return DuplicateGroup(
        kind="duplicate_conflict",
        short_version_id=short_version_id,
        member_count=len(member_references),
        member_references=member_references,
        internal_members=tuple(member for _ in member_references),
    )


def _issue(*, reason_code: str) -> DiscoveryIssue:
    return DiscoveryIssue(
        status=RecordStatus.CORRUPT,
        reference="issue-0001",
        label="Unreadable version record",
        reason_code=reason_code,
    )


def _result(
    *,
    versions: tuple[DiscoveredVersion, ...] = (),
    issues: tuple[DiscoveryIssue, ...] = (),
    duplicates: tuple[DuplicateGroup, ...] = (),
) -> DiscoveryResult:
    return DiscoveryResult(
        root_status=RootStatus.OK,
        root_reason="",
        enumeration_complete=True,
        result_complete=True,
        reopen_safe=True,
        entries_observed=len(versions) + len(issues),
        candidates_retained=len(versions) + len(issues),
        sidecars_parsed=len(versions),
        records_returned=len(versions),
        duplicate_group_count=len(duplicates),
        duplicate_member_count=sum(group.member_count for group in duplicates),
        versions=versions,
        issues=issues,
        duplicates=duplicates,
        omitted_count=0,
        reason_codes=(),
    )


def _linear_family() -> tuple[dict[str, str], tuple[DiscoveredVersion, ...]]:
    """Root -> parent -> selected -> child, plus a grandchild of the child.

    The root is an imported root whose ``content_id`` equals the shared
    ``root_content_id``; every descendant carries that same ``root_content_id``.
    """
    fam = new_family_id()
    ids = {name: new_version_id() for name in ("root", "parent", "sel", "child", "grand")}
    root_content = _cid(b"root-bytes")
    parent_content = _cid(b"parent-bytes")
    sel_content = _cid(b"sel-bytes")
    child_content = _cid(b"child-bytes")
    grand_content = _cid(b"grand-bytes")
    root = _ver(
        "v-root0001",
        vid=ids["root"],
        fid=fam,
        content=root_content,
        root_content=root_content,
        parent=None,
        created_by=CreationMechanism.ROOT_IMPORT,
        label="root",
    )
    parent = _ver(
        "v-parent01",
        vid=ids["parent"],
        fid=fam,
        content=parent_content,
        root_content=root_content,
        parent=ParentRef(version_id=ids["root"], content_id=root_content),
        label="parent",
    )
    sel = _ver(
        "v-select01",
        vid=ids["sel"],
        fid=fam,
        content=sel_content,
        root_content=root_content,
        parent=ParentRef(version_id=ids["parent"], content_id=parent_content),
        label="selected",
    )
    child = _ver(
        "v-child001",
        vid=ids["child"],
        fid=fam,
        content=child_content,
        root_content=root_content,
        parent=ParentRef(version_id=ids["sel"], content_id=sel_content),
        label="child",
    )
    grand = _ver(
        "v-grand001",
        vid=ids["grand"],
        fid=fam,
        content=grand_content,
        root_content=root_content,
        parent=ParentRef(version_id=ids["child"], content_id=child_content),
        label="grandchild",
    )
    return ids, (root, parent, sel, child, grand)


# --- A. signatures and live provenance -------------------------------------


def test_project_lineage_signature_is_exact() -> None:
    sig = inspect.signature(project_lineage)
    assert list(sig.parameters) == ["result", "selected_reference", "active_reference", "max_nodes"]
    assert sig.parameters["active_reference"].kind is inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["max_nodes"].kind is inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["max_nodes"].default == 64
    assert MAX_LINEAGE_NODES == 64


def test_empty_lineage_signature_is_exact() -> None:
    sig = inspect.signature(empty_lineage)
    assert list(sig.parameters) == ["state"]
    assert sig.parameters["state"].kind is inspect.Parameter.KEYWORD_ONLY


def _module_source() -> str:
    return Path(lineage_mod.__file__).read_text(encoding="utf-8")


def _imported_names() -> set[str]:
    tree = ast.parse(_module_source())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(alias.name for alias in node.names)
    return names


def test_service_consumes_live_discovery_result_types() -> None:
    names = _imported_names()
    assert "data_quality_toolkit.adapters.ui.services.dataset_discovery" in names
    assert "DiscoveryResult" in names
    assert "DiscoveredVersion" in names
    assert "data_quality_toolkit.adapters.ui.services.dataset_versions" in names
    assert "DatasetVersionRecord" in names


# --- B. immutable frozen/slots results -------------------------------------


def test_result_types_are_frozen_and_slotted() -> None:
    _, versions = _linear_family()
    view = project_lineage(_result(versions=versions), "v-select01", active_reference=None)
    assert view.selected is not None
    with pytest.raises(FrozenInstanceError):
        view.state = LineageState.EMPTY  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        view.selected.label = "x"  # type: ignore[misc]
    assert not hasattr(view, "__dict__")
    assert not hasattr(view.selected, "__dict__")


def test_result_field_types_are_ui_safe() -> None:
    allowed = {
        "LineageNode | None",
        "tuple[LineageNode, ...]",
        "LineageState",
        "LineageRelationship",
        "str",
        "int",
        "bool",
    }
    for cls in (LineageNode, LineageView):
        for field in dataclasses.fields(cls):
            assert field.type in allowed, (cls.__name__, field.name, field.type)
        names = {field.name for field in dataclasses.fields(cls)}
        assert not names & {"record", "locator", "internal_members", "content_id", "version_id"}


# --- C. deterministic selected / root / parent / child projection ----------


def test_direct_projection_resolves_selected_root_parent_children() -> None:
    _, versions = _linear_family()
    view = project_lineage(_result(versions=versions), "v-select01", active_reference=None)
    assert view.state is LineageState.READY
    assert view.selected is not None and view.selected.short_version_id == "v-select01"
    assert view.selected.relationship is LineageRelationship.SELECTED
    assert view.root is not None and view.root.short_version_id == "v-root0001"
    assert view.root.relationship is LineageRelationship.ROOT
    assert view.parent is not None and view.parent.short_version_id == "v-parent01"
    assert view.parent.relationship is LineageRelationship.PARENT
    assert tuple(child.short_version_id for child in view.children) == ("v-child001",)
    assert view.children[0].relationship is LineageRelationship.CHILD
    assert view.unavailable_relatives == 0
    assert view.corrupt_relatives == 0
    assert view.truncated is False


def test_projection_is_deterministic() -> None:
    _, versions = _linear_family()
    result = _result(versions=versions)
    assert project_lineage(result, "v-select01", active_reference=None) == project_lineage(
        result, "v-select01", active_reference=None
    )


def test_created_at_normalized_to_utc() -> None:
    fam = new_family_id()
    vid = new_version_id()
    plus_two = timezone(timedelta(hours=2))
    ver = _ver(
        "v-tz000001",
        vid=vid,
        fid=fam,
        content=_cid(b"x"),
        root_content=_cid(b"x"),
        parent=None,
        created_by=CreationMechanism.ROOT_IMPORT,
        created_at=datetime(2026, 3, 1, 9, 0, 0, tzinfo=plus_two),
    )
    view = project_lineage(_result(versions=(ver,)), "v-tz000001", active_reference=None)
    assert view.selected is not None
    assert view.selected.created_at == "2026-03-01 07:00:00 UTC"


# --- D. independent selected-versus-active state ---------------------------


def test_selected_and_active_are_independent_states() -> None:
    _, versions = _linear_family()
    # Active is the child; selected is the middle version. They must not couple.
    view = project_lineage(_result(versions=versions), "v-select01", active_reference="v-child001")
    assert view.selected is not None
    assert view.selected.is_selected is True
    assert view.selected.is_active is False
    assert view.selected.status_label == "Selected"
    child = view.children[0]
    assert child.is_active is True
    assert child.is_selected is False
    assert child.status_label == "Active"


def test_selected_can_also_be_active() -> None:
    _, versions = _linear_family()
    view = project_lineage(_result(versions=versions), "v-select01", active_reference="v-select01")
    assert view.selected is not None
    assert view.selected.is_selected is True
    assert view.selected.is_active is True
    assert view.selected.status_label == "Active"


# --- E. zero-parent root ----------------------------------------------------


def test_zero_parent_root_is_its_own_root() -> None:
    fam = new_family_id()
    vid = new_version_id()
    root_content = _cid(b"root")
    ver = _ver(
        "v-onlyroot",
        vid=vid,
        fid=fam,
        content=root_content,
        root_content=root_content,
        parent=None,
        created_by=CreationMechanism.ROOT_IMPORT,
    )
    view = project_lineage(_result(versions=(ver,)), "v-onlyroot", active_reference=None)
    assert view.state is LineageState.READY
    assert view.parent is None
    assert view.root is not None and view.root.short_version_id == "v-onlyroot"
    assert view.root.is_selected is True
    assert view.children == ()
    assert view.corrupt_relatives == 0


# --- F. unavailable parent / root ------------------------------------------


def test_derived_from_unmanaged_source_has_unavailable_parent_and_root() -> None:
    # First managed version of a family whose immediate parent is an unmanaged
    # source: ParentRef.version_id is None and no managed record equals the
    # root content. Both relations are unavailable, never corruption.
    fam = new_family_id()
    vid = new_version_id()
    src_content = _cid(b"unmanaged-source")
    ver = _ver(
        "v-firstman",
        vid=vid,
        fid=fam,
        content=_cid(b"processed"),
        root_content=src_content,
        parent=ParentRef(version_id=None, content_id=src_content),
    )
    view = project_lineage(_result(versions=(ver,)), "v-firstman", active_reference=None)
    assert view.state is LineageState.READY
    assert view.parent is None
    assert view.root is None
    assert view.corrupt_relatives == 0
    assert view.unavailable_relatives == 2


def test_dangling_parent_reference_is_unavailable_not_corrupt() -> None:
    fam = new_family_id()
    sel_vid = new_version_id()
    missing_parent = new_version_id()
    root_content = _cid(b"root")
    ver = _ver(
        "v-dangling1",
        vid=sel_vid,
        fid=fam,
        content=_cid(b"s"),
        root_content=root_content,
        parent=ParentRef(version_id=missing_parent, content_id=_cid(b"gone")),
    )
    view = project_lineage(_result(versions=(ver,)), "v-dangling1", active_reference=None)
    assert view.parent is None
    assert view.corrupt_relatives == 0
    assert view.unavailable_relatives >= 1


# --- G. exact duplicate quarantine from live discovery representation -------


def test_selected_reference_matching_duplicate_group_is_quarantined() -> None:
    dupe = _duplicate(short_version_id="v-dupe0001")
    view = project_lineage(_result(duplicates=(dupe,)), "v-dupe0001", active_reference=None)
    assert view.state is LineageState.SELECTED_AMBIGUOUS
    assert view.selected is None
    assert view.root is None
    assert view.parent is None
    assert view.children == ()


# --- H. ambiguous selected reference ---------------------------------------


def test_multiple_valid_matches_are_ambiguous() -> None:
    fam = new_family_id()
    root_content = _cid(b"root")
    a = _ver(
        "v-ambig001",
        vid=new_version_id(),
        fid=fam,
        content=_cid(b"a"),
        root_content=root_content,
        created_by=CreationMechanism.ROOT_IMPORT,
    )
    b = _ver(
        "v-ambig001",
        vid=new_version_id(),
        fid=fam,
        content=_cid(b"b"),
        root_content=root_content,
        created_by=CreationMechanism.ROOT_IMPORT,
    )
    view = project_lineage(_result(versions=(a, b)), "v-ambig001", active_reference=None)
    assert view.state is LineageState.SELECTED_AMBIGUOUS
    assert view.selected is None


def test_missing_selected_reference_is_unavailable() -> None:
    fam = new_family_id()
    ver = _ver(
        "v-present1",
        vid=new_version_id(),
        fid=fam,
        content=_cid(b"a"),
        root_content=_cid(b"a"),
        created_by=CreationMechanism.ROOT_IMPORT,
    )
    view = project_lineage(_result(versions=(ver,)), "v-absent999", active_reference=None)
    assert view.state is LineageState.SELECTED_UNAVAILABLE
    assert view.selected is None


# --- I. self-parent ---------------------------------------------------------


def test_self_parent_edge_is_corrupt() -> None:
    fam = new_family_id()
    vid = new_version_id()
    content = _cid(b"s")
    ver = _ver(
        "v-selfpar1",
        vid=vid,
        fid=fam,
        content=content,
        root_content=_cid(b"root"),
        parent=ParentRef(version_id=vid, content_id=content),
    )
    view = project_lineage(_result(versions=(ver,)), "v-selfpar1", active_reference=None)
    assert view.state is LineageState.CORRUPT_RELATION
    assert view.parent is None
    assert view.corrupt_relatives >= 1


# --- J. two-node and longer cycles -----------------------------------------


def test_two_node_cycle_drops_parent_edge_as_corrupt() -> None:
    fam = new_family_id()
    a_id, b_id = new_version_id(), new_version_id()
    a_content, b_content = _cid(b"a"), _cid(b"b")
    root_content = _cid(b"root")
    a = _ver(
        "v-cyc00a01",
        vid=a_id,
        fid=fam,
        content=a_content,
        root_content=root_content,
        parent=ParentRef(version_id=b_id, content_id=b_content),
    )
    b = _ver(
        "v-cyc00b01",
        vid=b_id,
        fid=fam,
        content=b_content,
        root_content=root_content,
        parent=ParentRef(version_id=a_id, content_id=a_content),
    )
    view = project_lineage(_result(versions=(a, b)), "v-cyc00a01", active_reference=None)
    assert view.state is LineageState.CORRUPT_RELATION
    assert view.parent is None
    assert view.corrupt_relatives >= 1


def test_three_node_cycle_drops_parent_edge_as_corrupt() -> None:
    fam = new_family_id()
    a_id, b_id, c_id = new_version_id(), new_version_id(), new_version_id()
    a_c, b_c, c_c = _cid(b"a"), _cid(b"b"), _cid(b"c")
    root_content = _cid(b"root")
    a = _ver(
        "v-tri00a01",
        vid=a_id,
        fid=fam,
        content=a_c,
        root_content=root_content,
        parent=ParentRef(version_id=b_id, content_id=b_c),
    )
    b = _ver(
        "v-tri00b01",
        vid=b_id,
        fid=fam,
        content=b_c,
        root_content=root_content,
        parent=ParentRef(version_id=c_id, content_id=c_c),
    )
    c = _ver(
        "v-tri00c01",
        vid=c_id,
        fid=fam,
        content=c_c,
        root_content=root_content,
        parent=ParentRef(version_id=a_id, content_id=a_c),
    )
    view = project_lineage(_result(versions=(a, b, c)), "v-tri00a01", active_reference=None)
    assert view.state is LineageState.CORRUPT_RELATION
    assert view.parent is None
    assert view.corrupt_relatives >= 1


# --- K. cross-family edge ---------------------------------------------------


def test_cross_family_parent_edge_is_corrupt() -> None:
    fam_a, fam_b = new_family_id(), new_family_id()
    parent_id = new_version_id()
    parent_content = _cid(b"p")
    root_content = _cid(b"root")
    parent = _ver(
        "v-xfampar1",
        vid=parent_id,
        fid=fam_b,
        content=parent_content,
        root_content=root_content,
        created_by=CreationMechanism.ROOT_IMPORT,
    )
    sel = _ver(
        "v-xfamsel1",
        vid=new_version_id(),
        fid=fam_a,
        content=_cid(b"s"),
        root_content=root_content,
        parent=ParentRef(version_id=parent_id, content_id=parent_content),
    )
    view = project_lineage(_result(versions=(parent, sel)), "v-xfamsel1", active_reference=None)
    assert view.state is LineageState.CORRUPT_RELATION
    assert view.parent is None
    assert view.corrupt_relatives >= 1


def test_cross_family_child_edge_is_excluded() -> None:
    fam_a, fam_b = new_family_id(), new_family_id()
    sel_id = new_version_id()
    root_content = _cid(b"root")
    sel = _ver(
        "v-selfam01",
        vid=sel_id,
        fid=fam_a,
        content=_cid(b"s"),
        root_content=root_content,
        parent=None,
        created_by=CreationMechanism.ROOT_IMPORT,
    )
    foreign_child = _ver(
        "v-foreign01",
        vid=new_version_id(),
        fid=fam_b,
        content=_cid(b"fc"),
        root_content=_cid(b"otherroot"),
        parent=ParentRef(version_id=sel_id, content_id=_cid(b"s")),
    )
    view = project_lineage(
        _result(versions=(sel, foreign_child)), "v-selfam01", active_reference=None
    )
    assert view.children == ()


def test_parent_content_mismatch_is_corrupt() -> None:
    fam = new_family_id()
    parent_id = new_version_id()
    root_content = _cid(b"root")
    parent = _ver(
        "v-mmpar001",
        vid=parent_id,
        fid=fam,
        content=_cid(b"real"),
        root_content=root_content,
        created_by=CreationMechanism.ROOT_IMPORT,
    )
    sel = _ver(
        "v-mmsel001",
        vid=new_version_id(),
        fid=fam,
        content=_cid(b"s"),
        root_content=root_content,
        parent=ParentRef(version_id=parent_id, content_id=_cid(b"claimed-different")),
    )
    view = project_lineage(_result(versions=(parent, sel)), "v-mmsel001", active_reference=None)
    assert view.parent is None
    assert view.corrupt_relatives >= 1


# --- L. safely proven root-content mismatch --------------------------------


def test_structural_root_content_mismatch_is_corrupt() -> None:
    fam = new_family_id()
    ver = _ver(
        "v-badroot1",
        vid=new_version_id(),
        fid=fam,
        content=_cid(b"actual"),
        root_content=_cid(b"declared-different"),
        parent=None,
        created_by=CreationMechanism.ROOT_IMPORT,
    )
    view = project_lineage(_result(versions=(ver,)), "v-badroot1", active_reference=None)
    assert view.state is LineageState.CORRUPT_RELATION
    assert view.root is None
    assert view.corrupt_relatives >= 1


# --- M. missing-root evidence not misclassified as corruption --------------


def test_missing_root_evidence_is_unavailable_not_corrupt() -> None:
    fam = new_family_id()
    parent_id = new_version_id()
    parent_content = _cid(b"p")
    root_content = _cid(b"root-not-present")
    parent = _ver(
        "v-mrpar001",
        vid=parent_id,
        fid=fam,
        content=parent_content,
        root_content=root_content,
        parent=ParentRef(version_id=None, content_id=root_content),
    )
    sel = _ver(
        "v-mrsel001",
        vid=new_version_id(),
        fid=fam,
        content=_cid(b"s"),
        root_content=root_content,
        parent=ParentRef(version_id=parent_id, content_id=parent_content),
    )
    view = project_lineage(_result(versions=(parent, sel)), "v-mrsel001", active_reference=None)
    assert view.state is LineageState.READY
    assert view.root is None
    assert view.corrupt_relatives == 0
    assert view.unavailable_relatives >= 1


# --- N. invalid max_nodes ---------------------------------------------------


@pytest.mark.parametrize("bad", [0, -1, 65, 1000, True])
def test_invalid_max_nodes_raises(bad: Any) -> None:
    result = _result()
    with pytest.raises(ValueError):
        project_lineage(result, "v-anything", active_reference=None, max_nodes=bad)


@pytest.mark.parametrize("good", [1, 32, 64])
def test_valid_max_nodes_accepted(good: int) -> None:
    fam = new_family_id()
    ver = _ver(
        "v-okmax001",
        vid=new_version_id(),
        fid=fam,
        content=_cid(b"a"),
        root_content=_cid(b"a"),
        parent=None,
        created_by=CreationMechanism.ROOT_IMPORT,
    )
    view = project_lineage(
        _result(versions=(ver,)), "v-okmax001", active_reference=None, max_nodes=good
    )
    assert view.selected is not None


# --- O. deterministic truncation -------------------------------------------


def _family_with_children(count: int) -> tuple[str, tuple[DiscoveredVersion, ...]]:
    fam = new_family_id()
    sel_id = new_version_id()
    sel_content = _cid(b"sel")
    sel = _ver(
        "v-parent99",
        vid=sel_id,
        fid=fam,
        content=sel_content,
        root_content=sel_content,
        parent=None,
        created_by=CreationMechanism.ROOT_IMPORT,
        label="parent",
    )
    children = tuple(
        _ver(
            f"v-kid{index:05d}",
            vid=new_version_id(),
            fid=fam,
            content=_cid(f"kid{index}".encode()),
            root_content=sel_content,
            parent=ParentRef(version_id=sel_id, content_id=sel_content),
            label=f"kid{index}",
        )
        for index in range(count)
    )
    return "v-parent99", (sel, *children)


def test_truncation_at_default_max_nodes() -> None:
    ref, versions = _family_with_children(70)
    view = project_lineage(_result(versions=versions), ref, active_reference=None)
    assert len(view.children) == MAX_LINEAGE_NODES
    assert view.truncated is True
    assert view.state is LineageState.TRUNCATED
    # Deterministic: the retained children are the first 64 in discovery order.
    expected = tuple(f"v-kid{index:05d}" for index in range(MAX_LINEAGE_NODES))
    assert tuple(child.short_version_id for child in view.children) == expected


def test_truncation_respects_custom_max_nodes() -> None:
    ref, versions = _family_with_children(8)
    view = project_lineage(_result(versions=versions), ref, active_reference=None, max_nodes=5)
    assert len(view.children) == 5
    assert view.truncated is True


def test_children_preserve_discovery_order() -> None:
    ref, versions = _family_with_children(4)
    view = project_lineage(_result(versions=versions), ref, active_reference=None)
    assert tuple(child.short_version_id for child in view.children) == (
        "v-kid00000",
        "v-kid00001",
        "v-kid00002",
        "v-kid00003",
    )


# --- P. no ancestry or descendant traversal beyond direct ------------------


def test_only_direct_relations_are_exposed() -> None:
    _, versions = _linear_family()
    view = project_lineage(_result(versions=versions), "v-select01", active_reference=None)
    # Direct parent is the parent, never the grandparent (root is content-resolved,
    # not a traversal step).
    assert view.parent is not None and view.parent.short_version_id == "v-parent01"
    # Direct children are only the immediate child; the grandchild is excluded.
    child_ids = {child.short_version_id for child in view.children}
    assert child_ids == {"v-child001"}
    assert "v-grand001" not in child_ids
    # The grandchild identity never appears anywhere in the view.
    assert "v-grand001" not in view.text_alternative


# --- Q. purity: no filesystem / session / durable access -------------------


def test_service_performs_no_io_or_session_access() -> None:
    source = _module_source()
    assert "session_state" not in source
    assert "import streamlit" not in source
    assert "open(" not in source
    assert "Path(" not in source
    names = _imported_names()
    assert not any(name.startswith("streamlit") for name in names)
    assert "os" not in names
    assert "data_quality_toolkit.adapters.ui.services.dataset_activation" not in names
    assert "data_quality_toolkit.adapters.ui.state.context" not in names
    assert "DatasetContext" not in names


def test_service_takes_no_session_argument() -> None:
    for name in inspect.signature(project_lineage).parameters:
        assert "session" not in name.lower()
        assert "state" not in name.lower()


def test_projection_does_not_mutate_the_result() -> None:
    _, versions = _linear_family()
    result = _result(versions=versions)
    before = result
    project_lineage(result, "v-select01", active_reference=None)
    assert result is before
    assert result.versions == versions


# --- R. privacy redaction ---------------------------------------------------


def _sensitive_tokens(versions: tuple[DiscoveredVersion, ...]) -> list[str]:
    tokens: list[str] = [_PRIVATE_DIR, "preprocessed/orders.dqtv.json", _VALID_SHA1]
    for version in versions:
        record = version.record
        tokens.extend(
            [
                record.version_id,
                record.version_id.replace("-", ""),
                record.family_id,
                record.family_id.replace("-", ""),
                record.content_id,
                record.root_content_id,
            ]
        )
    return tokens


def test_view_serialization_leaks_no_sensitive_values() -> None:
    _, versions = _linear_family()
    view = project_lineage(_result(versions=versions), "v-select01", active_reference="v-child001")
    serialized = repr(view) + " " + str(dataclasses.asdict(view)) + " " + view.text_alternative
    for token in _sensitive_tokens(versions):
        assert token not in serialized


def test_family_summary_uses_short_identifier_only() -> None:
    fam = new_family_id()
    ver = _ver(
        "v-fam00001",
        vid=new_version_id(),
        fid=fam,
        content=_cid(b"a"),
        root_content=_cid(b"a"),
        parent=None,
        created_by=CreationMechanism.ROOT_IMPORT,
    )
    view = project_lineage(_result(versions=(ver,)), "v-fam00001", active_reference=None)
    assert view.selected is not None
    summary = view.selected.family_summary
    assert summary.startswith("Family f-")
    assert fam not in summary
    assert fam.replace("-", "") not in summary


# --- S. no raw issues or exceptions ----------------------------------------


def test_discovery_issues_never_surface_in_lineage() -> None:
    fam = new_family_id()
    ver = _ver(
        "v-withissu",
        vid=new_version_id(),
        fid=fam,
        content=_cid(b"a"),
        root_content=_cid(b"a"),
        parent=None,
        created_by=CreationMechanism.ROOT_IMPORT,
    )
    result = _result(versions=(ver,), issues=(_issue(reason_code="CORRUPT_SECRET_MARKER"),))
    view = project_lineage(result, "v-withissu", active_reference=None)
    blob = repr(view) + " " + str(dataclasses.asdict(view)) + " " + view.text_alternative
    assert "CORRUPT_SECRET_MARKER" not in blob
    assert "issue-0001" not in blob
    assert "Traceback" not in blob


# --- T. normalized text alternative ----------------------------------------


def test_text_alternative_is_complete_and_safe() -> None:
    _, versions = _linear_family()
    view = project_lineage(_result(versions=versions), "v-select01", active_reference=None)
    text = view.text_alternative
    assert "Selected:" in text
    assert "Root:" in text
    assert "Direct parent:" in text
    assert "Direct children:" in text
    assert "\\" not in text  # no windows path fragment


def test_empty_text_alternative_matches_message() -> None:
    view = empty_lineage(state=LineageState.EMPTY)
    assert view.text_alternative == view.message
    assert view.selected is None
    assert view.children == ()


def test_truncation_reported_in_text_alternative() -> None:
    ref, versions = _family_with_children(70)
    view = project_lineage(_result(versions=versions), ref, active_reference=None)
    assert "not listed" in view.text_alternative


# --- U. no activation or recipe-reload mutation ----------------------------


def test_service_imports_no_activation_reopen_or_trust_symbols() -> None:
    names = _imported_names()
    for forbidden_module in (
        "data_quality_toolkit.adapters.ui.services.dataset_activation",
        "data_quality_toolkit.adapters.ui.services.managed_version_reopen",
        "data_quality_toolkit.adapters.ui.services.managed_trust",
    ):
        assert forbidden_module not in names
    for forbidden_symbol in (
        "activate_dataset_context",
        "reopen_managed_version",
        "commit_trust_root",
        "make_managed_context",
        "ensure_session_capability",
    ):
        assert forbidden_symbol not in names


def test_service_makes_no_activation_or_reopen_calls() -> None:
    tree = ast.parse(_module_source())
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    for forbidden in (
        "activate_dataset_context",
        "reopen_managed_version",
        "commit_trust_root",
        "make_managed_context",
    ):
        assert forbidden not in called


def test_blank_selection_returns_empty_state() -> None:
    view = project_lineage(_result(), "", active_reference=None)
    assert view.state is LineageState.EMPTY
    assert view.selected is None
