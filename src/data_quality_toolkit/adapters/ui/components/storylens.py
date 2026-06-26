"""StoryLens explanation card — renders deterministic Explanation records.

Explanation only, not validation. DQT metrics remain the source of truth.
Takes the streamlit module (or a test double) as its first argument; imports
no streamlit, no storage, makes no network/AI calls, computes no metrics,
mutates no app state.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from data_quality_toolkit.application.explanation import Explanation

_SEVERITY_RENDERER = {
    "ok": "success",
    "info": "info",
    "warn": "warning",
    "breach": "error",
}


def render_storylens_card(st: Any, explanations: Iterable[Explanation]) -> None:
    """Render a StoryLens card for each Explanation, styled by severity."""
    items = list(explanations)
    if not items:
        return
    st.subheader("🧠 StoryLens")
    st.caption("DQT metric explanation — explanation only, not validation.")
    for exp in items:
        renderer_name = _SEVERITY_RENDERER.get(exp.severity, "info")
        render = getattr(st, renderer_name, None)
        if callable(render):
            render(f"**{exp.title}**")
        else:
            st.write(f"**{exp.title}**")
        st.write(exp.summary)
        if exp.evidence:
            st.write("**Evidence**")
            for line in exp.evidence:
                st.write(f"- {line}")
        st.write(f"**Why it matters:** {exp.why_it_matters}")
        st.write(f"**Recommended action:** {exp.recommended_action}")
        st.caption(f"Limitations: {exp.limitations}")
