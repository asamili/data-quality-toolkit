"""H4 contracts for explicit, confirmed, revalidated abandoned-temp cleanup.

Cleanup is the only destructive operation in this surface, so these tests spend
most of their effort proving what it *cannot* do: delete without confirmation,
delete something it was not handed, delete a managed artifact, delete a
directory, or trust a record that has gone stale since the scan.
"""

from __future__ import annotations

import inspect
import os
import time
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.services.dataset_confirmation import (
    ConfirmationStatus,
    confirm_processed_version,
)
from data_quality_toolkit.adapters.ui.services.lifecycle_maintenance import (
    ABANDONED_AFTER_SECONDS,
    MAX_CLEANUP_BATCH,
    CleanupOutcome,
    CleanupStatus,
    DiagnosticCategory,
    LifecycleDiagnosticsReport,
    TempArtifactLocator,
    collect_lifecycle_diagnostics,
    execute_lifecycle_cleanup,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.application.workflow.preprocessing import (
    make_recipe_step,
    recipe_to_json_payload,
)

_PARENT_CSV = b"n,c\n1,a\n2,a\n2,b\n3,b\n"
_CHILD_CSV = b"n,c\n10,a\n20,b\n"


class Workspace:
    """A real confirmed workspace plus its managed artifact paths."""

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


def _scan(workspace: Workspace) -> LifecycleDiagnosticsReport:
    return collect_lifecycle_diagnostics(str(workspace.root))


def _eligible_references(report: LifecycleDiagnosticsReport) -> list[str]:
    return [
        record.reference
        for record in report.records
        if record.category is DiagnosticCategory.ABANDONED_TEMP_ARTIFACT
    ]


def _outcomes(result: Any) -> list[tuple[str, str, str]]:
    return [(item.reference, item.outcome.value, item.reason_code) for item in result.items]


# --- 13. Cleanup runs only on an explicit, confirmed request ----------------


def test_unconfirmed_cleanup_deletes_nothing(workspace: Workspace) -> None:
    temp = workspace.abandoned_temp()
    report = _scan(workspace)

    result = execute_lifecycle_cleanup(report, _eligible_references(report), confirmed=False)

    assert result.status is CleanupStatus.REFUSED
    assert result.reason_code == "NOT_CONFIRMED"
    assert result.items == ()
    assert temp.is_file()


def test_an_empty_selection_deletes_nothing(workspace: Workspace) -> None:
    temp = workspace.abandoned_temp()
    report = _scan(workspace)

    result = execute_lifecycle_cleanup(report, [], confirmed=True)

    assert result.status is CleanupStatus.REFUSED
    assert result.reason_code == "NOTHING_SELECTED"
    assert temp.is_file()


def test_cleanup_without_a_scan_is_refused(workspace: Workspace) -> None:
    temp = workspace.abandoned_temp()

    result = execute_lifecycle_cleanup(
        LifecycleDiagnosticsReport(state="not_scanned", scanned=False),
        ["temp-000000000000"],
        confirmed=True,
    )

    assert result.status is CleanupStatus.REFUSED
    assert result.reason_code == "NOT_SCANNED"
    assert temp.is_file()


def test_an_oversized_batch_is_refused_before_any_deletion(workspace: Workspace) -> None:
    for index in range(MAX_CLEANUP_BATCH + 1):
        workspace.abandoned_temp(tag=f"tk{index:06d}"[:8])
    report = _scan(workspace)
    references = _eligible_references(report)
    assert len(references) == MAX_CLEANUP_BATCH + 1

    result = execute_lifecycle_cleanup(report, references, confirmed=True)

    assert result.status is CleanupStatus.REFUSED
    assert result.reason_code == "BATCH_TOO_LARGE"
    assert len(list(workspace.preprocessed.glob("*.tmp"))) == MAX_CLEANUP_BATCH + 1


def test_a_replaced_location_refuses_the_whole_batch(workspace: Workspace) -> None:
    workspace.abandoned_temp()
    report = _scan(workspace)
    references = _eligible_references(report)
    workspace.preprocessed.rename(workspace.root / "preprocessed_old")
    workspace.preprocessed.mkdir()

    result = execute_lifecycle_cleanup(report, references, confirmed=True)

    assert result.status is CleanupStatus.REFUSED
    assert result.reason_code == "LOCATION_CHANGED"
    assert result.items == ()


# --- 14. Only the selected, eligible artifacts are deleted ------------------


def test_only_the_selected_temp_artifact_is_deleted(workspace: Workspace) -> None:
    chosen = workspace.abandoned_temp(tag="aaaaaaaa")
    untouched = workspace.abandoned_temp(tag="bbbbbbbb")
    report = _scan(workspace)
    chosen_reference = next(
        locator.reference for locator in report.candidates if locator.basename == chosen.name
    )

    result = execute_lifecycle_cleanup(report, [chosen_reference], confirmed=True)

    assert result.status is CleanupStatus.COMPLETED
    assert result.deleted_count == 1
    assert not chosen.exists()
    assert untouched.is_file()
    assert workspace.csv.is_file()
    assert workspace.recipe.is_file()
    assert workspace.sidecar.is_file()


def test_a_selection_that_matches_no_candidate_is_reported_not_guessed(
    workspace: Workspace,
) -> None:
    temp = workspace.abandoned_temp()
    report = _scan(workspace)

    result = execute_lifecycle_cleanup(report, ["temp-deadbeefcafe"], confirmed=True)

    assert result.status is CleanupStatus.COMPLETED
    assert _outcomes(result) == [("temp-deadbeefcafe", "skipped", "UNKNOWN_SELECTION")]
    assert temp.is_file()


# --- 15. Eligibility is re-proven immediately before each deletion ----------


def test_a_temp_refreshed_after_the_scan_is_skipped(workspace: Workspace) -> None:
    temp = workspace.abandoned_temp()
    report = _scan(workspace)
    references = _eligible_references(report)
    now_ns = time.time_ns()
    os.utime(temp, ns=(now_ns, now_ns))

    result = execute_lifecycle_cleanup(report, references, confirmed=True)

    assert result.deleted_count == 0
    assert _outcomes(result) == [(references[0], "skipped", "NOT_ELIGIBLE")]
    assert temp.is_file()


def test_a_temp_replaced_by_a_directory_after_the_scan_is_skipped(workspace: Workspace) -> None:
    temp = workspace.abandoned_temp()
    report = _scan(workspace)
    references = _eligible_references(report)
    temp.unlink()
    temp.mkdir()

    result = execute_lifecycle_cleanup(report, references, confirmed=True)

    assert result.deleted_count == 0
    assert _outcomes(result) == [(references[0], "skipped", "NOT_ELIGIBLE")]
    assert temp.is_dir()


def test_a_temp_that_vanishes_at_the_unlink_is_reported_unavailable(workspace: Workspace) -> None:
    temp = workspace.abandoned_temp()
    report = _scan(workspace)
    references = _eligible_references(report)
    calls: list[str] = []

    def already_gone(path: Any, *_args: Any, **_kwargs: Any) -> None:
        calls.append(str(path))
        raise FileNotFoundError(2, "vanished")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "unlink", already_gone)
        result = execute_lifecycle_cleanup(report, references, confirmed=True)

    assert calls == [str(temp.resolve())]
    assert _outcomes(result) == [(references[0], "unavailable", "ALREADY_ABSENT")]


