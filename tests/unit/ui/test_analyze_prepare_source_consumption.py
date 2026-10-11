"""Focused tests for Analyze/Prepare DatasetContext source consumption."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pandas as pd

from data_quality_toolkit.adapters.ui.pages import (
    data_overview,
    eda_explorer,
    preprocess_studio,
    quality_score,
    statistics_lab,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT


class FakeSt:
    """Streamlit-like recorder with minimal widget behavior."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.text_values: dict[str, str] = {}
        self.checkbox_values: dict[str, bool] = {}
        self.button_values: dict[str, bool] = {}

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def __getattr__(self, name: str) -> Any:
        def recorder(*args: Any, **kwargs: Any) -> None:
            self._record(name, *args, **kwargs)

        return recorder

    def columns(self, count: int) -> list[FakeSt]:
        self._record("columns", count)
        return [self for _ in range(count)]

    def expander(self, label: str, **kwargs: Any) -> FakeSt:
        self._record("expander", label, **kwargs)
        return self

    def text_input(self, label: str, **kwargs: Any) -> str:
        self._record("text_input", label, **kwargs)
        return self.text_values.get(label, str(kwargs.get("value", "")))

    def checkbox(self, label: str, **kwargs: Any) -> bool:
        self._record("checkbox", label, **kwargs)
        return self.checkbox_values.get(label, bool(kwargs.get("value", False)))

    def button(self, label: str, **kwargs: Any) -> bool:
        self._record("button", label, **kwargs)
        return self.button_values.get(label, False)

    def selectbox(self, label: str, options: list[Any], **kwargs: Any) -> Any:
        self._record("selectbox", label, options, **kwargs)
        return options[0] if options else None

    def multiselect(self, label: str, options: list[Any], **kwargs: Any) -> list[Any]:
        self._record("multiselect", label, options, **kwargs)
        return []

    def number_input(self, label: str, **kwargs: Any) -> int | float:
        self._record("number_input", label, **kwargs)
        value = kwargs.get("value", kwargs.get("min_value", 0))
        return value if isinstance(value, int | float) else 0

    def rendered_text(self) -> str:
        return " ".join(
            str(value) for _, args, _ in self.calls for value in args if isinstance(value, str)
        )

    def calls_named(self, name: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        return [(args, kwargs) for kind, args, kwargs in self.calls if kind == name]


def _context(*, large_file_mode: bool = False) -> DatasetContext:
    return DatasetContext(
        source_path=r"C:\Users\example_user\private\customers.csv",
        display_name="customers.csv",
        size_bytes=4096,
        modified_ns=1,
        large_file_mode=large_file_mode,
    )


def _assessment_result() -> tuple[pd.DataFrame, dict[str, Any], None]:
    df = pd.DataFrame({"amount": [10, 20], "segment": ["a", "b"]})
    result = {
        "profile": {
            "rows": 2,
            "cols": 2,
            "memory_mb": 0.01,
            "columns": [
                {
                    "name": "amount",
                    "dtype": "int64",
                    "nulls": 0,
                    "unique": 2,
                    "min": 10,
                    "max": 20,
                },
                {"name": "segment", "dtype": "object", "nulls": 0, "unique": 2},
            ],
        },
        "assessment": {"score": 1.0, "quality_score": 1.0, "issues": []},
    }
    return df, result, None


def test_missing_dataset_context_callout_points_to_start() -> None:
    pages = (
        data_overview._render_data_overview,
        eda_explorer._render_eda_explorer,
        statistics_lab._render_statistics_lab,
        quality_score._render_quality_score,
        preprocess_studio._render_preprocess_studio,
    )

    for render_page in pages:
        st = FakeSt()
        render_page(st, {})
        text = st.rendered_text()
        assert "Set the dataset source in Start / Load Dataset" in text
        assert "Advanced/manual CSV path override" in text
        assert any(args[0] == "CSV path" for args, _ in st.calls_named("text_input"))


def test_data_overview_prefers_dataset_context_path_without_leaking_source() -> None:
    state = {DATASET_CONTEXT: _context()}
    st = FakeSt()
    captured: dict[str, str] = {}

    def load(csv_path: str) -> tuple[pd.DataFrame, dict[str, Any], None]:
        captured["csv_path"] = csv_path
        return _assessment_result()

    with patch(
        "data_quality_toolkit.adapters.ui.pages.data_overview._load_df_and_assess",
        side_effect=load,
    ):
        data_overview._render_data_overview(st, state)

    text = st.rendered_text()
    assert captured["csv_path"] == state[DATASET_CONTEXT].source_path
    assert "Using dataset source from Start" in text
    assert "customers.csv" in text
    assert r"C:\Users\example_user\private" not in text
    assert not st.calls_named("text_input")


def test_large_mode_analyze_prepare_pages_show_basename_source_summary() -> None:
    state = {DATASET_CONTEXT: _context(large_file_mode=True)}
    pages = (
        eda_explorer._render_eda_explorer,
        statistics_lab._render_statistics_lab,
        quality_score._render_quality_score,
        preprocess_studio._render_preprocess_studio,
    )

    for render_page in pages:
        st = FakeSt()
        render_page(st, state)
        text = st.rendered_text()
        assert "Using dataset source from Start" in text
        assert "customers.csv" in text
        assert "large-file profile mode" in text
        assert r"C:\Users\example_user\private" not in text
