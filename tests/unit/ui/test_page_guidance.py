"""Focused tests for the reusable page-guidance component."""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.ui.components.page_guidance import render_page_guidance


class FakeSt:
    """Records expander/markdown/caption calls; expander is a context manager."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def expander(self, label: str, **_: Any) -> FakeSt:
        self.calls.append(("expander", label))
        return self

    def markdown(self, text: str, **_: Any) -> None:
        self.calls.append(("markdown", str(text)))

    def caption(self, text: str, **_: Any) -> None:
        self.calls.append(("caption", str(text)))

    def named(self, name: str) -> list[str]:
        return [text for kind, text in self.calls if kind == name]


def test_rich_renders_expander_and_all_sections() -> None:
    st = FakeSt()
    render_page_guidance(
        st,
        purpose="P",
        inputs="I",
        workflow="W",
        next_step="N",
        outputs="O",
        safety="S",
    )
    assert st.named("expander") == ["How to use this page"]
    markdown = st.named("markdown")
    assert "**Purpose:** P" in markdown
    assert "**Inputs:** I" in markdown
    assert "**Workflow:** W" in markdown
    assert "**Outputs:** O" in markdown
    assert "**Local & private:** S" in markdown
    assert "**Next step:** N" in markdown
    assert not st.named("caption")


def test_rich_omits_optional_sections_when_absent() -> None:
    st = FakeSt()
    render_page_guidance(st, purpose="P", inputs="I", workflow="W", next_step="N")
    markdown = " ".join(st.named("markdown"))
    assert "Outputs" not in markdown
    assert "Local & private" not in markdown
    assert "**Next step:** N" in markdown


def test_compact_renders_single_caption_only() -> None:
    st = FakeSt()
    render_page_guidance(
        st, purpose="Load data.", inputs="I", workflow="W", next_step="Overview", compact=True
    )
    captions = st.named("caption")
    assert len(captions) == 1
    assert "Load data." in captions[0]
    assert "Next → Overview" in captions[0]
    assert not st.named("expander")
    assert not st.named("markdown")
