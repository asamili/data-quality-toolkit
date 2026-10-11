"""Tests for large-data profile-only mode.

Covers _load_profile_chunked, _render_large_data_profile_overview,
and the large-mode branch in _render_data_overview.
All tests run without a live Streamlit instance.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.pages.data_overview import (
    _LARGE_MODE_BANNER,
    _MANAGED_FAIL_CLOSED_MESSAGE,
    _SMART_PREVIEW_TITLE,
    _render_data_overview,
    _render_large_data_profile_overview,
)
from data_quality_toolkit.adapters.ui.services import managed_frame_loader as _mfl
from data_quality_toolkit.adapters.ui.services.assessment import _load_profile_chunked
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    commit_trust_root,
    ensure_session_capability,
    make_source_locator,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT
from data_quality_toolkit.shared.managed_export_source import MANAGED_FULL_MAX_SOURCE_BYTES

# ---------------------------------------------------------------------------
# Minimal Streamlit test double
# ---------------------------------------------------------------------------


class FakeSt:
    """Minimal Streamlit test double — records calls, configurable return values."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._text_input_vals: dict[str, str] = {}
        self._checkbox_vals: dict[str, bool] = {}
        self._number_input_vals: dict[str, Any] = {}
        self._button_clicks: dict[str, bool] = {}

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def _r(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def call_args(self, name: str) -> list[tuple[Any, ...]]:
        return [c[1] for c in self.calls if c[0] == name]

    def call_count(self, name: str) -> int:
        return sum(1 for c in self.calls if c[0] == name)

    def header(self, *a: Any, **kw: Any) -> None:
        self._r("header", *a, **kw)

    def subheader(self, *a: Any, **kw: Any) -> None:
        self._r("subheader", *a, **kw)

    def caption(self, *a: Any, **kw: Any) -> None:
        self._r("caption", *a, **kw)

    def info(self, *a: Any, **kw: Any) -> None:
        self._r("info", *a, **kw)

    def error(self, *a: Any, **kw: Any) -> None:
        self._r("error", *a, **kw)

    def warning(self, *a: Any, **kw: Any) -> None:
        self._r("warning", *a, **kw)

    def write(self, *a: Any, **kw: Any) -> None:
        self._r("write", *a, **kw)

    def metric(self, *a: Any, **kw: Any) -> None:
        self._r("metric", *a, **kw)

    def dataframe(self, *a: Any, **kw: Any) -> None:
        self._r("dataframe", *a, **kw)

    def bar_chart(self, *a: Any, **kw: Any) -> None:
        self._r("bar_chart", *a, **kw)

    def scatter_chart(self, *a: Any, **kw: Any) -> None:
        self._r("scatter_chart", *a, **kw)

    def download_button(self, *a: Any, **kw: Any) -> None:
        self._r("download_button", *a, **kw)

    def selectbox(self, label: str, options: list[Any], key: str | None = None, **kw: Any) -> Any:
        self._r("selectbox", label, options, key=key, **kw)
        return options[0] if options else None

    def divider(self, *a: Any, **kw: Any) -> None:
        self._r("divider", *a, **kw)

    def expander(self, label: str, **kw: Any) -> FakeSt:
        self._r("expander", label, **kw)
        return self

    def columns(self, n: int) -> list[FakeSt]:
        return [FakeSt() for _ in range(n)]

    def text_input(self, label: str, **kw: Any) -> str:
        self._r("text_input", label, **kw)
        return self._text_input_vals.get(label, "")

    def checkbox(self, label: str, **kw: Any) -> bool:
        self._r("checkbox", label, **kw)
        return self._checkbox_vals.get(label, False)

    def number_input(self, label: str, **kw: Any) -> Any:
        self._r("number_input", label, **kw)
        return self._number_input_vals.get(label, kw.get("value", kw.get("min_value", 1)))

    def button(self, label: str, **kw: Any) -> bool:
        self._r("button", label, **kw)
        return self._button_clicks.get(label, False)

    def set_text_input(self, label: str, value: str) -> FakeSt:
        self._text_input_vals[label] = value
        return self

    def set_checkbox(self, label: str, value: bool) -> FakeSt:
        self._checkbox_vals[label] = value
        return self

    def set_number_input(self, label: str, value: Any) -> FakeSt:
        self._number_input_vals[label] = value
        return self

    def set_button_clicked(self, label: str, value: bool = True) -> FakeSt:
        self._button_clicks[label] = value
        return self


# ---------------------------------------------------------------------------
# Fixtures / constants
# ---------------------------------------------------------------------------

_FAKE_ENVELOPE: dict[str, Any] = {
    "run_id": "r1",
    "dataset_id": "sha1:abc",
    "ts": "2024-01-01T00:00:00Z",
    "meta": {"chunksize": 2},
    "profile": {
        "rows": 4,
        "cols": 3,
        "memory_mb": None,
        "columns": [
            {"name": "id", "dtype": "int64", "nulls": 0},
            {"name": "val", "dtype": "float64", "nulls": 1},
            {"name": "name", "dtype": "object", "nulls": 1},
        ],
    },
    "approximate": True,
    "unsupported_metrics": ["unique", "memory_mb"],
}

_LARGE_CHECKBOX_LABEL = "Large-data mode (profile-only, chunked streaming)"
_CHUNK_INPUT_LABEL = "Chunk size (rows per chunk)"

_MOCK_LOAD_CHUNKED = "data_quality_toolkit.adapters.ui.pages.data_overview._load_profile_chunked"
_MOCK_LOAD_DF = "data_quality_toolkit.adapters.ui.pages.data_overview._load_df_and_assess"


# ---------------------------------------------------------------------------
# _load_profile_chunked
# ---------------------------------------------------------------------------


def test_load_profile_chunked_success() -> None:
    with patch("data_quality_toolkit.api.profile_csv", return_value=_FAKE_ENVELOPE):
        envelope, err = _load_profile_chunked("data.csv", chunksize=2)
    assert err is None
    assert envelope is not None
    assert envelope["approximate"] is True
    assert envelope["profile"]["rows"] == 4


def test_load_profile_chunked_file_not_found() -> None:
    with patch(
        "data_quality_toolkit.api.profile_csv",
        side_effect=FileNotFoundError("data.csv not found"),
    ):
        envelope, err = _load_profile_chunked("data.csv", chunksize=2)
    assert envelope is None
    assert err is not None
    assert "not found" in err


def test_load_profile_chunked_strips_whitespace() -> None:
    with patch("data_quality_toolkit.api.profile_csv", return_value=_FAKE_ENVELOPE) as mock:
        _load_profile_chunked("  data.csv  ", chunksize=100)
    mock.assert_called_once_with("data.csv", chunksize=100)


def test_load_profile_chunked_value_error_returns_error() -> None:
    with patch(
        "data_quality_toolkit.api.profile_csv",
        side_effect=ValueError("chunksize must be positive"),
    ):
        envelope, err = _load_profile_chunked("data.csv", chunksize=0)
    assert envelope is None
    assert err is not None


# ---------------------------------------------------------------------------
# _render_large_data_profile_overview
# ---------------------------------------------------------------------------


def test_render_large_data_profile_overview_shows_banner() -> None:
    st = FakeSt()
    _render_large_data_profile_overview(st, _FAKE_ENVELOPE)
    assert st.called("warning")
    warning_args = st.call_args("warning")
    assert any(_LARGE_MODE_BANNER in str(a) for a in warning_args[0])


def test_render_large_data_profile_overview_shows_row_col_count() -> None:
    st = FakeSt()
    _render_large_data_profile_overview(st, _FAKE_ENVELOPE)
    assert st.called("write")
    write_args = st.call_args("write")
    assert any("4" in str(a) and "3" in str(a) for a in write_args[0])


def test_render_large_data_profile_overview_shows_column_dataframe() -> None:
    st = FakeSt()
    _render_large_data_profile_overview(st, _FAKE_ENVELOPE)
    assert st.called("dataframe")


def test_render_large_data_profile_overview_shows_download_button() -> None:
    st = FakeSt()
    _render_large_data_profile_overview(st, _FAKE_ENVELOPE)
    assert st.called("download_button")


def test_render_large_data_profile_overview_shows_save_button() -> None:
    """Opt-in Save-to-Workspace button is wired without touching the browser download."""
    st = FakeSt()
    _render_large_data_profile_overview(st, _FAKE_ENVELOPE)
    assert st.called("button")  # save-to-workspace button rendered
    assert st.called("download_button")  # browser download preserved


def test_render_large_data_profile_overview_no_eda_selectbox() -> None:
    """Large mode must not render EDA (no selectbox for column explorer)."""
    st = FakeSt()
    _render_large_data_profile_overview(st, _FAKE_ENVELOPE)
    assert not st.called("selectbox")


def test_render_large_data_profile_overview_no_scatter_chart() -> None:
    st = FakeSt()
    _render_large_data_profile_overview(st, _FAKE_ENVELOPE)
    assert not st.called("scatter_chart")


def test_render_large_data_profile_overview_shows_unsupported_metrics() -> None:
    st = FakeSt()
    _render_large_data_profile_overview(st, _FAKE_ENVELOPE)
    caption_args = [str(a) for args in st.call_args("caption") for a in args]
    assert any("unique" in s or "memory_mb" in s for s in caption_args)


def test_render_large_data_profile_overview_empty_columns_shows_info() -> None:
    envelope = {**_FAKE_ENVELOPE, "profile": {"rows": 0, "cols": 0, "columns": []}}
    st = FakeSt()
    _render_large_data_profile_overview(st, envelope)
    assert st.called("warning")
    assert st.called("info")
    assert not st.called("dataframe")


def test_render_large_data_profile_overview_null_pct_bar_chart_when_nulls_present() -> None:
    st = FakeSt()
    _render_large_data_profile_overview(st, _FAKE_ENVELOPE)
    assert st.called("bar_chart")


def test_render_large_data_profile_overview_no_bar_chart_when_no_nulls() -> None:
    zero_null_envelope: dict[str, Any] = {
        **_FAKE_ENVELOPE,
        "profile": {
            "rows": 4,
            "cols": 2,
            "columns": [
                {"name": "id", "dtype": "int64", "nulls": 0},
                {"name": "val", "dtype": "float64", "nulls": 0},
            ],
        },
    }
    st = FakeSt()
    _render_large_data_profile_overview(st, zero_null_envelope)
    assert not st.called("bar_chart")


# ---------------------------------------------------------------------------
# _render_data_overview — large mode routing
# ---------------------------------------------------------------------------


def test_render_data_overview_large_mode_off_by_default() -> None:
    """Checkbox unchecked → normal full-load path (not chunked)."""
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    with (
        patch(_MOCK_LOAD_DF, return_value=(None, None, "load error")),
        patch(_MOCK_LOAD_CHUNKED) as mock_chunked,
    ):
        _render_data_overview(st)
    mock_chunked.assert_not_called()


def test_render_data_overview_large_mode_enabled_routes_to_chunked() -> None:
    """Checkbox checked → _load_profile_chunked called, not _load_df_and_assess."""
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    st.set_checkbox(_LARGE_CHECKBOX_LABEL, True)
    with (
        patch(_MOCK_LOAD_CHUNKED, return_value=(_FAKE_ENVELOPE, None)) as mock_chunked,
        patch(_MOCK_LOAD_DF) as mock_full,
    ):
        _render_data_overview(st)
    mock_chunked.assert_called_once()
    mock_full.assert_not_called()


def test_render_data_overview_large_mode_shows_warning_banner() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    st.set_checkbox(_LARGE_CHECKBOX_LABEL, True)
    with patch(_MOCK_LOAD_CHUNKED, return_value=(_FAKE_ENVELOPE, None)):
        _render_data_overview(st)
    assert st.called("warning")


def test_render_data_overview_large_mode_shows_number_input_for_chunksize() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    st.set_checkbox(_LARGE_CHECKBOX_LABEL, True)
    with patch(_MOCK_LOAD_CHUNKED, return_value=(_FAKE_ENVELOPE, None)):
        _render_data_overview(st)
    assert st.called("number_input")


def test_render_data_overview_large_mode_no_metric_for_quality_score() -> None:
    """Large mode must not call st.metric (quality score display)."""
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    st.set_checkbox(_LARGE_CHECKBOX_LABEL, True)
    with patch(_MOCK_LOAD_CHUNKED, return_value=(_FAKE_ENVELOPE, None)):
        _render_data_overview(st)
    assert not st.called("metric")


def test_render_data_overview_large_mode_no_eda_selectbox() -> None:
    """Large mode must not render EDA column selector."""
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    st.set_checkbox(_LARGE_CHECKBOX_LABEL, True)
    with patch(_MOCK_LOAD_CHUNKED, return_value=(_FAKE_ENVELOPE, None)):
        _render_data_overview(st)
    assert not st.called("selectbox")


def test_render_data_overview_large_mode_no_scatter_chart() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    st.set_checkbox(_LARGE_CHECKBOX_LABEL, True)
    with patch(_MOCK_LOAD_CHUNKED, return_value=(_FAKE_ENVELOPE, None)):
        _render_data_overview(st)
    assert not st.called("scatter_chart")


def test_render_data_overview_large_mode_load_error_shows_error() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "bad.csv")
    st.set_checkbox(_LARGE_CHECKBOX_LABEL, True)
    with patch(_MOCK_LOAD_CHUNKED, return_value=(None, "file not found")):
        _render_data_overview(st)
    assert st.called("error")
    assert not st.called("warning")


