"""Tests for opt-in Save-to-Workspace parity on the Quality Score page.

The existing browser ``quality_rule_breakdown.csv`` download stays available; the
new save requires an explicit click (never on render); a blank Workspace Root is a
no-op with guidance; saved files land under ``<root>/analysis/`` with a safe,
dataset-prefixed name; the saved payload matches the browser download exactly; and
no absolute path is displayed. Coverage isolates the changed ``_render_rule_table``
wiring by patching the scoring helper it reads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd

from data_quality_toolkit.adapters.ui.pages.quality_score import (
    _SAVE_RULE_BREAKDOWN_BTN,
    _render_rule_table,
)
from data_quality_toolkit.adapters.ui.state.keys import SRC_WORKSPACE_ROOT

_MOCK_ROWS = "data_quality_toolkit.adapters.ui.pages.quality_score.rule_contribution_rows"
_ROWS = [
    {"rule": "completeness", "penalty": 0.10},
    {"rule": "schema", "penalty": 0.05},
]
_EXPECTED_CSV = pd.DataFrame(_ROWS).to_csv(index=False).encode("utf-8")


class FakeSt:
    """Streamlit recorder with session state and keyed buttons."""

    def __init__(self, session_state: dict[str, Any] | None = None) -> None:
        self.session_state = session_state if session_state is not None else {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.clicks: dict[str, bool] = {}

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
        return bool(self.clicks.get(k.get("key", label), False))

    def download_button(self, *a: Any, **k: Any) -> None:
        self._rec("download_button", *a, **k)

    def count(self, name: str) -> int:
        return sum(1 for c in self.calls if c[0] == name)

    def has_key(self, key: str) -> bool:
        return any(c[2].get("key") == key for c in self.calls)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))


def _analysis_files(root: Path) -> list[str]:
    folder = root / "analysis"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def test_save_button_wired_and_download_preserved_no_write_on_render(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})  # no click
    with patch(_MOCK_ROWS, return_value=_ROWS):
        _render_rule_table(st, {}, dataset_name=None)

    assert st.count("download_button") == 1  # browser download preserved
    assert st.has_key(_SAVE_RULE_BREAKDOWN_BTN)  # save button wired
    assert not (tmp_path / "analysis").exists()  # nothing written on render
    assert "Saved to workspace" not in st.texts()


def test_save_on_click_writes_under_analysis_byte_equal(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.clicks[_SAVE_RULE_BREAKDOWN_BTN] = True
    with patch(_MOCK_ROWS, return_value=_ROWS):
        _render_rule_table(st, {}, dataset_name=None)

    assert _analysis_files(tmp_path) == ["quality_rule_breakdown.csv"]
    saved = (tmp_path / "analysis" / "quality_rule_breakdown.csv").read_bytes()
    assert saved == _EXPECTED_CSV  # identical to the browser download payload
    assert "Saved to workspace: analysis/quality_rule_breakdown.csv" in st.texts()
    assert str(tmp_path) not in st.texts()  # no absolute path displayed


def test_save_uses_dataset_name_prefix(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.clicks[_SAVE_RULE_BREAKDOWN_BTN] = True
    with patch(_MOCK_ROWS, return_value=_ROWS):
        _render_rule_table(st, {}, dataset_name="customers.csv")

    assert _analysis_files(tmp_path) == ["customers_quality_rule_breakdown.csv"]


def test_blank_workspace_root_writes_nothing(tmp_path: Path) -> None:
    st = FakeSt({})  # no SRC_WORKSPACE_ROOT
    st.clicks[_SAVE_RULE_BREAKDOWN_BTN] = True
    with patch(_MOCK_ROWS, return_value=_ROWS):
        _render_rule_table(st, {}, dataset_name=None)

    assert not (tmp_path / "analysis").exists()
    text = st.texts()
    assert "Workspace Root" in text and "Start" in text
    assert "Saved to workspace" not in text


def test_no_rows_renders_no_download_or_save(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    with patch(_MOCK_ROWS, return_value=[]):
        _render_rule_table(st, {}, dataset_name=None)

    assert st.count("download_button") == 0
    assert not st.has_key(_SAVE_RULE_BREAKDOWN_BTN)
    assert not (tmp_path / "analysis").exists()
