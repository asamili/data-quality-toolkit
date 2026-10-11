"""Tests for opt-in Save-to-Workspace wiring on the KPI Catalog page.

Existing DAX/TMSL/Mermaid browser downloads stay available; saving requires an
explicit button click (never on render); a blank Workspace Root is a no-op with
guidance; saved files land under ``<root>/kpi/`` with safe names; the helper's
no-overwrite/suffix behavior is honored; and no absolute path is displayed.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import patch

from data_quality_toolkit.adapters.ui.pages import kpi_catalog
from data_quality_toolkit.adapters.ui.pages.kpi_catalog import (
    _SAVE_DAX_BTN,
    _SAVE_GRAPH_BTN,
    _SAVE_TMSL_BTN,
    _render_kpi_artifacts,
)
from data_quality_toolkit.adapters.ui.state.keys import SRC_WORKSPACE_ROOT

_PATCH_EMIT = "data_quality_toolkit.adapters.ui.pages.kpi_catalog._kpi_emit_to_bytes"
_PATCH_GRAPH = "data_quality_toolkit.adapters.ui.pages.kpi_catalog._kpi_graph_to_str"

_DAX = b"MEASURE Sales := SUM(fact[amount])"
_TMSL = b'{"model": {}}'
_GRAPH = "graph TD; a-->b"


class FakeSt:
    """Streamlit recorder with columns/expander context managers and keyed buttons."""

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

    def columns(self, n: int) -> list[FakeSt]:
        self._rec("columns", n)
        return [self for _ in range(n)]

    def expander(self, label: str, **k: Any) -> FakeSt:
        self._rec("expander", label, **k)
        return self

    def download_button(self, label: str, **k: Any) -> None:
        self._rec("download_button", label, **k)

    def button(self, label: str, **k: Any) -> bool:
        self._rec("button", label, **k)
        return bool(self.clicks.get(k.get("key", label), False))

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def count(self, name: str) -> int:
        return sum(1 for c in self.calls if c[0] == name)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))


def _kpi_files(root: Path) -> list[str]:
    folder = root / "kpi"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def _render(st: FakeSt) -> None:
    with (
        patch(_PATCH_EMIT, return_value=(_DAX, _TMSL, None)),
        patch(_PATCH_GRAPH, return_value=(_GRAPH, None)),
    ):
        _render_kpi_artifacts(st, "config/kpi_catalog.yaml", 5)


def test_kpi_downloads_preserved_and_no_write_on_render(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})  # no clicks
    _render(st)

    assert st.count("download_button") == 3  # DAX + TMSL + Mermaid intact
    assert st.called("button")  # save buttons rendered
    assert not (tmp_path / "kpi").exists()
    assert "Saved to workspace" not in st.texts()


def test_kpi_save_dax_writes_under_kpi(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.clicks[_SAVE_DAX_BTN] = True
    _render(st)

    assert _kpi_files(tmp_path) == ["kpi_measures.dax"]
    assert (tmp_path / "kpi" / "kpi_measures.dax").read_bytes() == _DAX
    assert "Saved to workspace: kpi/kpi_measures.dax" in st.texts()


def test_kpi_save_tmsl_writes_under_kpi(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.clicks[_SAVE_TMSL_BTN] = True
    _render(st)

    assert _kpi_files(tmp_path) == ["kpi_model.json"]
    assert (tmp_path / "kpi" / "kpi_model.json").read_bytes() == _TMSL


def test_kpi_save_graph_writes_under_kpi(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.clicks[_SAVE_GRAPH_BTN] = True
    _render(st)

    assert _kpi_files(tmp_path) == ["kpi_graph.mmd"]
    assert (tmp_path / "kpi" / "kpi_graph.mmd").read_text(encoding="utf-8") == _GRAPH


def test_kpi_save_blank_workspace_root_writes_nothing(tmp_path: Path) -> None:
    st = FakeSt({})  # no SRC_WORKSPACE_ROOT
    st.clicks[_SAVE_DAX_BTN] = True
    _render(st)

    assert not (tmp_path / "kpi").exists()
    assert st.count("download_button") == 3  # downloads still available
    text = st.texts()
    assert "Workspace Root" in text and "Start" in text
    assert "Saved to workspace" not in text


def test_kpi_repeated_save_does_not_overwrite_and_suffixes(tmp_path: Path) -> None:
    for _ in range(2):
        st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
        st.clicks[_SAVE_DAX_BTN] = True
        _render(st)

    assert _kpi_files(tmp_path) == ["kpi_measures-1.dax", "kpi_measures.dax"]


def test_kpi_save_result_display_has_no_absolute_path(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.clicks[_SAVE_DAX_BTN] = True
    _render(st)

    text = st.texts()
    assert str(tmp_path) not in text
    assert "kpi/kpi_measures.dax" in text


def test_kpi_save_only_clicked_output_is_written(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.clicks[_SAVE_GRAPH_BTN] = True  # only the graph
    _render(st)

    assert _kpi_files(tmp_path) == ["kpi_graph.mmd"]


def test_kpi_download_filenames_remain_wired(tmp_path: Path) -> None:
    """Browser-download filenames are the stable public contract of this page."""
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    _render(st)

    file_names = [k.get("file_name") for name, _a, k in st.calls if name == "download_button"]
    assert file_names == ["measures.dax", "model.tmsl.json", "kpi_graph.mmd"]


def test_kpi_module_has_no_export_pbi_pipeline_imports() -> None:
    """No server-write export/PBI/pipeline/other-page coupling introduced.

    The pre-existing in-memory ``services.kpi`` import (DAX/TMSL/graph generation to
    a temp dir, no persistence) is intentionally allowed.
    """
    source = Path(kpi_catalog.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    forbidden = (
        "services.export",
        "services.powerbi_package",
        "pages.export",
        "pages.pipeline_runner",
        "pages.dim_time",
        "pages.preprocess_studio",
    )
    for module in imported:
        for bad in forbidden:
            assert bad not in module, f"unexpected coupling introduced: {module}"
