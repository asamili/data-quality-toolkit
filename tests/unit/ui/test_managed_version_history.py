"""Tests for the Start-page managed-version history surface.

Cover the pure safe-projection boundary
(:mod:`...services.managed_version_history`), the framework-thin renderer
(:mod:`...components.managed_version_history`), and the Start-page integration in
:func:`...pages.start._render_managed_version_history`.

Assertions are semantic: presence of safe meaning and absence of every sensitive
value (paths, filenames, full UUIDs, hashes, family UUIDs, raw exceptions, and
complete discovery objects). Since trusted reopen, the Set Active affordance is enabled for
valid rows and reports an explicit click as a privacy-safe action reference; the
renderer itself still performs no reopen, activation, or session-state mutation
(the explicit reopen workflow is covered by ``test_managed_version_reopen``).
"""

from __future__ import annotations

import ast
import dataclasses
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.components import managed_version_history as renderer_mod
from data_quality_toolkit.adapters.ui.components.managed_version_history import (
    SET_ACTIVE_HELP,
    render_managed_version_history,
    render_managed_version_lineage,
)
from data_quality_toolkit.adapters.ui.pages import start as start_mod
from data_quality_toolkit.adapters.ui.pages.start import (
    _derive_active_reference,
    _derive_selected_reference,
    _render_managed_version_history,
)
from data_quality_toolkit.adapters.ui.services import managed_version_history as service_mod
from data_quality_toolkit.adapters.ui.services.dataset_discovery import (
    DiscoveredVersion,
    DiscoveryIssue,
    DiscoveryResult,
    DuplicateGroup,
    InternalLocator,
    RecordStatus,
    RootStatus,
    VersionDisplay,
    discover_managed_versions,
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
    to_mapping,
)
from data_quality_toolkit.adapters.ui.services.managed_version_history import (
    MAX_DUPLICATE_ROWS,
    MAX_ISSUE_ROWS,
    MAX_VALID_ROWS,
    STATE_DIRECTORY_ABSENT,
    STATE_DIRECTORY_CHANGED,
    STATE_EMPTY,
    STATE_LIMIT_EXCEEDED,
    STATE_NO_WORKSPACE_ROOT,
    STATE_OK,
    STATE_PERMISSION_DENIED,
    STATE_ROOT_MISSING,
    STATE_UNSAFE_DIRECTORY,
    ManagedVersionDuplicateRow,
    ManagedVersionHistoryRow,
    ManagedVersionHistoryView,
    ManagedVersionIssueRow,
    blank_workspace_view,
    project_history,
)
from data_quality_toolkit.adapters.ui.services.managed_version_lineage import (
    LineageState,
    empty_lineage,
    project_lineage,
)
from data_quality_toolkit.adapters.ui.services.managed_version_reopen import ReopenOutcome
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT, SRC_WORKSPACE_ROOT

_VALID_SHA1 = "sha1:" + "0" * 40
_PRIVATE_DIR = r"C:\Users\example_user\private"


# --- direct-construction helpers (full control over sensitive fields) ------


def _record(**overrides: Any) -> DatasetVersionRecord:
    fields: dict[str, Any] = {
        "schema_version": 1,
        "version_id": new_version_id(),
        "family_id": new_family_id(),
        "root_content_id": content_id_from_bytes(b"root"),
        "content_id": content_id_from_bytes(b"data"),
        "dataset_id": _VALID_SHA1,
        "label": "orders v1",
        "file_relative_path": "preprocessed/data.csv",
        "format": DatasetFormat.CSV,
        "size_bytes": 16,
        "created_at": datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC),
        "created_by": CreationMechanism.ROOT_IMPORT,
    }
    fields.update(overrides)
    # A processed version must carry an immediate parent and a recipe; a root
    # import carries neither. Any caller-supplied parent is preserved, so parent
    # summaries under test are unaffected.
    if fields["created_by"] is CreationMechanism.PREPROCESS_RECIPE:
        fields.setdefault(
            "parent", ParentRef(version_id=None, content_id=content_id_from_bytes(b"p"))
        )
        fields.setdefault(
            "recipe", RecipeRef(digest="sha256:" + "0" * 64, relative_path="recipes/r.json")
        )
    return DatasetVersionRecord(**fields)