def test_render_data_overview_large_mode_passes_chunksize_to_loader() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    st.set_checkbox(_LARGE_CHECKBOX_LABEL, True)
    st.set_number_input(_CHUNK_INPUT_LABEL, 50_000)
    with patch(_MOCK_LOAD_CHUNKED, return_value=(_FAKE_ENVELOPE, None)) as mock:
        _render_data_overview(st)
    _, kwargs = mock.call_args
    assert kwargs.get("chunksize") == 50_000 or mock.call_args[0][1] == 50_000


# ---------------------------------------------------------------------------
# Backward compatibility: normal mode unchanged
# ---------------------------------------------------------------------------

_FAKE_DF = pd.DataFrame({"n": [1.0, 2.0, 3.0], "c": ["a", "b", "a"]})
_FAKE_PROFILE: dict[str, Any] = {
    "rows": 3,
    "cols": 2,
    "memory_mb": 0.01,
    "columns": [
        {"name": "n", "dtype": "float64", "nulls": 0, "unique": 3, "min": 1.0, "max": 3.0},
        {"name": "c", "dtype": "object", "nulls": 0, "unique": 2},
    ],
}
_FAKE_ASSESSMENT: dict[str, Any] = {"score": 0.95, "issues": []}
_FAKE_RESULT: dict[str, Any] = {
    "run_id": "r1",
    "dataset_id": "sha1:abc",
    "ts": "2025-01-01T00:00:00Z",
    "meta": {},
    "profile": _FAKE_PROFILE,
    "assessment": _FAKE_ASSESSMENT,
}


