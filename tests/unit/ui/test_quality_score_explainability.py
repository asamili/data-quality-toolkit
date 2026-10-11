"""Tests for the Quality Score / Rule Breakdown explainability page and service."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.pages.quality_score import (
    _MANAGED_FAIL_CLOSED_MESSAGE,
    _assess_frame_for_quality,
    _render_quality_score,
)
from data_quality_toolkit.adapters.ui.services import managed_frame_loader as mfl
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    ManagedTrustRoot,
    commit_trust_root,
    ensure_session_capability,
    make_source_locator,
    retire_managed_trust,
)
from data_quality_toolkit.adapters.ui.services.quality_score import (
    PUBLISH_THRESHOLD,
    penalty_breakdown,
    rule_contribution_rows,
    score_overview,
    severity_penalty_table,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT

_PATCH_LOAD = "data_quality_toolkit.adapters.ui.pages.quality_score._load_df_and_assess"

_ASSESSMENT: dict[str, Any] = {
    "score": 0.80,
    "completeness_score": 0.80,
    "quality_score": 0.76,
    "issues": [
        {
            "type": "missing",
            "column": "a",
            "pct": 0.3,
            "severity": "high",
            "category": "Completeness",
        },
        {"type": "duplicate_column_name", "column": "b", "severity": "high", "category": "Schema"},
        {"type": "numeric_outliers", "column": "c", "severity": "low", "category": "Distribution"},
    ],
}

_DF = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"], "c": [1.0, 2.0, 3.0]})
_RESULT: dict[str, Any] = {"profile": {"rows": 3, "cols": 3}, "assessment": _ASSESSMENT}


class FakeSt:
    """Minimal Streamlit recorder supporting columns/context-manager use."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.text_values: dict[str, str] = {}

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def _rec(self, name: str, *a: Any, **k: Any) -> None:
        self.calls.append((name, a, k))

    def __getattr__(self, name: str) -> Any:
        def recorder(*a: Any, **k: Any) -> None:
            self._rec(name, *a, **k)

        return recorder

    def columns(self, n: int) -> list[FakeSt]:
        self._rec("columns", n)
        return [FakeSt() for _ in range(n)]

    def text_input(self, label: str, **k: Any) -> str:
        self._rec("text_input", label, **k)
        return self.text_values.get(label, str(k.get("value", "")))

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))


# ── service: score_overview ───────────────────────────────────────────────────


def test_score_overview_prefers_quality_score_as_headline() -> None:
    overview = score_overview(_ASSESSMENT)
    assert overview["completeness_score"] == 0.80
    assert overview["quality_score"] == 0.76
    assert overview["headline_score"] == 0.76
    assert overview["issues_total"] == 3
    assert overview["meets_threshold"] is (0.76 >= PUBLISH_THRESHOLD)


def test_score_overview_reports_missing_quality_score_as_none() -> None:
    overview = score_overview({"score": 0.95, "issues": []})
    assert overview["quality_score"] is None
    assert overview["headline_score"] == 0.95
    assert overview["meets_threshold"] is True


# ── service: rule contributions ────────────────────────────────────────────────


def test_rule_contribution_excludes_completeness_issues() -> None:
    rows = rule_contribution_rows(_ASSESSMENT)
    by_type = {r["type"]: r for r in rows}
    assert by_type["missing"]["counted_in_score"] is False
    assert by_type["missing"]["penalty_points"] == 0.0
    assert by_type["duplicate_column_name"]["counted_in_score"] is True
    assert by_type["duplicate_column_name"]["penalty_bucket"] == "schema"
    assert by_type["numeric_outliers"]["penalty_bucket"] == "distribution"


def test_penalty_breakdown_caps_and_derives_score() -> None:
    breakdown = penalty_breakdown(_ASSESSMENT)
    assert breakdown["schema_penalty_applied"] == 0.03
    assert breakdown["distribution_penalty_applied"] == 0.01
    # 0.80 - 0.03 - 0.01 == 0.76, matching the reported quality_score.
    assert breakdown["derived_quality_score"] == 0.76
    assert breakdown["reported_quality_score"] == 0.76


def test_severity_penalty_table_is_ordered() -> None:
    table = severity_penalty_table()
    assert [r["severity"] for r in table] == ["critical", "high", "medium", "low"]


