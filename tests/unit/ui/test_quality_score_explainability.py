"""Tests for the Quality Score / Rule Breakdown explainability page and service."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pandas as pd

from data_quality_toolkit.adapters.ui.pages.quality_score import _render_quality_score
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
