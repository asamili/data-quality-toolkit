"""H4 contracts for the bounded, read-only lifecycle diagnostics scan.

Every workspace here is a real pytest ``tmp_path`` driven through the accepted
confirmation service, so sidecars, CSVs, and recipe artifacts are genuine rather
than synthetic. No operator workspace, dataset, recipe, or export is ever read.
"""

from __future__ import annotations

import inspect
import os
import stat
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.services import lifecycle_maintenance
from data_quality_toolkit.adapters.ui.services.dataset_confirmation import (
    ConfirmationStatus,
    confirm_processed_version,
)
from data_quality_toolkit.adapters.ui.services.lifecycle_maintenance import (
    ABANDONED_AFTER_SECONDS,
    MAX_TEMP_ARTIFACTS,
    STATE_LOCATION_ABSENT,
    STATE_LOCATION_UNAVAILABLE,
    STATE_NOT_SCANNED,
    STATE_OK,
    STATE_SCAN_LIMIT_EXCEEDED,
    DiagnosticCategory,
    collect_lifecycle_diagnostics,
    is_owned_temp_name,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.application.workflow.preprocessing import (
    make_recipe_step,
    recipe_to_json_payload,
)

_PARENT_CSV = b"n,c\n1,a\n2,a\n2,b\n3,b\n"
_CHILD_CSV = b"n,c\n10,a\n20,b\n"
_STAGE_TAG = "a1b2c3d4"


# --- Workspace helpers ------------------------------------------------------


def _recipe() -> dict[str, Any]:
    return recipe_to_json_payload([make_recipe_step("drop_duplicates", [], {})], None)


class Workspace:
    """A real confirmed workspace plus the paths H4 must reason about."""

    def __init__(self, root: Path, csv: Path, recipe: Path, sidecar: Path) -> None:
        self.root = root
        self.csv = csv
        self.recipe = recipe
        self.sidecar = sidecar

    @property
    def preprocessed(self) -> Path:
        return self.root / "preprocessed"

    def owned_temp(self, *, final: str | None = None, tag: str = _STAGE_TAG) -> Path:
        """Create a staging file named exactly as confirmation would name it."""
        base = final if final is not None else self.csv.name
        path = self.preprocessed / f".{base}.{tag}.tmp"
        path.write_bytes(b"staged")
        return path


def _confirm(root: Path) -> Workspace:
    root.mkdir(parents=True, exist_ok=True)
    parent_file = root / "source.csv"
    parent_file.write_bytes(_PARENT_CSV)
    result = confirm_processed_version(
        workspace_root=str(root),
        csv_bytes=_CHILD_CSV,
        recipe=_recipe(),
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


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return _confirm(tmp_path / "ws")


def _abandon(path: Path) -> None:
    """Age a file well past the declared grace period."""
    old_ns = time.time_ns() - (ABANDONED_AFTER_SECONDS + 3_600) * 1_000_000_000
    os.utime(path, ns=(old_ns, old_ns))


def _snapshot(directory: Path) -> dict[str, tuple[int, int]]:
    return {
        entry.name: (entry.stat().st_size, entry.stat().st_mtime_ns)
        for entry in sorted(directory.iterdir())
    }


def _references(report: Any, category: DiagnosticCategory) -> list[str]:
    return [record.reference for record in report.records if record.category is category]


def _temp_labels(report: Any) -> list[str]:
    return [
        record.label
        for record in report.records
        if record.category is DiagnosticCategory.ABANDONED_TEMP_ARTIFACT
    ]


def _try_symlink(link: Path, target: Path) -> bool:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        return False
    return True


# --- 1. The scan is confined to the authoritative lifecycle location ---------


def test_scan_reports_only_the_preprocessed_location(workspace: Workspace) -> None:
    """Owned-looking names elsewhere are invisible: only one directory is read."""
    outside = [
        workspace.root / f".{workspace.csv.name}.{_STAGE_TAG}.tmp",
        workspace.root / "recipes" / f".orders.csv.{_STAGE_TAG}.tmp",
        workspace.root / "inputs",
    ]
    outside[2].mkdir(parents=True, exist_ok=True)
    (outside[2] / f".other.csv.{_STAGE_TAG}.tmp").write_bytes(b"x")
    for path in (outside[0], outside[1]):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        _abandon(path)
    _abandon(outside[2] / f".other.csv.{_STAGE_TAG}.tmp")

    report = collect_lifecycle_diagnostics(str(workspace.root))

    assert report.state == STATE_OK
    assert _references(report, DiagnosticCategory.ABANDONED_TEMP_ARTIFACT) == []


def test_scan_never_descends_into_a_subdirectory(workspace: Workspace) -> None:
    """Enumeration is flat: depth one, no recursion, no walk, no glob."""
    nested = workspace.preprocessed / "nested"
    nested.mkdir()
    buried = nested / f".orders.csv.{_STAGE_TAG}.tmp"
    buried.write_bytes(b"x")
    _abandon(buried)

    report = collect_lifecycle_diagnostics(str(workspace.root))

    assert _references(report, DiagnosticCategory.ABANDONED_TEMP_ARTIFACT) == []
    assert buried.is_file()


def test_blank_workspace_root_scans_nothing() -> None:
    report = collect_lifecycle_diagnostics("   ")
    assert report.state == STATE_NOT_SCANNED
    assert report.scanned is False
    assert report.records == ()
    assert report.candidates == ()


def test_absent_lifecycle_location_reports_absence_not_a_failure(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    report = collect_lifecycle_diagnostics(str(root))
    assert report.state == STATE_LOCATION_ABSENT
    assert report.scanned is False
    assert report.candidates == ()


# --- 2. Count and depth are bounded ----------------------------------------


def test_retained_temp_artifacts_are_bounded(workspace: Workspace) -> None:
    for index in range(MAX_TEMP_ARTIFACTS + 3):
        _abandon(workspace.owned_temp(tag=f"tk{index:06d}"[:8]))

    report = collect_lifecycle_diagnostics(str(workspace.root))

    assert len(_references(report, DiagnosticCategory.ABANDONED_TEMP_ARTIFACT)) == (
        MAX_TEMP_ARTIFACTS
    )
    assert report.temp_omitted == 3
    assert len(report.candidates) == MAX_TEMP_ARTIFACTS


def test_observed_entry_bound_fails_closed(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _abandon(workspace.owned_temp())
    monkeypatch.setattr(lifecycle_maintenance, "MAX_ENTRIES_OBSERVED", 1)

    report = collect_lifecycle_diagnostics(str(workspace.root))

    assert report.state == STATE_SCAN_LIMIT_EXCEEDED
    assert report.scanned is False
    assert report.candidates == ()
    assert _references(report, DiagnosticCategory.FILESYSTEM_CAPABILITY_UNAVAILABLE) == [
        "capability-0001"
    ]


# --- 3. Ordering is deterministic ------------------------------------------


def test_ordering_is_deterministic_and_name_sorted(workspace: Workspace) -> None:
    for tag in ("zzzzzzzz", "aaaaaaaa", "mmmmmmmm"):
        _abandon(workspace.owned_temp(tag=tag))

    first = collect_lifecycle_diagnostics(str(workspace.root))
    second = collect_lifecycle_diagnostics(str(workspace.root))

    assert first.records == second.records
    assert first.candidates == second.candidates
    tokens = [locator.basename for locator in first.candidates]
    assert tokens == sorted(tokens, key=str.lower)


# --- 4. Symlinks and path escapes are rejected ------------------------------


def test_a_symlinked_temp_name_is_never_eligible(workspace: Workspace, tmp_path: Path) -> None:
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"not ours")
    link = workspace.preprocessed / f".orders.csv.{_STAGE_TAG}.tmp"
    if not _try_symlink(link, outside):
        pytest.skip("symlink creation is not permitted in this environment")
    _abandon(outside)

    report = collect_lifecycle_diagnostics(str(workspace.root))

    assert _references(report, DiagnosticCategory.ABANDONED_TEMP_ARTIFACT) == []
    assert outside.is_file()


def _fake_stat(mode: int, *, attributes: int = 0) -> SimpleNamespace:
    # An explicit stub exposing exactly the fields the guard reads: a POSIX
    # ``os.stat_result`` silently drops ``st_file_attributes``.
    return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)


@pytest.mark.parametrize(
    ("mode", "attributes"),
    [
        (stat.S_IFLNK | 0o777, 0),
        (stat.S_IFDIR | 0o755, 0),
        (stat.S_IFCHR | 0o666, 0),
        (stat.S_IFIFO | 0o644, 0),
        (stat.S_IFREG | 0o644, stat.FILE_ATTRIBUTE_REPARSE_POINT),
    ],
)
def test_the_non_following_guard_admits_only_plain_regular_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int, attributes: int
) -> None:
    """Proven directly, because this host forbids creating symlinks at all."""
    monkeypatch.setattr(os, "lstat", lambda *_a, **_k: _fake_stat(mode, attributes=attributes))
    assert lifecycle_maintenance._lstat_regular(tmp_path / "x") is None


def test_a_temp_resolving_outside_the_location_is_rejected(
    workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "elsewhere" / "evil.bin"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(b"not ours")
    temp = workspace.owned_temp()
    _abandon(temp)
    real_resolve = Path.resolve

    def fake_resolve(self: Path, strict: bool = False) -> Path:
        if self.name == temp.name:
            return outside
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", fake_resolve)

    report = collect_lifecycle_diagnostics(str(workspace.root))

    assert report.candidates == ()
    assert outside.read_bytes() == b"not ours"


def test_a_temp_resolving_into_a_nested_directory_is_rejected(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Containment is not enough: the parent must be the scanned directory."""
    nested = workspace.preprocessed / "nested"
    nested.mkdir()
    temp = workspace.owned_temp()
    _abandon(temp)
    real_resolve = Path.resolve

    def fake_resolve(self: Path, strict: bool = False) -> Path:
        if self.name == temp.name:
            return nested / temp.name
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", fake_resolve)

    report = collect_lifecycle_diagnostics(str(workspace.root))

    assert report.candidates == ()


def test_a_directory_named_like_a_temp_is_never_eligible(workspace: Workspace) -> None:
    decoy = workspace.preprocessed / f".orders.csv.{_STAGE_TAG}.tmp"
    decoy.mkdir()
    _abandon(decoy)

    report = collect_lifecycle_diagnostics(str(workspace.root))

    assert _references(report, DiagnosticCategory.ABANDONED_TEMP_ARTIFACT) == []
    assert decoy.is_dir()


# --- 5-7. Ownership and abandonment classification --------------------------


def test_owned_abandoned_temp_is_classified_and_eligible(workspace: Workspace) -> None:
    temp = workspace.owned_temp()
    _abandon(temp)

    report = collect_lifecycle_diagnostics(str(workspace.root))
    records = [
        record
        for record in report.records
        if record.category is DiagnosticCategory.ABANDONED_TEMP_ARTIFACT
    ]

    assert len(records) == 1
    assert records[0].cleanup_eligible is True
    assert records[0].reason_code == "TEMP_ABANDONED"
    assert records[0].label == temp.name
    assert report.counts()[DiagnosticCategory.ABANDONED_TEMP_ARTIFACT] == 1


def test_a_sidecar_staging_name_is_also_owned(workspace: Workspace) -> None:
    temp = workspace.owned_temp(final=workspace.sidecar.name)
    _abandon(temp)

    report = collect_lifecycle_diagnostics(str(workspace.root))

    assert _temp_labels(report) == [temp.name]


def test_a_fresh_temp_is_never_cleanup_eligible(workspace: Workspace) -> None:
    workspace.owned_temp()

    report = collect_lifecycle_diagnostics(str(workspace.root))

    assert _references(report, DiagnosticCategory.ABANDONED_TEMP_ARTIFACT) == []
    assert report.candidates == ()


def test_a_temp_just_inside_the_grace_period_is_not_abandoned(workspace: Workspace) -> None:
    temp = workspace.owned_temp()
    now = datetime.now(UTC)
    stamp_ns = int((now - timedelta(seconds=ABANDONED_AFTER_SECONDS - 60)).timestamp() * 1e9)
    os.utime(temp, ns=(stamp_ns, stamp_ns))

    report = collect_lifecycle_diagnostics(str(workspace.root), now=now)

    assert report.candidates == ()


def test_a_future_dated_temp_is_never_abandoned(workspace: Workspace) -> None:
    temp = workspace.owned_temp()
    now = datetime.now(UTC)
    stamp_ns = int((now + timedelta(days=30)).timestamp() * 1e9)
    os.utime(temp, ns=(stamp_ns, stamp_ns))

    report = collect_lifecycle_diagnostics(str(workspace.root), now=now)

    assert report.candidates == ()


@pytest.mark.parametrize(
    "name",
    [
        "scratch.tmp",
        ".scratch.tmp",
        ".orders.txt.a1b2c3d4.tmp",
        ".orders.csv.A1B2C3D4.tmp",
        ".orders.csv.a1b2c3.tmp",
        "orders.csv.a1b2c3d4.tmp",
        ".orders.csv.a1b2c3d4.tmp.bak",
        "../etc/passwd",
        ".sub/orders.csv.a1b2c3d4.tmp",
        "",
    ],
)
def test_unknown_temporary_names_are_never_owned(name: str) -> None:
    assert is_owned_temp_name(name) is False


def test_unknown_temporary_files_are_never_reported_or_touched(workspace: Workspace) -> None:
    unknown = workspace.preprocessed / "scratch.tmp"
    unknown.write_bytes(b"operator data")
    _abandon(unknown)

    report = collect_lifecycle_diagnostics(str(workspace.root))

    assert report.candidates == ()
    assert unknown.read_bytes() == b"operator data"


def test_owned_name_matches_what_confirmation_actually_creates(tmp_path: Path) -> None:
    """Ownership is proven against the real staging name, not an assumed one."""
    root = tmp_path / "ws"
    root.mkdir()
    parent_file = root / "source.csv"
    parent_file.write_bytes(_PARENT_CSV)
    seen: list[str] = []
    original = os.link

    def capture(src: Any, dst: Any, *args: Any, **kwargs: Any) -> None:
        seen.append(Path(src).name)
        original(src, dst, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "link", capture)
        result = confirm_processed_version(
            workspace_root=str(root),
            csv_bytes=_CHILD_CSV,
            recipe=_recipe(),
            parent=DatasetContext(
                source_path=str(parent_file),
                display_name="orders",
                size_bytes=len(_PARENT_CSV),
                modified_ns=1,
            ),
            label="cleaned",
            filename_stem="orders",
        )
    assert result.status is ConfirmationStatus.CONFIRMED
    preprocessed_names = [name for name in seen if ".csv" in name]
    assert preprocessed_names
    assert all(is_owned_temp_name(name) for name in preprocessed_names)


# --- 8. Sidecar-referenced artifacts are never candidates -------------------


def test_referenced_managed_artifacts_are_never_candidates(workspace: Workspace) -> None:
    for path in (workspace.csv, workspace.recipe, workspace.sidecar):
        _abandon(path)

    report = collect_lifecycle_diagnostics(str(workspace.root))

    assert report.candidates == ()
    assert workspace.csv.is_file()
    assert workspace.recipe.is_file()
    assert workspace.sidecar.is_file()


# --- 9-10. Managed-record classifications stay distinct ---------------------


def test_missing_csv_and_missing_recipe_are_distinct_categories(tmp_path: Path) -> None:
    without_csv = _confirm(tmp_path / "a")
    without_csv.csv.unlink()
    without_recipe = _confirm(tmp_path / "b")
    without_recipe.recipe.unlink()

    csv_report = collect_lifecycle_diagnostics(str(without_csv.root))
    recipe_report = collect_lifecycle_diagnostics(str(without_recipe.root))

    assert len(_references(csv_report, DiagnosticCategory.MISSING_CSV_REFERENCE)) == 1
    assert _references(csv_report, DiagnosticCategory.MISSING_RECIPE_REFERENCE) == []
    assert len(_references(recipe_report, DiagnosticCategory.MISSING_RECIPE_REFERENCE)) == 1
    assert _references(recipe_report, DiagnosticCategory.MISSING_CSV_REFERENCE) == []


def test_a_missing_reference_is_never_reported_as_a_corrupt_sidecar(workspace: Workspace) -> None:
    workspace.csv.unlink()

    report = collect_lifecycle_diagnostics(str(workspace.root))

    assert _references(report, DiagnosticCategory.CORRUPT_SIDECAR) == []
    assert len(_references(report, DiagnosticCategory.MISSING_CSV_REFERENCE)) == 1


def test_a_corrupt_sidecar_stays_quarantined(workspace: Workspace) -> None:
    broken = workspace.preprocessed / "broken.csv.dqtv.json"
    broken.write_text("{not json", encoding="utf-8")

    report = collect_lifecycle_diagnostics(str(workspace.root))
    corrupt = [
        record for record in report.records if record.category is DiagnosticCategory.CORRUPT_SIDECAR
    ]

    assert len(corrupt) == 1
    assert corrupt[0].cleanup_eligible is False
    assert broken.is_file()
    assert report.candidates == ()


def test_managed_records_are_never_cleanup_eligible(tmp_path: Path) -> None:
    workspace = _confirm(tmp_path / "ws")
    workspace.recipe.unlink()
    (workspace.preprocessed / "broken.csv.dqtv.json").write_text("nope", encoding="utf-8")

    report = collect_lifecycle_diagnostics(str(workspace.root))

    assert report.records
    assert all(not record.cleanup_eligible for record in report.records)


# --- 11. Capability findings are represented, never reclassified ------------


def test_a_non_directory_location_reports_a_capability_finding(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "preprocessed").write_text("not a directory", encoding="utf-8")

    report = collect_lifecycle_diagnostics(str(root))

    assert report.state == STATE_LOCATION_UNAVAILABLE
    assert report.scanned is False
    assert report.candidates == ()
    capability = [
        record
        for record in report.records
        if record.category is DiagnosticCategory.FILESYSTEM_CAPABILITY_UNAVAILABLE
    ]
    assert len(capability) == 1
    assert capability[0].reason_code == "DISCOVERY_DIR_NOT_A_DIRECTORY"
    assert capability[0].cleanup_eligible is False
    assert _references(report, DiagnosticCategory.CORRUPT_SIDECAR) == []


def test_a_recognized_hardlink_limit_is_reported_without_reclassification(
    workspace: Workspace,
) -> None:
    report = collect_lifecycle_diagnostics(str(workspace.root), capability_unavailable=True)

    capability = [
        record
        for record in report.records
        if record.category is DiagnosticCategory.FILESYSTEM_CAPABILITY_UNAVAILABLE
    ]
    assert [record.reason_code for record in capability] == ["HARDLINK_UNSUPPORTED"]
    assert _references(report, DiagnosticCategory.CORRUPT_SIDECAR) == []
    assert report.state == STATE_OK


# --- 12. Diagnostics mutate nothing ----------------------------------------


def test_diagnostics_mutate_nothing_on_disk(workspace: Workspace) -> None:
    _abandon(workspace.owned_temp())
    (workspace.preprocessed / "broken.csv.dqtv.json").write_text("nope", encoding="utf-8")
    before = _snapshot(workspace.preprocessed)
    root_before = sorted(entry.name for entry in workspace.root.iterdir())

    collect_lifecycle_diagnostics(str(workspace.root))
    collect_lifecycle_diagnostics(str(workspace.root))

    assert _snapshot(workspace.preprocessed) == before
    assert sorted(entry.name for entry in workspace.root.iterdir()) == root_before


def test_diagnostics_take_no_session_state() -> None:
    """The entry point accepts a root and a clock — never session state."""
    parameters = set(inspect.signature(collect_lifecycle_diagnostics).parameters)
    assert parameters == {"workspace_root", "now", "capability_unavailable"}


def test_no_absolute_path_reaches_a_record(workspace: Workspace) -> None:
    _abandon(workspace.owned_temp())
    workspace.recipe.unlink()

    report = collect_lifecycle_diagnostics(str(workspace.root))

    rendered = " ".join(
        f"{record.reference} {record.label} {record.reason_code}" for record in report.records
    )
    assert str(workspace.root) not in rendered
    assert str(workspace.preprocessed) not in rendered
    assert "/" not in rendered and "\\" not in rendered