# ── page render ────────────────────────────────────────────────────────────────


def test_render_empty_path_shows_info() -> None:
    st = FakeSt()
    _render_quality_score(st, {})
    assert st.called("header")
    assert st.called("info")
    assert not st.called("metric")


def test_render_load_error_shows_error() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "bad.csv"
    with patch(_PATCH_LOAD, return_value=(None, None, "file not found")):
        _render_quality_score(st, {})
    assert st.called("error")
    assert not st.called("metric")


def test_render_happy_path_shows_scores_and_breakdown() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_quality_score(st, {})
    assert st.called("metric")
    assert st.called("dataframe")
    assert "Quality Score" in st.texts()


def test_render_large_file_context_blocks_without_loading() -> None:
    st = FakeSt()
    context = DatasetContext(
        source_path="C:/safe/data.csv",
        display_name="data.csv",
        size_bytes=10,
        modified_ns=1,
        large_file_mode=True,
    )
    with patch(_PATCH_LOAD) as load:
        _render_quality_score(st, {DATASET_CONTEXT: context})
    load.assert_not_called()
    assert st.called("warning")


# ── managed assessment dispatch ────────────────────────────────────────────────

_MANAGED_ABS = "C:\\workspace\\versions\\v1\\data.csv"
_PATCH_MANAGED_ASSESS = (
    "data_quality_toolkit.adapters.ui.pages.quality_score.get_managed_assessment"
)


@pytest.fixture(autouse=True)
def _clean_managed_caches() -> Iterator[None]:
    mfl.clear_managed_caches()
    yield
    mfl.clear_managed_caches()


def _managed_csv(tmp_path: Path) -> Path:
    target = tmp_path / "versions" / "v1" / "data.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("a,b,c\n1,x,1.0\n2,y,2.0\n3,z,3.0\n", encoding="utf-8")
    return target


def _trusted_session(
    *, large: bool = False, csv_path: Path | None = None
) -> tuple[dict[str, Any], ManagedTrustRoot]:
    state: dict[str, Any] = {}
    capability = ensure_session_capability(state)
    if csv_path is not None:
        stat = csv_path.stat()
        absolute, size, mtime = str(csv_path.resolve()), int(stat.st_size), int(stat.st_mtime_ns)
    else:
        absolute, size, mtime = _MANAGED_ABS, 2048, 10
    root = commit_trust_root(
        state,
        capability,
        version_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        content_id="sha256:" + "a" * 64,
        root_content_id="sha256:" + "b" * 64,
        parent_version_id=None,
        version_label="cleaned v2",
        locator=make_source_locator(
            display_name="data.csv",
            relative_posix="versions/v1/data.csv",
            absolute_path=absolute,
        ),
        size_bytes=size,
        modified_ns=mtime,
        large_file_mode=large,
    )
    return state, root


def _managed_mirror_session() -> dict[str, Any]:
    return {
        DATASET_CONTEXT: DatasetContext(
            source_path=_MANAGED_ABS,
            display_name="data.csv",
            size_bytes=2048,
            modified_ns=10,
            managed=True,
            version_id=str(uuid.uuid4()),
            family_id=str(uuid.uuid4()),
            content_id="sha256:" + "a" * 64,
            root_content_id="sha256:" + "b" * 64,
            version_label="cleaned v2",
        )
    }


def test_managed_render_uses_managed_assessment_not_legacy_loader() -> None:
    st = FakeSt()
    session, _root = _trusted_session()
    with (
        patch(_PATCH_MANAGED_ASSESS, return_value=_RESULT) as managed,
        patch(_PATCH_LOAD) as legacy,
    ):
        _render_quality_score(st, session)
    managed.assert_called_once()
    legacy.assert_not_called()
    assert st.called("metric")
    assert "Quality Score" in st.texts()


def test_managed_mirror_without_trust_fails_closed() -> None:
    st = FakeSt()
    with (
        patch(_PATCH_MANAGED_ASSESS) as managed,
        patch(_PATCH_LOAD) as legacy,
    ):
        _render_quality_score(st, _managed_mirror_session())
    managed.assert_not_called()
    legacy.assert_not_called()
    assert st.called("error")
    assert _MANAGED_FAIL_CLOSED_MESSAGE in st.texts()


