"""EDA Explorer Save-to-Workspace and CSV download parity tests."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.eda_sections import (
    _SAVE_CATEGORIES_BTN,
    _SAVE_CORRELATION_BTN,
    _SAVE_CROSSTAB_BTN,
    _SAVE_DISTRIBUTION_BTN,
    _SAVE_MISSINGNESS_BTN,
    _SAVE_NUMERIC_BY_CATEGORY_BTN,
    _SAVE_OUTLIERS_BTN,
    _SAVE_SKEW_KURTOSIS_BTN,
    _SAVE_TIME_AGGREGATION_BTN,
    _SAVE_TIME_CATEGORIES_BTN,
    _render_cat_cat,
    _render_correlation_matrix,
    _render_dt_cat,
    _render_dt_num,
    _render_eda_univariate,
    _render_missingness,
    _render_num_cat,
    _render_numeric_shape,
    _render_outlier_summary,
)
from data_quality_toolkit.adapters.ui.state.keys import SRC_WORKSPACE_ROOT


class FakeSt:
    """Streamlit recorder with keyed buttons and enough inputs for EDA renderers."""

    def __init__(self, session_state: dict[str, Any] | None = None) -> None:
        self.session_state = session_state if session_state is not None else {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.clicks: dict[str, bool] = {}
        self.selectbox_values: dict[str, Any] = {}
        self.checkbox_values: dict[str, bool] = {}

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

    def button(self, label: str, **k: Any) -> bool:
        self._rec("button", label, **k)
        key = k.get("key")
        clicked = self.clicks.get(str(key), self.clicks.get(label, False))
        on_click = k.get("on_click")
        if clicked and callable(on_click):
            on_click(*k.get("args", ()), **k.get("kwargs", {}))
        return bool(clicked)

    def download_button(self, *a: Any, **k: Any) -> None:
        self._rec("download_button", *a, **k)

    def columns(self, n: int) -> list[FakeSt]:
        self._rec("columns", n)
        return [self for _ in range(n)]

    def expander(self, label: str, **k: Any) -> FakeSt:
        self._rec("expander", label, **k)
        return self

    def selectbox(self, label: str, options: Sequence[Any] = (), **k: Any) -> Any:
        values = list(options)
        self._rec("selectbox", label, values, **k)
        lookup = str(k.get("key") or label)
        return self.selectbox_values.get(lookup, values[0] if values else None)

    def checkbox(self, label: str, **k: Any) -> bool:
        self._rec("checkbox", label, **k)
        key = str(k.get("key") or label)
        return self.checkbox_values.get(key, bool(k.get("value", False)))

    def number_input(self, label: str, **k: Any) -> Any:
        self._rec("number_input", label, **k)
        return k.get("value", k.get("min_value", 1))

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))


_DF = pd.DataFrame(
    {
        "n": [1.0, 2.0, 3.0, 4.0, 5.0, 20.0],
        "m": [2.0, 4.0, 6.0, 8.0, 10.0, 12.0],
        "c": ["a", "a", "b", "b", "c", "c"],
        "d": ["x", "y", "x", "y", "x", "y"],
        "ts": [
            "2025-01-01",
            "2025-01-02",
            "2025-01-03",
            "2025-01-04",
            "2025-01-05",
            "2025-01-06",
        ],
    }
)

_EXPECTED_SAVE_KEYS = {
    _SAVE_MISSINGNESS_BTN,
    _SAVE_DISTRIBUTION_BTN,
    _SAVE_CATEGORIES_BTN,
    _SAVE_SKEW_KURTOSIS_BTN,
    _SAVE_CORRELATION_BTN,
    _SAVE_OUTLIERS_BTN,
    _SAVE_NUMERIC_BY_CATEGORY_BTN,
    _SAVE_CROSSTAB_BTN,
    _SAVE_TIME_AGGREGATION_BTN,
    _SAVE_TIME_CATEGORIES_BTN,
}


def _analysis_files(root: Path) -> list[str]:
    folder = root / "analysis"
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


def _button_keys(st: FakeSt) -> list[str]:
    return [k["key"] for name, _, k in st.calls if name == "button" and "key" in k]


def _download_file_names(st: FakeSt) -> list[str]:
    return [
        k["file_name"] for name, _, k in st.calls if name == "download_button" and "file_name" in k
    ]


def _render_all_workspace_save_outputs(st: FakeSt) -> None:
    _render_missingness(st, _DF)
    _render_eda_univariate(st, _DF)
    _render_numeric_shape(st, _DF)
    _render_correlation_matrix(st, _DF)
    _render_outlier_summary(st, _DF)
    _render_num_cat(st, _DF, "n", "c")
    _render_cat_cat(st, _DF, "c", "d")
    _render_dt_num(st, _DF, "ts", "n")
    _render_dt_cat(st, _DF, "ts", "c")


def test_eda_workspace_save_buttons_render_without_writing(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})

    _render_all_workspace_save_outputs(st)

    assert set(_button_keys(st)) >= _EXPECTED_SAVE_KEYS
    assert not (tmp_path / "analysis").exists()
    assert "Saved to workspace" not in st.texts()


def test_eda_workspace_save_blank_root_writes_nothing(tmp_path: Path) -> None:
    st = FakeSt()
    st.clicks[_SAVE_MISSINGNESS_BTN] = True

    _render_missingness(st, _DF)

    assert not (tmp_path / "analysis").exists()
    text = st.texts()
    assert "Workspace Root" in text and "Start" in text
    assert "Saved to workspace" not in text


def test_eda_workspace_save_clicks_write_selected_outputs_under_analysis(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    for key in (
        _SAVE_MISSINGNESS_BTN,
        _SAVE_CORRELATION_BTN,
        _SAVE_NUMERIC_BY_CATEGORY_BTN,
        _SAVE_TIME_AGGREGATION_BTN,
    ):
        st.clicks[key] = True

    _render_missingness(st, _DF)
    _render_correlation_matrix(st, _DF)
    _render_num_cat(st, _DF, "n", "c")
    _render_dt_num(st, _DF, "ts", "n")

    assert _analysis_files(tmp_path) == [
        "eda_correlation.csv",
        "eda_missingness.csv",
        "eda_numeric_by_category.csv",
        "eda_time_aggregation.csv",
    ]
    text = st.texts()
    assert "analysis/eda_missingness.csv" in text
    assert "analysis/eda_correlation.csv" in text
    assert "analysis/eda_numeric_by_category.csv" in text
    assert "analysis/eda_time_aggregation.csv" in text
    assert str(tmp_path) not in text


def test_eda_workspace_save_repeated_save_suffixes_without_overwrite(tmp_path: Path) -> None:
    for _ in range(2):
        st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
        st.clicks[_SAVE_MISSINGNESS_BTN] = True
        _render_missingness(st, _DF)

    assert _analysis_files(tmp_path) == ["eda_missingness-1.csv", "eda_missingness.csv"]


def test_new_bivariate_datetime_browser_downloads_are_wired() -> None:
    st = FakeSt()

    _render_num_cat(st, _DF, "n", "c")
    _render_cat_cat(st, _DF, "c", "d")
    _render_dt_num(st, _DF, "ts", "n")
    _render_dt_cat(st, _DF, "ts", "c")

    assert _download_file_names(st) == [
        "eda_numeric_by_category.csv",
        "eda_crosstab.csv",
        "eda_time_aggregation.csv",
        "eda_time_categories.csv",
    ]