def test_a_permission_failure_is_reported_and_never_retried(workspace: Workspace) -> None:
    workspace.abandoned_temp(tag="aaaaaaaa")
    workspace.abandoned_temp(tag="bbbbbbbb")
    report = _scan(workspace)
    references = _eligible_references(report)
    attempts: list[str] = []

    def refuse(path: Any, *_args: Any, **_kwargs: Any) -> None:
        attempts.append(str(path))
        raise PermissionError(13, "denied")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "unlink", refuse)
        result = execute_lifecycle_cleanup(report, references, confirmed=True)

    assert len(attempts) == 2
    assert len(set(attempts)) == 2
    assert result.failed_count == 2
    assert all(item.reason_code == "PERMISSION_DENIED" for item in result.items)


# --- 16. Managed artifacts, directories, and unknown files cannot be deleted --


def _forged(report: LifecycleDiagnosticsReport, target: Path) -> LifecycleDiagnosticsReport:
    """Hand cleanup a record naming a path it must refuse to act on."""
    locator = TempArtifactLocator(
        reference="temp-forged00000",
        basename=target.name,
        resolved_path=str(target.resolve()),
        parent_dev=0,
        parent_ino=0,
        mtime_ns=0,
    )
    return LifecycleDiagnosticsReport(
        state=report.state,
        scanned=True,
        records=report.records,
        candidates=(locator,),
        location=report.location,
    )


