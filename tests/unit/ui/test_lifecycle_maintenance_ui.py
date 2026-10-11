"""H4 contracts for the maintenance projection and the Start-page section.

The projection is proven to keep diagnostic-only findings apart from
cleanup-eligible artifacts and to leak nothing. The page section is proven to
scan nothing until asked, to delete nothing without both an explicit selection
and an explicit confirmation, and to render no path or exception.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.pages import start as start_page
from data_quality_toolkit.adapters.ui.pages.start import (
    _MAINT_CONFIRM,
    _MAINT_DELETE_BTN,
    _MAINT_SELECT_PREFIX,
    _MAINT_SHOW,
    _render_lifecycle_maintenance,
)
from data_quality_toolkit.adapters.ui.services.confirmation_capability import capability_guidance
from data_quality_toolkit.adapters.ui.services.dataset_confirmation import (
    ConfirmationStatus,
    confirm_processed_version,
)
from data_quality_toolkit.adapters.ui.services.lifecycle_maintenance import (
    ABANDONED_AFTER_SECONDS,
    STATE_LOCATION_UNAVAILABLE,
    STATE_NOT_SCANNED,
    STATE_OK,
    CleanupItemResult,
    CleanupOutcome,
    CleanupResult,
    CleanupStatus,
    DiagnosticCategory,
    DiagnosticRecord,
    LifecycleDiagnosticsReport,
    collect_lifecycle_diagnostics,
)
from data_quality_toolkit.adapters.ui.services.lifecycle_maintenance_view import (
    CATEGORY_LABELS,
    CLEANUP_SECTION_TITLE,
    ISSUE_SECTION_TITLE,
    MAINTENANCE_NOTICES,
    blank_maintenance_view,
    project_cleanup_result,
    project_maintenance,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import SRC_WORKSPACE_ROOT
from data_quality_toolkit.application.workflow.preprocessing import (
    make_recipe_step,
    recipe_to_json_payload,
)

_PARENT_CSV = b"n,c\n1,a\n2,a\n2,b\n3,b\n"
_CHILD_CSV = b"n,c\n10,a\n20,b\n"

# Fixed phrases that keep every diagnostic-only guidance honest about what this
# surface will not do on the operator's behalf.
_SAFETY_PHRASES = (
    "Cleanup cannot recreate it",
    "never activated, rewritten, or repaired",
    "Nothing was changed, repaired, or deleted",
    "Nothing was deleted automatically",
)


class FakeSt:
    """Records maintenance-section render calls and mimics keyed widgets."""

    def __init__(self, session_state: dict[str, Any]) -> None:
        self.session_state = session_state
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.button_clicks: dict[str, bool] = {}
        self.checkbox_values: dict[str, bool] = {}

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def subheader(self, *args: Any, **kwargs: Any) -> None:
        self._record("subheader", *args, **kwargs)

    def caption(self, *args: Any, **kwargs: Any) -> None:
        self._record("caption", *args, **kwargs)

    def write(self, *args: Any, **kwargs: Any) -> None:
        self._record("write", *args, **kwargs)

    def divider(self, *args: Any, **kwargs: Any) -> None:
        self._record("divider", *args, **kwargs)

    def info(self, *args: Any, **kwargs: Any) -> None:
        self._record("info", *args, **kwargs)

    def success(self, *args: Any, **kwargs: Any) -> None:
        self._record("success", *args, **kwargs)

    def warning(self, *args: Any, **kwargs: Any) -> None:
        self._record("warning", *args, **kwargs)

    def error(self, *args: Any, **kwargs: Any) -> None:
        self._record("error", *args, **kwargs)

    def checkbox(self, label: str, **kwargs: Any) -> bool:
        self._record("checkbox", label, **kwargs)
        key = kwargs.get("key")
        return bool(self.checkbox_values.get(str(key), False))

    def button(self, label: str, **kwargs: Any) -> bool:
        self._record("button", label, **kwargs)
        return bool(self.button_clicks.get(str(kwargs.get("key", label)), False))

    def rendered_text(self) -> str:
        parts: list[str] = []
        for name, args, kwargs in self.calls:
            parts.extend(str(value) for value in args)
            parts.extend(f"{key}={value}" for key, value in kwargs.items() if key != "key")
            parts.append(name)
        return " ".join(parts)

    def widget_keys(self, name: str) -> list[str]:
        return [
            str(kwargs["key"])
            for call_name, _args, kwargs in self.calls
            if call_name == name and "key" in kwargs
        ]


class Workspace:
    def __init__(self, root: Path, csv: Path, recipe: Path, sidecar: Path) -> None:
        self.root = root
        self.csv = csv
        self.recipe = recipe
        self.sidecar = sidecar

    @property
    def preprocessed(self) -> Path:
        return self.root / "preprocessed"

    def abandoned_temp(self, tag: str = "a1b2c3d4") -> Path:
        path = self.preprocessed / f".{self.csv.name}.{tag}.tmp"
        path.write_bytes(b"staged")
        old_ns = time.time_ns() - (ABANDONED_AFTER_SECONDS + 3_600) * 1_000_000_000
        os.utime(path, ns=(old_ns, old_ns))
        return path


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    root = tmp_path / "ws"
    root.mkdir()
    parent_file = root / "source.csv"
    parent_file.write_bytes(_PARENT_CSV)
    result = confirm_processed_version(
        workspace_root=str(root),
        csv_bytes=_CHILD_CSV,
        recipe=recipe_to_json_payload([make_recipe_step("drop_duplicates", [], {})], None),
        parent=DatasetContext(
            source_path=str(parent_file),
            display_name="orders",
            size_bytes=len(_PARENT_CSV),
            modified_ns=1,
        ),
        label="cleaned v1",
        filename_stem="orders",
    )
    assert result.status is ConfirmationStatus.CONFIRMED, result.message
    return Workspace(
        root=root,
        csv=root / Path(result.csv_relative_path),
        recipe=root / Path(result.recipe_relative_path),
        sidecar=root / Path(result.sidecar_relative_path),
    )


def _state(workspace: Workspace | None = None) -> dict[str, Any]:
    if workspace is None:
        return {}
    return {SRC_WORKSPACE_ROOT: str(workspace.root)}


# --- Projection: separation, bounds, guidance, privacy ----------------------


def _record(category: DiagnosticCategory, reference: str, **kwargs: Any) -> DiagnosticRecord:
    return DiagnosticRecord(
        category=category,
        reference=reference,
        label=kwargs.get("label", "item"),
        reason_code=kwargs.get("reason_code", "CODE"),
        cleanup_eligible=kwargs.get("cleanup_eligible", False),
    )


def test_projection_separates_cleanup_candidates_from_diagnostic_only_records() -> None:
    report = LifecycleDiagnosticsReport(
        state=STATE_OK,
        scanned=True,
        records=(
            _record(DiagnosticCategory.ABANDONED_TEMP_ARTIFACT, "temp-1", cleanup_eligible=True),
            _record(DiagnosticCategory.MISSING_CSV_REFERENCE, "issue-0001"),
            _record(DiagnosticCategory.MISSING_RECIPE_REFERENCE, "issue-0002"),
            _record(DiagnosticCategory.CORRUPT_SIDECAR, "issue-0003"),
        ),
    )

    view = project_maintenance(report)

    assert [row.reference for row in view.cleanup_rows] == ["temp-1"]
    assert [row.reference for row in view.issue_rows] == [
        "issue-0001",
        "issue-0002",
        "issue-0003",
    ]
    assert view.cleanup_total == 1
    assert view.issue_total == 3


def test_projection_bounds_rows_and_reports_what_it_omitted() -> None:
    records = tuple(
        _record(DiagnosticCategory.ABANDONED_TEMP_ARTIFACT, f"temp-{i}", cleanup_eligible=True)
        for i in range(5)
    ) + tuple(_record(DiagnosticCategory.CORRUPT_SIDECAR, f"issue-{i}") for i in range(5))
    report = LifecycleDiagnosticsReport(state=STATE_OK, scanned=True, records=records)

    view = project_maintenance(report, max_issue_rows=2, max_cleanup_rows=3)

    assert len(view.cleanup_rows) == 3
    assert len(view.issue_rows) == 2
    assert view.cleanup_omitted == 2
    assert view.issue_omitted == 3


def test_projection_gives_every_diagnostic_only_category_safe_guidance() -> None:
    categories = (
        DiagnosticCategory.MISSING_CSV_REFERENCE,
        DiagnosticCategory.MISSING_RECIPE_REFERENCE,
        DiagnosticCategory.CORRUPT_SIDECAR,
        DiagnosticCategory.FILESYSTEM_CAPABILITY_UNAVAILABLE,
    )
    report = LifecycleDiagnosticsReport(
        state=STATE_OK,
        scanned=True,
        records=tuple(
            _record(category, f"issue-{index}") for index, category in enumerate(categories)
        ),
    )

    view = project_maintenance(report)

    assert len(view.issue_rows) == 4
    for row in view.issue_rows:
        assert row.guidance
        # Each one names a safe operator step and rules out a repair here.
        assert any(phrase in row.guidance for phrase in _SAFETY_PHRASES)
        assert "/" not in row.guidance and "\\" not in row.guidance
    assert view.cleanup_rows == ()


def test_a_proven_hardlink_limit_reuses_the_confirmation_wording() -> None:
    report = LifecycleDiagnosticsReport(
        state=STATE_LOCATION_UNAVAILABLE,
        scanned=False,
        records=(
            _record(
                DiagnosticCategory.FILESYSTEM_CAPABILITY_UNAVAILABLE,
                "capability-0001",
                reason_code="HARDLINK_UNSUPPORTED",
            ),
        ),
    )

    view = project_maintenance(report)

    assert view.issue_rows[0].guidance == capability_guidance()


def test_a_scan_side_capability_limit_gets_supported_filesystem_guidance() -> None:
    report = LifecycleDiagnosticsReport(
        state=STATE_LOCATION_UNAVAILABLE,
        scanned=False,
        records=(
            _record(
                DiagnosticCategory.FILESYSTEM_CAPABILITY_UNAVAILABLE,
                "capability-0001",
                reason_code="DISCOVERY_DIR_NOT_A_DIRECTORY",
            ),
        ),
    )

    view = project_maintenance(report)

    assert "supported local filesystem" in view.issue_rows[0].guidance
    assert "Nothing was changed, repaired, or deleted." in view.issue_rows[0].guidance


def test_the_blank_view_scans_nothing_and_states_the_limits() -> None:
    view = blank_maintenance_view()
    assert view.state == STATE_NOT_SCANNED
    assert view.scanned is False
    assert view.notices == MAINTENANCE_NOTICES
    assert any("cannot repair" in notice for notice in view.notices)
    assert any("background deletion" in notice for notice in view.notices)


def test_counts_cover_every_category_even_when_zero() -> None:
    report = LifecycleDiagnosticsReport(state=STATE_OK, scanned=True, records=())
    view = project_maintenance(report)
    assert [item.label for item in view.counts] == list(CATEGORY_LABELS.values())
    assert all(item.count == 0 for item in view.counts)


def test_a_refused_cleanup_projects_a_fixed_message_and_no_rows() -> None:
    view = project_cleanup_result(
        CleanupResult(status=CleanupStatus.REFUSED, reason_code="NOT_CONFIRMED")
    )
    assert view.completed is False
    assert view.rows == ()
    assert "Nothing was deleted" in view.message


def test_a_completed_cleanup_projects_fixed_outcome_labels() -> None:
    result = CleanupResult(
        status=CleanupStatus.COMPLETED,
        items=(
            CleanupItemResult("temp-1", "a.tmp", CleanupOutcome.DELETED, "DELETED"),
            CleanupItemResult("temp-2", "b.tmp", CleanupOutcome.SKIPPED, "NOT_ELIGIBLE"),
            CleanupItemResult("temp-3", "c.tmp", CleanupOutcome.FAILED, "PERMISSION_DENIED"),
        ),
    )

    view = project_cleanup_result(result)

    assert [row.outcome_label for row in view.rows] == ["Deleted", "Skipped", "Failed"]
    assert view.deleted_count == 1
    assert view.failed_count == 1


# --- Page section: nothing happens without an explicit action ----------------


def test_the_section_scans_nothing_until_the_operator_turns_it_on(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        start_page,
        "collect_lifecycle_diagnostics",
        lambda root, **_kwargs: calls.append(root),
    )
    state = _state(workspace)
    st = FakeSt(state)

    _render_lifecycle_maintenance(st, state)

    assert calls == []
    assert "Lifecycle diagnostics are off" in st.rendered_text()
    for notice in MAINTENANCE_NOTICES:
        assert notice in st.rendered_text()


def test_the_section_scans_nothing_without_a_workspace_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        start_page,
        "collect_lifecycle_diagnostics",
        lambda root, **_kwargs: calls.append(root),
    )
    state: dict[str, Any] = {}
    st = FakeSt(state)
    st.checkbox_values[_MAINT_SHOW] = True

    _render_lifecycle_maintenance(st, state)

    assert calls == []
    assert blank_maintenance_view().message in st.rendered_text()


def test_an_enabled_section_renders_counts_and_both_groups(workspace: Workspace) -> None:
    workspace.abandoned_temp()
    workspace.recipe.unlink()
    state = _state(workspace)
    st = FakeSt(state)
    st.checkbox_values[_MAINT_SHOW] = True

    _render_lifecycle_maintenance(st, state)

    text = st.rendered_text()
    assert ISSUE_SECTION_TITLE in text
    assert CLEANUP_SECTION_TITLE in text
    assert CATEGORY_LABELS[DiagnosticCategory.MISSING_RECIPE_REFERENCE] in text
    assert any(key.startswith(_MAINT_SELECT_PREFIX) for key in st.widget_keys("checkbox"))


def test_diagnostic_only_records_get_no_selection_control(workspace: Workspace) -> None:
    workspace.recipe.unlink()
    (workspace.preprocessed / "broken.csv.dqtv.json").write_text("nope", encoding="utf-8")
    state = _state(workspace)
    st = FakeSt(state)
    st.checkbox_values[_MAINT_SHOW] = True

    _render_lifecycle_maintenance(st, state)

    assert [key for key in st.widget_keys("checkbox") if key.startswith(_MAINT_SELECT_PREFIX)] == []
    assert st.widget_keys("button") == []


def test_rendering_alone_never_calls_cleanup(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp = workspace.abandoned_temp()
    calls: list[Any] = []
    monkeypatch.setattr(
        start_page,
        "execute_lifecycle_cleanup",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    state = _state(workspace)
    st = FakeSt(state)
    st.checkbox_values[_MAINT_SHOW] = True
    st.checkbox_values[_MAINT_CONFIRM] = True

    _render_lifecycle_maintenance(st, state)

    assert calls == []
    assert temp.is_file()


def test_deleting_without_confirmation_refuses_and_keeps_the_file(
    workspace: Workspace,
) -> None:
    temp = workspace.abandoned_temp()
    report = collect_lifecycle_diagnostics(str(workspace.root))
    reference = report.candidates[0].reference
    state = _state(workspace)
    st = FakeSt(state)
    st.checkbox_values[_MAINT_SHOW] = True
    st.checkbox_values[f"{_MAINT_SELECT_PREFIX}{reference}"] = True
    st.button_clicks[_MAINT_DELETE_BTN] = True

    _render_lifecycle_maintenance(st, state)

    assert temp.is_file()
    assert "Confirm the cleanup checkbox" in st.rendered_text()


def test_an_explicit_confirmed_selection_deletes_only_that_file(workspace: Workspace) -> None:
    chosen = workspace.abandoned_temp(tag="aaaaaaaa")
    untouched = workspace.abandoned_temp(tag="bbbbbbbb")
    report = collect_lifecycle_diagnostics(str(workspace.root))
    reference = next(
        locator.reference for locator in report.candidates if locator.basename == chosen.name
    )
    state = _state(workspace)
    st = FakeSt(state)
    st.checkbox_values[_MAINT_SHOW] = True
    st.checkbox_values[_MAINT_CONFIRM] = True
    st.checkbox_values[f"{_MAINT_SELECT_PREFIX}{reference}"] = True
    st.button_clicks[_MAINT_DELETE_BTN] = True

    _render_lifecycle_maintenance(st, state)

    assert not chosen.exists()
    assert untouched.is_file()
    assert workspace.csv.is_file()
    assert workspace.sidecar.is_file()
    assert "Deleted 1" in st.rendered_text()


def test_confirming_with_nothing_selected_deletes_nothing(workspace: Workspace) -> None:
    temp = workspace.abandoned_temp()
    state = _state(workspace)
    st = FakeSt(state)
    st.checkbox_values[_MAINT_SHOW] = True
    st.checkbox_values[_MAINT_CONFIRM] = True
    st.button_clicks[_MAINT_DELETE_BTN] = True

    _render_lifecycle_maintenance(st, state)

    assert temp.is_file()
    assert "Select at least one" in st.rendered_text()


def test_the_section_never_renders_a_path_or_a_raw_error(workspace: Workspace) -> None:
    workspace.abandoned_temp()
    workspace.csv.unlink()
    (workspace.preprocessed / "broken.csv.dqtv.json").write_text("{", encoding="utf-8")
    state = _state(workspace)
    st = FakeSt(state)
    st.checkbox_values[_MAINT_SHOW] = True

    _render_lifecycle_maintenance(st, state)

    text = st.rendered_text()
    assert str(workspace.root) not in text
    assert str(workspace.preprocessed) not in text
    assert "Traceback" not in text
    assert "Errno" not in text


def test_the_section_writes_no_session_state(workspace: Workspace) -> None:
    workspace.abandoned_temp()
    state = _state(workspace)
    before = dict(state)
    st = FakeSt(state)
    st.checkbox_values[_MAINT_SHOW] = True

    _render_lifecycle_maintenance(st, state)

    assert state == before
