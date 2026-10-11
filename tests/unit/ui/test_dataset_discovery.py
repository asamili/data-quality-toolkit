"""Tests for the pure managed-version discovery service.

Cover root/discovery-directory states, deterministic bounded enumeration,
untrusted sidecar parsing and schema classification, bounded artifact
readability, full duplicate quarantine, privacy-safe output, post-classification
filtering and ordering, and service purity/immutability.

Assertions are semantic: presence of meaning and absence of sensitive values,
never a whole rendered snapshot.
"""

from __future__ import annotations

import ast
import json
import os
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pytest

from data_quality_toolkit.adapters.ui.services import dataset_discovery
from data_quality_toolkit.adapters.ui.services.dataset_confirmation import (
    confirm_processed_version,
)
from data_quality_toolkit.adapters.ui.services.dataset_discovery import (
    ARTIFACT_KIND_CSV,
    ARTIFACT_KIND_NONE,
    ARTIFACT_KIND_RECIPE,
    DiscoveryBounds,
    DiscoveryConfigError,
    DiscoveryFilters,
    RecordStatus,
    RootStatus,
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
    recipe_digest,
    to_mapping,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext

_VALID_SHA1 = "sha1:" + "0" * 40
_PRIVATE_DIR = r"C:\Users\example_user\private"


# --- fixtures / helpers ---------------------------------------------------


def _ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _pp(root: Path) -> Path:
    pp = root / "preprocessed"
    pp.mkdir(parents=True, exist_ok=True)
    return pp


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
    return DatasetVersionRecord(**fields)


def _write_sidecar(root: Path, filename: str, payload: dict[str, Any] | bytes) -> Path:
    target = _pp(root) / filename
    if isinstance(payload, bytes):
        target.write_bytes(payload)
    else:
        target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def _write_valid(
    root: Path,
    *,
    name: str,
    csv_bytes: bytes = b"c\n1\n",
    **overrides: Any,
) -> DatasetVersionRecord:
    """Write a valid, discoverable version: a real CSV plus a matching sidecar.

    A ``PREPROCESS_RECIPE`` record additionally receives a synthetic immediate
    parent and a real, readable recipe artifact so the schema-1 creator-reference
    invariant holds and the version stays discoverable.
    """
    csv_rel = f"preprocessed/{name}.csv"
    (_pp(root) / f"{name}.csv").write_bytes(csv_bytes)
    if overrides.get("created_by") is CreationMechanism.PREPROCESS_RECIPE:
        overrides.setdefault(
            "parent",
            ParentRef(
                version_id=None,
                content_id=content_id_from_bytes(b"parent-" + name.encode()),
            ),
        )
        if "recipe" not in overrides:
            (root / "recipes").mkdir(parents=True, exist_ok=True)
            (root / "recipes" / f"{name}.json").write_bytes(b"{}")
            overrides["recipe"] = RecipeRef(
                digest="sha256:" + "0" * 64, relative_path=f"recipes/{name}.json"
            )
    record = _record(file_relative_path=csv_rel, **overrides)
    _write_sidecar(root, f"{name}.dqtv.json", to_mapping(record))
    return record


def _legacy_parent(tmp_path: Path) -> DatasetContext:
    src = tmp_path / "src" / "customers.csv"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"id,value\n1,10\n2,20\n")
    stat = src.stat()
    return DatasetContext(
        source_path=str(src),
        display_name="customers.csv",
        size_bytes=int(stat.st_size),
        modified_ns=int(stat.st_mtime_ns),
    )


def _confirm(
    root: Path, tmp_path: Path, *, label: str = "cleaned v2", stem: str = "customers"
) -> Any:
    return confirm_processed_version(
        workspace_root=str(root),
        csv_bytes=b"id,value\n1,10\n2,20\n",
        recipe={"schema_version": 1, "steps": []},
        parent=_legacy_parent(tmp_path),
        label=label,
        filename_stem=stem,
    )


class _ReversedScandir:
    """Context manager yielding directory entries in reversed order."""

    def __init__(self, entries: list[os.DirEntry[str]]) -> None:
        self._entries = entries

    def __enter__(self) -> Any:
        return iter(self._entries)

    def __exit__(self, *_: Any) -> Literal[False]:
        return False


def _patch_scandir_reversed(monkeypatch: pytest.MonkeyPatch) -> None:
    real = os.scandir

    def fake(path: Any) -> Any:
        with real(path) as iterator:
            entries = list(iterator)
        return _ReversedScandir(list(reversed(entries)))

    monkeypatch.setattr(dataset_discovery.os, "scandir", fake)


def _script_capture(monkeypatch: pytest.MonkeyPatch, script: dict[int, Any]) -> None:
    real = dataset_discovery._capture_identity
    state = {"n": 0}

    def fake(path: Any) -> Any:
        state["n"] += 1
        return script.get(state["n"]) or real(path)

    monkeypatch.setattr(dataset_discovery, "_capture_identity", fake)


def _patch_pp_resolve(monkeypatch: pytest.MonkeyPatch, *, occurrence: int, override: Any) -> None:
    real = dataset_discovery._resolve_strict
    state = {"seen": 0}

    def fake(path: Any) -> Any:
        if str(path).rstrip("/\\").endswith("preprocessed"):
            state["seen"] += 1
            if state["seen"] == occurrence:
                return override
        return real(path)

    monkeypatch.setattr(dataset_discovery, "_resolve_strict", fake)


