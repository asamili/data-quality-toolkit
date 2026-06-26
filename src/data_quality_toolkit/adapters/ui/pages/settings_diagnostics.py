"""Settings / Governance page: truthful, read-only runtime and governance info.

Replaces the previous placeholder diagnostics. Shows real version/capability
data, the default-off optional-AI state (display only), deterministic
thresholds, the privacy/compute posture, and a stable writable-directory probe.
Exposes no secrets, credentials, or absolute paths.
"""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_page_header,
    render_section_header,
    render_status_chip,
)
from data_quality_toolkit.adapters.ui.services import diagnostics

_PROBE_PATH_INPUT = "settings_probe_path"
_PROBE_BTN = "settings_probe_btn"


def _render_settings_governance(st: Any) -> None:
    """Render the Settings / Governance page body."""
    render_page_header(
        st,
        "Settings / Governance",
        "Truthful, read-only runtime, capability, and governance information.",
        step_label="Step 10 of 11 — Settings / Governance",
    )

    render_section_header(st, "Versions")
    st.table(list(diagnostics.collect_versions().items()))

    render_section_header(st, "Optional dependencies", "Presence is detected without importing.")
    st.table(list(diagnostics.collect_capability_snapshot().items()))

    render_section_header(st, "Optional local AI")
    ai = diagnostics.collect_ai_availability()
    render_status_chip(
        st,
        f"Optional AI {'enabled' if ai['enabled'] else 'disabled'} (default-off).",
        tone="info" if not ai["enabled"] else "warn",
    )
    st.caption(ai["reason"])

    render_section_header(st, "Deterministic thresholds")
    st.json(diagnostics.collect_thresholds())

    render_section_header(st, "Privacy & compute posture")
    for label, statement in diagnostics.privacy_posture().items():
        st.write(f"- **{label.replace('_', ' ').title()}:** {statement}")

    render_section_header(st, "Writable-directory probe")
    st.caption("Creates and immediately deletes a temporary file; writes nothing durable.")
    probe_path = st.text_input("Directory to probe", value=".", key=_PROBE_PATH_INPUT)
    if st.button("Run writable-directory probe", key=_PROBE_BTN):
        success, err = diagnostics.probe_writable_dir(probe_path)
        if success:
            st.success(f"Writable: {probe_path}")
        else:
            st.error(f"Not writable: {err}")


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_settings_governance(st)
