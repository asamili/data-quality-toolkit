"""Tests for the Quality History Dataset ID hand-off from the current dataset.

The hand-off lets an operator reuse the dataset already loaded via Start / Load
Dataset instead of pasting an opaque ``sha1:`` Dataset ID. On an explicit click it
computes the canonical content-hash Dataset ID (the same value ``dqt export`` keys
the quality-history database by) and seeds the shared ``SRC_DATASET_ID`` key.

Guarantees covered here:
- clicking sets the exact ``dataset_id_from_file`` value into shared state;
- the button shows only the basename (no absolute path, no full opaque ID echoed);
- nothing is computed or set on render (no click);
- an unreadable source path fails safe with a warning and no state change;
- manual Dataset ID entry still works when no dataset context is present.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from data_quality_toolkit.adapters.loaders.file.csv_loader import dataset_id_from_file
from data_quality_toolkit.adapters.ui.components.source_hub import (
    render_use_current_dataset_id,
)
from data_quality_toolkit.adapters.ui.pages import run_history
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import (
    SRC_DATASET_ID,
    SRC_QUALITY_HISTORY_DB,
)

_MOCK_LOAD_HISTORY = "data_quality_toolkit.adapters.ui.pages.run_history._load_run_history"
_BUTTON_KEY = "qh_use_current_dataset_id"


class FakeSt:
    """Minimal Streamlit recorder with session state and keyed buttons."""

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

    def columns(self, n: int) -> list[FakeSt]:
        self._rec("columns", n)
        return [self for _ in range(n)]

    def text_input(self, label: str, **k: Any) -> str:
        self._rec("text_input", label, **k)
        return self._text_input_vals.get(label, str(k.get("value", "")))

    def set_text_input(self, label: str, value: str) -> FakeSt:
        self._text_input_vals[label] = value
        return self

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))


def _context_for(csv: Path) -> DatasetContext:
    stat = csv.stat()
    return DatasetContext(
        source_path=str(csv),
        display_name=csv.name,
        size_bytes=int(stat.st_size),
        modified_ns=int(stat.st_mtime_ns),
    )


def _write_csv(tmp_path: Path) -> Path:
    csv = tmp_path / "customers.csv"
    csv.write_text("id,name\n1,alice\n2,bob\n", encoding="utf-8")
    return csv


# ── Helper behavior ──────────────────────────────────────────────────────────


def test_click_sets_canonical_dataset_id_into_shared_state(tmp_path: Path) -> None:
    csv = _write_csv(tmp_path)
    st = FakeSt({})
    st.clicks[_BUTTON_KEY] = True

    returned = render_use_current_dataset_id(st, _context_for(csv))

    expected = dataset_id_from_file(csv)
    assert returned == expected
    assert st.session_state[SRC_DATASET_ID] == expected


def test_button_shows_basename_and_never_exposes_path_or_full_id(tmp_path: Path) -> None:
    csv = _write_csv(tmp_path)
    st = FakeSt({})
    st.clicks[_BUTTON_KEY] = True

    render_use_current_dataset_id(st, _context_for(csv))

    text = st.texts()
    assert "customers.csv" in text  # basename shown on the button
    assert str(csv) not in text  # absolute source path never displayed
    assert str(tmp_path) not in text
    assert dataset_id_from_file(csv) not in text  # full opaque ID not echoed


def test_no_click_computes_and_sets_nothing(tmp_path: Path) -> None:
    csv = _write_csv(tmp_path)
    st = FakeSt({})  # no clicks

    returned = render_use_current_dataset_id(st, _context_for(csv))

    assert returned is None
    assert SRC_DATASET_ID not in st.session_state
    assert st.called("button")  # affordance offered
    assert not st.called("warning")


def test_no_dataset_context_shows_tip_and_no_button(tmp_path: Path) -> None:
    st = FakeSt({})  # empty session state → no context

    returned = render_use_current_dataset_id(st)

    assert returned is None
    assert not st.called("button")
    assert "load a dataset" in st.texts().lower()
    assert SRC_DATASET_ID not in st.session_state


def test_unreadable_source_fails_safe_with_warning(tmp_path: Path) -> None:
    missing = tmp_path / "gone.csv"  # never created
    ctx = DatasetContext(
        source_path=str(missing), display_name="gone.csv", size_bytes=0, modified_ns=0
    )
    st = FakeSt({})
    st.clicks[_BUTTON_KEY] = True

    returned = render_use_current_dataset_id(st, ctx)

    assert returned is None
    assert st.called("warning")
    assert SRC_DATASET_ID not in st.session_state


# ── run_history page wiring ──────────────────────────────────────────────────


def test_run_history_click_seeds_dataset_id_from_context(tmp_path: Path) -> None:
    csv = _write_csv(tmp_path)
    from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT

    st = FakeSt({DATASET_CONTEXT: _context_for(csv)})
    st.clicks[_BUTTON_KEY] = True  # DB left blank → page returns early after seeding

    run_history._render_run_history(st)

    assert st.session_state[SRC_DATASET_ID] == dataset_id_from_file(csv)


def test_run_history_manual_dataset_id_still_used_without_context() -> None:
    st = FakeSt({})  # no dataset context → hand-off shows tip only
    st.set_text_input("Quality-history database", "./dist/dqt.db")
    st.set_text_input("Dataset ID", "sha1:manual")
    st.session_state[SRC_QUALITY_HISTORY_DB] = "./dist/dqt.db"

    captured: dict[str, str] = {}

    def load(db: str, dataset_id: str) -> tuple[list[dict[str, Any]], None]:
        captured["db"] = db
        captured["dataset_id"] = dataset_id
        return [], None

    with patch(_MOCK_LOAD_HISTORY, side_effect=load):
        run_history._render_run_history(st)

    assert captured["dataset_id"] == "sha1:manual"
    assert not st.called("button")  # no context → no hand-off button
