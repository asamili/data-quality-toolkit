"""Tests for the explicit managed-version reopen workflow.

Cover the renderer's explicit enabled action and privacy-safe action reference,
the dedicated reopen service (:mod:`...services.managed_version_reopen`) —
fresh resolution, valid-only selection, artifact revalidation, confinement and
race handling, atomic state transition through the existing activation
contract — and the Start-page integration. Every workspace is a pytest
``tmp_path``; no real operator workspace, CSV, or recipe is ever touched, and
no recipe is parsed or executed.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.components.managed_version_history import (
    render_managed_version_history,
)
from data_quality_toolkit.adapters.ui.pages import start as start_mod
from data_quality_toolkit.adapters.ui.pages.start import _render_managed_version_history
from data_quality_toolkit.adapters.ui.services import dataset_activation
from data_quality_toolkit.adapters.ui.services import managed_frame_loader as _mfl
from data_quality_toolkit.adapters.ui.services import managed_version_reopen as reopen_mod
from data_quality_toolkit.adapters.ui.services.dataset_activation import (
    activate_dataset_context,
)
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
    RecipeRef,
    content_id_from_bytes,
    new_family_id,
    new_version_id,
    to_mapping,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    MANAGED_TRUST_STATE_KEY,
    SessionCapability,
    TrustAuthority,
    current_generation,
    get_valid_trust_root,
    peek_session_capability,
    resolve_trust_authority,
)
from data_quality_toolkit.adapters.ui.services.managed_version_history import (
    MAX_VALID_ROWS,
    project_history,
)
from data_quality_toolkit.adapters.ui.services.managed_version_reopen import (
    STATUS_ALREADY_ACTIVE,
    STATUS_FAILED,
    STATUS_REOPENED,
    STATUS_REQUIRES_REPAIR,
    STATUS_STALE,
    STATUS_UNAVAILABLE,
    ReopenOutcome,
    reopen_managed_version,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import (
    BIV_COL1,
    DATASET_CONTEXT,
    SRC_WORKSPACE_ROOT,
)

_VALID_SHA1 = "sha1:" + "0" * 40
_RECIPE_DIGEST = "sha256:" + "0" * 64
_CSV_BYTES = b"c\n1\n2\n"
_RECIPE_BYTES = b'{"steps": []}'
_PRIVATE_DIR = r"C:\Users\example_user\private"

_SENSITIVE_TYPES = (
    DiscoveryResult,
    DiscoveredVersion,
    DuplicateGroup,
    InternalLocator,
    DatasetVersionRecord,
)


# --- record / workspace helpers --------------------------------------------


def _record(**overrides: Any) -> DatasetVersionRecord:
    fields: dict[str, Any] = {
        "schema_version": 1,
        "version_id": new_version_id(),
        "family_id": new_family_id(),
        "root_content_id": content_id_from_bytes(b"root"),
        "content_id": content_id_from_bytes(b"data"),
        "dataset_id": _VALID_SHA1,
        "label": "orders v1",
        "file_relative_path": "preprocessed/orders.csv",
        "format": DatasetFormat.CSV,
        "size_bytes": len(_CSV_BYTES),
        "created_at": datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC),
        "created_by": CreationMechanism.ROOT_IMPORT,
    }
    fields.update(overrides)
    return DatasetVersionRecord(**fields)


def _short_ref(record: DatasetVersionRecord) -> str:
    return "v-" + uuid.UUID(record.version_id).hex[:8]


def _ws(tmp_path: Path, name: str = "ws") -> Path:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _pp(root: Path) -> Path:
    pp = root / "preprocessed"
    pp.mkdir(parents=True, exist_ok=True)
    return pp


def _write_version(
    root: Path,
    *,
    name: str = "orders",
    csv_bytes: bytes = _CSV_BYTES,
    with_recipe: bool = False,
    recipe_bytes: bytes = _RECIPE_BYTES,
    **overrides: Any,
) -> DatasetVersionRecord:
    pp = _pp(root)
    (pp / f"{name}.csv").write_bytes(csv_bytes)
    fields: dict[str, Any] = {
        "file_relative_path": f"preprocessed/{name}.csv",
        "size_bytes": len(csv_bytes),
        "label": name,
    }
    if with_recipe:
        (pp / f"{name}.recipe.json").write_bytes(recipe_bytes)
        fields["recipe"] = RecipeRef(
            digest=_RECIPE_DIGEST, relative_path=f"preprocessed/{name}.recipe.json"
        )
    fields.update(overrides)
    record = _record(**fields)
    (pp / f"{name}.dqtv.json").write_text(json.dumps(to_mapping(record)), encoding="utf-8")
    return record


def _legacy_context() -> DatasetContext:
    return DatasetContext(
        source_path=r"C:\data\prior.csv",
        display_name="prior.csv",
        size_bytes=10,
        modified_ns=1,
    )


# --- synthetic discovery-result helpers ------------------------------------


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
    **record_overrides: Any,
) -> DiscoveredVersion:
    record = _record(**record_overrides)
    display = VersionDisplay(
        label=label,
        short_version_id=short_id,
        status_label="Managed version",
        kind_label="Imported root",
    )
    return DiscoveredVersion(
        record=record,
        display=display,
        csv_status=csv_status,
        recipe_status=recipe_status,
        locator=_locator(record),
    )


def _issue() -> DiscoveryIssue:
    return DiscoveryIssue(
        status=RecordStatus.CORRUPT,
        reference="issue-0001",
        label="Unreadable version record",
        reason_code="CORRUPT_JSON",
    )


def _duplicate(short_version_id: str = "v-99998888") -> DuplicateGroup:
    record = _record()
    return DuplicateGroup(
        kind="duplicate_identical",
        short_version_id=short_version_id,
        member_count=2,
        member_references=("duplicate-0001", "duplicate-0002"),
        internal_members=(_locator(record), _locator(record)),
    )


def _result(
    *,
    versions: tuple[DiscoveredVersion, ...] = (),
    issues: tuple[DiscoveryIssue, ...] = (),
    duplicates: tuple[DuplicateGroup, ...] = (),
    root_status: RootStatus = RootStatus.OK,
    root_reason: str = "",
    result_complete: bool = True,
    reopen_safe: bool = True,
) -> DiscoveryResult:
    return DiscoveryResult(
        root_status=root_status,
        root_reason=root_reason,
        enumeration_complete=result_complete,
        result_complete=result_complete,
        reopen_safe=reopen_safe,
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


def _frozen_discover(result: DiscoveryResult) -> Any:
    def discover(workspace_root: str, **kwargs: Any) -> DiscoveryResult:
        return result

    return discover


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


# --- test double -----------------------------------------------------------


class RecorderSt:
    """Records renderer calls; a button "clicks" when its key was pressed."""

    def __init__(self, session_state: dict[str, Any] | None = None) -> None:
        self.session_state = session_state if session_state is not None else {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.pressed_keys: set[str] = set()

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

    def success(self, *args: Any, **kwargs: Any) -> None:
        self._rec("success", *args, **kwargs)

    def error(self, *args: Any, **kwargs: Any) -> None:
        self._rec("error", *args, **kwargs)

    def info(self, *args: Any, **kwargs: Any) -> None:
        self._rec("info", *args, **kwargs)

    def warning(self, *args: Any, **kwargs: Any) -> None:
        self._rec("warning", *args, **kwargs)

    def button(self, *args: Any, **kwargs: Any) -> bool:
        self._rec("button", *args, **kwargs)
        return kwargs.get("key") in self.pressed_keys

    def calls_named(self, name: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        return [(args, kwargs) for kind, args, kwargs in self.calls if kind == name]

    def all_text(self) -> str:
        parts: list[str] = []
        for _, args, _ in self.calls:
            parts.extend(str(arg) for arg in args)
        return " ".join(parts)


def _button_keys(st: RecorderSt) -> list[str]:
    return [str(kwargs.get("key", "")) for _, kwargs in st.calls_named("button")]


# --- A. UI and privacy ------------------------------------------------------


def test_valid_row_exposes_one_enabled_explicit_action(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    view = project_history(discover_managed_versions(str(root)))
    st = RecorderSt()
    render_managed_version_history(st, view)

    buttons = st.calls_named("button")
    assert len(buttons) == 1
    args, kwargs = buttons[0]
    assert args[0] == "Set Active"
    assert kwargs.get("disabled", False) is False
    assert kwargs["key"] == f"mvh_set_active_{_short_ref(record)}"


def test_issue_duplicate_and_omitted_rows_expose_no_action() -> None:
    versions = tuple(_version(short_id=f"v-{i:08x}") for i in range(MAX_VALID_ROWS + 5))
    view = project_history(
        _result(versions=versions, issues=(_issue(),), duplicates=(_duplicate(),))
    )
    st = RecorderSt()
    render_managed_version_history(st, view)

    keys = _button_keys(st)
    # One action per *displayed* valid row only; omitted/issue/duplicate rows none.
    assert len(keys) == MAX_VALID_ROWS
    expected = {f"mvh_set_active_{row.short_version_id}" for row in view.valid_rows}
    assert set(keys) == expected
    assert not any("issue" in key or "duplicate" in key for key in keys)


def test_no_click_means_no_reopen_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _ws(tmp_path)
    _write_version(root)
    calls: list[Any] = []
    monkeypatch.setattr(
        start_mod,
        "reopen_managed_version",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    _render_managed_version_history(RecorderSt(state), state)
    assert calls == []


def test_one_click_means_exactly_one_reopen_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    calls: list[Any] = []

    def fake_reopen(*args: Any, **kwargs: Any) -> ReopenOutcome:
        calls.append((args, kwargs))
        return ReopenOutcome(STATUS_REOPENED, "Managed version reopened.", "REOPENED")

    monkeypatch.setattr(start_mod, "reopen_managed_version", fake_reopen)
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    st = RecorderSt(state)
    st.pressed_keys.add(f"mvh_set_active_{_short_ref(record)}")
    _render_managed_version_history(st, state)

    assert len(calls) == 1
    success_args = [args[0] for args, _ in st.calls_named("success")]
    assert success_args == ["Managed version reopened."]


def test_page_passes_only_workspace_root_and_safe_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    captured: list[Any] = []

    def fake_reopen(*args: Any, **kwargs: Any) -> ReopenOutcome:
        captured.append((args, kwargs))
        return ReopenOutcome(STATUS_REOPENED, "Managed version reopened.", "REOPENED")

    monkeypatch.setattr(start_mod, "reopen_managed_version", fake_reopen)
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    st = RecorderSt(state)
    st.pressed_keys.add(f"mvh_set_active_{_short_ref(record)}")
    _render_managed_version_history(st, state)

    args, kwargs = captured[0]
    assert kwargs == {}
    assert len(args) == 3
    assert args[0] is state
    assert args[1] == str(root)
    assert isinstance(args[2], str)
    assert re.fullmatch(r"v-[0-9a-f]{8}", args[2])
    # No record, locator, path, or discovery object crosses this call.
    assert not any(isinstance(arg, _SENSITIVE_TYPES) for arg in args[1:])


def test_rendered_output_and_widget_keys_expose_no_sensitive_values() -> None:
    version = _version()
    view = project_history(
        _result(versions=(version,), issues=(_issue(),), duplicates=(_duplicate(),))
    )
    st = RecorderSt()
    reference = render_managed_version_history(st, view)
    assert reference is None  # rendering alone emits nothing

    keys = _button_keys(st)
    serialized = " ".join(
        (
            st.all_text(),
            " ".join(keys),
            repr(view),
            str(dataclasses.asdict(view)),
            json.dumps(dataclasses.asdict(view)),
        )
    )
    for token in _sensitive_tokens(version.record):
        assert token not in serialized
    for key in keys:
        assert re.fullmatch(r"mvh_set_active_v-[0-9a-f]{8}", key)


def test_outcomes_are_privacy_safe_through_repr_and_asdict(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    success = reopen_managed_version({}, str(root), _short_ref(record))
    failure = reopen_managed_version({}, str(root), "v-00000000")
    assert success.status == STATUS_REOPENED
    assert failure.status == STATUS_UNAVAILABLE
    for outcome in (success, failure):
        text = repr(outcome) + " " + str(dataclasses.asdict(outcome))
        assert str(root) not in text
        assert record.version_id not in text
        assert record.version_id.replace("-", "") not in text
        assert record.content_id not in text
        assert "\\" not in text


def test_no_internal_object_enters_session_state(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    st = RecorderSt(state)
    st.pressed_keys.add(f"mvh_set_active_{_short_ref(record)}")
    _render_managed_version_history(st, state)

    context = state.get(DATASET_CONTEXT)
    assert isinstance(context, DatasetContext)
    assert context.managed is True
    for value in state.values():
        assert not isinstance(value, _SENSITIVE_TYPES)
    # Feedback and rendered text stay generic: no root path, no full identifier.
    text = st.all_text()
    assert str(root) not in text
    assert record.version_id not in text
    assert record.content_id not in text
    assert [args[0] for args, _ in st.calls_named("success")] == ["Managed version reopened."]


# --- B. resolution ----------------------------------------------------------


def test_unique_current_valid_match_succeeds(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(state, str(root), _short_ref(record))
    assert outcome.status == STATUS_REOPENED
    assert outcome.reopened is True
    context = state[DATASET_CONTEXT]
    assert context.managed is True
    assert context.version_id == record.version_id
    assert context.content_id == record.content_id


def test_zero_match_fails_closed(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_version(root)
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(state, str(root), "v-00000000")
    assert outcome.status == STATUS_UNAVAILABLE
    assert outcome.reason_code == "REFERENCE_NOT_FOUND"
    assert DATASET_CONTEXT not in state


def test_multiple_matches_fail_closed() -> None:
    twins = (_version(short_id="v-1a2b3c4d"), _version(short_id="v-1a2b3c4d"))
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(
        state, "unused-root", "v-1a2b3c4d", discover=_frozen_discover(_result(versions=twins))
    )
    assert outcome.status == STATUS_STALE
    assert outcome.reason_code == "REFERENCE_AMBIGUOUS"
    assert state == {}


@pytest.mark.parametrize(
    "reference",
    ["", "   ", "v-XYZ12345", "..\\evil", "preprocessed/orders.csv", "v-" + "a" * 64, "0" * 8],
)
def test_malformed_reference_fails_closed_without_scan(reference: str) -> None:
    scans: list[Any] = []

    def counting_discover(workspace_root: str, **kwargs: Any) -> DiscoveryResult:
        scans.append(workspace_root)
        return _result()

    state: dict[str, Any] = {}
    outcome = reopen_managed_version(state, "some-root", reference, discover=counting_discover)
    assert outcome.status == STATUS_STALE
    assert outcome.reason_code == "REFERENCE_MALFORMED"
    assert scans == []
    assert state == {}


def test_stale_reference_after_replacement_fails_closed(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    reference = _short_ref(record)
    pp = _pp(root)
    (pp / "orders.dqtv.json").unlink()
    (pp / "orders.csv").unlink()
    _write_version(root, name="neworders")

    state: dict[str, Any] = {}
    outcome = reopen_managed_version(state, str(root), reference)
    assert outcome.status == STATUS_UNAVAILABLE
    assert DATASET_CONTEXT not in state


def test_unavailable_record_fails_closed(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    (_pp(root) / "orders.csv").unlink()
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(state, str(root), _short_ref(record))
    assert outcome.status == STATUS_UNAVAILABLE
    assert DATASET_CONTEXT not in state


def test_corrupt_record_fails_closed(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    (_pp(root) / "orders.dqtv.json").write_bytes(b"{corrupt")
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(state, str(root), _short_ref(record))
    assert outcome.status == STATUS_UNAVAILABLE
    assert DATASET_CONTEXT not in state


def test_identical_duplicate_group_fails_closed(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    pp = _pp(root)
    (pp / "copy.dqtv.json").write_bytes((pp / "orders.dqtv.json").read_bytes())
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(state, str(root), _short_ref(record))
    assert outcome.status == STATUS_REQUIRES_REPAIR
    assert outcome.reason_code == "DUPLICATE_GROUP"
    assert DATASET_CONTEXT not in state


def test_conflicting_duplicate_group_fails_closed(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    mapping = to_mapping(record)
    mapping["label"] = "conflicting label"
    (_pp(root) / "copy.dqtv.json").write_text(json.dumps(mapping), encoding="utf-8")
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(state, str(root), _short_ref(record))
    assert outcome.status == STATUS_REQUIRES_REPAIR
    assert outcome.reason_code == "DUPLICATE_GROUP"
    assert DATASET_CONTEXT not in state


def test_incomplete_or_unsafe_discovery_fails_closed() -> None:
    unsafe = _result(
        root_status=RootStatus.LIMIT_EXCEEDED, result_complete=False, reopen_safe=False
    )
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(
        state, "some-root", "v-1a2b3c4d", discover=_frozen_discover(unsafe)
    )
    assert outcome.status == STATUS_FAILED
    assert outcome.reason_code == "DISCOVERY_NOT_SAFE"
    assert state == {}


def test_discovery_exception_fails_closed() -> None:
    def boom(workspace_root: str, **kwargs: Any) -> DiscoveryResult:
        raise RuntimeError("internal detail that must never surface")

    state: dict[str, Any] = {}
    outcome = reopen_managed_version(state, "some-root", "v-1a2b3c4d", discover=boom)
    assert outcome.status == STATUS_FAILED
    assert outcome.reason_code == "DISCOVERY_FAILED"
    assert "internal detail" not in outcome.message
    assert state == {}


def test_fresh_discovery_used_rather_than_render_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    render_scans: list[str] = []
    service_scans: list[str] = []
    real = discover_managed_versions

    def counting_render(workspace_root: str, **kwargs: Any) -> DiscoveryResult:
        render_scans.append(workspace_root)
        return real(workspace_root, **kwargs)

    def counting_service(workspace_root: str, **kwargs: Any) -> DiscoveryResult:
        service_scans.append(workspace_root)
        return real(workspace_root, **kwargs)

    monkeypatch.setattr(start_mod, "discover_managed_versions", counting_render)
    monkeypatch.setattr(reopen_mod, "discover_managed_versions", counting_service)
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    st = RecorderSt(state)
    st.pressed_keys.add(f"mvh_set_active_{_short_ref(record)}")
    _render_managed_version_history(st, state)

    # One render-time scan plus one fresh click-time scan inside the service.
    assert len(render_scans) == 1
    assert len(service_scans) == 1
    assert isinstance(state.get(DATASET_CONTEXT), DatasetContext)


# --- C. artifact revalidation ----------------------------------------------


def test_missing_csv_fails_closed(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    frozen = discover_managed_versions(str(root))
    (_pp(root) / "orders.csv").unlink()
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(
        state, str(root), _short_ref(record), discover=_frozen_discover(frozen)
    )
    assert outcome.status == STATUS_UNAVAILABLE
    assert outcome.reason_code == "CSV_MISSING"
    assert state == {}


def test_unreadable_csv_fails_closed(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    frozen = discover_managed_versions(str(root))
    csv_path = _pp(root) / "orders.csv"
    csv_path.unlink()
    csv_path.mkdir()  # same name, no longer a readable regular file
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(
        state, str(root), _short_ref(record), discover=_frozen_discover(frozen)
    )
    assert outcome.status == STATUS_UNAVAILABLE
    assert outcome.reason_code == "CSV_NOT_REGULAR"
    assert state == {}


def test_csv_content_change_race_fails_closed(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    # Same path, different byte length: fresh discovery still probes readable,
    # so only click-time identity revalidation can catch the change.
    (_pp(root) / "orders.csv").write_bytes(_CSV_BYTES + b"3\n")
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(state, str(root), _short_ref(record))
    assert outcome.status == STATUS_UNAVAILABLE
    assert outcome.reason_code == "CSV_CHANGED"
    assert state == {}


def test_csv_mtime_change_fails_closed_when_recorded(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    pp = _pp(root)
    (pp / "orders.csv").write_bytes(_CSV_BYTES)
    mtime_ns = os.stat(pp / "orders.csv").st_mtime_ns
    record = _record(mtime_ns=mtime_ns, label="orders")
    (pp / "orders.dqtv.json").write_text(json.dumps(to_mapping(record)), encoding="utf-8")

    sanity: dict[str, Any] = {}
    assert reopen_managed_version(sanity, str(root), _short_ref(record)).reopened is True

    os.utime(pp / "orders.csv", ns=(123_456_789, 987_654_321))
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(state, str(root), _short_ref(record))
    assert outcome.status == STATUS_UNAVAILABLE
    assert outcome.reason_code == "CSV_CHANGED"
    assert state == {}


def test_csv_resolved_elsewhere_fails_closed(tmp_path: Path) -> None:
    ws_a = _ws(tmp_path, "ws_a")
    record = _write_version(ws_a)
    frozen = discover_managed_versions(str(ws_a))
    ws_b = _ws(tmp_path, "ws_b")
    (_pp(ws_b) / "orders.csv").write_bytes(_CSV_BYTES)

    state: dict[str, Any] = {}
    outcome = reopen_managed_version(
        state, str(ws_b), _short_ref(record), discover=_frozen_discover(frozen)
    )
    assert outcome.status == STATUS_UNAVAILABLE
    assert outcome.reason_code == "CSV_REPLACED"
    assert state == {}


def test_csv_escaping_root_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    outside = tmp_path / "outside.csv"
    monkeypatch.setattr(reopen_mod, "_resolve_artifact", lambda lexical: outside)
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(state, str(root), _short_ref(record))
    assert outcome.status == STATUS_UNAVAILABLE
    assert outcome.reason_code == "CSV_ESCAPES_ROOT"
    assert state == {}


def test_missing_recipe_fails_closed(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root, with_recipe=True)
    frozen = discover_managed_versions(str(root))
    (_pp(root) / "orders.recipe.json").unlink()
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(
        state, str(root), _short_ref(record), discover=_frozen_discover(frozen)
    )
    assert outcome.status == STATUS_UNAVAILABLE
    assert outcome.reason_code == "RECIPE_MISSING"
    assert state == {}


def test_unreadable_recipe_fails_closed(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root, with_recipe=True)
    frozen = discover_managed_versions(str(root))
    recipe_path = _pp(root) / "orders.recipe.json"
    recipe_path.unlink()
    recipe_path.mkdir()
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(
        state, str(root), _short_ref(record), discover=_frozen_discover(frozen)
    )
    assert outcome.status == STATUS_UNAVAILABLE
    assert outcome.reason_code == "RECIPE_NOT_REGULAR"
    assert state == {}


def test_retargeted_recipe_fails_closed(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root, with_recipe=True)
    result = discover_managed_versions(str(root))
    version = result.versions[0]
    retargeted_locator = dataclasses.replace(
        version.locator, recipe_resolved_path=str(_pp(root) / "other.recipe.json")
    )
    retargeted = dataclasses.replace(
        result, versions=(dataclasses.replace(version, locator=retargeted_locator),)
    )
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(
        state, str(root), _short_ref(record), discover=_frozen_discover(retargeted)
    )
    assert outcome.status == STATUS_UNAVAILABLE
    assert outcome.reason_code == "RECIPE_REPLACED"
    assert state == {}


def test_recipe_escaping_root_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _ws(tmp_path)
    record = _write_version(root, with_recipe=True)
    outside = tmp_path / "outside.recipe.json"
    real_resolve = reopen_mod._resolve_artifact

    def fake(lexical: Path) -> Path | None:
        if lexical.name.endswith(".recipe.json"):
            return outside
        return real_resolve(lexical)

    monkeypatch.setattr(reopen_mod, "_resolve_artifact", fake)
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(state, str(root), _short_ref(record))
    assert outcome.status == STATUS_UNAVAILABLE
    assert outcome.reason_code == "RECIPE_ESCAPES_ROOT"
    assert state == {}


# --- D. state atomicity -----------------------------------------------------


def test_every_failure_leaves_state_exactly_unchanged(tmp_path: Path) -> None:
    prior = _legacy_context()

    ws_valid = _ws(tmp_path, "valid")
    record_valid = _write_version(ws_valid)

    ws_dup = _ws(tmp_path, "dup")
    record_dup = _write_version(ws_dup)
    pp_dup = _pp(ws_dup)
    (pp_dup / "copy.dqtv.json").write_bytes((pp_dup / "orders.dqtv.json").read_bytes())

    ws_gone = _ws(tmp_path, "gone")
    record_gone = _write_version(ws_gone)
    frozen_gone = discover_managed_versions(str(ws_gone))
    (_pp(ws_gone) / "orders.csv").unlink()

    ws_recipe = _ws(tmp_path, "recipe")
    record_recipe = _write_version(ws_recipe, with_recipe=True)
    frozen_recipe = discover_managed_versions(str(ws_recipe))
    (_pp(ws_recipe) / "orders.recipe.json").unlink()

    def raising_activate(state: Any, context: Any) -> Any:
        raise RuntimeError("activation exploded")

    scenarios: list[tuple[str, str, str, dict[str, Any]]] = [
        ("zero_match", str(ws_valid), "v-00000000", {}),
        ("malformed_reference", str(ws_valid), "not-a-reference", {}),
        ("blank_root", "", _short_ref(record_valid), {}),
        ("duplicate_group", str(ws_dup), _short_ref(record_dup), {}),
        (
            "missing_csv",
            str(ws_gone),
            _short_ref(record_gone),
            {"discover": _frozen_discover(frozen_gone)},
        ),
        (
            "missing_recipe",
            str(ws_recipe),
            _short_ref(record_recipe),
            {"discover": _frozen_discover(frozen_recipe)},
        ),
        (
            "activation_rejected",
            str(ws_valid),
            _short_ref(record_valid),
            {"activate": raising_activate},
        ),
    ]

    for name, workspace_root, reference, kwargs in scenarios:
        state: dict[str, Any] = {
            DATASET_CONTEXT: prior,
            BIV_COL1: "col_a",
            "unrelated_key": "keep",
        }
        before = dict(state)
        outcome = reopen_managed_version(state, workspace_root, reference, **kwargs)
        assert outcome.reopened is False, name
        if name == "activation_rejected":
            # Post-commit interruption. R3 forbids rolling back after the trust
            # commit, so the retired binding legitimately leaves a
            # generation-bearing trust entry behind; erasing it would *be* the
            # forbidden rollback. Everything else must still be untouched, and
            # the session must be fail-closed rather than half-activated.
            assert get_valid_trust_root(state) is None, name
            assert resolve_trust_authority(state).authority is not (
                TrustAuthority.MANAGED_AUTHORITY
            ), name
            assert state[MANAGED_TRUST_STATE_KEY].root is None, name
            assert current_generation(state) >= 1, name
            unrelated = {k: v for k, v in state.items() if k != MANAGED_TRUST_STATE_KEY}
            assert unrelated == before, name
        else:
            # Every pre-commit failure leaves session state exactly unchanged.
            assert state == before, name


def test_success_calls_existing_activation_api_once(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root, with_recipe=True)
    calls: list[Any] = []

    def counting_activate(state: Any, context: Any) -> Any:
        calls.append(context)
        return activate_dataset_context(state, context)

    state: dict[str, Any] = {}
    outcome = reopen_managed_version(
        state, str(root), _short_ref(record), activate=counting_activate
    )
    assert outcome.status == STATUS_REOPENED
    assert len(calls) == 1

    context = state[DATASET_CONTEXT]
    assert context.managed is True
    assert context.version_id == record.version_id
    assert context.family_id == record.family_id
    assert context.content_id == record.content_id
    assert context.root_content_id == record.root_content_id
    assert context.version_label == record.label
    assert context.size_bytes == len(_CSV_BYTES)
    resolved_root = os.path.normcase(str(root.resolve()))
    assert os.path.normcase(context.source_path).startswith(resolved_root)


def test_success_clears_derived_state_via_existing_contract(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    state: dict[str, Any] = {
        DATASET_CONTEXT: _legacy_context(),
        BIV_COL1: "stale-selection",
        "unrelated_key": "keep",
    }
    outcome = reopen_managed_version(state, str(root), _short_ref(record))
    assert outcome.status == STATUS_REOPENED
    assert BIV_COL1 not in state  # derived state cleared by the shared contract
    assert state["unrelated_key"] == "keep"  # unrelated keys never touched
    assert state[DATASET_CONTEXT].managed is True


def test_reopening_already_active_version_is_deterministic(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    state: dict[str, Any] = {}
    first = reopen_managed_version(state, str(root), _short_ref(record))
    assert first.status == STATUS_REOPENED
    activated = state[DATASET_CONTEXT]

    state[BIV_COL1] = "kept-between-reopens"
    second = reopen_managed_version(state, str(root), _short_ref(record))
    assert second.status == STATUS_ALREADY_ACTIVE
    assert second.reopened is True
    # No duplicate transition: identical context and no derived-state clearing.
    assert state[DATASET_CONTEXT] == activated
    assert state[BIV_COL1] == "kept-between-reopens"


def test_reopen_never_parses_or_executes_recipe(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    # A readable recipe artifact whose content is not even JSON: reopen must
    # succeed because it proves the recipe is never parsed or executed.
    record = _write_version(root, with_recipe=True, recipe_bytes=b"this is not json {")
    state: dict[str, Any] = {}
    outcome = reopen_managed_version(state, str(root), _short_ref(record))
    assert outcome.status == STATUS_REOPENED
    assert state[DATASET_CONTEXT].managed is True


# --- E. automation prohibitions ---------------------------------------------


def test_blank_workspace_root_performs_no_scan_and_no_activation() -> None:
    scans: list[Any] = []

    def counting_discover(workspace_root: str, **kwargs: Any) -> DiscoveryResult:
        scans.append(workspace_root)
        return _result()

    for blank in ("", "   "):
        state: dict[str, Any] = {}
        outcome = reopen_managed_version(state, blank, "v-1a2b3c4d", discover=counting_discover)
        assert outcome.status == STATUS_FAILED
        assert outcome.reason_code == "WORKSPACE_ROOT_BLANK"
        assert state == {}
    none_state: dict[str, Any] = {}
    none_root: Any = None
    outcome = reopen_managed_version(
        none_state, none_root, "v-1a2b3c4d", discover=counting_discover
    )
    assert outcome.status == STATUS_FAILED
    assert outcome.reason_code == "WORKSPACE_ROOT_BLANK"
    assert none_state == {}
    assert scans == []


def test_nonblank_root_without_click_performs_history_discovery_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    _write_version(root)
    render_scans: list[str] = []
    service_scans: list[str] = []
    real = discover_managed_versions

    def counting_render(workspace_root: str, **kwargs: Any) -> DiscoveryResult:
        render_scans.append(workspace_root)
        return real(workspace_root, **kwargs)

    def counting_service(workspace_root: str, **kwargs: Any) -> DiscoveryResult:
        service_scans.append(workspace_root)
        return real(workspace_root, **kwargs)

    monkeypatch.setattr(start_mod, "discover_managed_versions", counting_render)
    monkeypatch.setattr(reopen_mod, "discover_managed_versions", counting_service)
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    _render_managed_version_history(RecorderSt(state), state)

    assert len(render_scans) == 1
    assert service_scans == []
    assert DATASET_CONTEXT not in state


def test_startup_and_rerender_perform_no_automatic_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    _write_version(root)
    calls: list[Any] = []
    monkeypatch.setattr(
        start_mod,
        "reopen_managed_version",
        lambda *args, **kwargs: calls.append(args),
    )
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    _render_managed_version_history(RecorderSt(state), state)  # "startup" render
    _render_managed_version_history(RecorderSt(state), state)  # rerender
    assert calls == []
    assert DATASET_CONTEXT not in state


def test_unrelated_widget_click_does_not_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    _write_version(root)
    calls: list[Any] = []
    monkeypatch.setattr(
        start_mod,
        "reopen_managed_version",
        lambda *args, **kwargs: calls.append(args),
    )
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(root)}
    st = RecorderSt(state)
    st.pressed_keys.add("some_other_button_key")
    _render_managed_version_history(st, state)
    assert calls == []
    assert DATASET_CONTEXT not in state


# --- static guarantees ------------------------------------------------------


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


def test_reopen_service_static_guarantees() -> None:
    names = _imported_names(reopen_mod)
    # No UI, no dataframes, no JSON parsing (recipe reload is a separate scope).
    assert not any(name.startswith("streamlit") for name in names)
    assert not any(name.startswith("pandas") for name in names)
    assert "json" not in names
    assert not any(name.startswith("logging") for name in names)
    source = _module_source(reopen_mod)
    assert "print(" not in source
    assert "session_state[" not in source  # only the activation contract mutates state


# -- trusted managed activation ---------------------------------------------


@pytest.fixture(autouse=True)
def _clean_managed_state() -> Any:
    _mfl.clear_managed_caches()
    yield
    _mfl.clear_managed_caches()


@pytest.fixture
def trusted_activation(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Enable trusted managed activation for one test."""
    monkeypatch.setattr(dataset_activation, "_MANAGED_ACTIVATION_ENABLED", True)
    return True