def test_a_forged_record_cannot_delete_a_managed_artifact(workspace: Workspace) -> None:
    workspace.abandoned_temp()
    report = _scan(workspace)

    for target in (workspace.csv, workspace.recipe, workspace.sidecar):
        result = execute_lifecycle_cleanup(
            _forged(report, target), ["temp-forged00000"], confirmed=True
        )
        assert result.deleted_count == 0
        assert _outcomes(result) == [("temp-forged00000", "skipped", "NOT_ELIGIBLE")]
        assert target.is_file()


def test_a_forged_record_cannot_delete_a_directory(workspace: Workspace) -> None:
    workspace.abandoned_temp()
    report = _scan(workspace)

    result = execute_lifecycle_cleanup(
        _forged(report, workspace.preprocessed), ["temp-forged00000"], confirmed=True
    )

    assert result.deleted_count == 0
    assert workspace.preprocessed.is_dir()
    assert workspace.csv.is_file()


def test_a_forged_record_cannot_delete_an_unknown_file(workspace: Workspace) -> None:
    unknown = workspace.preprocessed / "scratch.tmp"
    unknown.write_bytes(b"operator data")
    old_ns = time.time_ns() - (ABANDONED_AFTER_SECONDS + 3_600) * 1_000_000_000
    os.utime(unknown, ns=(old_ns, old_ns))
    workspace.abandoned_temp()
    report = _scan(workspace)

    result = execute_lifecycle_cleanup(
        _forged(report, unknown), ["temp-forged00000"], confirmed=True
    )

    assert result.deleted_count == 0
    assert unknown.read_bytes() == b"operator data"