def test_render_data_overview_normal_mode_calls_full_load() -> None:
    """Without large mode, the normal full-load path must be used."""
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    with (
        patch(_MOCK_LOAD_DF, return_value=(_FAKE_DF, _FAKE_RESULT, None)) as mock_full,
        patch(_MOCK_LOAD_CHUNKED) as mock_chunked,
    ):
        _render_data_overview(st)
    mock_full.assert_called_once()
    mock_chunked.assert_not_called()


def test_render_data_overview_normal_mode_shows_metric() -> None:
    """Normal mode must show quality score metric."""
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    with patch(_MOCK_LOAD_DF, return_value=(_FAKE_DF, _FAKE_RESULT, None)):
        _render_data_overview(st)
    assert st.called("metric")


def test_render_data_overview_empty_csv_shows_info_before_checkbox() -> None:
    """No csv path → info shown, checkbox never reached."""
    st = FakeSt()
    _render_data_overview(st)
    assert st.called("info")
    assert not st.called("checkbox") or not st.called("metric")


# ---------------------------------------------------------------------------
# Issue-level StoryLens explanations
# ---------------------------------------------------------------------------

# score >= 0.90 → quality-score card is "ok" severity (no st.warning from the
# score card). st.warning is otherwise only emitted by the high-cardinality
# notice, so a missing-value issue card is identified by its text ("missing"),
# and a constant-column issue card by st.info text ("constant").


