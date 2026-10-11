"""Tests for opt-in Save-to-Workspace wiring on the Dim Time page.

The existing browser ``dim_time.csv`` download stays available; saving requires an
explicit button click (never on render); a blank Workspace Root is a no-op with
guidance; saved files land under ``<root>/exports/`` with a safe name; the helper's
no-overwrite/suffix behavior is honored; and no absolute path is displayed.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import patch

from data_quality_toolkit.adapters.ui.pages import dim_time
from data_quality_toolkit.adapters.ui.pages.dim_time import _SAVE_DIM_TIME_BTN, _render_dim_time
from data_quality_toolkit.adapters.ui.state.keys import SRC_WORKSPACE_ROOT

_PATCH_GEN = "data_quality_toolkit.adapters.ui.pages.dim_time._generate_dim_time_csv"
_CSV = "date\n2018-01-01\n"


class FakeSt:
    """Streamlit recorder with session state and per-key button clicks."""

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

    def text_input(self, label: str, **k: Any) -> str:
        self._rec("text_input", label, **k)
        return str(k.get("value", ""))

    def number_input(self, label: str, **k: Any) -> int:
        self._rec("number_input", label, **k)
        return int(k.get("value", k.get("min_value", 0)))

    def checkbox(self, label: str, **k: Any) -> bool:
        self._rec("checkbox", label, **k)
        return False

    def button(self, label: str, **k: Any) -> bool:
        self._rec("button", label, **k)
        return bool(self.clicks.get(k.get("key", label), False))

    def download_button(self, label: str, **k: Any) -> None:
        self._rec("download_button", label, **k)

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def count(self, name: str) -> int:
        return sum(1 for c in self.calls if c[0] == name)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))


def _exports_files(root: Path) -> list[str]:
    folder = root / "exports"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def test_dim_time_download_preserved_and_no_write_on_render(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})  # no clicks
    with patch(_PATCH_GEN, return_value=(_CSV, 1, None)):
        _render_dim_time(st)

    assert st.count("download_button") == 1  # browser download intact
    assert st.called("button")  # save button rendered
    assert not (tmp_path / "exports").exists()  # nothing written on render
    assert "Saved to workspace" not in st.texts()


def test_dim_time_save_writes_under_exports(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.clicks[_SAVE_DIM_TIME_BTN] = True
    with patch(_PATCH_GEN, return_value=(_CSV, 1, None)):
        _render_dim_time(st)

    assert _exports_files(tmp_path) == ["dim_time.csv"]
    saved = (tmp_path / "exports" / "dim_time.csv").read_text(encoding="utf-8")
    assert saved == _CSV  # same content as the browser download
    assert "Saved to workspace: exports/dim_time.csv" in st.texts()


def test_dim_time_save_blank_workspace_root_writes_nothing(tmp_path: Path) -> None:
    st = FakeSt({})  # no SRC_WORKSPACE_ROOT
    st.clicks[_SAVE_DIM_TIME_BTN] = True
    with patch(_PATCH_GEN, return_value=(_CSV, 1, None)):
        _render_dim_time(st)

    assert not (tmp_path / "exports").exists()
    assert st.count("download_button") == 1  # browser download still available
    text = st.texts()
    assert "Workspace Root" in text and "Start" in text
    assert "Saved to workspace" not in text


def test_dim_time_repeated_save_does_not_overwrite_and_suffixes(tmp_path: Path) -> None:
    for _ in range(2):
        st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
        st.clicks[_SAVE_DIM_TIME_BTN] = True
        with patch(_PATCH_GEN, return_value=(_CSV, 1, None)):
            _render_dim_time(st)

    assert _exports_files(tmp_path) == ["dim_time-1.csv", "dim_time.csv"]


def test_dim_time_save_result_display_has_no_absolute_path(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.clicks[_SAVE_DIM_TIME_BTN] = True
    with patch(_PATCH_GEN, return_value=(_CSV, 1, None)):
        _render_dim_time(st)

    text = st.texts()
    assert str(tmp_path) not in text
    assert "exports/dim_time.csv" in text


def test_dim_time_module_has_no_export_pbi_pipeline_imports() -> None:
    """No server-write export/PBI/pipeline/other-page coupling introduced.

    The pre-existing in-memory ``services.kpi`` generator import is intentionally
    allowed (it is where the dim_time CSV is produced, temp-only, no persistence).
    """
    source = Path(dim_time.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    forbidden = (
        "services.export",
        "services.powerbi_package",
        "pages.export",
        "pages.pipeline_runner",
        "pages.kpi_catalog",
        "pages.preprocess_studio",
    )
    for module in imported:
        for bad in forbidden:
            assert bad not in module, f"unexpected coupling introduced: {module}"