def _locator(record: DatasetVersionRecord) -> InternalLocator:
    return InternalLocator(
        sidecar_relative_posix="preprocessed/orders.dqtv.json",
        sidecar_resolved_path=rf"{_PRIVATE_DIR}\preprocessed\orders.dqtv.json",
        csv_resolved_path=rf"{_PRIVATE_DIR}\preprocessed\orders.csv",
        recipe_resolved_path=None,
        version_id=record.version_id,
        family_id=record.family_id,
        content_id=record.content_id,
        st_dev=1,
        st_ino=2,
    )


def _version(
    *,
    short_id: str = "v-1a2b3c4d",
    csv_status: str = "ARTIFACT_OK",
    recipe_status: str = "RECIPE_ABSENT",
    label: str = "orders v1",
    kind_label: str = "Imported root",
    **record_overrides: Any,
) -> DiscoveredVersion:
    record = _record(**record_overrides)
    display = VersionDisplay(
        label=label,
        short_version_id=short_id,
        status_label="Managed version",
        kind_label=kind_label,
    )
    return DiscoveredVersion(
        record=record,
        display=display,
        csv_status=csv_status,
        recipe_status=recipe_status,
        locator=_locator(record),
    )


def _issue(
    *,
    status: RecordStatus = RecordStatus.CORRUPT,
    reference: str = "issue-0001",
    label: str = "Unreadable version record",
    reason_code: str = "CORRUPT_JSON",
) -> DiscoveryIssue:
    return DiscoveryIssue(status=status, reference=reference, label=label, reason_code=reason_code)


def _duplicate(
    *,
    kind: str = "duplicate_identical",
    short_version_id: str = "v-1a2b3c4d",
    member_references: tuple[str, ...] = ("duplicate-0001", "duplicate-0002"),
) -> DuplicateGroup:
    record = _record()
    members = tuple(_locator(record) for _ in member_references)
    return DuplicateGroup(
        kind=kind,
        short_version_id=short_version_id,
        member_count=len(member_references),
        member_references=member_references,
        internal_members=members,
    )


