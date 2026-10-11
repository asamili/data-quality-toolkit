"""Tests for the file-fingerprint cache over ``_load_df_and_assess``.

These verify that repeated calls with an unchanged file reuse the cached
load/profile/assess work, that the cache invalidates when the file (or the
effective SAMPLE_SIZE env) changes, that errors are never cached, that a cached
DataFrame cannot be corrupted by a caller mutating a prior return, and that the
load path exposes no resolved absolute path and writes nothing to disk.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui import eda
from data_quality_toolkit.adapters.ui.services import managed_frame_loader as mfl
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    ManagedTrustRoot,
    commit_trust_root,
    ensure_session_capability,
    make_source_locator,
)


@pytest.fixture(autouse=True)
def _clear_load_cache() -> Iterator[None]:
    """Clear the fingerprint cache around each test so state never leaks."""

    def _clear() -> None:
        loader = eda._get_cached_loader()
        clear = getattr(loader, "clear", None)
        if callable(clear):
            clear()

    _clear()
    yield
    _clear()


def _fake_result() -> tuple[pd.DataFrame, dict[str, Any]]:
    return pd.DataFrame({"a": [1, 2, 3]}), {"profile": {"rows": 3, "cols": 1}}


def test_cache_hit_computes_once(tmp_path: Any) -> None:
    csv = tmp_path / "data.csv"
    csv.write_text("a,b\n1,2\n3,4\n")
    with patch.object(eda, "_compute_load_and_assess", return_value=_fake_result()) as comp:
        df1, res1, err1 = eda._load_df_and_assess(str(csv))
        df2, res2, err2 = eda._load_df_and_assess(str(csv))
    assert comp.call_count == 1  # second call served from cache
    assert err1 is None and err2 is None
    assert df1 is not None and df2 is not None
    assert res1 is not None and res2 is not None


def test_cache_invalidates_when_file_changes(tmp_path: Any) -> None:
    csv = tmp_path / "data.csv"
    csv.write_text("a,b\n1,2\n")
    with patch.object(eda, "_compute_load_and_assess", return_value=_fake_result()) as comp:
        eda._load_df_and_assess(str(csv))
        csv.write_text("a,b\n1,2\n3,4\n5,6\n")  # size (and mtime) change -> new key
        eda._load_df_and_assess(str(csv))
    assert comp.call_count == 2


def test_manual_csv_path_uses_the_cache_seam(tmp_path: Any) -> None:
    csv = tmp_path / "manual.csv"
    csv.write_text("a\n1\n")
    with patch.object(eda, "_compute_load_and_assess", return_value=_fake_result()) as comp:
        df, _res, err = eda._load_df_and_assess(str(csv))
        eda._load_df_and_assess(str(csv))
    assert err is None and df is not None
    assert comp.call_count == 1


def test_dataset_context_style_absolute_path_uses_the_cache_seam(tmp_path: Any) -> None:
    csv = tmp_path / "context.csv"
    csv.write_text("a\n1\n")
    # DatasetContext.source_path holds a resolved absolute path string.
    abs_path = str(csv.resolve())
    with patch.object(eda, "_compute_load_and_assess", return_value=_fake_result()) as comp:
        df, _res, err = eda._load_df_and_assess(abs_path)
        eda._load_df_and_assess(abs_path)
    assert err is None and df is not None
    assert comp.call_count == 1


def test_errors_are_not_cached_missing_then_created(tmp_path: Any) -> None:
    csv = tmp_path / "later.csv"

    # First call: file missing -> real loader raises -> error tuple, nothing cached.
    df1, res1, err1 = eda._load_df_and_assess(str(csv))
    assert df1 is None and res1 is None and err1 is not None

    # Second call: file now present -> recompute succeeds (error was not memoized).
    csv.write_text("a\n1\n")
    with patch.object(eda, "_compute_load_and_assess", return_value=_fake_result()) as comp:
        df2, res2, err2 = eda._load_df_and_assess(str(csv))
    assert err2 is None and df2 is not None and res2 is not None
    assert comp.call_count == 1


def test_mutating_returned_dataframe_does_not_corrupt_cache(tmp_path: Any) -> None:
    csv = tmp_path / "mut.csv"
    csv.write_text("a\n1\n")
    with patch.object(
        eda, "_compute_load_and_assess", side_effect=lambda _p: _fake_result()
    ) as comp:
        df1, _res1, err1 = eda._load_df_and_assess(str(csv))
        assert df1 is not None
        df1.loc[0, "a"] = 999  # mutate the first return
        df2, _res2, err2 = eda._load_df_and_assess(str(csv))
    assert err1 is None and err2 is None
    assert comp.call_count == 1  # cache hit (compute not re-invoked)
    assert df2 is not None
    assert int(df2.loc[0, "a"]) == 1  # copy-on-read: cached value untouched


def test_cache_key_includes_effective_sample_size_env(tmp_path: Any, monkeypatch: Any) -> None:
    csv = tmp_path / "s.csv"
    csv.write_text("a\n1\n")
    with patch.object(eda, "_compute_load_and_assess", return_value=_fake_result()) as comp:
        monkeypatch.delenv("SAMPLE_SIZE", raising=False)
        eda._load_df_and_assess(str(csv))
        monkeypatch.setenv("SAMPLE_SIZE", "1")
        eda._load_df_and_assess(str(csv))
    assert comp.call_count == 2  # env change -> different key -> recompute


def test_missing_relative_path_error_uses_supplied_path_not_resolved(
    tmp_path: Any, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    df, res, err = eda._load_df_and_assess("nope.csv")
    assert df is None and res is None
    assert err is not None
    assert "nope.csv" in err
    # The resolved absolute directory must not leak into the user-visible error.
    assert str(tmp_path.resolve()) not in err


def test_load_writes_no_files_on_render_path(tmp_path: Any) -> None:
    csv = tmp_path / "only.csv"
    csv.write_text("a\n1\n")
    before = {p.name for p in tmp_path.iterdir()}
    with patch.object(eda, "_compute_load_and_assess", return_value=_fake_result()):
        eda._load_df_and_assess(str(csv))
    after = {p.name for p in tmp_path.iterdir()}
    assert before == after  # no save-on-render; in-memory cache writes nothing to disk


# ---------------------------------------------------------------------------
# Managed load-cache isolation: session / parser / version / content
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_managed_caches() -> Iterator[None]:
    mfl.clear_managed_caches()
    yield
    mfl.clear_managed_caches()


class _CountingReader:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, path: str, options: Mapping[str, Any] | None) -> pd.DataFrame:
        self.calls += 1
        return pd.read_csv(path, **dict(options or {}))


def _managed_csv(tmp_path: Path) -> Path:
    target = tmp_path / "versions" / "v1" / "data.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("a,b\n1,2\n", encoding="utf-8")
    return target


def _commit_managed(
    state: dict[str, Any],
    csv_path: Path,
    *,
    version_id: str | None = None,
    content_id: str = "sha256:" + "a" * 64,
) -> ManagedTrustRoot:
    st = csv_path.stat()
    capability = ensure_session_capability(state)
    return commit_trust_root(
        state,
        capability,
        version_id=version_id or str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        content_id=content_id,
        root_content_id="sha256:" + "c" * 64,
        parent_version_id=None,
        version_label="cleaned v2",
        locator=make_source_locator(
            display_name="data.csv",
            relative_posix="versions/v1/data.csv",
            absolute_path=str(csv_path.resolve()),
        ),
        size_bytes=int(st.st_size),
        modified_ns=int(st.st_mtime_ns),
        large_file_mode=False,
    )


def test_managed_cache_hit_within_one_session(tmp_path: Any) -> None:
    csv = _managed_csv(tmp_path)
    state: dict[str, Any] = {}
    _commit_managed(state, csv)
    reader = _CountingReader()
    first = mfl.get_managed_frame(state, reader=reader)
    second = mfl.get_managed_frame(state, reader=reader)
    assert reader.calls == 1
    assert second is first


def test_managed_cache_is_session_isolated(tmp_path: Any) -> None:
    csv = _managed_csv(tmp_path)
    version = str(uuid.uuid4())
    state_one: dict[str, Any] = {}
    state_two: dict[str, Any] = {}
    _commit_managed(state_one, csv, version_id=version)
    reader = _CountingReader()
    mfl.get_managed_frame(state_one, reader=reader)
    _commit_managed(state_two, csv, version_id=version)  # same identity, other session
    mfl.get_managed_frame(state_two, reader=reader)
    assert reader.calls == 2  # a different SessionCapability can never hit the entry


def test_managed_cache_is_parser_isolated(tmp_path: Any) -> None:
    csv = _managed_csv(tmp_path)
    state: dict[str, Any] = {}
    _commit_managed(state, csv)
    reader = _CountingReader()
    mfl.get_managed_frame(state, parser_options={"sep": ","}, reader=reader)
    mfl.get_managed_frame(state, parser_options={"sep": ";"}, reader=reader)
    mfl.get_managed_frame(state, parser_options={"sep": ","}, reader=reader)
    assert reader.calls == 2  # parser fingerprint change misses; exact repeat hits


def test_managed_cache_is_version_isolated(tmp_path: Any) -> None:
    csv = _managed_csv(tmp_path)
    state: dict[str, Any] = {}
    _commit_managed(state, csv, version_id=str(uuid.uuid4()))
    reader = _CountingReader()
    mfl.get_managed_frame(state, reader=reader)
    _commit_managed(state, csv, version_id=str(uuid.uuid4()))  # version switch
    mfl.get_managed_frame(state, reader=reader)
    assert reader.calls == 2  # different version_id can never reuse the old frame


def test_managed_cache_is_content_isolated(tmp_path: Any) -> None:
    csv = _managed_csv(tmp_path)
    version = str(uuid.uuid4())
    state: dict[str, Any] = {}
    _commit_managed(state, csv, version_id=version, content_id="sha256:" + "a" * 64)
    reader = _CountingReader()
    mfl.get_managed_frame(state, reader=reader)
    _commit_managed(state, csv, version_id=version, content_id="sha256:" + "b" * 64)
    mfl.get_managed_frame(state, reader=reader)
    assert reader.calls == 2  # different content_id is a different dataset


def test_managed_and_legacy_caches_never_share_entries(tmp_path: Any) -> None:
    csv = _managed_csv(tmp_path)
    state: dict[str, Any] = {}
    _commit_managed(state, csv)
    reader = _CountingReader()
    mfl.get_managed_frame(state, reader=reader)
    assert reader.calls == 1
    # The legacy fingerprint cache must still compute its own load: the managed
    # frame cache is keyed by capability identity, never by path fingerprint.
    with patch.object(eda, "_compute_load_and_assess", return_value=_fake_result()) as comp:
        eda._load_df_and_assess(str(csv))
    assert comp.call_count == 1
