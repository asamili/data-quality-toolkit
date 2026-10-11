"""Unit tests for the root-first managed frame/assessment dispatcher.

Proves exact canonical key identity, session isolation, parser/assessment
fingerprint isolation, strict frame/assessment cache separation, FULL/LARGE
behavior including the exact byte boundary, cache-miss revalidation, stale
trust fail-closed behavior, privacy of every error surface, and invalidation.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.services import managed_frame_loader as mfl
from data_quality_toolkit.adapters.ui.services.managed_frame_loader import (
    MODE_FULL,
    MODE_LARGE,
    AssessmentKey,
    CanonicalFrameKey,
    ManagedFrameLoadError,
    clear_managed_caches,
    compute_assessment_fingerprint,
    compute_parser_fingerprint,
    get_managed_assessment,
    get_managed_frame,
    get_managed_header,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    ManagedTrustRoot,
    SessionCapability,
    commit_trust_root,
    ensure_session_capability,
    make_source_locator,
    retire_managed_trust,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT
from data_quality_toolkit.shared.managed_export_source import MANAGED_FULL_MAX_SOURCE_BYTES

_CONTENT = "sha256:" + "a" * 64
_CONTENT_OTHER = "sha256:" + "b" * 64
_ROOT_CONTENT = "sha256:" + "c" * 64


@pytest.fixture(autouse=True)
def _clean_caches() -> Iterator[None]:
    clear_managed_caches()
    yield
    clear_managed_caches()


def _write_csv(tmp_path: Path, relative: str = "versions/v1/data.csv") -> Path:
    target = tmp_path.joinpath(*relative.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    return target


def _commit_for_file(
    state: dict[str, Any],
    csv_path: Path,
    *,
    relative: str = "versions/v1/data.csv",
    large: bool = False,
    size_override: int | None = None,
    version_id: str | None = None,
    content_id: str = _CONTENT,
) -> ManagedTrustRoot:
    st = csv_path.stat()
    capability = ensure_session_capability(state)
    return commit_trust_root(
        state,
        capability,
        version_id=version_id or str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        content_id=content_id,
        root_content_id=_ROOT_CONTENT,
        parent_version_id=None,
        version_label="cleaned v2",
        locator=make_source_locator(
            display_name=csv_path.name,
            relative_posix=relative,
            absolute_path=str(csv_path.resolve()),
        ),
        size_bytes=size_override if size_override is not None else int(st.st_size),
        modified_ns=int(st.st_mtime_ns),
        large_file_mode=large,
    )


class _CountingReader:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, path: str, options: Mapping[str, Any] | None) -> pd.DataFrame:
        self.calls += 1
        return pd.read_csv(path, **dict(options or {}))


# --- A. Exact key identity and isolation -------------------------------------


def test_full_load_returns_dataframe_and_caches_under_exact_key(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv)
    reader = _CountingReader()

    first = get_managed_frame(state, reader=reader)
    second = get_managed_frame(state, reader=reader)

    assert isinstance(first, pd.DataFrame)
    assert second is first
    assert reader.calls == 1
    assert len(mfl._managed_frame_cache) == 1
    key = next(iter(mfl._managed_frame_cache))
    assert key.mode == MODE_FULL


def test_key_with_one_capability_cannot_hit_entry_of_another() -> None:
    cap_a, cap_b = SessionCapability(), SessionCapability()
    key_a = CanonicalFrameKey(cap_a, "v", "c", MODE_FULL, "fp")
    key_b = CanonicalFrameKey(cap_b, "v", "c", MODE_FULL, "fp")
    cache: dict[CanonicalFrameKey, str] = {key_a: "frame"}
    assert key_b not in cache
    assert key_a != key_b


def test_session_isolation_between_two_live_sessions(tmp_path: Path) -> None:
    csv = _write_csv(tmp_path)
    version = str(uuid.uuid4())
    state_one: dict[str, Any] = {}
    state_two: dict[str, Any] = {}
    _commit_for_file(state_one, csv, version_id=version)
    reader = _CountingReader()
    get_managed_frame(state_one, reader=reader)
    # Second session, same version/content identity, different capability.
    _commit_for_file(state_two, csv, version_id=version)
    get_managed_frame(state_two, reader=reader)
    assert reader.calls == 2  # no cross-session cache hit


@pytest.mark.parametrize(
    "mutation",
    [
        {"version_id": "other-version"},
        {"content_id": _CONTENT_OTHER},
        {"mode": MODE_LARGE},
        {"parser_fingerprint": "other-fp"},
    ],
)
def test_any_single_field_change_is_a_cache_miss(mutation: dict[str, str]) -> None:
    cap = SessionCapability()
    base = CanonicalFrameKey(cap, "version", _CONTENT, MODE_FULL, "fp")
    changed = CanonicalFrameKey(
        session_anchor=cap,
        version_id=mutation.get("version_id", "version"),
        content_id=mutation.get("content_id", _CONTENT),
        mode=mutation.get("mode", MODE_FULL),
        parser_fingerprint=mutation.get("parser_fingerprint", "fp"),
    )
    cache: dict[CanonicalFrameKey, str] = {base: "frame"}
    assert changed not in cache


def test_parser_fingerprint_change_causes_frame_miss(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv)
    reader = _CountingReader()
    get_managed_frame(state, parser_options={"sep": ","}, reader=reader)
    get_managed_frame(state, parser_options={"sep": ";"}, reader=reader)
    assert reader.calls == 2
    assert len(mfl._managed_frame_cache) == 2


def test_canonical_key_carries_no_filesystem_identity_fields() -> None:
    names = {f.name for f in __import__("dataclasses").fields(CanonicalFrameKey)}
    assert names == {"session_anchor", "version_id", "content_id", "mode", "parser_fingerprint"}
    assessment_names = {f.name for f in __import__("dataclasses").fields(AssessmentKey)}
    assert assessment_names == {"frame_key", "assessment_fingerprint"}


# --- B. Cache separation --------------------------------------------------------


def test_frame_cache_holds_dataframes_only(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv)
    get_managed_frame(state)
    get_managed_assessment(state, assessor=lambda frame: {"rows": int(len(frame))})
    assert all(isinstance(value, pd.DataFrame) for value in mfl._managed_frame_cache.values())
    assert all(
        isinstance(value, dict) and not isinstance(value, pd.DataFrame)
        for value in mfl._managed_assessment_cache.values()
    )


def test_assessment_result_that_is_a_dataframe_is_refused(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv)
    with pytest.raises(ManagedFrameLoadError) as excinfo:
        get_managed_assessment(state, assessor=lambda frame: frame)
    assert excinfo.value.reason_code == "ASSESSMENT_INVALID"
    assert len(mfl._managed_assessment_cache) == 0


def test_assessment_containing_dataframe_values_is_refused(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv)
    with pytest.raises(ManagedFrameLoadError) as excinfo:
        get_managed_assessment(state, assessor=lambda frame: {"frame": frame})
    assert excinfo.value.reason_code == "ASSESSMENT_INVALID"


def test_assessment_fingerprint_change_reruns_assessment(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv)
    calls: list[str] = []

    def assessor(frame: pd.DataFrame) -> dict[str, Any]:
        calls.append("run")
        return {"rows": int(len(frame))}

    get_managed_assessment(state, assessor=assessor, assessment_options={"rules": "v1"})
    get_managed_assessment(state, assessor=assessor, assessment_options={"rules": "v1"})
    assert calls == ["run"]  # exact-key hit
    get_managed_assessment(state, assessor=assessor, assessment_options={"rules": "v2"})
    assert calls == ["run", "run"]  # changed fingerprint never reuses stale assessment


def test_caches_are_bounded() -> None:
    cap = SessionCapability()
    for index in range(mfl._FRAME_CACHE_MAX_ENTRIES + 3):
        key = CanonicalFrameKey(cap, f"v{index}", _CONTENT, MODE_FULL, "fp")
        mfl._bounded_store(
            mfl._managed_frame_cache, key, pd.DataFrame(), mfl._FRAME_CACHE_MAX_ENTRIES
        )
    assert len(mfl._managed_frame_cache) <= mfl._FRAME_CACHE_MAX_ENTRIES


# --- C. FULL / LARGE behavior ------------------------------------------------------


def test_large_mode_never_materializes_and_never_enters_frame_cache(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv, large=True)
    with pytest.raises(ManagedFrameLoadError) as excinfo:
        get_managed_frame(state)
    assert excinfo.value.reason_code == "LARGE_MODE_REFUSED"
    assert len(mfl._managed_frame_cache) == 0


def test_large_header_only_is_refused(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv, large=True)
    with pytest.raises(ManagedFrameLoadError) as excinfo:
        get_managed_header(state)
    assert excinfo.value.reason_code == "LARGE_HEADER_REFUSED"


def test_large_assessment_is_refused(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv, large=True)
    with pytest.raises(ManagedFrameLoadError) as excinfo:
        get_managed_assessment(state, assessor=lambda frame: {})
    assert excinfo.value.reason_code == "LARGE_MODE_REFUSED"


def test_header_only_full_works(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv)
    assert get_managed_header(state) == ["a", "b"]
    assert len(mfl._managed_frame_cache) == 0  # header reads never cache a frame


def test_full_exactly_at_boundary_is_permitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv, size_override=MANAGED_FULL_MAX_SOURCE_BYTES)
    monkeypatch.setattr(mfl, "_revalidate", lambda root: None)
    frame = get_managed_frame(state, reader=lambda path, options: pd.DataFrame({"a": [1]}))
    assert isinstance(frame, pd.DataFrame)


def test_full_above_boundary_is_refused(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv, size_override=MANAGED_FULL_MAX_SOURCE_BYTES + 1)
    with pytest.raises(ManagedFrameLoadError) as excinfo:
        get_managed_frame(state)
    assert excinfo.value.reason_code == "FULL_SIZE_EXCEEDED"
    with pytest.raises(ManagedFrameLoadError):
        get_managed_header(state)


# --- D. Cache-miss revalidation ------------------------------------------------------


def test_cache_miss_revalidates_missing_source(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv)
    csv.unlink()
    with pytest.raises(ManagedFrameLoadError) as excinfo:
        get_managed_frame(state)
    assert excinfo.value.reason_code == "SOURCE_MISSING"


def test_cache_miss_revalidates_content_identity(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv)
    csv.write_text("a,b,c\n1,2,3\n", encoding="utf-8")  # replaced content
    with pytest.raises(ManagedFrameLoadError) as excinfo:
        get_managed_frame(state)
    assert excinfo.value.reason_code == "CONTENT_MISMATCH"


def test_cache_miss_revalidates_confinement(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    stray = tmp_path / "stray.csv"
    stray.write_text("a,b\n1,2\n", encoding="utf-8")
    # Locator claims a workspace-relative identity the artifact does not have.
    _commit_for_file(state, stray, relative="versions/v1/data.csv")
    with pytest.raises(ManagedFrameLoadError) as excinfo:
        get_managed_frame(state)
    assert excinfo.value.reason_code == "SOURCE_NOT_CONFINED"


# --- E. Stale / missing trust ----------------------------------------------------------


def test_no_trust_fails_closed() -> None:
    with pytest.raises(ManagedFrameLoadError) as excinfo:
        get_managed_frame({})
    assert excinfo.value.reason_code == "NO_VALID_TRUST"


def test_managed_mirror_without_trust_fails_closed() -> None:
    state: dict[str, Any] = {
        DATASET_CONTEXT: DatasetContext(
            source_path="C:/anywhere/data.csv",
            display_name="data.csv",
            size_bytes=1,
            modified_ns=1,
            managed=True,
            version_id=str(uuid.uuid4()),
            family_id=str(uuid.uuid4()),
            content_id=_CONTENT,
            root_content_id=_ROOT_CONTENT,
            version_label="v",
        )
    }
    with pytest.raises(ManagedFrameLoadError) as excinfo:
        get_managed_frame(state)
    assert excinfo.value.reason_code == "NO_VALID_TRUST"


def test_retired_trust_fails_closed(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv)
    retire_managed_trust(state)
    with pytest.raises(ManagedFrameLoadError) as excinfo:
        get_managed_frame(state)
    assert excinfo.value.reason_code == "NO_VALID_TRUST"


# --- F. Invalidation ----------------------------------------------------------------------


def test_retire_clears_both_caches(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv)
    get_managed_frame(state)
    get_managed_assessment(state, assessor=lambda frame: {"rows": int(len(frame))})
    assert mfl._managed_frame_cache and mfl._managed_assessment_cache
    retire_managed_trust(state)
    assert len(mfl._managed_frame_cache) == 0
    assert len(mfl._managed_assessment_cache) == 0


def test_version_switch_recommit_clears_both_caches(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv)
    get_managed_frame(state)
    get_managed_assessment(state, assessor=lambda frame: {"rows": int(len(frame))})
    _commit_for_file(state, csv, content_id=_CONTENT_OTHER)  # managed version switch
    assert len(mfl._managed_frame_cache) == 0
    assert len(mfl._managed_assessment_cache) == 0


def test_capability_replacement_makes_previous_keys_unreachable() -> None:
    old_cap, new_cap = SessionCapability(), SessionCapability()
    old_key = CanonicalFrameKey(old_cap, "v", _CONTENT, MODE_FULL, "fp")
    cache: dict[CanonicalFrameKey, str] = {old_key: "frame"}
    replayed = CanonicalFrameKey(new_cap, "v", _CONTENT, MODE_FULL, "fp")
    assert replayed not in cache  # identity anchor gone -> unreachable forever


# --- G. Fingerprints and privacy -------------------------------------------------------------


def test_fingerprints_are_deterministic_and_contract_separated() -> None:
    assert compute_parser_fingerprint({"sep": ","}) == compute_parser_fingerprint({"sep": ","})
    assert compute_parser_fingerprint({"sep": ","}) != compute_parser_fingerprint({"sep": ";"})
    assert compute_assessment_fingerprint({"r": 1}) != compute_parser_fingerprint({"r": 1})
    assert len(compute_parser_fingerprint()) == 64
    assert compute_parser_fingerprint() != compute_assessment_fingerprint()


def test_fingerprint_options_refuse_absolute_paths() -> None:
    for options in ({"path": "C:\\secret\\data.csv"}, {"path": "/secret/data.csv"}):
        with pytest.raises(ManagedFrameLoadError) as excinfo:
            compute_parser_fingerprint(options)
        assert excinfo.value.reason_code == "OPTION_NOT_CANONICAL"
        with pytest.raises(ManagedFrameLoadError):
            compute_assessment_fingerprint(options)


def test_error_surfaces_are_privacy_safe(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    csv = _write_csv(tmp_path)
    _commit_for_file(state, csv)
    csv.unlink()
    with pytest.raises(ManagedFrameLoadError) as excinfo:
        get_managed_frame(state)
    text = str(excinfo.value) + repr(excinfo.value)
    assert str(tmp_path) not in text
    assert "C:\\" not in text and "c:\\" not in text
    assert "ManagedTrustRoot(" not in text
