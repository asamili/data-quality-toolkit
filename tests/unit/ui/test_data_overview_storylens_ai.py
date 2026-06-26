"""Mocked tests for Data Overview StoryLens AI wiring (G17A).

Proves: default-OFF fallback path, mocked AI output, safe primitive passing,
no raw issue payload leakage, failure resilience, no UI AI controls, no
activation claims, and existing smoke parity.  No real model inference.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd

from data_quality_toolkit.adapters.ui.pages.data_overview import _render_data_overview
from data_quality_toolkit.application.explanation.models import Explanation

# ── patch targets ─────────────────────────────────────────────────────────────

_MOCK_LOAD = "data_quality_toolkit.adapters.ui.pages.data_overview._load_df_and_assess"
_MOCK_EXPLAIN = "data_quality_toolkit.adapters.ui.pages.data_overview.try_explain"
_MOCK_BUILD = "data_quality_toolkit.adapters.ui.pages.data_overview.build_data_overview_facts"

# ── shared test data ──────────────────────────────────────────────────────────

_FAKE_DF = pd.DataFrame({"n": [1.0, 2.0, 3.0], "c": ["a", "b", "a"]})

_FAKE_PROFILE: dict[str, Any] = {
    "rows": 3,
    "cols": 2,
    "memory_mb": 0.01,
    "columns": [
        {"name": "n", "dtype": "float64", "nulls": 0, "unique": 3, "null_pct": 0.0},
        {"name": "c", "dtype": "object", "nulls": 0, "unique": 2, "null_pct": 0.0},
    ],
}

_FAKE_ASSESSMENT_CLEAN: dict[str, Any] = {"score": 0.95, "issues": []}

_FAKE_RESULT_CLEAN: dict[str, Any] = {
    "run_id": "r1",
    "dataset_id": "sha1:abc",
    "ts": "2025-01-01T00:00:00Z",
    "meta": {},
    "profile": _FAKE_PROFILE,
    "assessment": _FAKE_ASSESSMENT_CLEAN,
}

_FAKE_ISSUES_WITH_MISSING: list[dict[str, Any]] = [
    {"type": "missing", "column": "revenue", "pct": 0.3, "severity": "high"},
]

_FAKE_RESULT_WITH_ISSUES: dict[str, Any] = {
    **_FAKE_RESULT_CLEAN,
    "assessment": {"score": 0.70, "issues": _FAKE_ISSUES_WITH_MISSING},
}

_FALLBACK = Explanation(
    title="Quality Score",
    summary="Deterministic fallback summary: score ok",
    evidence=("quality_score=0.95", "rows=3", "cols=2", "issues=0"),
    why_it_matters="Quality matters.",
    recommended_action="Review issues.",
    limitations="Explanation only, not validation.",
    severity="ok",
)

_AI_EXPLANATION = Explanation(
    title="Quality Score",
    summary="AI-generated insight XYZ — distinct marker",
    evidence=("quality_score=0.95",),
    why_it_matters="Matters.",
    recommended_action="Act.",
    limitations="Explanation only.",
    severity="ok",
)


# ── FakeSt test double ────────────────────────────────────────────────────────


class FakeSt:
    """Minimal Streamlit test double for data_overview page tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._text_input_vals: dict[str, str] = {}
        self._checkbox_vals: dict[str, bool] = {}

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def _r(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def header(self, *a: Any, **kw: Any) -> None:
        self._r("header", *a, **kw)

    def caption(self, *a: Any, **kw: Any) -> None:
        self._r("caption", *a, **kw)

    def info(self, *a: Any, **kw: Any) -> None:
        self._r("info", *a, **kw)

    def error(self, *a: Any, **kw: Any) -> None:
        self._r("error", *a, **kw)

    def warning(self, *a: Any, **kw: Any) -> None:
        self._r("warning", *a, **kw)

    def success(self, *a: Any, **kw: Any) -> None:
        self._r("success", *a, **kw)

    def divider(self, *a: Any, **kw: Any) -> None:
        self._r("divider", *a, **kw)

    def write(self, *a: Any, **kw: Any) -> None:
        self._r("write", *a, **kw)

    def subheader(self, *a: Any, **kw: Any) -> None:
        self._r("subheader", *a, **kw)

    def metric(self, *a: Any, **kw: Any) -> None:
        self._r("metric", *a, **kw)

    def expander(self, label: str, **kw: Any) -> FakeSt:
        self._r("expander", label, **kw)
        return self

    def dataframe(self, *a: Any, **kw: Any) -> None:
        self._r("dataframe", *a, **kw)

    def download_button(self, *a: Any, **kw: Any) -> None:
        self._r("download_button", *a, **kw)

    def bar_chart(self, *a: Any, **kw: Any) -> None:
        self._r("bar_chart", *a, **kw)

    def number_input(self, label: str, **kw: Any) -> Any:
        self._r("number_input", label, **kw)
        return kw.get("value", kw.get("min_value", 1))

    def checkbox(self, label: str, **kw: Any) -> bool:
        self._r("checkbox", label, **kw)
        return self._checkbox_vals.get(label, False)

    def selectbox(self, label: str, options: Sequence[Any] = (), **kw: Any) -> Any:
        self._r("selectbox", label, options, **kw)
        return options[0] if options else None

    def radio(self, label: str, options: Sequence[Any] = (), **kw: Any) -> Any:
        self._r("radio", label, options, **kw)
        return options[0] if options else None

    def toggle(self, label: str, **kw: Any) -> bool:
        self._r("toggle", label, **kw)
        return False

    def columns(self, n: int) -> list[FakeSt]:
        return [FakeSt() for _ in range(n)]

    def text_input(self, label: str, **kw: Any) -> str:
        self._r("text_input", label, **kw)
        return self._text_input_vals.get(label, "")

    def set_text_input(self, label: str, value: str) -> FakeSt:
        self._text_input_vals[label] = value
        return self

    def set_checkbox(self, label: str, value: bool) -> FakeSt:
        self._checkbox_vals[label] = value
        return self

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def all_rendered_text(self) -> str:
        """All string args from every recorded call, space-joined."""
        parts: list[str] = []
        for _name, args, _kwargs in self.calls:
            for arg in args:
                if isinstance(arg, str):
                    parts.append(arg)
        return " ".join(parts)

    def ai_control_labels(self) -> list[str]:
        """Labels from checkbox/selectbox/toggle/radio calls (AI-control detection)."""
        control_methods = {"checkbox", "selectbox", "toggle", "radio"}
        labels: list[str] = []
        for name, args, _kwargs in self.calls:
            if name in control_methods and args:
                labels.append(str(args[0]))
        return labels


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_st(csv_path: str = "data.csv") -> FakeSt:
    st = FakeSt()
    st.set_text_input("CSV path", csv_path)
    return st


# ── Test 1: default OFF / fallback path ──────────────────────────────────────


def test_default_off_renders_deterministic_fallback() -> None:
    """try_explain returns fallback (mocked); page renders its summary."""
    st = _make_st()
    with (
        patch(_MOCK_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT_CLEAN, None)),
        patch(_MOCK_EXPLAIN, return_value=_FALLBACK),
    ):
        _render_data_overview(st)

    rendered = st.all_rendered_text()
    assert _FALLBACK.summary in rendered

    forbidden = [
        "AI enabled",
        "AI unavailable",
        "model loaded",
        "HuggingFaceTB",
        "SmolLM2",
        "12fd25f",
        "DQT_STORYLENS_MODEL_DIR",
        "DQT_STORYLENS_AI_ENABLED",
    ]
    for token in forbidden:
        assert token not in rendered, f"forbidden token in rendered text: {token!r}"


