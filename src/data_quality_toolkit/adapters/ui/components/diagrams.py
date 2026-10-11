"""Lightweight diagram/relationship rendering helpers (no new dependencies).

Pure helpers compute display rows; render helpers take the streamlit module as
their first argument and perform no I/O. Inline Mermaid rendering is shown as a
fenced code block (Streamlit does not natively render Mermaid via ``st.code``);
true graph rendering is intentionally left as a residual.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def relationships_to_rows(spec: Mapping[str, Any] | None) -> list[dict[str, str]]:
    """Flatten a ``relationships.json`` spec into display rows.

    Each row: ``{"From": "table.col", "To": "table.col", "Type", "Cross-filter"}``.
    Malformed entries are skipped; never raises.
    """
    if not isinstance(spec, Mapping):
        return []
    relationships = spec.get("relationships")
    if not isinstance(relationships, list):
        return []
    rows: list[dict[str, str]] = []
    for rel in relationships:
        if not isinstance(rel, Mapping):
            continue
        frm = rel.get("from")
        to = rel.get("to")
        if not (isinstance(frm, list) and len(frm) == 2):
            continue
        if not (isinstance(to, list) and len(to) == 2):
            continue
        rows.append(
            {
                "From": f"{frm[0]}.{frm[1]}",
                "To": f"{to[0]}.{to[1]}",
                "Type": str(rel.get("type", "")),
                "Cross-filter": str(rel.get("crossFilter", "")),
            }
        )
    return rows


def render_mermaid_block(st: Any, mermaid_text: str, *, download_name: str | None = None) -> None:
    """Render a Mermaid graph as a fenced code block, optionally offering download.

    True inline graph rendering is deferred (residual); the graph text is shown
    verbatim so it stays copy/paste-able into a Mermaid renderer.
    """
    st.code(mermaid_text, language="text")
    if download_name:
        st.download_button(
            "Download graph (Mermaid)",
            data=mermaid_text,
            file_name=download_name,
            mime="text/plain",
        )