def _result(
    *,
    versions: tuple[DiscoveredVersion, ...] = (),
    issues: tuple[DiscoveryIssue, ...] = (),
    duplicates: tuple[DuplicateGroup, ...] = (),
    root_status: RootStatus = RootStatus.OK,
    root_reason: str = "",
) -> DiscoveryResult:
    return DiscoveryResult(
        root_status=root_status,
        root_reason=root_reason,
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


# --- filesystem helpers (real discovery output) ----------------------------


def _ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _pp(root: Path) -> Path:
    pp = root / "preprocessed"
    pp.mkdir(parents=True, exist_ok=True)
    return pp


def _write_valid(root: Path, *, name: str, **overrides: Any) -> DatasetVersionRecord:
    (_pp(root) / f"{name}.csv").write_bytes(b"c\n1\n")
    record = _record(file_relative_path=f"preprocessed/{name}.csv", **overrides)
    (_pp(root) / f"{name}.dqtv.json").write_text(json.dumps(to_mapping(record)), encoding="utf-8")
    return record


# --- test double -----------------------------------------------------------


class RecorderSt:
    """Records renderer calls and mimics keyed widget behavior."""

    def __init__(self, session_state: dict[str, Any] | None = None) -> None:
        self.session_state = session_state if session_state is not None else {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.button_return = False

    def _rec(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def subheader(self, *args: Any, **kwargs: Any) -> None:
        self._rec("subheader", *args, **kwargs)

    def caption(self, *args: Any, **kwargs: Any) -> None:
        self._rec("caption", *args, **kwargs)

    def write(self, *args: Any, **kwargs: Any) -> None:
        self._rec("write", *args, **kwargs)

    def divider(self, *args: Any, **kwargs: Any) -> None:
        self._rec("divider", *args, **kwargs)

    def button(self, *args: Any, **kwargs: Any) -> bool:
        self._rec("button", *args, **kwargs)
        return self.button_return

    def success(self, *args: Any, **kwargs: Any) -> None:
        self._rec("success", *args, **kwargs)

    def error(self, *args: Any, **kwargs: Any) -> None:
        self._rec("error", *args, **kwargs)

    def calls_named(self, name: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        return [(args, kwargs) for kind, args, kwargs in self.calls if kind == name]

    def all_text(self) -> str:
        parts: list[str] = []
        for _, args, _ in self.calls:
            parts.extend(str(arg) for arg in args)
        return " ".join(parts)


# --- A. projected type shape and immutability ------------------------------

_PROJECTED_TYPES = (
    ManagedVersionHistoryRow,
    ManagedVersionIssueRow,
    ManagedVersionDuplicateRow,
    ManagedVersionHistoryView,
)

_ALLOWED_FIELD_TYPES = {
    "str",
    "int",
    "bool",
    "tuple[str, ...]",
    "tuple[ManagedVersionHistoryRow, ...]",
    "tuple[ManagedVersionIssueRow, ...]",
    "tuple[ManagedVersionDuplicateRow, ...]",
}


def test_projected_types_expose_only_primitive_ui_safe_fields() -> None:
    for cls in _PROJECTED_TYPES:
        for field in dataclasses.fields(cls):
            assert field.type in _ALLOWED_FIELD_TYPES, (cls.__name__, field.name, field.type)
        names = {field.name for field in dataclasses.fields(cls)}
        # No record, locator, or internal-member field ever appears.
        assert not names & {"record", "locator", "internal_members", "versions", "issues"}


def test_projected_types_are_frozen() -> None:
    view = project_history(_result(versions=(_version(),)))
    with pytest.raises(FrozenInstanceError):
        view.state = "x"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        view.valid_rows[0].label = "x"  # type: ignore[misc]


def test_duplicate_row_has_no_internal_member_attribute() -> None:
    view = project_history(_result(duplicates=(_duplicate(),)))
    row = view.duplicate_rows[0]
    assert not hasattr(row, "internal_members")
    assert not hasattr(row, "locator")


# --- B. valid version row projection ---------------------------------------


def test_valid_row_carries_safe_display_fields() -> None:
    view = project_history(_result(versions=(_version(label="orders", short_id="v-abcd1234"),)))
    row = view.valid_rows[0]
    assert row.label == "orders"
    assert row.short_version_id == "v-abcd1234"
    assert row.action_label == "Set Active"
    assert row.confirmation_timestamp == "2026-07-16 12:00:00 UTC"


def test_family_summary_uses_short_identifier_only() -> None:
    fam = new_family_id()
    view = project_history(_result(versions=(_version(family_id=fam),)))
    summary = view.valid_rows[0].family_summary
    assert summary.startswith("Family f-")
    assert len("Family f-") + 8 == len(summary)
    assert fam not in summary
    assert fam.replace("-", "") not in summary


def test_root_version_has_root_parent_summary() -> None:
    view = project_history(_result(versions=(_version(parent=None),)))
    assert view.valid_rows[0].parent_summary == "Root version"


def test_child_version_shows_short_parent_summary() -> None:
    parent_vid = new_version_id()
    parent = ParentRef(version_id=parent_vid, content_id=content_id_from_bytes(b"p"))
    view = project_history(
        _result(versions=(_version(created_by=CreationMechanism.PREPROCESS_RECIPE, parent=parent),))
    )
    summary = view.valid_rows[0].parent_summary
    assert summary.startswith("Parent v-")
    assert len("Parent v-") + 8 == len(summary)
    assert parent_vid not in summary


def test_unmanaged_parent_is_root_version() -> None:
    parent = ParentRef(version_id=None, content_id=content_id_from_bytes(b"p"))
    view = project_history(
        _result(versions=(_version(created_by=CreationMechanism.PREPROCESS_RECIPE, parent=parent),))
    )
    assert view.valid_rows[0].parent_summary == "Root version"


def test_creation_mechanism_labels() -> None:
    root = project_history(_result(versions=(_version(created_by=CreationMechanism.ROOT_IMPORT),)))
    proc = project_history(
        _result(versions=(_version(created_by=CreationMechanism.PREPROCESS_RECIPE),))
    )
    assert root.valid_rows[0].creation_mechanism == "Root import"
    assert proc.valid_rows[0].creation_mechanism == "Preprocess recipe"


def test_csv_and_recipe_availability_labels() -> None:
    available = project_history(
        _result(versions=(_version(csv_status="ARTIFACT_OK", recipe_status="ARTIFACT_OK"),))
    )
    absent = project_history(
        _result(versions=(_version(csv_status="ARTIFACT_OK", recipe_status="RECIPE_ABSENT"),))
    )
    assert available.valid_rows[0].csv_availability == "CSV available"
    assert available.valid_rows[0].recipe_availability == "Recipe available"
    assert absent.valid_rows[0].recipe_availability == "No recipe"


def test_confirmation_timestamp_normalized_to_utc() -> None:
    from datetime import timedelta, timezone

    plus_two = timezone(timedelta(hours=2))
    view = project_history(
        _result(versions=(_version(created_at=datetime(2026, 3, 1, 9, 0, 0, tzinfo=plus_two)),))
    )
    # 09:00 +02:00 normalizes to 07:00 UTC.
    assert view.valid_rows[0].confirmation_timestamp == "2026-03-01 07:00:00 UTC"


# --- C. ordering and bounds ------------------------------------------------


def test_valid_ordering_is_preserved_from_discovery(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="old", created_at=datetime(2026, 1, 1, tzinfo=UTC), label="old")
    _write_valid(root, name="new", created_at=datetime(2026, 6, 1, tzinfo=UTC), label="new")
    view = project_history(discover_managed_versions(str(root)))
    assert [row.label for row in view.valid_rows] == ["new", "old"]


def test_valid_rows_capped_with_omitted_count() -> None:
    versions = tuple(_version(label=f"v{i}") for i in range(25))
    view = project_history(_result(versions=versions))
    assert len(view.valid_rows) == MAX_VALID_ROWS
    assert view.valid_total == 25
    assert view.valid_omitted == 5


def test_issue_rows_capped_with_omitted_count() -> None:
    issues = tuple(_issue(reference=f"issue-{i:04d}") for i in range(25))
    view = project_history(_result(issues=issues))
    assert len(view.issue_rows) == MAX_ISSUE_ROWS
    assert view.issue_total == 25
    assert view.issue_omitted == 5


def test_duplicate_rows_capped_with_omitted_count() -> None:
    duplicates = tuple(_duplicate() for _ in range(12))
    view = project_history(_result(duplicates=duplicates))
    assert len(view.duplicate_rows) == MAX_DUPLICATE_ROWS
    assert view.duplicate_total == 12
    assert view.duplicate_omitted == 2


def test_custom_bounds_are_respected() -> None:
    versions = tuple(_version(label=f"v{i}") for i in range(3))
    view = project_history(_result(versions=versions), max_valid_rows=2)
    assert len(view.valid_rows) == 2
    assert view.valid_omitted == 1


def test_repeated_projection_is_deterministic() -> None:
    result = _result(versions=(_version(),), issues=(_issue(),), duplicates=(_duplicate(),))
    assert project_history(result) == project_history(result)


# --- D. issue and duplicate projection -------------------------------------


@pytest.mark.parametrize(
    "status,expected_label",
    [
        (RecordStatus.CORRUPT, "Corrupt record"),
        (RecordStatus.UNSUPPORTED, "Unsupported record"),
        (RecordStatus.UNAVAILABLE, "Unavailable artifact"),
    ],
)
def test_issue_status_labels(status: RecordStatus, expected_label: str) -> None:
    view = project_history(
        _result(issues=(_issue(status=status, label="Unreadable version record"),))
    )
    row = view.issue_rows[0]
    assert row.status_label == expected_label
    assert row.reference == "issue-0001"
    assert row.label == "Unreadable version record"


def test_issue_reason_code_passes_through_generic() -> None:
    view = project_history(_result(issues=(_issue(reason_code="ARTIFACT_VANISHED"),)))
    assert view.issue_rows[0].reason_code == "ARTIFACT_VANISHED"


def test_identical_and_conflicting_duplicate_labels() -> None:
    identical = project_history(_result(duplicates=(_duplicate(kind="duplicate_identical"),)))
    conflicting = project_history(_result(duplicates=(_duplicate(kind="duplicate_conflict"),)))
    assert identical.duplicate_rows[0].kind_label == "Identical duplicate"
    assert conflicting.duplicate_rows[0].kind_label == "Conflicting duplicate"


def test_duplicate_row_exposes_only_safe_fields() -> None:
    view = project_history(
        _result(
            duplicates=(
                _duplicate(
                    short_version_id="v-1a2b3c4d",
                    member_references=("duplicate-0001", "duplicate-0002"),
                ),
            )
        )
    )
    row = view.duplicate_rows[0]
    assert row.short_version_id == "v-1a2b3c4d"
    assert row.member_count == 2
    assert row.member_references == ("duplicate-0001", "duplicate-0002")
    assert row.status_label == "Quarantined"


# --- E. root / discovery state projection ----------------------------------


@pytest.mark.parametrize(
    "root_status,root_reason,expected_state",
    [
        (RootStatus.OK, "DISCOVERY_DIR_ABSENT", STATE_DIRECTORY_ABSENT),
        (RootStatus.OK, "", STATE_EMPTY),
        (RootStatus.MISSING, "ROOT_MISSING", STATE_ROOT_MISSING),
        (RootStatus.PERMISSION_DENIED, "ROOT_PERMISSION_DENIED", STATE_PERMISSION_DENIED),
        (
            RootStatus.UNSAFE_DISCOVERY_DIRECTORY,
            "DISCOVERY_DIR_OUTSIDE_ROOT",
            STATE_UNSAFE_DIRECTORY,
        ),
        (RootStatus.DIRECTORY_CHANGED, "DISCOVERY_DIR_PRECHECK_REPLACED", STATE_DIRECTORY_CHANGED),
        (RootStatus.LIMIT_EXCEEDED, "LIMIT_EXCEEDED", STATE_LIMIT_EXCEEDED),
    ],
)
def test_root_state_projection(
    root_status: RootStatus, root_reason: str, expected_state: str
) -> None:
    view = project_history(_result(root_status=root_status, root_reason=root_reason))
    assert view.state == expected_state
    assert view.scanned is True
    # The message never leaks a path or raw exception.
    assert "\\" not in view.message
    assert ":" not in view.message
    assert view.valid_rows == ()


def test_populated_ok_state() -> None:
    view = project_history(_result(versions=(_version(),)))
    assert view.state == STATE_OK


def test_absent_discovery_dir_shows_safe_empty_state(tmp_path: Path) -> None:
    root = _ws(tmp_path)  # no preprocessed directory
    view = project_history(discover_managed_versions(str(root)))
    assert view.state == STATE_DIRECTORY_ABSENT
    assert view.valid_rows == ()
    assert str(root) not in view.message


def test_blank_workspace_view_does_not_scan() -> None:
    view = blank_workspace_view()
    assert view.state == STATE_NO_WORKSPACE_ROOT
    assert view.scanned is False
    assert view.valid_rows == ()
    assert view.issue_rows == ()
    assert view.duplicate_rows == ()


# --- F. privacy: repr / asdict never leak sensitive values -----------------


def _sensitive_tokens(record: DatasetVersionRecord) -> list[str]:
    return [
        record.version_id,
        record.version_id.replace("-", ""),
        record.family_id,
        record.family_id.replace("-", ""),
        record.content_id,
        record.root_content_id,
        record.dataset_id,
        _PRIVATE_DIR,
        "preprocessed/orders.dqtv.json",
    ]


def test_repr_and_asdict_contain_no_sensitive_values() -> None:
    version = _version()
    duplicate = _duplicate()
    view = project_history(
        _result(versions=(version,), issues=(_issue(),), duplicates=(duplicate,))
    )
    serialized = repr(view) + " " + str(dataclasses.asdict(view))
    for token in _sensitive_tokens(version.record):
        assert token not in serialized
    # Duplicate internal members must not have leaked either.
    for member in duplicate.internal_members:
        assert member.sidecar_resolved_path not in serialized
        assert member.version_id not in serialized


def test_issue_row_never_exposes_untrusted_label() -> None:
    view = project_history(
        _result(issues=(_issue(label="Unreadable version record", reason_code="CORRUPT_SCHEMA"),))
    )
    row = view.issue_rows[0]
    combined = repr(row) + " " + str(dataclasses.asdict(row))
    assert "SECRET" not in combined
    assert row.label == "Unreadable version record"


def test_path_like_label_stays_basename_via_discovery_contract(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a", label=rf"{_PRIVATE_DIR}\leaky.csv")
    view = project_history(discover_managed_versions(str(root)))
    label = view.valid_rows[0].label
    assert label == "leaky.csv"
    assert _PRIVATE_DIR not in label


# --- G. renderer: explicit Set Active action, no mutation -------------------


def test_renderer_renders_section_and_enabled_set_active() -> None:
    view = project_history(_result(versions=(_version(label="orders"),)))
    st = RecorderSt()
    render_managed_version_history(st, view)

    subheaders = [args[0] for args, _ in st.calls_named("subheader")]
    assert "Managed version history" in subheaders

    buttons = st.calls_named("button")
    assert len(buttons) == 1
    args, kwargs = buttons[0]
    assert args[0] == "Set Active"
    # Reopen: the action is enabled and keyed only by the privacy-safe short id.
    assert kwargs.get("disabled", False) is False
    assert kwargs["key"] == f"mvh_set_active_{view.valid_rows[0].short_version_id}"
    assert kwargs["help"] == SET_ACTIVE_HELP


def test_renderer_makes_no_state_mutation_even_when_button_returns_true() -> None:
    view = project_history(_result(versions=(_version(),)))
    st = RecorderSt(session_state={})
    st.button_return = True  # simulate a "click"; the renderer only reports it
    reference = render_managed_version_history(st, view)
    # The renderer emits only the privacy-safe reference and mutates nothing.
    assert reference == view.valid_rows[0].short_version_id
    assert st.session_state == {}


def test_renderer_shows_issue_and_duplicate_sections() -> None:
    view = project_history(
        _result(
            versions=(_version(),),
            issues=(_issue(reference="issue-0007"),),
            duplicates=(_duplicate(short_version_id="v-99998888"),),
        )
    )
    st = RecorderSt()
    render_managed_version_history(st, view)
    text = st.all_text()
    assert "issue-0007" in text
    assert "duplicate-0001" in text
    assert "v-99998888" in text


def test_renderer_reports_omitted_counts() -> None:
    versions = tuple(_version(label=f"v{i}") for i in range(25))
    view = project_history(_result(versions=versions))
    st = RecorderSt()
    render_managed_version_history(st, view)
    assert "5 more versions not shown" in st.all_text()


def test_renderer_blank_view_renders_prompt_only() -> None:
    st = RecorderSt()
    render_managed_version_history(st, blank_workspace_view())
    assert st.calls_named("button") == []
    assert "Enter a Workspace Root" in st.all_text()


# --- H. Start-page integration --------------------------------------------


def _capture_render(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    captured: list[Any] = []

    def fake_render(st: Any, view: Any) -> None:
        captured.append(view)

    monkeypatch.setattr(start_mod, "render_managed_version_history", fake_render)
    return captured


def test_blank_workspace_root_performs_no_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_discover(workspace_root: str, **kwargs: Any) -> Any:
        calls.append(workspace_root)
        raise AssertionError("discovery must not run for a blank workspace root")

    monkeypatch.setattr(start_mod, "discover_managed_versions", fake_discover)
    captured = _capture_render(monkeypatch)

    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: "   "}
    _render_managed_version_history(RecorderSt(state), state)

    assert calls == []
    assert isinstance(captured[0], ManagedVersionHistoryView)
    assert captured[0].scanned is False
    assert captured[0].state == STATE_NO_WORKSPACE_ROOT


def test_valid_workspace_invokes_discovery_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a", label="orders")
    calls: list[str] = []
    real = discover_managed_versions

    def counting(workspace_root: str, **kwargs: Any) -> Any:
        calls.append(workspace_root)
        return real(workspace_root, **kwargs)

    monkeypatch.setattr(start_mod, "discover_managed_versions", counting)
    captured = _capture_render(monkeypatch)

    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    _render_managed_version_history(RecorderSt(state), state)

    assert len(calls) == 1
    assert isinstance(captured[0], ManagedVersionHistoryView)
    assert captured[0].valid_total == 1


def test_start_converts_before_rendering_and_stores_no_discovery_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")
    captured = _capture_render(monkeypatch)

    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    _render_managed_version_history(RecorderSt(state), state)

    # Renderer receives only the safe projected view.
    assert isinstance(captured[0], ManagedVersionHistoryView)
    # No complete discovery object is stored anywhere in session state.
    forbidden = (DiscoveryResult, DiscoveredVersion, DuplicateGroup, InternalLocator)
    for value in state.values():
        assert not isinstance(value, forbidden)


def test_history_section_never_activates_a_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    # No render monkeypatch: exercise the real renderer end-to-end.
    _render_managed_version_history(RecorderSt(state), state)
    # No automatic restoration/activation: the active pointer is never written.
    assert DATASET_CONTEXT not in state


# --- I. static guarantees --------------------------------------------------


def _module_source(module: Any) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")


def _imported_names(module: Any) -> set[str]:
    tree = ast.parse(_module_source(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(alias.name for alias in node.names)
    return names


@pytest.mark.parametrize("module", [service_mod, renderer_mod])
def test_new_modules_do_not_import_activation_or_context(module: Any) -> None:
    names = _imported_names(module)
    assert "data_quality_toolkit.adapters.ui.services.dataset_activation" not in names
    assert "activate_dataset_context" not in names
    assert "data_quality_toolkit.adapters.ui.state.context" not in names
    assert "DatasetContext" not in names


@pytest.mark.parametrize("module", [service_mod, renderer_mod])
def test_new_modules_construct_no_dataset_context(module: Any) -> None:
    assert "DatasetContext(" not in _module_source(module)


def test_renderer_writes_no_session_state_and_serializes_no_discovery() -> None:
    source = _module_source(renderer_mod)
    assert "session_state" not in source
    assert "asdict" not in source
    assert "DiscoveryResult" not in source
    assert "import streamlit" not in source


def test_service_does_not_import_streamlit_or_session_state() -> None:
    names = _imported_names(service_mod)
    assert not any(name.startswith("streamlit") for name in names)
    assert "streamlit" not in names
    source = _module_source(service_mod)
    assert "session_state" not in source


# --- J. Start-page direct-lineage integration ------------------------------


def test_lineage_renderer_lives_in_the_existing_component_module() -> None:
    # The direct-lineage renderer is added to the existing component module, not a
    # new page or component hierarchy.
    assert hasattr(renderer_mod, "render_managed_version_lineage")
    assert render_managed_version_lineage.__module__ == renderer_mod.__name__


def test_start_renders_direct_lineage_section(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a", label="orders")
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    st = RecorderSt(state)
    _render_managed_version_history(st, state)
    text = st.all_text()
    assert "Direct lineage" in text
    assert "Lineage summary:" in text


def test_start_lineage_section_never_activates(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    _render_managed_version_history(RecorderSt(state), state)
    # Rendering (including deriving the active reference) writes no active pointer.
    assert DATASET_CONTEXT not in state


def test_start_history_and_lineage_add_no_session_state_key(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    before = set(state)
    _render_managed_version_history(RecorderSt(state), state)
    assert set(state) == before


def test_blank_workspace_renders_empty_lineage(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Any] = []

    def fake_lineage(st: Any, lineage: Any) -> None:
        captured.append(lineage)

    monkeypatch.setattr(start_mod, "render_managed_version_lineage", fake_lineage)
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: "   "}
    _render_managed_version_history(RecorderSt(state), state)
    assert captured and captured[0].state is LineageState.EMPTY
    assert captured[0].selected is None


def test_active_reference_derived_independently_from_context() -> None:
    active_vid = new_version_id()
    active = _version(short_id="v-active01", version_id=active_vid)
    other = _version(short_id="v-other001", version_id=new_version_id())
    result = _result(versions=(other, active))
    context = DatasetContext(
        source_path="x",
        display_name="x",
        size_bytes=1,
        modified_ns=1,
        managed=True,
        version_id=active_vid,
    )
    state: dict[str, Any] = {DATASET_CONTEXT: context}
    assert _derive_active_reference(state, result) == "v-active01"
    # Selection defaults to the active version when present, else the top row.
    assert _derive_selected_reference(result, "v-active01") == "v-active01"
    assert _derive_selected_reference(result, None) == "v-other001"


def test_unmanaged_or_absent_context_yields_no_active_reference() -> None:
    other = _version(short_id="v-other001", version_id=new_version_id())
    result = _result(versions=(other,))
    unmanaged = DatasetContext(source_path="x", display_name="x", size_bytes=1, modified_ns=1)
    assert _derive_active_reference({DATASET_CONTEXT: unmanaged}, result) is None
    assert _derive_active_reference({}, result) is None


def test_active_and_selected_labels_can_differ() -> None:
    active = _version(short_id="v-active01", version_id=new_version_id())
    other = _version(short_id="v-other001", version_id=new_version_id())
    result = _result(versions=(other, active))
    view = project_lineage(result, "v-other001", active_reference="v-active01")
    assert view.selected is not None
    assert view.selected.short_version_id == "v-other001"
    assert view.selected.is_selected is True
    assert view.selected.is_active is False


def test_reopen_remains_the_only_activation_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")
    calls: list[str] = []

    def fake_reopen(session_state: Any, workspace_root: str, reference: str, **kwargs: Any) -> Any:
        calls.append(reference)
        return ReopenOutcome(
            status="reopened", message="Managed version reopened.", reason_code="REOPENED"
        )

    monkeypatch.setattr(start_mod, "reopen_managed_version", fake_reopen)
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    st = RecorderSt(state)
    st.button_return = True  # explicit Set Active click
    _render_managed_version_history(st, state)
    # Exactly one explicit reopen from the click; the lineage section adds none.
    assert len(calls) == 1
    assert "Direct lineage" in st.all_text()


def test_lineage_renderer_shows_safe_corrupt_messaging() -> None:
    vid = new_version_id()
    corrupt = _version(
        short_id="v-corrupt1",
        version_id=vid,
        parent=ParentRef(version_id=vid, content_id=content_id_from_bytes(b"data")),
    )
    view = project_lineage(_result(versions=(corrupt,)), "v-corrupt1", active_reference=None)
    st = RecorderSt()
    render_managed_version_lineage(st, view)
    text = st.all_text()
    assert "could not be verified" in text or "unavailable" in text
    assert vid not in text


def test_start_lineage_leaks_no_sensitive_values(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_valid(root, name="a", label="orders")
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    st = RecorderSt(state)
    _render_managed_version_history(st, state)
    text = st.all_text()
    for token in (
        record.version_id,
        record.family_id,
        record.content_id,
        record.root_content_id,
        str(root),
    ):
        assert token not in text


def test_empty_lineage_view_renders_prompt_and_text_alternative() -> None:
    st = RecorderSt()
    render_managed_version_lineage(st, empty_lineage(state=LineageState.EMPTY))
    text = st.all_text()
    assert "Direct lineage" in text
    assert "Lineage summary:" in text
    assert st.calls_named("button") == []
