"""Tests for opt-in Save-to-Workspace wiring on Preprocess Studio recipe outputs.

These exercise the recipe export section directly: browser downloads stay available,
saving requires an explicit button click (never on render), a blank Workspace Root is
a no-op with guidance, saved files land under ``<root>/recipes/`` with safe names, the
helper's no-overwrite/suffix behavior is honored, and no absolute path is displayed.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.pages import preprocess_studio
from data_quality_toolkit.adapters.ui.pages.preprocess_studio import (
    _SAVE_RECIPE_JSON_BTN,
    _SAVE_RECIPE_STEPS_BTN,
    _SAVE_TRANSFORMED_BTN,
    _render_export,
    _render_transformed_output,
)
from data_quality_toolkit.adapters.ui.services.preprocessing import apply_recipe
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import SRC_WORKSPACE_ROOT
from data_quality_toolkit.application.workflow.preprocessing import make_recipe_step

_DF = pd.DataFrame({"n": [1.0, 2.0, 2.0, 3.0], "c": ["a", "a", "a", "b"]})
_STEPS = [make_recipe_step("drop_duplicates", [], {})]
_PRIVATE_ROOT = r"C:\Users\example_user\private\ws"


def _context() -> DatasetContext:
    return DatasetContext(
        source_path=r"C:\Users\example_user\private\customers.csv",
        display_name="customers.csv",
        size_bytes=100,
        modified_ns=1,
    )


class FakeSt:
    """Streamlit recorder with per-key button clicks."""

    def __init__(self) -> None:
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
        key = k.get("key", label)
        return bool(self.clicks.get(key, False))

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def count(self, name: str) -> int:
        return sum(1 for c in self.calls if c[0] == name)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))


def _recipes_files(root: Path) -> list[str]:
    folder = root / "recipes"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def _preprocessed_files(root: Path) -> list[str]:
    folder = root / "preprocessed"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def _transformed_frame() -> pd.DataFrame:
    """Real apply_recipe output: drop_duplicates collapses _DF's 4 rows to 3."""
    frame, _ = apply_recipe(_DF, _STEPS)
    return frame


# --- render: downloads preserved, no write on render --------------------------


def test_export_keeps_browser_downloads_and_writes_nothing_on_render(tmp_path: Path) -> None:
    st = FakeSt()  # no button clicks
    state = {SRC_WORKSPACE_ROOT: str(tmp_path)}

    _render_export(st, _DF, _STEPS, state, _context())

    # Both browser downloads remain.
    assert st.count("download_button") == 2
    # Save buttons are rendered but nothing is written on render.
    assert st.called("button")
    assert not (tmp_path / "recipes").exists()
    assert not st.called("success")


def test_export_without_steps_shows_info_and_no_save_section(tmp_path: Path) -> None:
    st = FakeSt()
    state = {SRC_WORKSPACE_ROOT: str(tmp_path)}

    _render_export(st, _DF, [], state, _context())

    assert st.called("info")
    assert not st.called("download_button")
    assert not st.called("button")


# --- explicit save writes under recipes/ --------------------------------------


def test_save_recipe_json_writes_under_recipes(tmp_path: Path) -> None:
    st = FakeSt()
    st.clicks[_SAVE_RECIPE_JSON_BTN] = True
    state = {SRC_WORKSPACE_ROOT: str(tmp_path)}

    _render_export(st, _DF, _STEPS, state, _context())

    files = _recipes_files(tmp_path)
    assert len(files) == 1
    name = files[0]
    # save_to_workspace re-sanitizes the built name, collapsing the "__" separator.
    assert name == "customers_preprocess_recipe.json"
    saved = (tmp_path / "recipes" / name).read_text(encoding="utf-8")
    assert saved.strip().startswith("{")  # valid JSON payload content
    assert st.called("success")


def test_save_recipe_steps_csv_writes_under_recipes(tmp_path: Path) -> None:
    st = FakeSt()
    st.clicks[_SAVE_RECIPE_STEPS_BTN] = True
    state = {SRC_WORKSPACE_ROOT: str(tmp_path)}

    _render_export(st, _DF, _STEPS, state, _context())

    files = _recipes_files(tmp_path)
    assert files == ["customers_preprocess_recipe_steps.csv"]
    csv_text = (tmp_path / "recipes" / files[0]).read_text(encoding="utf-8")
    # Recipe steps table serialized via to_csv(index=False): header + one step row,
    # no leading index column (same serialization the browser CSV download uses).
    lines = csv_text.strip().splitlines()
    assert len(lines) == 2
    assert not lines[0].startswith(",")
    assert "drop_duplicates" in csv_text


def test_save_omits_dataset_when_no_context(tmp_path: Path) -> None:
    st = FakeSt()
    st.clicks[_SAVE_RECIPE_JSON_BTN] = True
    state = {SRC_WORKSPACE_ROOT: str(tmp_path)}

    _render_export(st, _DF, _STEPS, state, None)

    assert _recipes_files(tmp_path) == ["preprocess_recipe.json"]