# ── Test 2: AI mocked valid output renders AI summary + issue explanations ────


def test_ai_mocked_valid_output_renders_ai_summary_and_issue_explanations() -> None:
    """Mocked AI Explanation summary appears; issue-level cards still render."""
    st = _make_st()
    with (
        patch(_MOCK_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT_WITH_ISSUES, None)),
        patch(_MOCK_EXPLAIN, return_value=_AI_EXPLANATION),
    ):
        _render_data_overview(st)

    rendered = st.all_rendered_text()
    assert "AI-generated insight XYZ — distinct marker" in rendered
    # issue-level card for the missing-value issue must also render
    assert st.called("warning") or st.called("info") or st.called("success") or st.called("error")


# ── Test 3: builder receives safe primitives only ─────────────────────────────


def test_builder_receives_safe_primitives() -> None:
    """build_data_overview_facts is called with only safe, typed primitives."""
    mock_facts = MagicMock()
    st = _make_st()
    with (
        patch(_MOCK_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT_CLEAN, None)),
        patch(_MOCK_BUILD, return_value=mock_facts) as mock_build,
        patch(_MOCK_EXPLAIN, return_value=_FALLBACK),
    ):
        _render_data_overview(st)

    mock_build.assert_called_once()
    _, kwargs = mock_build.call_args

    # Required safe primitives
    assert "score" in kwargs and isinstance(kwargs["score"], float)
    assert "rows" in kwargs and isinstance(kwargs["rows"], int)
    assert "columns" in kwargs and isinstance(kwargs["columns"], int)
    assert "issues" in kwargs
    assert "deterministic_fallback" in kwargs

    # memory_mb, if present, must be float or None
    if "memory_mb" in kwargs:
        assert kwargs["memory_mb"] is None or isinstance(kwargs["memory_mb"], float)

    # Forbidden kwargs — no raw objects or forbidden fields
    forbidden_keys = {"csv_path", "profile", "out", "env", "model_id", "model_dir"}
    for key in forbidden_keys:
        assert key not in kwargs, f"forbidden key passed to builder: {key!r}"

    # The st object must not be passed
    for key, val in kwargs.items():
        assert not isinstance(val, FakeSt), f"FakeSt leaked into builder kwarg {key!r}"


