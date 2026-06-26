"""Help / About page: concise orientation for the DQT dashboard.

Static, deterministic copy. Explains deterministic operation and the default-off
optional AI, the page workflow, the privacy/path-redaction posture, and where
each feature fits. Makes no public-release or readiness claims.
"""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_page_header,
    render_section_header,
)

_WORKFLOW = (
    "1. **Start / Load Dataset** — select a local CSV once; later pages reuse it.\n"
    "2. **Data Overview** — shape, quality score, issue count, and column health.\n"
    "3. **EDA Explorer** — charts and visual exploration.\n"
    "4. **Statistics Lab** — descriptive statistics and tables (the numbers).\n"
    "5. **Quality Score / Rule Breakdown** — how the score is calculated and why.\n"
    "6. **Preprocess Studio** — dependency-free, in-memory recipe workflow with "
    "before/after validation and recipe export.\n"
    "7. **Pipeline Runner** — dry-run and evidence workflow with a CLI-equivalent "
    "preview; legacy write-capable execution stays behind explicit confirmation.\n"
    "8. **Drift Monitoring** — read-only drift evidence from a local monitoring database.\n"
    "9. **Artifact Center** — review generated artifacts, basenames only.\n"
    "10. **Settings / Governance** — truthful runtime, capability, and threshold info.\n"
    "11. **Help / About** — this page."
)


def _render_help_about(st: Any) -> None:
    """Render the Help / About page body."""
    render_page_header(
        st,
        "Help / About",
        "How the dashboard works and how it handles your data.",
        step_label="Step 11 of 11 — Help / About",
    )

    render_section_header(st, "Deterministic by default")
    st.write(
        "Every score, table, and explanation in this dashboard is computed deterministically "
        "from your data — the same input always produces the same output. Optional local AI "
        "explanations are **off by default** and are not activated by this UI; deterministic "
        "explanations are always the source of truth."
    )

    render_section_header(st, "Page workflow")
    st.markdown(_WORKFLOW)

    render_section_header(st, "Privacy & path redaction")
    st.write(
        "Datasets are read from local paths and are never uploaded. Artifact and dataset paths "
        "are shown as basenames only — full local paths are kept out of the primary UI. "
        "Server-side exports require an absolute path and explicit confirmation."
    )

    render_section_header(st, "Where features fit")
    st.markdown(
        "- **Statistics** vs **EDA**: Statistics Lab is tables and numbers; EDA Explorer is charts.\n"
        "- **Quality Score**: completeness minus capped rule penalties — see its dedicated page.\n"
        "- **Drift**: a distribution change over time, not a defect or a cause.\n"
        "- **Pipeline**: a dry-run preview with a CLI-equivalent command; the legacy "
        "write-capable run stays behind explicit confirmation.\n"
        "- **Artifacts**: review names/types/status before sharing anything outside this machine."
    )


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_help_about(st)
