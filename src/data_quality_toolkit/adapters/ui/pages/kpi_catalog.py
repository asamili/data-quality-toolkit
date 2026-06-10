"""KPI Catalog page: validate a KPI catalog YAML and download generated artifacts."""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.components.errors import show_error
from data_quality_toolkit.adapters.ui.services.kpi import (
    _kpi_emit_to_bytes,
    _kpi_graph_to_str,
    _run_kpi_validate,
)


def _render_kpi_artifacts(st: Any, config_path: str, kpi_count: int) -> None:
    """Render DAX/TMSL/graph download buttons for a validated KPI catalog."""
    st.divider()
    st.subheader("Download Artifacts")

    dax_bytes, tmsl_bytes, emit_err = _kpi_emit_to_bytes(config_path)
    if emit_err:
        st.warning(f"DAX/TMSL generation unavailable: {emit_err}")
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

    graph_content, graph_err = _kpi_graph_to_str(config_path, graph_format="mermaid")
    if graph_err:
        st.warning(f"Graph generation unavailable: {graph_err}")
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


def _render_kpi_catalog(st: Any) -> None:
    """Render the KPI Catalog tab — validate catalog and download generated artifacts."""
    st.header("KPI Catalog")
    st.caption("Validate a KPI catalog YAML and download DAX, TMSL, and dependency graph.")

    config_path = st.text_input(
        "KPI catalog YAML path",
        placeholder="e.g., config/kpi_catalog.yaml",
    )
    if not config_path:
        st.info("💡 Enter a KPI catalog path above to validate.")
        return

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
            st.subheader("Dependency Cycles")
            for cycle in cycles:
                st.write(" → ".join(str(c) for c in cycle))
        return

    kpi_count = result.get("kpis", 0)
    dep_count = result.get("dependencies", 0)
    st.success(f"✓ Catalog valid — {kpi_count} KPIs, {dep_count} dependencies")

    by_grain = result.get("by_grain") or {}
    if by_grain:
        st.subheader("KPIs by Grain")
        grain_df = pd.DataFrame([{"grain": g, "kpi_count": c} for g, c in by_grain.items()])
        st.dataframe(grain_df)

    _render_kpi_artifacts(st, config_path, kpi_count)


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_kpi_catalog(st)