# --- A. root and directory states -----------------------------------------


def test_blank_root_is_missing() -> None:
    result = discover_managed_versions("   ")
    assert result.root_status is RootStatus.MISSING
    assert result.root_reason == "ROOT_BLANK"
    assert result.versions == ()
    assert result.reopen_safe is False


def test_missing_root_is_missing(tmp_path: Path) -> None:
    result = discover_managed_versions(str(tmp_path / "nope"))
    assert result.root_status is RootStatus.MISSING
    assert result.reopen_safe is False


def test_non_directory_root(tmp_path: Path) -> None:
    file_root = tmp_path / "afile"
    file_root.write_bytes(b"x")
    result = discover_managed_versions(str(file_root))
    assert result.root_status is RootStatus.NOT_A_DIRECTORY


def test_root_permission_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _ws(tmp_path)
    monkeypatch.setattr(dataset_discovery, "_resolve_strict", lambda p: (None, "PERMISSION_DENIED"))
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.PERMISSION_DENIED
    assert result.root_reason == "ROOT_PERMISSION_DENIED"


def test_root_unresolvable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _ws(tmp_path)
    monkeypatch.setattr(dataset_discovery, "_resolve_strict", lambda p: (None, "UNRESOLVABLE"))
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.UNRESOLVABLE


def test_preprocessed_absent_is_proof_of_none(tmp_path: Path) -> None:
    root = _ws(tmp_path)  # no preprocessed directory at all
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.OK
    assert result.root_reason == "DISCOVERY_DIR_ABSENT"
    assert result.enumeration_complete is True
    assert result.result_complete is True
    assert result.reopen_safe is True
    assert result.versions == ()