def test_a_forged_record_cannot_delete_outside_the_location(
    workspace: Workspace, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere.csv"
    outside.write_bytes(b"private")
    workspace.abandoned_temp()
    report = _scan(workspace)

    result = execute_lifecycle_cleanup(
        _forged(report, outside), ["temp-forged00000"], confirmed=True
    )

    assert result.deleted_count == 0
    assert outside.read_bytes() == b"private"


def test_a_record_whose_path_no_longer_matches_its_name_is_skipped(
    workspace: Workspace, tmp_path: Path
) -> None:
    temp = workspace.abandoned_temp()
    report = _scan(workspace)
    tampered = LifecycleDiagnosticsReport(
        state=report.state,
        scanned=True,
        records=report.records,
        candidates=(
            TempArtifactLocator(
                reference=report.candidates[0].reference,
                basename=temp.name,
                resolved_path=str((tmp_path / "elsewhere.bin").resolve()),
                parent_dev=report.candidates[0].parent_dev,
                parent_ino=report.candidates[0].parent_ino,
                mtime_ns=report.candidates[0].mtime_ns,
            ),
        ),
        location=report.location,
    )

    result = execute_lifecycle_cleanup(tampered, [report.candidates[0].reference], confirmed=True)

    assert result.deleted_count == 0
    assert _outcomes(result) == [(report.candidates[0].reference, "skipped", "PATH_CHANGED")]
    assert temp.is_file()


# --- 17-18. Partial results are deterministic and privacy-safe --------------


def test_partial_results_are_deterministic_and_ordered_by_the_scan(workspace: Workspace) -> None:
    deletable = workspace.abandoned_temp(tag="aaaaaaaa")
    stale = workspace.abandoned_temp(tag="bbbbbbbb")
    report = _scan(workspace)
    references = _eligible_references(report)
    now_ns = time.time_ns()
    os.utime(stale, ns=(now_ns, now_ns))

    first = execute_lifecycle_cleanup(
        report, [*reversed(references), "temp-unknown0000"], confirmed=True
    )

    assert [item.reference for item in first.items] == [*references, "temp-unknown0000"]
    assert first.deleted_count == 1
    assert first.skipped_count == 2
    assert not deletable.exists()
    assert stale.is_file()

    second = execute_lifecycle_cleanup(
        report, [*reversed(references), "temp-unknown0000"], confirmed=True
    )
    assert [item.reference for item in second.items] == [item.reference for item in first.items]
    assert second.deleted_count == 0
    assert second.skipped_count == 3
    assert all(item.outcome is CleanupOutcome.SKIPPED for item in second.items)


def test_duplicate_selections_are_collapsed(workspace: Workspace) -> None:
    workspace.abandoned_temp()
    report = _scan(workspace)
    reference = _eligible_references(report)[0]

    result = execute_lifecycle_cleanup(report, [reference, reference, reference], confirmed=True)

    assert len(result.items) == 1
    assert result.deleted_count == 1


def test_no_path_or_exception_text_reaches_a_cleanup_item(workspace: Workspace) -> None:
    temp = workspace.abandoned_temp()
    report = _scan(workspace)
    references = _eligible_references(report)

    def refuse(_path: Any, *_args: Any, **_kwargs: Any) -> None:
        raise PermissionError(13, f"denied for {temp}")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "unlink", refuse)
        result = execute_lifecycle_cleanup(report, references, confirmed=True)

    rendered = " ".join(
        f"{item.reference} {item.label} {item.reason_code}" for item in result.items
    )
    assert str(workspace.root) not in rendered
    assert str(temp) not in rendered
    assert "denied" not in rendered
    assert "/" not in rendered and "\\" not in rendered


# --- 19. Nothing else in the lifecycle is touched ---------------------------


def test_cleanup_takes_no_session_state(workspace: Workspace) -> None:
    parameters = set(inspect.signature(execute_lifecycle_cleanup).parameters)
    assert parameters == {"report", "references", "confirmed", "now"}


def test_cleanup_leaves_every_managed_record_and_folder_intact(workspace: Workspace) -> None:
    workspace.abandoned_temp()
    before_recipes = sorted(entry.name for entry in (workspace.root / "recipes").iterdir())
    sidecar_bytes = workspace.sidecar.read_bytes()
    csv_bytes = workspace.csv.read_bytes()
    report = _scan(workspace)

    result = execute_lifecycle_cleanup(report, _eligible_references(report), confirmed=True)

    assert result.deleted_count == 1
    assert workspace.sidecar.read_bytes() == sidecar_bytes
    assert workspace.csv.read_bytes() == csv_bytes
    assert sorted(entry.name for entry in (workspace.root / "recipes").iterdir()) == (
        before_recipes
    )
    assert workspace.preprocessed.is_dir()


def test_the_managed_version_is_still_discoverable_after_cleanup(workspace: Workspace) -> None:
    workspace.abandoned_temp()
    report = _scan(workspace)
    execute_lifecycle_cleanup(report, _eligible_references(report), confirmed=True)

    after = _scan(workspace)

    assert after.records == ()
    assert after.candidates == ()