def _result_with_issues(issues: list[dict[str, Any]], score: float = 0.95) -> dict[str, Any]:
    return {
        **_FAKE_RESULT,
        "assessment": {"score": score, "issues": issues},
    }


def _all_text(st: FakeSt, name: str) -> str:
    return " ".join(str(a) for args in st.call_args(name) for a in args)


def test_render_data_overview_score_only_storylens_when_no_issue_details() -> None:
    """No issues → page renders the score card only, no issue warning/info card."""
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    with patch(_MOCK_LOAD_DF, return_value=(_FAKE_DF, _result_with_issues([]), None)):
        _render_data_overview(st)
    assert st.called("metric")
    assert "missing" not in _all_text(st, "warning")  # no missing-value card
    assert not st.called("info")  # no constant-column card


def test_render_data_overview_missing_value_issue_adds_explanation() -> None:
    """A missing-value issue produces an additional StoryLens explanation."""
    issues = [
        {
            "type": "missing",
            "column": "revenue",
            "pct": 0.3,
            "severity": "high",
            "category": "Completeness",
            "message": "Column 'revenue' has 30.0% missing values",
        }
    ]
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    with patch(_MOCK_LOAD_DF, return_value=(_FAKE_DF, _result_with_issues(issues), None)):
        _render_data_overview(st)
    assert st.called("warning")
    text = _all_text(st, "warning")
    assert "revenue" in text and "missing" in text