def test_manual_path_cannot_override_valid_trust_on_score_page() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "C:/manual/other.csv"
    session, _root = _trusted_session()
    with (
        patch(_PATCH_MANAGED_ASSESS, return_value=_RESULT) as managed,
        patch(_PATCH_LOAD) as legacy,
    ):
        _render_quality_score(st, session)
    managed.assert_called_once()
    legacy.assert_not_called()
    assert not st.called("text_input")


def test_managed_large_version_refuses_assessment() -> None:
    st = FakeSt()
    session, _root = _trusted_session(large=True)
    with (
        patch(_PATCH_MANAGED_ASSESS) as managed,
        patch(_PATCH_LOAD) as legacy,
    ):
        _render_quality_score(st, session)
    managed.assert_not_called()
    legacy.assert_not_called()
    assert st.called("warning")
    assert not st.called("metric")


def test_retired_trust_fails_closed_on_score_page() -> None:
    st = FakeSt()
    session, root = _trusted_session()
    mirror = DatasetContext(
        source_path=_MANAGED_ABS,
        display_name="data.csv",
        size_bytes=root.size_bytes,
        modified_ns=root.modified_ns,
        managed=True,
        version_id=root.version_id,
        family_id=root.family_id,
        content_id=root.content_id,
        root_content_id=root.root_content_id,
        version_label=root.version_label,
    )
    retire_managed_trust(session)
    session[DATASET_CONTEXT] = mirror  # marker deliberately left behind
    with patch(_PATCH_MANAGED_ASSESS) as managed:
        _render_quality_score(st, session)
    managed.assert_not_called()
    assert st.called("error")


def test_managed_loader_refusal_is_privacy_safe(tmp_path: Path) -> None:
    st = FakeSt()
    session, _root = _trusted_session()
    refusal = mfl.ManagedFrameLoadError("SOURCE_MISSING")
    with patch(_PATCH_MANAGED_ASSESS, side_effect=refusal):
        _render_quality_score(st, session)
    assert st.called("error")
    text = st.texts()
    assert _MANAGED_ABS not in text
    assert "C:\\workspace" not in text
    assert not st.called("metric")


def test_managed_assessment_cache_identity_is_exact(tmp_path: Path) -> None:
    """The real assessment cache is keyed by AssessmentKey, not by version alone."""
    csv = _managed_csv(tmp_path)
    session, _root = _trusted_session(csv_path=csv)
    calls: list[str] = []

    def counting_assessor(frame: pd.DataFrame) -> dict[str, Any]:
        calls.append("run")
        return _assess_frame_for_quality(frame)

    first = mfl.get_managed_assessment(
        session, assessor=counting_assessor, assessment_options={"rules": "v1"}
    )
    second = mfl.get_managed_assessment(
        session, assessor=counting_assessor, assessment_options={"rules": "v1"}
    )
    assert calls == ["run"]  # exact-key hit
    assert second is first
    assert "assessment" in first

    mfl.get_managed_assessment(
        session, assessor=counting_assessor, assessment_options={"rules": "v2"}
    )
    assert calls == ["run", "run"]  # changed fingerprint never reuses stale assessment


def test_managed_assessment_cache_holds_no_dataframes(tmp_path: Path) -> None:
    csv = _managed_csv(tmp_path)
    session, _root = _trusted_session(csv_path=csv)
    mfl.get_managed_assessment(session, assessor=_assess_frame_for_quality)
    assert mfl._managed_assessment_cache
    for value in mfl._managed_assessment_cache.values():
        assert isinstance(value, dict)
        assert not isinstance(value, pd.DataFrame)
        assert not any(isinstance(inner, pd.DataFrame) for inner in value.values())


def test_managed_version_switch_clears_assessment_cache(tmp_path: Path) -> None:
    csv = _managed_csv(tmp_path)
    session, _root = _trusted_session(csv_path=csv)
    mfl.get_managed_assessment(session, assessor=_assess_frame_for_quality)
    assert mfl._managed_assessment_cache
    retire_managed_trust(session)
    assert len(mfl._managed_assessment_cache) == 0
