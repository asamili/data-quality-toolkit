"""KPI Catalog page: validate a KPI catalog YAML and download generated artifacts."""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui import journey
from data_quality_toolkit.adapters.ui.components.errors import redact_message_paths, show_error
from data_quality_toolkit.adapters.ui.components.page_guidance import render_page_guidance
from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_page_header,
    render_section_header,
)
from data_quality_toolkit.adapters.ui.components.workspace_save_ui import (
    WORKSPACE_ROOT_EMPTY_STATE,
    _workspace_root_value,
)
from data_quality_toolkit.adapters.ui.services.kpi import (
    _kpi_emit_to_bytes,
    _kpi_graph_to_str,
    _run_kpi_validate,
)
from data_quality_toolkit.adapters.ui.services.workspace_save import (
    WorkspaceSaveResult,
    build_workspace_filename,
    save_to_workspace,
)

# Workspace subfolder and widget keys for the opt-in KPI Save-to-Workspace actions.
# Defined locally (not in state/keys.py); this gate does not add shared source keys.
_KPI_SUBFOLDER = "kpi"
_SAVE_DAX_BTN = "kpi_save_dax_btn"
_SAVE_TMSL_BTN = "kpi_save_tmsl_btn"
_SAVE_GRAPH_BTN = "kpi_save_graph_btn"

# One-line operator flow map shown under the page guidance so the numbered stage
# headers below read as a single guided sequence.
_FLOW_MAP = (
    "Flow: 1 Choose KPI catalog source → 2 Validate catalog → "
    "3 Review KPIs by grain → 4 Download or save artifacts"
)


def _render_kpi_artifacts(st: Any, config_path: str, kpi_count: int) -> None:
    """Render DAX/TMSL/graph download buttons for a validated KPI catalog."""
    st.divider()
    render_section_header(st, "4 · Download or save artifacts")
    st.caption(
        "Downloads stay in your browser. Optionally save generated outputs under your "
        "Workspace Root / kpi; existing files are not overwritten."
    )

    dax_bytes, tmsl_bytes, emit_err = _kpi_emit_to_bytes(config_path)
    if emit_err:
        st.warning(f"DAX/TMSL generation unavailable: {redact_message_paths(emit_err)}")
        st.code(
            "dqt kpi-emit --config config/kpi_catalog.yaml "
            "--dax-out measures.dax --tmsl-out model.tmsl.json",
            language="bash",
        )
    else:
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                "Download DAX measures",
                data=dax_bytes,
                file_name="measures.dax",
                mime="text/plain",
            )
        with dl_col2:
            st.download_button(
                "Download TMSL model",
                data=tmsl_bytes,
                file_name="model.tmsl.json",
                mime="application/json",
            )
        _render_kpi_save(
            st, "Save DAX measures to workspace", _SAVE_DAX_BTN, "kpi_measures", "dax", dax_bytes
        )
        _render_kpi_save(
            st, "Save TMSL model to workspace", _SAVE_TMSL_BTN, "kpi_model", "json", tmsl_bytes
        )

    graph_content, graph_err = _kpi_graph_to_str(config_path, graph_format="mermaid")
    if graph_err:
        st.warning(f"Graph generation unavailable: {redact_message_paths(graph_err)}")
        st.code(
            "dqt kpi-graph --config config/kpi_catalog.yaml --out kpi_graph.mmd",
            language="bash",
        )
    else:
        st.download_button(
            "Download Mermaid graph",
            data=(graph_content or "").encode(),
            file_name="kpi_graph.mmd",
            mime="text/plain",
        )
        if kpi_count <= 20 and graph_content:
            with st.expander("Preview graph"):
                preview_lines = (graph_content or "").splitlines()[:30]
                st.code("\n".join(preview_lines), language="text")
        _render_kpi_save(
            st,
            "Save Mermaid graph to workspace",
            _SAVE_GRAPH_BTN,
            "kpi_graph",
            "mmd",
            graph_content,
        )


def _render_kpi_save(
    st: Any,
    button_label: str,
    key: str,
    artifact: str,
    extension: str,
    data: str | bytes | None,
) -> None:
    """Offer an opt-in Save-to-Workspace action for one KPI output (browser downloads stay)."""
    if not st.button(button_label, key=key):
        return
    workspace_root = _workspace_root_value(st)
    if not workspace_root.strip():
        st.info(WORKSPACE_ROOT_EMPTY_STATE)
        return
    # Save the exact same content served by the browser download above.
    payload: str | bytes = data if data is not None else ""
    filename = build_workspace_filename(artifact=artifact, extension=extension)
    result = save_to_workspace(workspace_root, _KPI_SUBFOLDER, filename, payload)
    _render_save_result(st, result)


def _render_save_result(st: Any, result: WorkspaceSaveResult) -> None:
    """Render the save outcome using basename / workspace-relative fields only."""
    if result.status == "saved":
        st.success(f"Saved to workspace: {result.relative_path}")
    elif result.status == "invalid":
        st.info(result.message)
    else:
        st.error(result.message or "Could not save KPI output.")


def _render_kpi_catalog(st: Any) -> None:
    """Render the KPI Catalog tab — validate catalog and download generated artifacts."""
    render_page_header(
        st,
        "KPI Catalog",
        "Validate a KPI catalog YAML and download DAX, TMSL, and dependency graph.",
        step_label=journey.step_label("kpi_catalog"),
    )
    render_page_guidance(
        st,
        purpose="Validate a KPI catalog and generate BI helper outputs.",
        inputs="A KPI catalog YAML path.",
        workflow="Validate the catalog, review grain and dependency graph, then download "
        "DAX/TMSL/graph.",
        next_step="Export or Artifact Center",
    )
    st.caption(_FLOW_MAP)

    render_section_header(st, "1 · Choose KPI catalog source")
    st.caption(
        "Validation reads the entered catalog path only. Generated artifacts stay "
        "in memory until you download them or click a Save button."
    )
    config_path = st.text_input(
        "KPI catalog YAML path",
        placeholder="e.g., config/kpi_catalog.yaml",
    )
    if not config_path:
        st.info("💡 Enter a KPI catalog path above to validate.")
        return

    render_section_header(st, "2 · Validation result")
    result, err = _run_kpi_validate(config_path)
    if err is not None:
        show_error(st, "Validation error", err)
        return

    if result is None:
        return

    if result.get("status") == "invalid":
        st.error(f"✗ Catalog invalid — reason: {result.get('reason')}")
        cycles = result.get("cycles") or []
        if cycles:
            render_section_header(st, "Dependency cycles")
            for cycle in cycles:
                st.write(" → ".join(str(c) for c in cycle))
        return

    kpi_count = result.get("kpis", 0)
    dep_count = result.get("dependencies", 0)
    st.success(f"✓ Catalog valid — {kpi_count} KPIs, {dep_count} dependencies")

    by_grain = result.get("by_grain") or {}
    if by_grain:
        render_section_header(st, "3 · KPIs by grain")
        grain_df = pd.DataFrame([{"grain": g, "kpi_count": c} for g, c in by_grain.items()])
        st.dataframe(grain_df)

    _render_kpi_artifacts(st, config_path, kpi_count)


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_kpi_catalog(st)