def _reopen_ready(tmp_path: Path) -> tuple[Path, DatasetVersionRecord, str]:
    root = _ws(tmp_path)
    record = _write_version(root)
    return root, record, _short_ref(record)


def test_activation_stays_untrusted_while_the_flag_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the guard off, reopen keeps its accepted pre-R3 behavior exactly.

    The flag's *production* value is proven externally against the source text
    (False before the flag-only enable, True after); this pins the behavior of
    the disabled branch itself, which must stay legacy-identical.
    """
    monkeypatch.setattr(dataset_activation, "_MANAGED_ACTIVATION_ENABLED", False)
    root, record, ref = _reopen_ready(tmp_path)
    state: dict[str, Any] = {}

    outcome = reopen_managed_version(state, str(root), ref)

    assert outcome.reopened is True
    # No trust root and no capability: the trusted path never engaged.
    assert get_valid_trust_root(state) is None
    assert peek_session_capability(state) is None
    assert MANAGED_TRUST_STATE_KEY not in state


def test_trusted_reopen_commits_a_trust_root(tmp_path: Path, trusted_activation: Any) -> None:
    root, record, ref = _reopen_ready(tmp_path)
    state: dict[str, Any] = {}

    outcome = reopen_managed_version(state, str(root), ref)

    assert outcome.reopened is True
    trust_root = get_valid_trust_root(state)
    assert trust_root is not None
    assert trust_root.version_id == record.version_id
    assert trust_root.content_id == record.content_id
    assert trust_root.family_id == record.family_id
    assert trust_root.root_content_id == record.root_content_id
    assert trust_root.version_label == record.label
    assert trust_root.generation == 1


def test_trusted_reopen_creates_the_session_capability(
    tmp_path: Path, trusted_activation: Any
) -> None:
    root, _record, ref = _reopen_ready(tmp_path)
    state: dict[str, Any] = {}
    assert peek_session_capability(state) is None  # never created by a probe

    reopen_managed_version(state, str(root), ref)

    assert peek_session_capability(state) is not None


def test_trusted_reopen_locator_is_privacy_safe(tmp_path: Path, trusted_activation: Any) -> None:
    root, record, ref = _reopen_ready(tmp_path)
    state: dict[str, Any] = {}

    reopen_managed_version(state, str(root), ref)

    trust_root = get_valid_trust_root(state)
    assert trust_root is not None
    assert trust_root.locator.display_name == "orders.csv"
    assert trust_root.locator.relative_posix == record.file_relative_path
    assert str(root) not in repr(trust_root)


def test_trusted_reopen_makes_the_version_the_managed_authority(
    tmp_path: Path, trusted_activation: Any
) -> None:
    root, record, ref = _reopen_ready(tmp_path)
    state: dict[str, Any] = {}

    reopen_managed_version(state, str(root), ref)

    decision = resolve_trust_authority(state)
    assert decision.authority is TrustAuthority.MANAGED_AUTHORITY
    assert decision.root is not None
    assert decision.root.version_id == record.version_id
    assert decision.mirror_stale is False


def test_stale_mirror_is_overridden_by_a_trusted_reopen(
    tmp_path: Path, trusted_activation: Any
) -> None:
    root, record, ref = _reopen_ready(tmp_path)
    state: dict[str, Any] = {DATASET_CONTEXT: _legacy_context()}

    reopen_managed_version(state, str(root), ref)

    decision = resolve_trust_authority(state)
    assert decision.authority is TrustAuthority.MANAGED_AUTHORITY
    assert decision.root is not None
    assert decision.root.version_id == record.version_id


def test_manual_path_cannot_override_trusted_managed_authority(
    tmp_path: Path, trusted_activation: Any
) -> None:
    root, record, ref = _reopen_ready(tmp_path)
    state: dict[str, Any] = {}
    reopen_managed_version(state, str(root), ref)

    # An operator later plants a manual unmanaged context.
    state[DATASET_CONTEXT] = _legacy_context()

    decision = resolve_trust_authority(state)
    assert decision.authority is TrustAuthority.MANAGED_AUTHORITY
    assert decision.root is not None
    assert decision.root.version_id == record.version_id
    assert decision.mirror_stale is True


def test_missing_capability_after_reopen_fails_closed(
    tmp_path: Path, trusted_activation: Any
) -> None:
    root, _record, ref = _reopen_ready(tmp_path)
    state: dict[str, Any] = {}
    reopen_managed_version(state, str(root), ref)

    state[MANAGED_TRUST_STATE_KEY].capability = None

    assert get_valid_trust_root(state) is None
    assert resolve_trust_authority(state).authority is not TrustAuthority.MANAGED_AUTHORITY


def test_replaced_capability_after_reopen_fails_closed(
    tmp_path: Path, trusted_activation: Any
) -> None:
    root, _record, ref = _reopen_ready(tmp_path)
    state: dict[str, Any] = {}
    reopen_managed_version(state, str(root), ref)

    state[MANAGED_TRUST_STATE_KEY].capability = SessionCapability()

    assert get_valid_trust_root(state) is None


def test_content_failure_commits_no_trust(tmp_path: Path, trusted_activation: Any) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    ref = _short_ref(record)
    # Replace the CSV so the size/mtime identity no longer matches the record.
    (_pp(root) / "orders.csv").write_bytes(b"c\n1\n2\n3\n4\n5\n")

    state: dict[str, Any] = {}
    outcome = reopen_managed_version(state, str(root), ref)

    assert outcome.reopened is False
    assert get_valid_trust_root(state) is None
    assert MANAGED_TRUST_STATE_KEY not in state


def test_precommit_failure_leaves_previous_authority_unchanged(
    tmp_path: Path, trusted_activation: Any
) -> None:
    root = _ws(tmp_path)
    first = _write_version(root, name="orders")
    state: dict[str, Any] = {}
    reopen_managed_version(state, str(root), _short_ref(first))
    original = get_valid_trust_root(state)
    assert original is not None

    # A malformed reference fails before any filesystem or trust work.
    outcome = reopen_managed_version(state, str(root), "not-a-reference")

    assert outcome.reopened is False
    assert get_valid_trust_root(state) is original


def test_post_commit_failure_never_restores_stale_trust(
    tmp_path: Path, trusted_activation: Any
) -> None:
    root = _ws(tmp_path)
    first = _write_version(root, name="orders")
    second = _write_version(root, name="invoices")
    state: dict[str, Any] = {}
    reopen_managed_version(state, str(root), _short_ref(first))
    stale = get_valid_trust_root(state)
    assert stale is not None

    def failing_activate(_state: Any, _context: Any) -> Any:
        raise RuntimeError("injected post-commit failure")

    outcome = reopen_managed_version(
        state, str(root), _short_ref(second), activate=failing_activate
    )

    assert outcome.reopened is False
    assert outcome.reason_code == "ACTIVATION_INTERRUPTED"
    # Forward reconciliation: the stale root is never restored and the session
    # is left fail-closed rather than half-activated.
    assert get_valid_trust_root(state) is None
    assert resolve_trust_authority(state).authority is not TrustAuthority.MANAGED_AUTHORITY


def test_post_commit_failure_retires_the_generation_forward(
    tmp_path: Path, trusted_activation: Any
) -> None:
    root = _ws(tmp_path)
    first = _write_version(root, name="orders")
    second = _write_version(root, name="invoices")
    state: dict[str, Any] = {}
    reopen_managed_version(state, str(root), _short_ref(first))
    first_generation = current_generation(state)

    def failing_activate(_state: Any, _context: Any) -> Any:
        raise RuntimeError("injected post-commit failure")

    reopen_managed_version(state, str(root), _short_ref(second), activate=failing_activate)

    # Generation only ever advances: commit (+1) then forward retirement (+1).
    assert current_generation(state) == first_generation + 2


def test_reopen_reconciliation_is_marker_independent(
    tmp_path: Path, trusted_activation: Any
) -> None:
    root = _ws(tmp_path)
    first = _write_version(root, name="orders")
    state: dict[str, Any] = {}
    reopen_managed_version(state, str(root), _short_ref(first))
    committed = get_valid_trust_root(state)
    assert committed is not None
    mirror = state[DATASET_CONTEXT]

    # Invalidate by capability replacement; the physical mirror is left behind.
    state[MANAGED_TRUST_STATE_KEY].capability = SessionCapability()
    state[DATASET_CONTEXT] = mirror

    outcome = reopen_managed_version(state, str(root), "not-a-reference")

    assert outcome.reopened is False
    # Reconciliation dropped the invalid binding without needing marker cleanup.
    assert state[MANAGED_TRUST_STATE_KEY].root is None


def test_version_switch_advances_generation_and_rebinds(
    tmp_path: Path, trusted_activation: Any
) -> None:
    root = _ws(tmp_path)
    first = _write_version(root, name="orders")
    second = _write_version(root, name="invoices")
    state: dict[str, Any] = {}

    reopen_managed_version(state, str(root), _short_ref(first))
    generation_one = current_generation(state)
    reopen_managed_version(state, str(root), _short_ref(second))

    trust_root = get_valid_trust_root(state)
    assert trust_root is not None
    assert trust_root.version_id == second.version_id
    assert current_generation(state) == generation_one + 1


def test_version_switch_clears_managed_caches(tmp_path: Path, trusted_activation: Any) -> None:
    root = _ws(tmp_path)
    first = _write_version(root, name="orders")
    second = _write_version(root, name="invoices")
    state: dict[str, Any] = {}
    reopen_managed_version(state, str(root), _short_ref(first))
    _mfl.get_managed_frame(state)
    assert _mfl._managed_frame_cache

    reopen_managed_version(state, str(root), _short_ref(second))

    assert len(_mfl._managed_frame_cache) == 0


def test_trusted_reopen_enables_managed_frame_loading(
    tmp_path: Path, trusted_activation: Any
) -> None:
    root, _record, ref = _reopen_ready(tmp_path)
    state: dict[str, Any] = {}

    reopen_managed_version(state, str(root), ref)

    frame = _mfl.get_managed_frame(state)
    assert list(frame.columns) == ["c"]


def test_no_implicit_activation_without_an_explicit_reopen(
    tmp_path: Path, trusted_activation: Any
) -> None:
    root = _ws(tmp_path)
    _write_version(root)
    state: dict[str, Any] = {}

    # Discovery alone must never mint trust.
    discover_managed_versions(str(root))

    assert get_valid_trust_root(state) is None
    assert peek_session_capability(state) is None
    assert MANAGED_TRUST_STATE_KEY not in state


def test_failed_reopen_never_creates_trust(tmp_path: Path, trusted_activation: Any) -> None:
    root = _ws(tmp_path)
    _write_version(root)
    state: dict[str, Any] = {}

    outcome = reopen_managed_version(state, str(root), "v-deadbeef")

    assert outcome.reopened is False
    assert get_valid_trust_root(state) is None


def test_trusted_outcome_messages_stay_privacy_safe(
    tmp_path: Path, trusted_activation: Any
) -> None:
    root = _ws(tmp_path)
    record = _write_version(root)
    state: dict[str, Any] = {}

    outcome = reopen_managed_version(state, str(root), _short_ref(record))

    text = outcome.status + outcome.message + outcome.reason_code
    assert str(root) not in text
    for token in _sensitive_tokens(record):
        assert token not in text
