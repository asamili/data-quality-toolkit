"""Tests for the Statistics Lab inferential section render (page tier).

Reuses the lightweight ``FakeSt`` recorder pattern from
``test_statistics_lab.py``. The section header renders regardless of scipy; the
unavailable message renders when scipy is reported absent; real-scipy rendering
is guarded with ``importorskip`` so the suite passes with or without ``[stats]``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.pages import statistics_lab
from data_quality_toolkit.adapters.ui.pages.statistics_lab import _render_inferential


class FakeSt:
    """Minimal Streamlit recorder supporting columns/selectbox/context use."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

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

    def selectbox(self, label: str, options: Any = (), **k: Any) -> Any:
        self._rec("selectbox", label, options, **k)
        opts = list(options)
        return opts[0] if opts else None

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))


# group column first so the group selectbox picks a non-metric column.
_DF = pd.DataFrame(
    {
        "group": ["a", "b"] * 15,
        "value": [float(i % 7) + (0.0 if i % 2 == 0 else 3.0) for i in range(30)],
    }
)


def test_section_header_always_renders() -> None:
    st = FakeSt()
    _render_inferential(st, _DF)
    assert "Inferential Tests" in st.texts()


def test_unavailable_message_when_scipy_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(statistics_lab, "inferential_available", lambda: False)
    st = FakeSt()
    _render_inferential(st, _DF)
    assert st.called("warning")
    assert "unavailable" in st.texts()


def test_no_crash_on_tiny_frame() -> None:
    tiny = pd.DataFrame({"group": ["a", "b"], "value": [1.0, 2.0]})
    st = FakeSt()
    _render_inferential(st, tiny)  # must not raise on degenerate input
    assert "Inferential Tests" in st.texts()


def test_happy_path_renders_results_with_scipy() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()
    _render_inferential(st, _DF)
    text = st.texts()
    assert "Normality check" in text
    assert "Group comparison" in text
    assert "A/B comparison" in text
    # Two-group comparison renders a results table and metric cards.
    assert st.called("dataframe")
    assert st.called("metric")
