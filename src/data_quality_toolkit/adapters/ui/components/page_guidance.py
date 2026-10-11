"""Reusable page-level guidance ("How to use this page").

A single render helper keeps per-page guidance consistent and skimmable. The
default rendering uses a collapsed expander with structured markdown; a compact
one-line caption variant is available for the earliest pages whose lightweight
test doubles do not support ``expander``/``markdown``.

Guidance text must describe only implemented, local behavior. It must not claim
release, public availability, private-push readiness, telemetry, external
services, or AI/model activation. It is framework-thin: the ``st`` module (or a
test double) is passed in and no business logic runs here.
"""

from __future__ import annotations

from typing import Any


def render_page_guidance(
    st: Any,
    *,
    purpose: str,
    inputs: str,
    workflow: str,
    next_step: str,
    outputs: str | None = None,
    safety: str | None = None,
    compact: bool = False,
) -> None:
    """Render a concise "How to use this page" guidance block.

    ``compact`` renders a single caption line (purpose + next step) for pages
    whose test doubles support only ``caption``; otherwise a collapsed expander
    with purpose / inputs / workflow / outputs / safety / next-step is shown.
    """
    if compact:
        st.caption(f"ℹ️ How to use — {purpose} Next → {next_step}")
        return
    lines = [
        f"**Purpose:** {purpose}",
        f"**Inputs:** {inputs}",
        f"**Workflow:** {workflow}",
    ]
    if outputs:
        lines.append(f"**Outputs:** {outputs}")
    if safety:
        lines.append(f"**Local & private:** {safety}")
    lines.append(f"**Next step:** {next_step}")

    # Use the expander as a context manager when available; degrade to inline
    # markdown for lightweight test doubles whose expander returns no context.
    container = st.expander("How to use this page", expanded=False)
    if hasattr(container, "__enter__") and hasattr(container, "__exit__"):
        with container:
            for line in lines:
                st.markdown(line)
    else:
        for line in lines:
            st.markdown(line)