def test_empty_preprocessed_is_complete_empty(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _pp(root)
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.OK
    assert result.root_reason == ""
    assert result.reopen_safe is True
    assert result.versions == ()
    assert result.entries_observed == 0


def test_preprocessed_regular_file_is_not_a_directory(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    (root / "preprocessed").write_bytes(b"not a dir")
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.NOT_A_DIRECTORY
    assert result.root_reason == "DISCOVERY_DIR_NOT_A_DIRECTORY"


def test_preprocessed_permission_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _ws(tmp_path)
    denied = os.fspath(root.resolve() / "preprocessed")
    real_lstat = os.lstat

    # Deny only the discovery directory. ``os`` is the global module, and POSIX
    # ``Path.resolve`` walks the root through ``os.lstat``; denying every call
    # would make the root itself unresolvable instead.
    def fake_lstat(path: Any, *args: Any, **kwargs: Any) -> Any:
        if os.fspath(path) == denied:
            raise PermissionError("denied")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(dataset_discovery.os, "lstat", fake_lstat)
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.PERMISSION_DENIED
    assert result.root_reason == "DISCOVERY_DIR_PERMISSION_DENIED"


def test_dangling_preprocessed_is_not_absent(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    link = root / "preprocessed"
    try:
        link.symlink_to(root / "missing_target", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted on this host")
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.UNRESOLVABLE
    assert result.root_reason == "DISCOVERY_DIR_DANGLING"
    assert result.reopen_safe is False


def test_confined_linked_directory_is_scanned(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    real_dir = root / "real_preprocessed"
    real_dir.mkdir()
    try:
        (root / "preprocessed").symlink_to(real_dir, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted on this host")
    (real_dir / "a.csv").write_bytes(b"c\n1\n")
    record = _record(file_relative_path="preprocessed/a.csv")
    (real_dir / "a.dqtv.json").write_text(json.dumps(to_mapping(record)), encoding="utf-8")
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.OK
    assert result.records_returned == 1


def test_escaping_linked_directory_is_unsafe(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "preprocessed").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted on this host")
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.UNSAFE_DISCOVERY_DIRECTORY
    assert result.reopen_safe is False


def test_discovery_directory_resolving_outside_root_is_unsafe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Host-independent coverage of the prepare-time confinement branch: the
    # lexical entry exists, but its resolved target lands outside the root.
    root = _ws(tmp_path)
    _pp(root)
    _patch_pp_resolve(monkeypatch, occurrence=1, override=(tmp_path, None))
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.UNSAFE_DISCOVERY_DIRECTORY
    assert result.root_reason == "DISCOVERY_DIR_OUTSIDE_ROOT"
    assert result.reopen_safe is False


def test_directory_changed_before_enumeration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="one")
    _script_capture(monkeypatch, {2: (dataset_discovery._DirIdentity(999, 999), None)})
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.DIRECTORY_CHANGED
    assert result.root_reason == "DISCOVERY_DIR_PRECHECK_REPLACED"
    assert result.versions == ()


def test_directory_changed_after_enumeration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="one")
    _script_capture(monkeypatch, {3: (dataset_discovery._DirIdentity(999, 999), None)})
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.DIRECTORY_CHANGED
    assert result.root_reason == "DISCOVERY_DIR_POSTCHECK_REPLACED"
    assert result.versions == ()
    assert result.reopen_safe is False


def test_directory_vanished_on_postcheck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="one")
    _patch_pp_resolve(monkeypatch, occurrence=3, override=(None, "MISSING"))
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.DIRECTORY_CHANGED
    assert result.root_reason == "DISCOVERY_DIR_POSTCHECK_VANISHED"


def test_directory_retargeted_on_precheck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="one")
    _patch_pp_resolve(monkeypatch, occurrence=2, override=(tmp_path, None))
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.DIRECTORY_CHANGED
    assert result.root_reason == "DISCOVERY_DIR_PRECHECK_RETARGETED"


def test_directory_identity_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _ws(tmp_path)
    _pp(root)
    _script_capture(monkeypatch, {1: (None, "IDENTITY_UNAVAILABLE")})
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.DIRECTORY_CHANGED
    assert result.root_reason == "DISCOVERY_DIR_IDENTITY_UNAVAILABLE"


# --- B. enumeration -------------------------------------------------------


def test_normal_complete_discovery(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="alpha")
    _write_valid(root, name="beta")
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.OK
    assert result.records_returned == 2
    assert result.enumeration_complete is True
    assert result.sidecars_parsed == 2


def test_confirmation_output_round_trip(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    outcome = _confirm(root, tmp_path)
    assert outcome.confirmed is True
    result = discover_managed_versions(str(root))
    assert result.records_returned == 1
    version = result.versions[0]
    assert version.csv_status == "ARTIFACT_OK"
    assert version.recipe_status == "ARTIFACT_OK"
    assert version.display.status_label == "Managed version"
    assert version.display.label == "cleaned v2"


def test_entry_cap_fails_closed(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    pp = _pp(root)
    for index in range(4):
        (pp / f"plain_{index}.txt").write_bytes(b"x")
    result = discover_managed_versions(str(root), bounds=DiscoveryBounds(max_entries=3))
    assert result.root_status is RootStatus.LIMIT_EXCEEDED
    assert result.entries_observed == 3
    assert result.versions == ()
    assert result.omitted_count is None


def test_sidecar_candidate_cap_fails_closed(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    for index in range(3):
        _write_sidecar(root, f"s{index}.dqtv.json", b"{}")
    result = discover_managed_versions(str(root), bounds=DiscoveryBounds(max_sidecar_candidates=2))
    assert result.root_status is RootStatus.LIMIT_EXCEEDED
    assert result.candidates_retained == 2
    assert result.versions == ()
    assert result.omitted_count is None


def test_deterministic_under_permuted_enumeration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    for name in ("a", "b", "c"):
        _write_valid(root, name=name, label=f"label {name}")
    natural = discover_managed_versions(str(root))
    _patch_scandir_reversed(monkeypatch)
    reversed_order = discover_managed_versions(str(root))
    natural_ids = [v.record.version_id for v in natural.versions]
    reversed_ids = [v.record.version_id for v in reversed_order.versions]
    assert natural_ids == reversed_ids


# --- C. parsing and schema ------------------------------------------------


def test_malformed_utf8_is_corrupt(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_sidecar(root, "bad.dqtv.json", b"\xff\xfe\x00not utf8")
    result = discover_managed_versions(str(root))
    assert result.records_returned == 0
    assert len(result.issues) == 1
    assert result.issues[0].status is RecordStatus.CORRUPT
    assert result.issues[0].reason_code == "CORRUPT_ENCODING"


def test_invalid_json_is_corrupt(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_sidecar(root, "bad.dqtv.json", b"{not json")
    result = discover_managed_versions(str(root))
    assert result.issues[0].reason_code == "CORRUPT_JSON"


def test_non_mapping_json_is_corrupt(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_sidecar(root, "bad.dqtv.json", b"[1, 2, 3]")
    result = discover_managed_versions(str(root))
    assert result.issues[0].reason_code == "CORRUPT_STRUCTURE"


def test_missing_schema_version_is_corrupt(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    mapping = to_mapping(_record())
    del mapping["schema_version"]
    _write_sidecar(root, "bad.dqtv.json", mapping)
    result = discover_managed_versions(str(root))
    assert result.issues[0].reason_code == "CORRUPT_SCHEMA_MISSING"


@pytest.mark.parametrize(
    "mutate",
    [
        {"version_id": "not-a-uuid"},
        {"created_at": "not-a-timestamp"},
        {"file_relative_path": "../escape.csv"},
    ],
)
def test_schema_field_violations_are_corrupt(tmp_path: Path, mutate: dict[str, Any]) -> None:
    root = _ws(tmp_path)
    mapping = to_mapping(_record())
    mapping.update(mutate)
    _write_sidecar(root, "bad.dqtv.json", mapping)
    result = discover_managed_versions(str(root))
    assert result.records_returned == 0
    assert result.issues[0].status is RecordStatus.CORRUPT
    assert result.issues[0].reason_code == "CORRUPT_SCHEMA"


def test_unsupported_schema_version(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    mapping = to_mapping(_record())
    mapping["schema_version"] = 2
    _write_sidecar(root, "future.dqtv.json", mapping)
    result = discover_managed_versions(str(root))
    assert result.records_returned == 0
    assert result.issues[0].status is RecordStatus.UNSUPPORTED
    assert result.issues[0].reason_code == "UNSUPPORTED_SCHEMA"
    # The claimed schema version is never exposed.
    assert "2" not in result.issues[0].label


def test_oversized_sidecar_is_corrupt(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_sidecar(root, "big.dqtv.json", json.dumps(to_mapping(_record())).encode())
    result = discover_managed_versions(str(root), bounds=DiscoveryBounds(max_sidecar_bytes=10))
    assert result.issues[0].reason_code == "CORRUPT_OVERSIZE"


def test_unknown_extra_fields_are_tolerated(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")
    mapping = to_mapping(_record(file_relative_path="preprocessed/a.csv"))
    mapping["unknown_future_field"] = {"nested": True}
    _write_sidecar(root, "extra.dqtv.json", mapping)
    result = discover_managed_versions(str(root))
    # Both the plain valid record and the extra-field one parse and are valid.
    assert result.records_returned == 2


# --- D. artifact availability ---------------------------------------------


def test_missing_csv_makes_record_unavailable(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _record(file_relative_path="preprocessed/missing.csv")
    _write_sidecar(root, "s.dqtv.json", to_mapping(record))
    result = discover_managed_versions(str(root))
    assert result.records_returned == 0
    assert result.issues[0].status is RecordStatus.UNAVAILABLE
    assert result.issues[0].reason_code == "ARTIFACT_VANISHED"


def test_empty_csv_is_unavailable(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    (_pp(root) / "empty.csv").write_bytes(b"")
    record = _record(file_relative_path="preprocessed/empty.csv")
    _write_sidecar(root, "s.dqtv.json", to_mapping(record))
    result = discover_managed_versions(str(root))
    assert result.issues[0].reason_code == "ARTIFACT_EMPTY"


def test_non_regular_csv_target_is_unavailable(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    (_pp(root) / "adir").mkdir()
    record = _record(file_relative_path="preprocessed/adir")
    _write_sidecar(root, "s.dqtv.json", to_mapping(record))
    result = discover_managed_versions(str(root))
    assert result.issues[0].reason_code == "ARTIFACT_NOT_REGULAR_FILE"


def test_csv_permission_denied_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")
    target = str((root / "preprocessed" / "a.csv").resolve())
    real_open = open

    def fake_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if str(file) == target:
            raise PermissionError("denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)
    result = discover_managed_versions(str(root))
    assert result.issues[0].reason_code == "ARTIFACT_PERMISSION_DENIED"


def test_csv_sharing_violation_is_locked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")
    target = str((root / "preprocessed" / "a.csv").resolve())
    real_open = open

    def fake_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if str(file) == target:
            err = OSError("sharing violation")
            setattr(err, "winerror", 32)  # noqa: B010
            raise err
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)
    result = discover_managed_versions(str(root))
    assert result.issues[0].reason_code == "ARTIFACT_LOCKED"


def test_csv_vanished_between_stat_and_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")
    target = str((root / "preprocessed" / "a.csv").resolve())
    real_open = open

    def fake_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if str(file) == target:
            raise FileNotFoundError("vanished")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)
    result = discover_managed_versions(str(root))
    assert result.issues[0].reason_code == "ARTIFACT_VANISHED"


def test_artifact_open_reads_one_byte_with_no_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")
    target = str((root / "preprocessed" / "a.csv").resolve())
    calls: list[int] = []
    real_open = open

    def fake_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        handle = real_open(file, *args, **kwargs)
        if str(file) == target:
            calls.append(1)
            original_read = handle.read

            def spy_read(size: int = -1) -> Any:
                assert size == 1
                return original_read(size)

            handle.read = spy_read
        return handle

    monkeypatch.setattr("builtins.open", fake_open)
    result = discover_managed_versions(str(root))
    assert result.records_returned == 1
    assert calls == [1]  # opened exactly once, no retries


def test_recipe_absent_on_root_import_is_valid(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a", created_by=CreationMechanism.ROOT_IMPORT)
    result = discover_managed_versions(str(root))
    assert result.records_returned == 1
    assert result.versions[0].recipe_status == "RECIPE_ABSENT"
    assert result.versions[0].display.kind_label == "Imported root"


def test_recipe_reference_present_but_missing_is_unavailable(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    (_pp(root) / "a.csv").write_bytes(b"c\n1\n")
    record = _record(
        file_relative_path="preprocessed/a.csv",
        created_by=CreationMechanism.PREPROCESS_RECIPE,
        parent=ParentRef(version_id=None, content_id=content_id_from_bytes(b"parent")),
        recipe=RecipeRef(digest=recipe_digest({"op": "x"}), relative_path="recipes/missing.json"),
    )
    _write_sidecar(root, "a.dqtv.json", to_mapping(record))
    result = discover_managed_versions(str(root))
    assert result.records_returned == 0
    assert result.issues[0].status is RecordStatus.UNAVAILABLE


# --- D2. which reference an unavailable issue is about ---------------------
#
# The two artifact probes deliberately share their reason codes, so the artifact
# kind is the only thing that keeps "the dataset is gone" and "the recipe is
# gone" apart for a downstream reader.


def test_missing_csv_issue_names_the_csv_reference(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _record(file_relative_path="preprocessed/missing.csv")
    _write_sidecar(root, "s.dqtv.json", to_mapping(record))
    result = discover_managed_versions(str(root))
    assert result.issues[0].status is RecordStatus.UNAVAILABLE
    assert result.issues[0].artifact_kind == ARTIFACT_KIND_CSV


def test_missing_recipe_issue_names_the_recipe_reference(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    (_pp(root) / "a.csv").write_bytes(b"c\n1\n")
    record = _record(
        file_relative_path="preprocessed/a.csv",
        created_by=CreationMechanism.PREPROCESS_RECIPE,
        parent=ParentRef(version_id=None, content_id=content_id_from_bytes(b"parent")),
        recipe=RecipeRef(digest=recipe_digest({"op": "x"}), relative_path="recipes/missing.json"),
    )
    _write_sidecar(root, "a.dqtv.json", to_mapping(record))
    result = discover_managed_versions(str(root))
    assert result.issues[0].status is RecordStatus.UNAVAILABLE
    assert result.issues[0].artifact_kind == ARTIFACT_KIND_RECIPE


def test_the_two_missing_reference_issues_share_a_reason_code_but_not_a_kind(
    tmp_path: Path,
) -> None:
    csv_root = _ws(tmp_path / "a")
    _write_sidecar(
        csv_root, "s.dqtv.json", to_mapping(_record(file_relative_path="preprocessed/gone.csv"))
    )
    recipe_root = _ws(tmp_path / "b")
    (_pp(recipe_root) / "a.csv").write_bytes(b"c\n1\n")
    _write_sidecar(
        recipe_root,
        "a.dqtv.json",
        to_mapping(
            _record(
                file_relative_path="preprocessed/a.csv",
                created_by=CreationMechanism.PREPROCESS_RECIPE,
                parent=ParentRef(version_id=None, content_id=content_id_from_bytes(b"p")),
                recipe=RecipeRef(
                    digest=recipe_digest({"op": "x"}), relative_path="recipes/gone.json"
                ),
            )
        ),
    )

    csv_issue = discover_managed_versions(str(csv_root)).issues[0]
    recipe_issue = discover_managed_versions(str(recipe_root)).issues[0]

    assert csv_issue.reason_code == recipe_issue.reason_code == "ARTIFACT_VANISHED"
    assert csv_issue.artifact_kind != recipe_issue.artifact_kind


def test_a_sidecar_parse_issue_names_no_artifact_reference(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_sidecar(root, "bad.dqtv.json", b"{not json")
    result = discover_managed_versions(str(root))
    assert result.issues[0].status is RecordStatus.CORRUPT
    assert result.issues[0].artifact_kind == ARTIFACT_KIND_NONE


def test_artifact_kind_is_a_closed_value_free_token(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_sidecar(
        root, "s.dqtv.json", to_mapping(_record(file_relative_path="preprocessed/gone.csv"))
    )
    _write_sidecar(root, "bad.dqtv.json", b"{not json")
    result = discover_managed_versions(str(root))
    kinds = {issue.artifact_kind for issue in result.issues}
    assert kinds <= {ARTIFACT_KIND_NONE, ARTIFACT_KIND_CSV, ARTIFACT_KIND_RECIPE}
    assert all("/" not in kind and "\\" not in kind for kind in kinds)


# --- E. duplicate quarantine ----------------------------------------------


def test_identical_duplicate_group_is_quarantined(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    mapping = to_mapping(_record())
    _write_sidecar(root, "d1.dqtv.json", mapping)
    _write_sidecar(root, "d2.dqtv.json", mapping)
    result = discover_managed_versions(str(root))
    assert result.records_returned == 0
    assert result.duplicate_group_count == 1
    assert result.duplicate_member_count == 2
    assert result.duplicates[0].kind == "duplicate_identical"


def test_conflicting_duplicate_group_is_quarantined(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    vid = new_version_id()
    fid = new_family_id()
    base = to_mapping(_record(version_id=vid, family_id=fid, label="A"))
    conflict = dict(base)
    conflict["label"] = "B"
    _write_sidecar(root, "d1.dqtv.json", base)
    _write_sidecar(root, "d2.dqtv.json", conflict)
    result = discover_managed_versions(str(root))
    assert result.records_returned == 0
    assert result.duplicates[0].kind == "duplicate_conflict"


def test_unavailable_member_still_quarantines_group(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    vid = new_version_id()
    # Neither member's CSV exists; the whole identity is still quarantined.
    _write_sidecar(root, "d1.dqtv.json", to_mapping(_record(version_id=vid, label="A")))
    _write_sidecar(root, "d2.dqtv.json", to_mapping(_record(version_id=vid, label="B")))
    result = discover_managed_versions(str(root))
    assert result.records_returned == 0
    assert result.duplicate_group_count == 1


def test_duplicate_group_has_no_canonical_member(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    mapping = to_mapping(_record())
    _write_sidecar(root, "d1.dqtv.json", mapping)
    _write_sidecar(root, "d2.dqtv.json", mapping)
    result = discover_managed_versions(str(root))
    group = result.duplicates[0]
    assert not hasattr(group, "canonical")
    assert not hasattr(group, "selected")
    assert not hasattr(group, "canonical_member")


def test_trusted_versions_unique_and_disjoint_from_duplicates(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="solo")
    mapping = to_mapping(_record())
    _write_sidecar(root, "d1.dqtv.json", mapping)
    _write_sidecar(root, "d2.dqtv.json", mapping)
    result = discover_managed_versions(str(root))
    version_ids = [v.record.version_id for v in result.versions]
    assert len(version_ids) == len(set(version_ids))
    duplicate_ids = {loc.version_id for g in result.duplicates for loc in g.internal_members}
    assert set(version_ids).isdisjoint(duplicate_ids)


# --- F. privacy -----------------------------------------------------------


def test_operator_label_path_is_reduced_to_basename(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a", label=rf"{_PRIVATE_DIR}\leaky.csv")
    result = discover_managed_versions(str(root))
    label = result.versions[0].display.label
    assert label == "leaky.csv"
    assert _PRIVATE_DIR not in label


def test_version_display_never_exposes_full_identifiers(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    record = _write_valid(root, name="a", label="orders")
    result = discover_managed_versions(str(root))
    display = result.versions[0].display
    combined = " ".join(
        (display.label, display.short_version_id, display.status_label, display.kind_label)
    )
    assert record.version_id not in combined
    assert record.content_id not in combined
    assert record.family_id not in combined
    assert display.short_version_id.startswith("v-")
    assert len(display.short_version_id) <= len("v-") + 12


def test_issue_and_duplicate_references_are_opaque_ordinals(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_sidecar(root, "bad.dqtv.json", b"{not json")
    mapping = to_mapping(_record())
    _write_sidecar(root, "d1.dqtv.json", mapping)
    _write_sidecar(root, "d2.dqtv.json", mapping)
    result = discover_managed_versions(str(root))
    assert result.issues[0].reference == "issue-0001"
    dup_refs = result.duplicates[0].member_references
    assert dup_refs == ("duplicate-0001", "duplicate-0002")
    vid = mapping["version_id"]
    for reference in (result.issues[0].reference, *dup_refs):
        assert vid not in reference
        assert "preprocessed" not in reference


def test_issues_expose_no_untrusted_label(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    mapping = to_mapping(_record())
    mapping["label"] = "SECRET_SOURCE_NAME"
    del mapping["version_id"]  # now corrupt, but its label must not leak
    _write_sidecar(root, "bad.dqtv.json", mapping)
    result = discover_managed_versions(str(root))
    issue = result.issues[0]
    assert issue.label == "Unreadable version record"
    assert "SECRET_SOURCE_NAME" not in issue.label
    assert "SECRET_SOURCE_NAME" not in issue.reason_code


def test_total_private_sort_key_handles_unresolved_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    _write_sidecar(root, "unresolved.dqtv.json", b"{}")
    _write_sidecar(root, "plain.dqtv.json", b"{not json")
    real = dataset_discovery._resolve_strict

    def fake(path: Any) -> Any:
        if str(path).endswith("unresolved.dqtv.json"):
            return (None, "MISSING")
        return real(path)

    monkeypatch.setattr(dataset_discovery, "_resolve_strict", fake)
    result = discover_managed_versions(str(root))
    # Both issues are ordered and referenced without a resolved path for one.
    assert {issue.reference for issue in result.issues} == {"issue-0001", "issue-0002"}


def test_confirmation_paths_absent_from_operator_output(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _confirm(root, tmp_path)
    result = discover_managed_versions(str(root))
    display = result.versions[0].display
    for field in (
        display.label,
        display.short_version_id,
        display.status_label,
        display.kind_label,
    ):
        assert str(root) not in field
        assert "preprocessed" not in field


# --- G. filtering and ordering --------------------------------------------


def test_family_filter(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    keep = new_family_id()
    _write_valid(root, name="a", family_id=keep, label="A")
    _write_valid(root, name="b", family_id=new_family_id(), label="B")
    result = discover_managed_versions(str(root), filters=DiscoveryFilters(family_id=keep))
    assert result.records_returned == 1
    assert result.versions[0].record.family_id == keep


def test_version_filter(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    vid = new_version_id()
    _write_valid(root, name="a", version_id=vid)
    _write_valid(root, name="b")
    result = discover_managed_versions(str(root), filters=DiscoveryFilters(version_id=vid))
    assert result.records_returned == 1


def test_created_by_and_roots_only_filters(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="root_one", created_by=CreationMechanism.ROOT_IMPORT)
    _write_valid(root, name="proc_one", created_by=CreationMechanism.PREPROCESS_RECIPE)
    roots = discover_managed_versions(str(root), filters=DiscoveryFilters(roots_only=True))
    assert roots.records_returned == 1
    assert roots.versions[0].record.created_by is CreationMechanism.ROOT_IMPORT
    processed = discover_managed_versions(
        str(root), filters=DiscoveryFilters(created_by="preprocess_recipe")
    )
    assert processed.records_returned == 1


def test_parent_version_filter(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    parent_vid = new_version_id()
    _write_valid(
        root,
        name="child",
        created_by=CreationMechanism.PREPROCESS_RECIPE,
        parent=ParentRef(version_id=parent_vid, content_id=content_id_from_bytes(b"p")),
    )
    _write_valid(root, name="orphan")
    result = discover_managed_versions(
        str(root), filters=DiscoveryFilters(parent_version_id=parent_vid)
    )
    assert result.records_returned == 1


def test_status_filter_valid_only(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")
    excluded = discover_managed_versions(str(root), filters=DiscoveryFilters(statuses=("corrupt",)))
    assert excluded.records_returned == 0
    included = discover_managed_versions(str(root), filters=DiscoveryFilters(statuses=("valid",)))
    assert included.records_returned == 1


def test_malformed_filter_returns_empty_with_reason(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")
    result = discover_managed_versions(str(root), filters=DiscoveryFilters(family_id="not-a-uuid"))
    assert result.records_returned == 0
    assert "FILTER_INVALID_FAMILY_ID" in result.reason_codes


def test_newest_first_ordering(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="old", created_at=datetime(2026, 1, 1, tzinfo=UTC), label="old")
    _write_valid(root, name="new", created_at=datetime(2026, 6, 1, tzinfo=UTC), label="new")
    result = discover_managed_versions(str(root))
    assert result.versions[0].display.label == "new"
    assert result.versions[1].display.label == "old"


def test_duplicates_never_enter_filtered_versions(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    fam = new_family_id()
    mapping = to_mapping(_record(family_id=fam))
    _write_sidecar(root, "d1.dqtv.json", mapping)
    _write_sidecar(root, "d2.dqtv.json", mapping)
    result = discover_managed_versions(str(root), filters=DiscoveryFilters(family_id=fam))
    assert result.records_returned == 0
    assert result.duplicate_group_count == 1


# --- H. purity and immutability -------------------------------------------


def test_result_types_are_frozen(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")
    result = discover_managed_versions(str(root))
    with pytest.raises(FrozenInstanceError):
        result.reopen_safe = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.versions[0].display.label = "x"  # type: ignore[misc]


def test_discovery_leaves_the_tree_unchanged(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")
    _write_sidecar(root, "bad.dqtv.json", b"{not json")
    before = {p: p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
    discover_managed_versions(str(root))
    after = {p: p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
    assert before == after


def test_repeated_discovery_is_equal(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")
    _write_valid(root, name="b")
    assert discover_managed_versions(str(root)) == discover_managed_versions(str(root))


def test_bounds_validation_rejects_out_of_range() -> None:
    with pytest.raises(DiscoveryConfigError):
        DiscoveryBounds(max_entries=0)
    with pytest.raises(DiscoveryConfigError):
        DiscoveryBounds(max_entries=10_001)
    with pytest.raises(DiscoveryConfigError):
        DiscoveryBounds(max_sidecar_bytes=2_000_000)
    with pytest.raises(DiscoveryConfigError):
        DiscoveryBounds(max_entries=True)


def test_module_has_no_forbidden_imports() -> None:
    tree = ast.parse(Path(dataset_discovery.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(alias.name for alias in node.names)
    forbidden = {
        "streamlit",
        "pandas",
        "data_quality_toolkit.adapters.ui.services.dataset_activation",
        "data_quality_toolkit.adapters.ui.state.context",
        "data_quality_toolkit.adapters.ui.state.keys",
        "DatasetContext",
    }
    for name in imported:
        assert name not in forbidden
        assert not name.startswith("data_quality_toolkit.adapters.ui.pages")
        assert not name.startswith("streamlit")


# --- I. deep-JSON fail-closed (host-independent) --------------------------

# Far above the default recursion limit (1000) yet a few tens of KiB on disk,
# so it is comfortably inside the 1 MiB sidecar byte cap. The bytes are built
# directly (never via ``json.dumps`` of a Python object, which would itself
# recurse) so real, deeply nested JSON reaches the production loader.
_DEEP_NESTING = 20_000


def _deep_array_bytes(depth: int) -> bytes:
    return b"[" * depth + b"]" * depth


def _deep_object_bytes(depth: int) -> bytes:
    return b'{"a":' * depth + b"0" + b"}" * depth


def _public_strings(result: Any) -> list[str]:
    """Every operator-facing string field of a result (never internals)."""
    fields = [result.root_reason, *result.reason_codes]
    for issue in result.issues:
        fields.extend((issue.reference, issue.label, issue.reason_code))
    for group in result.duplicates:
        fields.extend((group.kind, group.short_version_id, *group.member_references))
    return fields


def test_deeply_nested_array_is_corrupt_json_depth(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    payload = _deep_array_bytes(_DEEP_NESTING)
    assert len(payload) < DiscoveryBounds().max_sidecar_bytes
    _write_sidecar(root, "deep_array.dqtv.json", payload)
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.OK
    assert result.records_returned == 0
    assert len(result.issues) == 1
    assert result.issues[0].status is RecordStatus.CORRUPT
    assert result.issues[0].reason_code == "CORRUPT_JSON_DEPTH"
    assert result.issues[0].label == "Unreadable version record"


def test_deeply_nested_object_is_corrupt_json_depth(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    payload = _deep_object_bytes(_DEEP_NESTING)
    assert len(payload) < DiscoveryBounds().max_sidecar_bytes
    _write_sidecar(root, "deep_object.dqtv.json", payload)
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.OK
    assert result.records_returned == 0
    assert len(result.issues) == 1
    assert result.issues[0].status is RecordStatus.CORRUPT
    assert result.issues[0].reason_code == "CORRUPT_JSON_DEPTH"


def test_deep_json_does_not_abort_discovery(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="ok", label="good one")
    _write_sidecar(root, "deep.dqtv.json", _deep_object_bytes(_DEEP_NESTING))
    result = discover_managed_versions(str(root))
    # The corrupt-by-depth sidecar is classified, the valid one still returns.
    assert result.root_status is RootStatus.OK
    assert result.records_returned == 1
    assert result.versions[0].display.label == "good one"
    depth_issues = [i for i in result.issues if i.reason_code == "CORRUPT_JSON_DEPTH"]
    assert len(depth_issues) == 1
    assert depth_issues[0].status is RecordStatus.CORRUPT


def test_deep_json_exposes_no_raw_recursion_text(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_sidecar(root, "deep.dqtv.json", _deep_array_bytes(_DEEP_NESTING))
    result = discover_managed_versions(str(root))
    combined = " ".join(_public_strings(result)).lower()
    assert "recursion" not in combined
    assert "maximum" not in combined
    assert "depth exceeded" not in combined


def test_deep_json_discovery_is_repeatable(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="ok")
    _write_sidecar(root, "deep.dqtv.json", _deep_array_bytes(_DEEP_NESTING))
    assert discover_managed_versions(str(root)) == discover_managed_versions(str(root))


# --- J. confinement fault injection (host-independent, non-skipped) --------

# These exercise the security-relevant confinement branches deterministically,
# with no symlink/junction creation, Developer Mode, or elevated privileges.
# They inject resolution outcomes into the single canonical resolver so the
# real production branch runs.


def _redirect_dir_resolve(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    """Redirect every strict resolution of the lexical ``preprocessed`` entry to
    ``target`` (an already-resolved directory), a deterministic stand-in for a
    directory link. All other resolutions run for real."""
    real = dataset_discovery._resolve_strict

    def fake(path: Any) -> Any:
        if str(path).rstrip("/\\").endswith("preprocessed"):
            return target, None
        return real(path)

    monkeypatch.setattr(dataset_discovery, "_resolve_strict", fake)


def _redirect_named_resolve(
    monkeypatch: pytest.MonkeyPatch, *, name: str, parent: str, target: Path
) -> None:
    """Redirect the strict resolution of a single artifact (matched by file name
    and immediate parent directory name) to ``target``. All else runs for real."""
    real = dataset_discovery._resolve_strict

    def fake(path: Any) -> Any:
        candidate = Path(path)
        if candidate.name == name and candidate.parent.name == parent:
            return target, None
        return real(path)

    monkeypatch.setattr(dataset_discovery, "_resolve_strict", fake)


def test_lexical_present_but_unresolvable_is_dangling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The lexical `preprocessed` entry exists (lstat passes) but strict
    # resolution fails: a dangling directory link, host-independent.
    root = _ws(tmp_path)
    _pp(root)
    _patch_pp_resolve(monkeypatch, occurrence=1, override=(None, "MISSING"))
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.UNRESOLVABLE
    assert result.root_reason == "DISCOVERY_DIR_DANGLING"
    assert result.versions == ()
    assert result.records_returned == 0
    assert result.enumeration_complete is False
    assert result.result_complete is False
    assert result.reopen_safe is False


def test_confined_linked_directory_is_scanned_injected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The lexical `preprocessed` entry resolves to a *different* real directory
    # that is still inside the workspace root; identity checks pass and the
    # target is scanned successfully.
    root = _ws(tmp_path)
    lexical_pp = _pp(root)
    (lexical_pp / "a.csv").write_bytes(b"c\n1\n")  # artifact under the lexical dir
    target = root / "linked_target"
    target.mkdir()
    record = _record(file_relative_path="preprocessed/a.csv")
    (target / "a.dqtv.json").write_text(json.dumps(to_mapping(record)), encoding="utf-8")
    resolved_target = target.resolve(strict=True)
    assert dataset_discovery._is_confined(resolved_target, root.resolve(strict=True))
    _redirect_dir_resolve(monkeypatch, resolved_target)
    result = discover_managed_versions(str(root))
    assert result.root_status is RootStatus.OK
    assert result.records_returned == 1
    assert result.versions[0].csv_status == "ARTIFACT_OK"


def test_sidecar_resolving_outside_root_is_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    _write_sidecar(root, "escape.dqtv.json", b"{}")  # real entry so scandir sees it
    outside = tmp_path / "outside_sidecar.json"
    outside.write_bytes(b"{}")
    outside_resolved = outside.resolve(strict=True)
    _redirect_named_resolve(
        monkeypatch, name="escape.dqtv.json", parent="preprocessed", target=outside_resolved
    )
    result = discover_managed_versions(str(root))
    assert result.records_returned == 0
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.status is RecordStatus.CORRUPT
    assert issue.reason_code == "CORRUPT_SIDECAR_UNSAFE_PATH"
    for field in (issue.reference, issue.label, issue.reason_code):
        assert str(outside_resolved) not in field
        assert "outside_sidecar" not in field


def test_csv_resolving_outside_root_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    _write_valid(root, name="a")  # real preprocessed/a.csv + a.dqtv.json
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"c\n1\n")
    outside_resolved = outside.resolve(strict=True)
    _redirect_named_resolve(
        monkeypatch, name="a.csv", parent="preprocessed", target=outside_resolved
    )
    result = discover_managed_versions(str(root))
    assert result.records_returned == 0
    assert len(result.issues) == 1
    assert result.issues[0].status is RecordStatus.UNAVAILABLE
    assert result.issues[0].reason_code == "ARTIFACT_UNSAFE_PATH"


def test_recipe_resolving_outside_root_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _ws(tmp_path)
    (_pp(root) / "a.csv").write_bytes(b"c\n1\n")
    (root / "recipes").mkdir()
    (root / "recipes" / "r.json").write_bytes(b"{}")  # real recipe; only confinement fails
    record = _record(
        file_relative_path="preprocessed/a.csv",
        created_by=CreationMechanism.PREPROCESS_RECIPE,
        parent=ParentRef(version_id=None, content_id=content_id_from_bytes(b"parent")),
        recipe=RecipeRef(digest=recipe_digest({"op": "x"}), relative_path="recipes/r.json"),
    )
    _write_sidecar(root, "a.dqtv.json", to_mapping(record))
    outside = tmp_path / "outside_recipe.json"
    outside.write_bytes(b"{}")
    outside_resolved = outside.resolve(strict=True)
    _redirect_named_resolve(monkeypatch, name="r.json", parent="recipes", target=outside_resolved)
    result = discover_managed_versions(str(root))
    assert result.records_returned == 0
    assert len(result.issues) == 1
    assert result.issues[0].status is RecordStatus.UNAVAILABLE
    assert result.issues[0].reason_code == "ARTIFACT_UNSAFE_PATH"
