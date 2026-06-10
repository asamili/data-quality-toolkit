"""Tests for large-data profile-only mode.

Covers _load_profile_chunked, _render_large_data_profile_overview,
and the large-mode branch in _render_data_overview.
All tests run without a live Streamlit instance.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pandas as pd

from data_quality_toolkit.adapters.ui.pages.data_overview import (
    _LARGE_MODE_BANNER,
    _render_data_overview,
    _render_large_data_profile_overview,
)
from data_quality_toolkit.adapters.ui.services.assessment import _load_profile_chunked

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