# --- blank workspace root: no write -------------------------------------------


def test_save_with_blank_workspace_root_writes_nothing(tmp_path: Path) -> None:
    st = FakeSt()
    st.clicks[_SAVE_RECIPE_JSON_BTN] = True
    state: dict[str, Any] = {}  # no SRC_WORKSPACE_ROOT

    _render_export(st, _DF, _STEPS, state, _context())

    assert not (tmp_path / "recipes").exists()
    assert not st.called("success")
    text = st.texts()
    assert "Workspace Root" in text and "Start" in text


# --- no overwrite by default (helper suffix behavior) -------------------------


def test_repeated_save_does_not_overwrite_and_suffixes(tmp_path: Path) -> None:
    state = {SRC_WORKSPACE_ROOT: str(tmp_path)}
    for _ in range(2):
        st = FakeSt()
        st.clicks[_SAVE_RECIPE_JSON_BTN] = True
        _render_export(st, _DF, _STEPS, state, _context())

    assert _recipes_files(tmp_path) == [
        "customers_preprocess_recipe-1.json",
        "customers_preprocess_recipe.json",
    ]


# --- result display safety ----------------------------------------------------


def test_save_result_display_has_no_absolute_path(tmp_path: Path) -> None:
    st = FakeSt()
    st.clicks[_SAVE_RECIPE_JSON_BTN] = True
    state = {SRC_WORKSPACE_ROOT: str(tmp_path)}

    _render_export(st, _DF, _STEPS, state, _context())

    text = st.texts()
    assert str(tmp_path) not in text
    assert "recipes/customers_preprocess_recipe.json" in text


# --- transformed dataset output: download preserved, opt-in save under preprocessed/ --


def test_transformed_output_hidden_when_no_transformed_frame(tmp_path: Path) -> None:
    st = FakeSt()
    state = {SRC_WORKSPACE_ROOT: str(tmp_path)}

    _render_transformed_output(st, None, state, _context())

    assert not st.called("download_button")
    assert not st.called("button")
    assert not (tmp_path / "preprocessed").exists()


def test_transformed_output_writes_nothing_on_render(tmp_path: Path) -> None:
    st = FakeSt()  # no button clicks
    state = {SRC_WORKSPACE_ROOT: str(tmp_path)}

    _render_transformed_output(st, _transformed_frame(), state, _context())

    # Browser download stays available; the save button is rendered but not acted on.
    assert st.count("download_button") == 1
    assert st.called("button")
    assert not (tmp_path / "preprocessed").exists()
    assert not st.called("success")


def test_save_transformed_data_writes_transformed_frame_under_preprocessed(
    tmp_path: Path,
) -> None:
    st = FakeSt()
    st.clicks[_SAVE_TRANSFORMED_BTN] = True
    state = {SRC_WORKSPACE_ROOT: str(tmp_path)}

    _render_transformed_output(st, _transformed_frame(), state, _context())

    files = _preprocessed_files(tmp_path)
    # save_to_workspace re-sanitizes the built name, collapsing the "__" separator.
    assert files == ["customers_preprocessed_dataset.csv"]
    saved = pd.read_csv(tmp_path / "preprocessed" / files[0])
    # The saved payload is the transformed frame (3 rows), not the 4-row original input.
    assert len(saved) == 3
    assert len(saved) != len(_DF)
    assert st.called("success")


def test_save_transformed_data_with_blank_workspace_root_writes_nothing(
    tmp_path: Path,
) -> None:
    st = FakeSt()
    st.clicks[_SAVE_TRANSFORMED_BTN] = True
    state: dict[str, Any] = {}  # no SRC_WORKSPACE_ROOT

    _render_transformed_output(st, _transformed_frame(), state, _context())

    assert not (tmp_path / "preprocessed").exists()
    assert not st.called("success")
    text = st.texts()
    assert "Workspace Root" in text and "Start" in text


def test_save_transformed_data_result_display_has_no_absolute_path(tmp_path: Path) -> None:
    st = FakeSt()
    st.clicks[_SAVE_TRANSFORMED_BTN] = True
    state = {SRC_WORKSPACE_ROOT: str(tmp_path)}

    _render_transformed_output(st, _transformed_frame(), state, _context())

    text = st.texts()
    assert str(tmp_path) not in text
    assert "preprocessed/customers_preprocessed_dataset.csv" in text


# --- safety: no Export/PBI/Pipeline coupling introduced -----------------------


def test_module_has_no_export_pbi_pipeline_service_imports() -> None:
    source = Path(preprocess_studio.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    forbidden = (
        "services.export",
        "services.powerbi_package",
        "pages.export",
        "pages.pipeline_runner",
    )
    for module in imported:
        for bad in forbidden:
            assert bad not in module, f"unexpected coupling introduced: {module}"
