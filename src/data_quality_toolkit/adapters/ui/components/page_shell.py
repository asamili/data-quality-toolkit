"""Shared page-shell renderers for the Streamlit UI.

Framework-thin presentation helpers only: each takes the streamlit module (or a
test double) as its first argument, computes no business metrics, performs no
I/O, and imports no streamlit. Same inputs render the same calls.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# Tone -> streamlit renderer name. Used by status chips and inline notes so a
# single vocabulary ("ok"/"info"/"warn"/"error") maps consistently everywhere.
_TONE_RENDERER: dict[str, str] = {
    "ok": "success",
    "info": "info",
    "warn": "warning",
    "error": "error",
}

_TONE_BADGE: dict[str, str] = {
    "ok": "🟢",
    "info": "🔵",
    "warn": "🟠",
    "error": "🔴",
}


def render_page_header(
    st: Any,
    title: str,
    caption: str,
    *,
    step_label: str | None = None,
) -> None:
    """Render a consistent page title, optional journey step, and caption."""
    st.header(title)
    if step_label:
        st.caption(step_label)
    st.caption(caption)


def render_section_header(st: Any, title: str, caption: str | None = None) -> None:
    """Render a consistent section subheading with an optional caption."""
    st.subheader(title)
    if caption:
        st.caption(caption)


def render_status_chip(st: Any, label: str, *, tone: str = "info") -> None:
    """Render a compact status badge line for the current page/section.

    ``tone`` is one of ``ok``/``info``/``warn``/``error``; unknown tones fall
    back to ``info``. Rendered as a caption so it stays visually lightweight.
    """
    badge = _TONE_BADGE.get(tone, _TONE_BADGE["info"])
    st.caption(f"{badge} {label}")


def render_metric_cards(st: Any, cards: Iterable[Mapping[str, Any]]) -> None:
    """Render a row of compact KPI cards from ``{label, value, help?, delta?}`` dicts.

    Lays the cards out in equal columns. Calls are made on the passed ``st`` so
    the rendering stays observable by lightweight test doubles. No-op for an
    empty sequence.
    """
    items = [dict(card) for card in cards]
    if not items:
        return
    columns = st.columns(len(items))
    for column, card in zip(columns, items):
        kwargs: dict[str, Any] = {}
        if card.get("help"):
            kwargs["help"] = str(card["help"])
        if card.get("delta") is not None:
            kwargs["delta"] = card["delta"]
        with column:
            st.metric(str(card.get("label", "")), card.get("value", "—"), **kwargs)
