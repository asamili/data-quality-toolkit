"""Deterministic StoryLens wiring tests (G27G).

Proves:
- StoryLens caption is source-neutral (no "AI explanation" wording)
- EDA, Run History, Drift Explorer, Export StoryLens wiring renders correctly
- Optional AI modules are never loaded by deterministic UI import paths
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd

# ── Minimal Streamlit test double ─────────────────────────────────────────────


class FakeSt:
    """Minimal Streamlit double shared by all page tests in this module."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._text_input_vals: dict[str, str] = {}
        self._checkbox_vals: dict[str, bool] = {}

    def _r(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    # ── render methods ────────────────────────────────────────────────────────

    def header(self, *a: Any, **kw: Any) -> None:
        self._r("header", *a, **kw)

    def subheader(self, *a: Any, **kw: Any) -> None:
        self._r("subheader", *a, **kw)

    def caption(self, *a: Any, **kw: Any) -> None:
        self._r("caption", *a, **kw)

    def write(self, *a: Any, **kw: Any) -> None:
        self._r("write", *a, **kw)

    def info(self, *a: Any, **kw: Any) -> None:
        self._r("info", *a, **kw)

    def warning(self, *a: Any, **kw: Any) -> None:
        self._r("warning", *a, **kw)

    def error(self, *a: Any, **kw: Any) -> None:
        self._r("error", *a, **kw)

    def success(self, *a: Any, **kw: Any) -> None:
        self._r("success", *a, **kw)

    def divider(self, *a: Any, **kw: Any) -> None:
        self._r("divider", *a, **kw)

    def metric(self, *a: Any, **kw: Any) -> None:
        self._r("metric", *a, **kw)

    def dataframe(self, *a: Any, **kw: Any) -> None:
        self._r("dataframe", *a, **kw)

    def table(self, *a: Any, **kw: Any) -> None:
        self._r("table", *a, **kw)

    def download_button(self, *a: Any, **kw: Any) -> None:
        self._r("download_button", *a, **kw)

    def bar_chart(self, *a: Any, **kw: Any) -> None:
        self._r("bar_chart", *a, **kw)

    def line_chart(self, *a: Any, **kw: Any) -> None:
        self._r("line_chart", *a, **kw)

    def scatter_chart(self, *a: Any, **kw: Any) -> None:
        self._r("scatter_chart", *a, **kw)

    def code(self, *a: Any, **kw: Any) -> None:
        self._r("code", *a, **kw)

    def markdown(self, *a: Any, **kw: Any) -> None:
        self._r("markdown", *a, **kw)

    def expander(self, label: str, **kw: Any) -> FakeSt:
        self._r("expander", label, **kw)
        return self

    def number_input(self, label: str, **kw: Any) -> Any:
        self._r("number_input", label, **kw)
        return kw.get("value", kw.get("min_value", 1))

    def checkbox(self, label: str, **kw: Any) -> bool:
        self._r("checkbox", label, **kw)
        return self._checkbox_vals.get(label, False)

    def button(self, label: str, **kw: Any) -> bool:
        self._r("button", label, **kw)
        return False

    def selectbox(self, label: str, options: Sequence[Any] = (), **kw: Any) -> Any:
        self._r("selectbox", label, options, **kw)
        return options[0] if options else None

    def text_input(self, label: str, **kw: Any) -> str:
        self._r("text_input", label, **kw)
        default: str = str(kw.get("value", ""))
        return self._text_input_vals.get(label, default)

    def columns(self, n: int) -> list[FakeSt]:
        return [FakeSt() for _ in range(n)]

    def set_text_input(self, label: str, value: str) -> FakeSt:
        self._text_input_vals[label] = value
        return self

    def set_checkbox(self, label: str, value: bool) -> FakeSt:
        self._checkbox_vals[label] = value
        return self

    # ── helpers ───────────────────────────────────────────────────────────────

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def all_rendered_text(self) -> str:
        parts: list[str] = []
        for _name, args, _kwargs in self.calls:
            for arg in args:
                if isinstance(arg, str):
                    parts.append(arg)
        return " ".join(parts)

    def all_captions(self) -> list[str]:
        return [args[0] for name, args, _ in self.calls if name == "caption" and args]


# ── Shared test data ───────────────────────────────────────────────────────────

_FAKE_DF = pd.DataFrame({"n": [1.0, 2.0], "c": ["a", "b"]})

_FAKE_PROFILE: dict[str, Any] = {
    "rows": 2,
    "cols": 2,
    "memory_mb": 0.01,
    "columns": [
        {"name": "n", "dtype": "float64", "nulls": 0, "unique": 2, "null_pct": 0.0},
        {"name": "c", "dtype": "object", "nulls": 0, "unique": 2, "null_pct": 0.0},
    ],
}

_FAKE_RESULT: dict[str, Any] = {
    "run_id": "r1",
    "dataset_id": "sha1:abc",
    "ts": "2025-01-01T00:00:00Z",
    "meta": {},
    "profile": _FAKE_PROFILE,
    "assessment": {"score": 0.95, "issues": []},
}


# ── Test 1: caption is source-neutral ─────────────────────────────────────────


def test_render_storylens_card_caption_is_source_neutral() -> None:
    """StoryLens caption must not claim AI authorship for deterministic cards."""
    from data_quality_toolkit.adapters.ui.components.storylens import render_storylens_card
    from data_quality_toolkit.application.explanation import explain_quality_score

    fake_st = MagicMock()
    exp = explain_quality_score(score=0.95, rows=100, columns=5, issues_total=0)
    render_storylens_card(fake_st, [exp])

    # Gather all caption calls
    caption_text = " ".join(
        str(call.args[0]) for call in fake_st.caption.call_args_list if call.args
    )
    assert "AI explanation" not in caption_text
    assert "ai explanation" not in caption_text.lower()
    assert "DQT metric explanation" in caption_text


# ── Test 2: EDA StoryLens renders quality score card ──────────────────────────


def test_eda_explorer_renders_storylens_card() -> None:
    """EDA Explorer renders a quality-score StoryLens card on happy path."""
    from data_quality_toolkit.adapters.ui.pages.eda_explorer import _render_eda_explorer

    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")

    with patch(
        "data_quality_toolkit.adapters.ui.pages.eda_explorer._load_df_and_assess",
        return_value=(_FAKE_DF, _FAKE_RESULT, None),
    ):
        _render_eda_explorer(st)

    # StoryLens subheader must have been rendered
    assert st.called("subheader")
    # At least one severity-level render call (ok → success, warn → warning, etc.)
    assert st.called("success") or st.called("info") or st.called("warning") or st.called("error")


def test_eda_storylens_empty_on_bad_result() -> None:
    """_eda_storylens returns [] when result is None — no crash, no fabrication."""
    from data_quality_toolkit.adapters.ui.pages.eda_explorer import _eda_storylens

    result = _eda_storylens(None, None)
    assert result == []


def test_eda_storylens_quality_score_present() -> None:
    """_eda_storylens returns a quality-score explanation for a clean result."""
    from data_quality_toolkit.adapters.ui.pages.eda_explorer import _eda_storylens

    cards = _eda_storylens(_FAKE_RESULT, _FAKE_PROFILE)
    assert len(cards) >= 1
    assert "95%" in cards[0].title or "score" in cards[0].title.lower()


def test_eda_storylens_adds_missing_value_card() -> None:
    """_eda_storylens appends a missing-value card when an issue is present."""
    from data_quality_toolkit.adapters.ui.pages.eda_explorer import _eda_storylens

    result_with_issue: dict[str, Any] = {
        **_FAKE_RESULT,
        "assessment": {
            "score": 0.70,
            "issues": [{"type": "missing", "column": "revenue", "pct": 0.3, "severity": "high"}],
        },
    }
    cards = _eda_storylens(result_with_issue, _FAKE_PROFILE)
    assert len(cards) == 2  # quality score + missing value
    titles = [c.title for c in cards]
    assert any("revenue" in t for t in titles)


def test_eda_storylens_bounded_max_two() -> None:
    """_eda_storylens returns at most 2 cards even with many issues."""
    from data_quality_toolkit.adapters.ui.pages.eda_explorer import _eda_storylens

    many_issues = [
        {"type": "missing", "column": f"col{i}", "pct": 0.1 * i, "severity": "medium"}
        for i in range(1, 6)
    ]
    result_many = {**_FAKE_RESULT, "assessment": {"score": 0.5, "issues": many_issues}}
    cards = _eda_storylens(result_many, _FAKE_PROFILE)
    assert len(cards) <= 2


# ── Test 3: Run History StoryLens — 1-record state ────────────────────────────


def test_run_history_1_record_renders_not_enough_runs_card() -> None:
    """Run History with exactly 1 record renders explain_not_enough_runs card."""
    from data_quality_toolkit.adapters.ui.pages.run_history import _render_run_history

    one_record = [{"ts": "2025-01-01T00:00:00Z", "score": 0.90}]
    st = FakeSt()
    st.set_text_input("Database path", "dqt.db")
    st.set_text_input("Dataset ID", "sha1:abc")

    with (
        patch(
            "data_quality_toolkit.adapters.ui.pages.run_history._load_run_history",
            return_value=(one_record, None),
        ),
        patch(
            "data_quality_toolkit.adapters.ui.pages.run_history._extract_trend_data",
            return_value=[],
        ),
        patch(
            "data_quality_toolkit.adapters.ui.pages.run_history._extract_latest_issues",
            return_value=({}, {}),
        ),
    ):
        _render_run_history(st)

    rendered = st.all_rendered_text()
    assert (
        "enough" in rendered.lower() or "history" in rendered.lower() or "run" in rendered.lower()
    )
    assert st.called("subheader") or st.called("info")


# ── Test 4: Drift Explorer StoryLens ──────────────────────────────────────────


def _make_mock_overview(total_runs: int, drifted_runs: int, latest_run_id: str | None) -> Any:
    summary = MagicMock()
    summary.total_runs = total_runs
    summary.drifted_runs = drifted_runs
    summary.drift_rate = drifted_runs / max(total_runs, 1)
    summary.latest_run_id = latest_run_id
    overview = MagicMock()
    overview.summary = summary
    overview.runs = []
    return overview


def test_drift_summary_storylens_not_enough_runs() -> None:
    """_drift_summary_storylens returns explain_not_enough_runs when total_runs < 2."""
    from data_quality_toolkit.adapters.ui.pages.drift_explorer import _drift_summary_storylens

    cards = _drift_summary_storylens(_make_mock_overview(1, 0, None).summary)
    assert len(cards) == 1
    assert "history" in cards[0].title.lower() or "enough" in cards[0].title.lower()


def test_drift_summary_storylens_no_drift() -> None:
    """_drift_summary_storylens returns explain_no_drift when 2+ runs, 0 drifted."""
    from data_quality_toolkit.adapters.ui.pages.drift_explorer import _drift_summary_storylens

    cards = _drift_summary_storylens(_make_mock_overview(5, 0, "run-42").summary)
    assert len(cards) == 1
    assert "no drift" in cards[0].title.lower() or "ok" in cards[0].title.lower()


def test_drift_summary_storylens_drift_present_returns_empty() -> None:
    """_drift_summary_storylens returns [] when drift is present (no column-level data)."""
    from data_quality_toolkit.adapters.ui.pages.drift_explorer import _drift_summary_storylens

    cards = _drift_summary_storylens(_make_mock_overview(5, 2, "run-42").summary)
    assert cards == []


def test_drift_summary_storylens_never_raises() -> None:
    """_drift_summary_storylens returns [] on any unexpected error, never raises."""
    from data_quality_toolkit.adapters.ui.pages.drift_explorer import _drift_summary_storylens

    bad_summary = object()  # has no attributes
    result = _drift_summary_storylens(bad_summary)
    assert result == []


# ── Test 5: Export StoryLens ──────────────────────────────────────────────────


def test_export_storylens_renders_after_success() -> None:
    """_render_export_storylens renders an artifact card using basenames only."""
    from data_quality_toolkit.adapters.ui.pages.export import _render_export_storylens

    fake_st = MagicMock()
    export_paths = {
        "quality_report": "/data/dist/star/quality_report.json",
        "fact_issues": "/data/dist/star/fact_issues.csv",
    }
    _render_export_storylens(fake_st, export_paths, "/data/dist")

    fake_st.subheader.assert_called_once()
    # No absolute path must appear in any rendered text
    all_text = " ".join(
        str(a) for call in fake_st.write.call_args_list for a in call.args if isinstance(a, str)
    )
    assert "/data/dist" not in all_text


def test_export_storylens_uses_basenames_only() -> None:
    """Absolute paths are stripped; only basenames appear in evidence."""
    from data_quality_toolkit.application.explanation import explain_export_artifacts

    basenames = ("quality_report.json", "fact_issues.csv")
    exp = explain_export_artifacts(artifact_basenames=basenames, outdir_name="dist")
    for ev in exp.evidence:
        assert "/" not in ev, f"Absolute path component in evidence: {ev!r}"
        assert "\\" not in ev, f"Absolute path component in evidence: {ev!r}"


def test_export_storylens_empty_paths_no_crash() -> None:
    """_render_export_storylens with empty paths does not crash and renders nothing."""
    from data_quality_toolkit.adapters.ui.pages.export import _render_export_storylens

    fake_st = MagicMock()
    _render_export_storylens(fake_st, {}, "")
    fake_st.subheader.assert_not_called()


# ── Test 6: Optional AI import guard ──────────────────────────────────────────


_OPTIONAL_AI_MODULES = frozenset(
    {
        "torch",
        "transformers",
        "tokenizers",
        "safetensors",
        "sentence_transformers",
        "huggingface_hub",
    }
)


def test_deterministic_ui_imports_do_not_load_optional_ai() -> None:
    """Importing all deterministic StoryLens UI paths must not load optional AI modules."""
    # These imports exercise provenance, models, narrator, storylens component, and all
    # wired pages without triggering any AI backend.
    import data_quality_toolkit.adapters.ui.components.storylens  # noqa: F401
    import data_quality_toolkit.adapters.ui.pages.drift_explorer  # noqa: F401
    import data_quality_toolkit.adapters.ui.pages.eda_explorer  # noqa: F401
    import data_quality_toolkit.adapters.ui.pages.export  # noqa: F401
    import data_quality_toolkit.adapters.ui.pages.run_history  # noqa: F401
    import data_quality_toolkit.application.explanation  # noqa: F401
    import data_quality_toolkit.application.explanation.provenance  # noqa: F401

    loaded = set(sys.modules.keys())
    for mod in _OPTIONAL_AI_MODULES:
        assert mod not in loaded, f"Optional AI module loaded by deterministic path: {mod!r}"


def test_optional_ai_modules_absent_from_provenance_import() -> None:
    """Importing provenance.py alone must not drag in optional AI packages."""
    import data_quality_toolkit.application.explanation.provenance  # noqa: F401

    loaded = set(sys.modules.keys())
    for mod in _OPTIONAL_AI_MODULES:
        assert mod not in loaded, f"Optional AI module loaded by provenance import: {mod!r}"