def test_render_data_overview_constant_column_issue_adds_explanation() -> None:
    """A constant-column issue produces an additional StoryLens explanation."""
    issues = [
        {
            "type": "constant_column",
            "column": "status",
            "severity": "medium",
            "category": "Completeness",
            "message": "Column 'status' has only one distinct non-null value",
        }
    ]
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    with patch(_MOCK_LOAD_DF, return_value=(_FAKE_DF, _result_with_issues(issues), None)):
        _render_data_overview(st)
    assert st.called("info")
    text = _all_text(st, "info")
    assert "status" in text and "constant" in text


def test_render_data_overview_unsupported_or_incomplete_issue_skipped() -> None:
    """Unsupported type and a missing-issue lacking column/pct are skipped safely."""
    issues = [
        {"type": "some_other_check", "column": "x", "severity": "low"},
        {"type": "missing"},  # no column, no pct → skipped, no fabrication
    ]
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    with patch(_MOCK_LOAD_DF, return_value=(_FAKE_DF, _result_with_issues(issues), None)):
        _render_data_overview(st)
    assert st.called("metric")  # page still rendered, no raise
    assert "missing" not in _all_text(st, "warning")  # no missing-value card
    assert not st.called("info")  # no constant-column card


# ---------------------------------------------------------------------------
# Managed root-first dispatch: FULL / LARGE / source-size behavior
# ---------------------------------------------------------------------------

_MOCK_MANAGED_FRAME = "data_quality_toolkit.adapters.ui.pages.data_overview.get_managed_frame"
_MOCK_MANAGED_ASSESS = "data_quality_toolkit.adapters.ui.pages.data_overview.get_managed_assessment"
_MANAGED_ABS = "C:\\workspace\\versions\\v1\\data.csv"


@pytest.fixture(autouse=True)
def _clean_managed_caches() -> Any:
    _mfl.clear_managed_caches()
    yield
    _mfl.clear_managed_caches()


def _trusted_session(
    *, large: bool = False, size: int = 2048, absolute: str = _MANAGED_ABS
) -> dict[str, Any]:
    state: dict[str, Any] = {}
    capability = ensure_session_capability(state)
    commit_trust_root(
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
        modified_ns=10,
        large_file_mode=large,
    )
    return state


