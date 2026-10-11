"""Cross-helper tests for the consolidated Workspace Root empty-state message.

Every opt-in Save-to-Workspace helper shows the SAME clear empty-state message when
Workspace Root is blank — only on an explicit click (never on render) — and writes
no file. The message distinguishes browser downloads (always available) from the
optional workspace save, so a missing Workspace Root never reads like a failed
download. Browser download behavior itself is unaffected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.components.workspace_save_ui import (
    WORKSPACE_ROOT_EMPTY_STATE,
    render_analysis_csv_save,
)
from data_quality_toolkit.adapters.ui.pages.dim_time import (
    _SAVE_DIM_TIME_BTN,
    _render_dim_time_workspace_save,
)
from data_quality_toolkit.adapters.ui.pages.kpi_catalog import _render_kpi_save
from data_quality_toolkit.adapters.ui.pages.preprocess_studio import _save_recipe_output

_DF = pd.DataFrame({"a": [1, 2]})


class FakeSt:
    """Minimal Streamlit recorder: keyed buttons, session state, string capture."""

    def __init__(self, session_state: dict[str, Any] | None = None) -> None:
        self.session_state = session_state if session_state is not None else {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.clicks: dict[str, bool] = {}

    def _rec(self, name: str, *a: Any, **k: Any) -> None:
        self.calls.append((name, a, k))

    def __getattr__(self, name: str) -> Any:
        def recorder(*a: Any, **k: Any) -> None:
            self._rec(name, *a, **k)

        return recorder

    def button(self, label: str, **k: Any) -> bool:
        self._rec("button", label, **k)
        return bool(self.clicks.get(k.get("key", label), False))

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))


def test_empty_state_wording_distinguishes_download_from_workspace_save() -> None:
    # Clear about browser downloads vs. workspace save; never implies a failed
    # download or that analysis needs a Workspace Root.
    assert "Browser downloads are available" in WORKSPACE_ROOT_EMPTY_STATE
    assert "also save" in WORKSPACE_ROOT_EMPTY_STATE
    assert "Workspace Root" in WORKSPACE_ROOT_EMPTY_STATE
    assert "Start" in WORKSPACE_ROOT_EMPTY_STATE
    # Consolidation guard: no leftover per-artifact "into your workspace" phrasing.
    assert "into your workspace" not in WORKSPACE_ROOT_EMPTY_STATE


def test_analysis_helper_blank_root_shows_shared_message_and_writes_nothing(
    tmp_path: Path,
) -> None:
    st = FakeSt({})  # no SRC_WORKSPACE_ROOT
    st.clicks["k"] = True
    render_analysis_csv_save(
        st, button_label="Save", key="k", artifact="column_analysis", dataframe=_DF
    )

    assert WORKSPACE_ROOT_EMPTY_STATE in st.texts()
    assert not (tmp_path / "analysis").exists()
    assert "Saved to workspace" not in st.texts()


def test_dim_time_helper_blank_root_shows_shared_message_and_writes_nothing(
    tmp_path: Path,
) -> None:
    st = FakeSt({})
    st.clicks[_SAVE_DIM_TIME_BTN] = True
    _render_dim_time_workspace_save(st, "col\n1\n")

    assert WORKSPACE_ROOT_EMPTY_STATE in st.texts()
    assert not (tmp_path / "exports").exists()
    assert "Saved to workspace" not in st.texts()


def test_kpi_helper_blank_root_shows_shared_message_and_writes_nothing(tmp_path: Path) -> None:
    st = FakeSt({})
    st.clicks["k"] = True
    _render_kpi_save(
        st, button_label="Save DAX", key="k", artifact="kpi_measures", extension="dax", data=b"x"
    )

    assert WORKSPACE_ROOT_EMPTY_STATE in st.texts()
    assert not (tmp_path / "kpi").exists()
    assert "Saved to workspace" not in st.texts()


def test_recipe_helper_blank_root_shows_shared_message_and_writes_nothing(
    tmp_path: Path,
) -> None:
    st = FakeSt({})
    _save_recipe_output(st, "", None, "preprocess_recipe", "json", "{}")

    assert WORKSPACE_ROOT_EMPTY_STATE in st.texts()
    assert not (tmp_path / "recipes").exists()
    assert "Saved to workspace" not in st.texts()


def test_helpers_show_no_empty_state_message_on_render_without_click() -> None:
    # No click → no save attempted → no empty-state message (no save on render).
    st = FakeSt({})
    render_analysis_csv_save(
        st, button_label="Save", key="k", artifact="column_analysis", dataframe=_DF
    )
    assert WORKSPACE_ROOT_EMPTY_STATE not in st.texts()

    st_dim = FakeSt({})
    _render_dim_time_workspace_save(st_dim, "col\n1\n")
    assert WORKSPACE_ROOT_EMPTY_STATE not in st_dim.texts()

    st_kpi = FakeSt({})
    _render_kpi_save(
        st_kpi,
        button_label="Save DAX",
        key="k",
        artifact="kpi_measures",
        extension="dax",
        data=b"x",
    )
    assert WORKSPACE_ROOT_EMPTY_STATE not in st_kpi.texts()