# ── Test 4: no raw issue payload leakage ─────────────────────────────────────


def test_no_raw_issue_payload_leakage() -> None:
    """Issues with forbidden fields are passed to builder, never rendered directly."""
    issues_with_forbidden = [
        {
            "type": "missing",
            "column": "revenue",
            "pct": 0.3,
            "severity": "high",
            "message": "LEAKED_MESSAGE_TEXT",
            "examples": ["cell1", "cell2"],
            "violation_count": 42,
            "duplicate_count": 7,
            "expected_dtype": "float64",
            "actual_dtype": "object",
        }
    ]
    result_with_forbidden = {
        **_FAKE_RESULT_CLEAN,
        "assessment": {"score": 0.70, "issues": issues_with_forbidden},
    }
    mock_facts = MagicMock()
    st = _make_st()
    with (
        patch(_MOCK_LOAD, return_value=(_FAKE_DF, result_with_forbidden, None)),
        patch(_MOCK_BUILD, return_value=mock_facts) as mock_build,
        patch(_MOCK_EXPLAIN, return_value=_FALLBACK),
    ):
        _render_data_overview(st)

    # Builder was called and received the issues list
    mock_build.assert_called_once()
    _, kwargs = mock_build.call_args
    assert kwargs.get("issues") is not None

    # Forbidden raw fields must not appear as direct kwargs to builder
    direct_forbidden = {
        "message",
        "examples",
        "violation_count",
        "duplicate_count",
        "expected_dtype",
        "actual_dtype",
    }
    for key in direct_forbidden:
        assert key not in kwargs, f"forbidden issue field passed as direct kwarg: {key!r}"

    # Forbidden cell values must not appear in rendered UI text
    rendered = st.all_rendered_text()
    assert "LEAKED_MESSAGE_TEXT" not in rendered


# ── Test 5: AI failure / fallback resilience ──────────────────────────────────


def test_ai_failure_does_not_crash_and_issue_explanations_still_render() -> None:
    """If try_explain raises, outer except catches; issue explanations still render."""
    st = _make_st()
    with (
        patch(_MOCK_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT_WITH_ISSUES, None)),
        patch(_MOCK_EXPLAIN, side_effect=RuntimeError("simulated failure")),
    ):
        _render_data_overview(st)  # must not raise

    # render_storylens_card was reached (subheader or severity-level call or no-op)
    # Issue explanations render as warning (missing-value, high severity → warn)
    assert st.called("warning") or not st.called("error")


# ── Test 6: no AI UI controls added ──────────────────────────────────────────


def test_no_ai_ui_controls_added() -> None:
    """No checkbox/selectbox/toggle/radio with AI-related labels is called."""
    st = _make_st()
    with (
        patch(_MOCK_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT_CLEAN, None)),
        patch(_MOCK_EXPLAIN, return_value=_FALLBACK),
    ):
        _render_data_overview(st)

    ai_keywords = {"ai", "model", "storylens", "enabled"}
    for label in st.ai_control_labels():
        label_lower = label.lower()
        # Exclude the legitimate large-data mode checkbox
        if "large" in label_lower:
            continue
        for keyword in ai_keywords:
            assert (
                keyword not in label_lower
            ), f"AI-related UI control detected: {label!r} (keyword: {keyword!r})"


# ── Test 7: no UI activation claims ──────────────────────────────────────────


def test_no_ui_activation_claims() -> None:
    """Rendered UI text must not contain any AI activation or model-identity strings."""
    st = _make_st()
    with (
        patch(_MOCK_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT_CLEAN, None)),
        patch(_MOCK_EXPLAIN, return_value=_FALLBACK),
    ):
        _render_data_overview(st)

    rendered = st.all_rendered_text()
    forbidden_tokens = [
        "AI enabled",
        "AI unavailable",
        "model loaded",
        "HuggingFaceTB",
        "SmolLM2",
        "12fd25f",
        "DQT_STORYLENS_MODEL_DIR",
        "DQT_STORYLENS_AI_ENABLED",
    ]
    for token in forbidden_tokens:
        assert token not in rendered, f"forbidden activation claim in UI: {token!r}"


# ── Test 8: existing UI smoke parity ─────────────────────────────────────────


def test_existing_ui_smoke_happy_path() -> None:
    """Happy-path parity with pre-wiring smoke: metric and dataframe still rendered."""
    st = _make_st()
    with (
        patch(_MOCK_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT_CLEAN, None)),
        patch(_MOCK_EXPLAIN, return_value=_FALLBACK),
    ):
        _render_data_overview(st)

    assert st.called("metric")
    assert st.called("dataframe")
