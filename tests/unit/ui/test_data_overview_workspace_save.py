"""Tests for opt-in Save-to-Workspace wiring on the Data Overview page.

The existing browser ``column_analysis.csv`` download stays available; saving
requires an explicit button click (never on render); a blank Workspace Root is a
no-op with guidance; saved files land under ``<root>/analysis/`` with a safe,
dataset-prefixed name; the foundation's no-overwrite/suffix behavior is honored;
the saved payload matches the browser download exactly; and no absolute path is
displayed.

Coverage is split between the reusable helper (``render_analysis_csv_save``) and
the Data Overview full-mode wiring that calls it.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd

from data_quality_toolkit.adapters.ui.components.workspace_save_ui import (
    render_analysis_csv_save,
)
from data_quality_toolkit.adapters.ui.eda import _build_overview_table
from data_quality_toolkit.adapters.ui.pages import data_overview
from data_quality_toolkit.adapters.ui.pages.data_overview import (
    _SAVE_COLUMN_ANALYSIS_BTN,
    _SAVE_FLAGGED_ISSUES_BTN,
    _SAVE_LARGE_COLUMN_ANALYSIS_BTN,
    _render_data_overview,
    _render_large_data_profile_overview,
)
from data_quality_toolkit.adapters.ui.state.keys import SRC_WORKSPACE_ROOT
from data_quality_toolkit.application.explanation.models import Explanation

_MOCK_LOAD = "data_quality_toolkit.adapters.ui.pages.data_overview._load_df_and_assess"
_MOCK_EXPLAIN = "data_quality_toolkit.adapters.ui.pages.data_overview.try_explain"

_OVERVIEW_DF = pd.DataFrame(
    {"column": ["a", "b"], "dtype": ["int64", "object"], "null_pct": [0.0, 25.0]}
)

_FAKE_DF = pd.DataFrame({"n": [1.0, 2.0, 3.0], "c": ["a", "b", "a"]})
_FAKE_PROFILE: dict[str, Any] = {
    "rows": 3,
    "cols": 2,
    "memory_mb": 0.01,
    "columns": [
        {"name": "n", "dtype": "float64", "nulls": 0, "unique": 3, "null_pct": 0.0},
        {"name": "c", "dtype": "object", "nulls": 0, "unique": 2, "null_pct": 0.0},
    ],
}
_FAKE_RESULT_CLEAN: dict[str, Any] = {
    "profile": _FAKE_PROFILE,
    "assessment": {"score": 0.95, "issues": []},
}
_FAKE_ISSUES: list[dict[str, Any]] = [
    {
        "type": "missing",
        "column": "n",
        "pct": 0.1,
        "severity": "low",
        "category": "Completeness",
        "message": "Column 'n' has 10.0% missing values",
    }
]
_FAKE_RESULT_WITH_ISSUES: dict[str, Any] = {
    "profile": _FAKE_PROFILE,
    "assessment": {"score": 0.80, "issues": _FAKE_ISSUES},
}
# Large-mode profile-only envelope (chunked path — no full DataFrame, no context).
_LARGE_ENVELOPE: dict[str, Any] = {
    "profile": {
        "rows": 4,
        "cols": 2,
        "columns": [
            {"name": "id", "dtype": "int64", "nulls": 0},
            {"name": "val", "dtype": "float64", "nulls": 1},
        ],
    },
    "unsupported_metrics": ["unique"],
}
_FALLBACK = Explanation(
    title="Quality Score",
    summary="Deterministic fallback summary.",
    evidence=("quality_score=0.95",),
    why_it_matters="Quality matters.",
    recommended_action="Review issues.",
    limitations="Explanation only, not validation.",
    severity="ok",
)


class FakeSt:
    """Streamlit recorder with session state, keyed buttons, and context managers."""

    def __init__(self, session_state: dict[str, Any] | None = None) -> None:
        self.session_state = session_state if session_state is not None else {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.clicks: dict[str, bool] = {}
        self._text_input_vals: dict[str, str] = {}

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

    def columns(self, n: int) -> list[FakeSt]:
        self._rec("columns", n)
        return [self for _ in range(n)]

    def expander(self, label: str, **k: Any) -> FakeSt:
        self._rec("expander", label, **k)
        return self

    def text_input(self, label: str, **k: Any) -> str:
        self._rec("text_input", label, **k)
        return self._text_input_vals.get(label, str(k.get("value", "")))

    def number_input(self, label: str, **k: Any) -> Any:
        self._rec("number_input", label, **k)
        return k.get("value", k.get("min_value", 1))

    def checkbox(self, label: str, **k: Any) -> bool:
        self._rec("checkbox", label, **k)
        return False

    def selectbox(self, label: str, options: Sequence[Any] = (), **k: Any) -> Any:
        self._rec("selectbox", label, options, **k)
        return options[0] if options else None

    def set_text_input(self, label: str, value: str) -> FakeSt:
        self._text_input_vals[label] = value
        return self

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def count(self, name: str) -> int:
        return sum(1 for c in self.calls if c[0] == name)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))


def _analysis_files(root: Path) -> list[str]:
    folder = root / "analysis"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


# ── Helper: render behavior ──────────────────────────────────────────────────


def test_helper_no_save_on_render_but_button_and_caption_shown(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})  # no clicks
    render_analysis_csv_save(
        st,
        button_label="Save column analysis to workspace",
        key="k",
        artifact="column_analysis",
        dataframe=_OVERVIEW_DF,
        dataset_name="sales.csv",
        caption="Optionally save under analysis.",
    )

    assert st.called("button")  # save button rendered
    assert "Optionally save under analysis." in st.texts()  # caption shown
    assert not (tmp_path / "analysis").exists()  # nothing written on render
    assert "Saved to workspace" not in st.texts()


def test_helper_save_writes_under_analysis_with_dataset_name(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.clicks["k"] = True
    render_analysis_csv_save(
        st,
        button_label="Save column analysis to workspace",
        key="k",
        artifact="column_analysis",
        dataframe=_OVERVIEW_DF,
        dataset_name="sales.csv",
    )

    # save_to_workspace re-sanitizes the built name, collapsing the "__" separator.
    assert _analysis_files(tmp_path) == ["sales_column_analysis.csv"]
    saved = (tmp_path / "analysis" / "sales_column_analysis.csv").read_bytes()
    # Byte-for-byte identical to the payload the browser download serves.
    assert saved == _OVERVIEW_DF.to_csv(index=False).encode("utf-8")
    assert "Saved to workspace: analysis/sales_column_analysis.csv" in st.texts()


def test_helper_save_without_dataset_uses_plain_filename(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.clicks["k"] = True
    render_analysis_csv_save(
        st, button_label="Save", key="k", artifact="column_analysis", dataframe=_OVERVIEW_DF
    )

    assert _analysis_files(tmp_path) == ["column_analysis.csv"]


def test_helper_blank_workspace_root_writes_nothing(tmp_path: Path) -> None:
    st = FakeSt({})  # no SRC_WORKSPACE_ROOT
    st.clicks["k"] = True
    render_analysis_csv_save(
        st, button_label="Save", key="k", artifact="column_analysis", dataframe=_OVERVIEW_DF
    )

    assert not (tmp_path / "analysis").exists()
    text = st.texts()
    assert "Workspace Root" in text and "Start" in text
    assert "Saved to workspace" not in text


def test_helper_repeated_save_suffixes_and_does_not_overwrite(tmp_path: Path) -> None:
    for _ in range(2):
        st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
        st.clicks["k"] = True
        render_analysis_csv_save(
            st, button_label="Save", key="k", artifact="column_analysis", dataframe=_OVERVIEW_DF
        )

    assert _analysis_files(tmp_path) == ["column_analysis-1.csv", "column_analysis.csv"]


def test_helper_result_display_has_no_absolute_path(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.clicks["k"] = True
    render_analysis_csv_save(
        st, button_label="Save", key="k", artifact="column_analysis", dataframe=_OVERVIEW_DF
    )

    text = st.texts()
    assert str(tmp_path) not in text
    assert "analysis/column_analysis.csv" in text


# ── Data Overview wiring ─────────────────────────────────────────────────────


def test_data_overview_full_mode_wires_save_button_and_preserves_download(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})  # no click → no save on render
    st.set_text_input("CSV path", "data.csv")
    with (
        patch(_MOCK_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT_CLEAN, None)),
        patch(_MOCK_EXPLAIN, return_value=_FALLBACK),
    ):
        _render_data_overview(st)

    # browser column-analysis download preserved (clean assessment → no issues download)
    assert st.count("download_button") == 1
    # save button wired
    assert any(c[0] == "button" and c[2].get("key") == _SAVE_COLUMN_ANALYSIS_BTN for c in st.calls)
    # nothing written on render
    assert not (tmp_path / "analysis").exists()
    assert "Saved to workspace" not in st.texts()


def test_data_overview_full_mode_save_on_click_writes_under_analysis(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.set_text_input("CSV path", "data.csv")
    st.clicks[_SAVE_COLUMN_ANALYSIS_BTN] = True
    with (
        patch(_MOCK_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT_CLEAN, None)),
        patch(_MOCK_EXPLAIN, return_value=_FALLBACK),
    ):
        _render_data_overview(st)

    files = _analysis_files(tmp_path)
    assert files == ["column_analysis.csv"]  # manual CSV path → no dataset context prefix
    assert "Saved to workspace: analysis/column_analysis.csv" in st.texts()
    assert str(tmp_path) not in st.texts()


def test_data_overview_module_has_no_export_pbi_pipeline_or_other_page_imports() -> None:
    """No server-write export/PBI/pipeline/other-analysis-page coupling introduced."""
    source = Path(data_overview.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    forbidden = (
        "services.export",
        "services.powerbi_package",
        "pages.export",
        "pages.pipeline_runner",
        "pages.kpi_catalog",
        "pages.dim_time",
        "pages.preprocess_studio",
        "pages.drift_explorer",
        "pages.eda_explorer",
        "pages.statistics_lab",
        "pages.quality_score",
    )
    for module in imported:
        for bad in forbidden:
            assert bad not in module, f"unexpected coupling introduced: {module}"


# ── Large-mode column_analysis wiring ────────────────────────────────────────


def _expected_large_column_analysis_csv() -> bytes:
    overview_df = pd.DataFrame(_build_overview_table(_LARGE_ENVELOPE["profile"]))
    csv_text: str = overview_df.to_csv(index=False)
    return csv_text.encode("utf-8")


def test_large_mode_column_analysis_no_save_on_render(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})  # no click → no save on render
    _render_large_data_profile_overview(st, _LARGE_ENVELOPE)

    # browser download preserved and save button wired to the large-mode key
    assert st.count("download_button") == 1
    assert any(
        c[0] == "button" and c[2].get("key") == _SAVE_LARGE_COLUMN_ANALYSIS_BTN for c in st.calls
    )
    # nothing written on render
    assert not (tmp_path / "analysis").exists()
    assert "Saved to workspace" not in st.texts()


def test_large_mode_column_analysis_save_on_click_writes_under_analysis(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.clicks[_SAVE_LARGE_COLUMN_ANALYSIS_BTN] = True
    _render_large_data_profile_overview(st, _LARGE_ENVELOPE)

    # no dataset context in large mode → plain column_analysis.csv
    assert _analysis_files(tmp_path) == ["column_analysis.csv"]
    saved = (tmp_path / "analysis" / "column_analysis.csv").read_bytes()
    assert saved == _expected_large_column_analysis_csv()  # byte-equal to browser download
    assert "Saved to workspace: analysis/column_analysis.csv" in st.texts()
    assert str(tmp_path) not in st.texts()  # no absolute path displayed


def test_large_mode_column_analysis_blank_workspace_root_writes_nothing(tmp_path: Path) -> None:
    st = FakeSt({})  # no SRC_WORKSPACE_ROOT
    st.clicks[_SAVE_LARGE_COLUMN_ANALYSIS_BTN] = True
    _render_large_data_profile_overview(st, _LARGE_ENVELOPE)

    assert not (tmp_path / "analysis").exists()
    text = st.texts()
    assert "Workspace Root" in text and "Start" in text
    assert "Saved to workspace" not in text


def test_large_mode_column_analysis_repeated_save_suffixes(tmp_path: Path) -> None:
    for _ in range(2):
        st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
        st.clicks[_SAVE_LARGE_COLUMN_ANALYSIS_BTN] = True
        _render_large_data_profile_overview(st, _LARGE_ENVELOPE)

    # no overwrite by default — second save gets a numeric suffix
    assert _analysis_files(tmp_path) == ["column_analysis-1.csv", "column_analysis.csv"]


# ── Full-mode flagged_issues wiring ──────────────────────────────────────────


def test_data_overview_flagged_issues_wires_save_button_and_preserves_download(
    tmp_path: Path,
) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})  # no click → no save on render
    st.set_text_input("CSV path", "data.csv")
    with (
        patch(_MOCK_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT_WITH_ISSUES, None)),
        patch(_MOCK_EXPLAIN, return_value=_FALLBACK),
    ):
        _render_data_overview(st)

    # both browser downloads preserved: flagged_issues + column_analysis
    assert st.count("download_button") == 2
    # flagged-issues save button wired by its own stable key
    assert any(c[0] == "button" and c[2].get("key") == _SAVE_FLAGGED_ISSUES_BTN for c in st.calls)
    # nothing written on render
    assert not (tmp_path / "analysis").exists()
    assert "Saved to workspace" not in st.texts()


def test_data_overview_flagged_issues_save_on_click_writes_under_analysis(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.set_text_input("CSV path", "data.csv")
    st.clicks[_SAVE_FLAGGED_ISSUES_BTN] = True
    with (
        patch(_MOCK_LOAD, return_value=(_FAKE_DF, _FAKE_RESULT_WITH_ISSUES, None)),
        patch(_MOCK_EXPLAIN, return_value=_FALLBACK),
    ):
        _render_data_overview(st)

    # flagged_issues artifact naming; manual CSV path → no dataset prefix
    assert _analysis_files(tmp_path) == ["flagged_issues.csv"]
    saved = (tmp_path / "analysis" / "flagged_issues.csv").read_bytes()
    assert saved == pd.DataFrame(_FAKE_ISSUES).to_csv(index=False).encode("utf-8")
    assert "Saved to workspace: analysis/flagged_issues.csv" in st.texts()
    assert str(tmp_path) not in st.texts()  # no absolute path displayed
