"""Focused Help/About copy tests for the current UI journey."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import data_quality_toolkit
from data_quality_toolkit.adapters.ui import journey
from data_quality_toolkit.adapters.ui.pages import help_about


class FakeSt:
    """Minimal Streamlit double for Help/About rendering."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def header(self, *args: Any, **kwargs: Any) -> None:
        self._record("header", *args, **kwargs)

    def caption(self, *args: Any, **kwargs: Any) -> None:
        self._record("caption", *args, **kwargs)

    def subheader(self, *args: Any, **kwargs: Any) -> None:
        self._record("subheader", *args, **kwargs)

    def write(self, *args: Any, **kwargs: Any) -> None:
        self._record("write", *args, **kwargs)

    def markdown(self, *args: Any, **kwargs: Any) -> None:
        self._record("markdown", *args, **kwargs)

    def expander(self, *args: Any, **kwargs: Any) -> FakeSt:
        self._record("expander", *args, **kwargs)
        return self


def _rendered_text(st: FakeSt) -> str:
    return "\n".join(
        str(arg) for _name, args, _kwargs in st.calls for arg in args if isinstance(arg, str)
    )


def _repo_root() -> Path:
    return Path(data_quality_toolkit.__file__).resolve().parents[2]


def test_help_about_renders_current_sixteen_page_journey() -> None:
    st = FakeSt()

    help_about._render_help_about(st)

    text = _rendered_text(st)
    assert journey.step_label("help_about") in text
    for index, (_key, name) in enumerate(journey.JOURNEY, start=1):
        assert f"{index}. **{name}**" in text


def test_help_about_includes_statistics_outputs_and_history_handoff() -> None:
    st = FakeSt()

    help_about._render_help_about(st)

    text = _rendered_text(st)
    for expected in (
        "Distributions",
        "Power & Sample Size",
        "downloaded",
        "saved to Workspace",
        "`dqt.db`",
        "Quality History",
        "Export",
        "KPI Catalog",
        "Dim Time",
        "Manifest Viewer",
    ):
        assert expected in text


def test_targeted_docs_do_not_use_legacy_product_spine_terms() -> None:
    root = _repo_root()
    targets = [
        root / "README.md",
        root / "docs" / "product.md",
        root / "docs" / "architecture.md",
        root / "docs" / "capability_matrix.md",
        root / "src" / "data_quality_toolkit" / "adapters" / "ui" / "pages" / "help_about.py",
    ]
    stale_terms = [
        "11" + "-step",
        "11" + " pages",
        "11" + "-page",
        "of " + "11",
    ]

    for path in targets:
        text = path.read_text(encoding="utf-8")
        for term in stale_terms:
            assert term not in text, f"{path.relative_to(root)} still contains {term!r}"