def _managed_envelope() -> dict[str, Any]:
    return {"profile": _FAKE_PROFILE, "assessment": _FAKE_ASSESSMENT}


def test_managed_full_dispatches_through_managed_loader() -> None:
    st = FakeSt()
    session = _trusted_session()
    with (
        patch(_MOCK_MANAGED_FRAME, return_value=_FAKE_DF) as mock_frame,
        patch(_MOCK_MANAGED_ASSESS, return_value=_managed_envelope()) as mock_assess,
        patch(_MOCK_LOAD_DF) as mock_full,
        patch(_MOCK_LOAD_CHUNKED) as mock_chunked,
    ):
        _render_data_overview(st, session)
    mock_frame.assert_called_once()
    mock_assess.assert_called_once()
    mock_full.assert_not_called()
    mock_chunked.assert_not_called()
    assert st.called("metric")


def test_managed_large_routes_to_profile_only_from_trusted_source() -> None:
    st = FakeSt()
    session = _trusted_session(large=True)
    with (
        patch(_MOCK_LOAD_CHUNKED, return_value=(_FAKE_ENVELOPE, None)) as mock_chunked,
        patch(_MOCK_MANAGED_FRAME) as mock_frame,
        patch(_MOCK_LOAD_DF) as mock_full,
    ):
        _render_data_overview(st, session)
    mock_chunked.assert_called_once()
    assert mock_chunked.call_args[0][0] == _MANAGED_ABS  # trusted machine path, root-first
    mock_frame.assert_not_called()  # LARGE never materializes a DataFrame
    mock_full.assert_not_called()
    assert st.called("warning")  # profile-only banner
    assert not st.called("metric")


def test_managed_mirror_without_trust_fails_closed() -> None:
    st = FakeSt()
    session: dict[str, Any] = {
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
    with (
        patch(_MOCK_MANAGED_FRAME) as mock_frame,
        patch(_MOCK_LOAD_DF) as mock_full,
        patch(_MOCK_LOAD_CHUNKED) as mock_chunked,
    ):
        _render_data_overview(st, session)
    mock_frame.assert_not_called()
    mock_full.assert_not_called()
    mock_chunked.assert_not_called()
    assert st.called("error")
    assert _MANAGED_FAIL_CLOSED_MESSAGE in _all_text(st, "error")


def test_manual_path_cannot_override_valid_managed_trust() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "C:/manual/other.csv")
    session = _trusted_session()
    with (
        patch(_MOCK_MANAGED_FRAME, return_value=_FAKE_DF) as mock_frame,
        patch(_MOCK_MANAGED_ASSESS, return_value=_managed_envelope()),
        patch(_MOCK_LOAD_DF) as mock_full,
    ):
        _render_data_overview(st, session)
    mock_frame.assert_called_once()
    mock_full.assert_not_called()
    assert not st.called("text_input")  # manual override input never rendered


def test_managed_full_above_size_ceiling_is_refused() -> None:
    st = FakeSt()
    session = _trusted_session(size=MANAGED_FULL_MAX_SOURCE_BYTES + 1)
    with patch(_MOCK_LOAD_DF) as mock_full:
        _render_data_overview(st, session)
    mock_full.assert_not_called()
    assert st.called("error")
    error_text = _all_text(st, "error")
    assert "size ceiling" in error_text
    assert _MANAGED_ABS not in error_text  # privacy-safe refusal


def test_managed_full_exactly_at_size_ceiling_is_permitted(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv = tmp_path / "versions" / "v1" / "data.csv"
    csv.parent.mkdir(parents=True)
    csv.write_text("n,c\n1,a\n", encoding="utf-8")
    session = _trusted_session(size=MANAGED_FULL_MAX_SOURCE_BYTES, absolute=str(csv.resolve()))
    monkeypatch.setattr(_mfl, "_revalidate", lambda root: None)
    st = FakeSt()
    with (
        patch(_MOCK_MANAGED_ASSESS, return_value=_managed_envelope()),
        patch(_MOCK_LOAD_DF) as mock_full,
    ):
        _render_data_overview(st, session)
    mock_full.assert_not_called()
    assert not st.called("error")  # exactly at the boundary is permitted
    assert st.called("metric")


def test_unmanaged_flow_is_unchanged_when_no_trust_exists() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    with (
        patch(_MOCK_LOAD_DF, return_value=(_FAKE_DF, _FAKE_RESULT, None)) as mock_full,
        patch(_MOCK_MANAGED_FRAME) as mock_frame,
    ):
        _render_data_overview(st, {})
    mock_full.assert_called_once()
    mock_frame.assert_not_called()
    assert st.called("metric")


# ---------------------------------------------------------------------------
# Smart Preview inside large-file mode
# ---------------------------------------------------------------------------
# The preview is additive: it reads the same approximate chunked profile the
# page already holds, never materializes a DataFrame, and never upgrades a
# sample-derived reading into a dataset-wide claim.


def _preview_text(st: FakeSt) -> str:
    """Return only the text rendered from the Smart Preview subheader onward."""
    whole = " ".join(
        str(value) for _, args, _ in st.calls for value in args if isinstance(value, str)
    )
    marker = whole.find(_SMART_PREVIEW_TITLE)
    return whole[marker:] if marker >= 0 else ""


def test_large_mode_renders_the_smart_preview_from_the_chunked_profile() -> None:
    st = FakeSt()
    _render_large_data_profile_overview(st, _FAKE_ENVELOPE)
    preview = _preview_text(st)
    assert preview
    assert "bounded sample" in preview
    assert "4 rows × 3 columns" in preview


def test_large_mode_smart_preview_does_not_materialize_a_dataframe() -> None:
    st = FakeSt()
    with (
        patch(_MOCK_LOAD_DF) as mock_full,
        patch(_MOCK_MANAGED_FRAME) as mock_frame,
    ):
        _render_large_data_profile_overview(st, _FAKE_ENVELOPE)
    mock_full.assert_not_called()
    mock_frame.assert_not_called()
    assert "no full DataFrame is loaded" in _preview_text(st)


def test_large_mode_smart_preview_never_claims_an_exact_fact() -> None:
    st = FakeSt()
    _render_large_data_profile_overview(st, _FAKE_ENVELOPE)
    preview = _preview_text(st)
    assert "Shape (bounded sample)" in preview
    assert "Shape (fact)" not in preview


def test_large_mode_approximate_profile_line_is_still_rendered_first() -> None:
    """The preview is inserted after — not before — the existing shape line."""
    st = FakeSt()
    _render_large_data_profile_overview(st, _FAKE_ENVELOPE)
    first_write = st.call_args("write")[0]
    assert any("Dataset Profile (approximate)" in str(a) for a in first_write)


def test_large_mode_smart_preview_adds_no_download_or_input_control() -> None:
    st = FakeSt()
    _render_large_data_profile_overview(st, _FAKE_ENVELOPE)
    assert st.call_count("download_button") == 1  # pre-existing column-analysis download only
    assert not st.called("number_input")  # chunk-size input belongs to the outer branch
    assert not st.called("selectbox")


def test_large_mode_empty_profile_keeps_the_safe_no_column_state() -> None:
    envelope = {**_FAKE_ENVELOPE, "profile": {"rows": 0, "cols": 0, "columns": []}}
    st = FakeSt()
    _render_large_data_profile_overview(st, envelope)
    preview = _preview_text(st)
    assert "No columns are available to group." in preview
    assert st.called("info")  # existing "No column data available." state preserved
    assert not st.called("dataframe")  # and still no table is drawn


def test_managed_large_mode_passes_the_managed_identity_to_the_preview() -> None:
    st = FakeSt()
    session = _trusted_session(large=True)
    with patch(_MOCK_LOAD_CHUNKED, return_value=(_FAKE_ENVELOPE, None)):
        _render_data_overview(st, session)
    preview = _preview_text(st)
    assert "Managed version" in preview
    assert "large-file profile mode" in preview
    assert _MANAGED_ABS not in preview
