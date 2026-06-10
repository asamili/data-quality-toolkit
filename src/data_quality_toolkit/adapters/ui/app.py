"""Streamlit dashboard app for Data Quality Toolkit.

Thin shell/router: feature pages live in adapters/ui/pages, toolkit access
wrappers in adapters/ui/services, shared renderers in adapters/ui/components.
"""

# ruff: noqa: E402 -- imports follow sys.path bootstrap below

from __future__ import annotations

import sys
from pathlib import Path

# Allow `streamlit run src/data_quality_toolkit/adapters/ui/app.py` without
# pip install -e . or PYTHONPATH set, by inserting src/ into sys.path.
_src_root = str(Path(__file__).resolve().parent.parent.parent.parent)
if _src_root not in sys.path:
    sys.path.insert(0, _src_root)


def main() -> None:
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError(
            "Streamlit is not installed. "
            "Install the UI extra when available: pip install data-quality-toolkit[ui]"
        ) from exc

    # Page imports are deferred so this module stays importable without streamlit.
    from data_quality_toolkit.adapters.ui.pages import (
        data_overview,
        dim_time,
        eda_explorer,
        export,
        kpi_catalog,
        manifest_viewer,
        pipeline_runner,
        run_history,
        settings_diagnostics,
    )

    st.title("Data Quality Toolkit Dashboard")

    nav = st.navigation(
        {
            "Data Quality": [
                st.Page(
                    data_overview.render,
                    title="Data Overview",
                    url_path="data-overview",
                    default=True,
                ),
                st.Page(eda_explorer.render, title="EDA Explorer", url_path="eda-explorer"),
                st.Page(run_history.render, title="Run History", url_path="run-history"),
            ],
            "Pipeline": [
                st.Page(
                    pipeline_runner.render,
                    title="Pipeline Runner",
                    url_path="pipeline-runner",
                ),
            ],
            "BI & Export": [
                st.Page(export.render, title="Export", url_path="export"),
                st.Page(kpi_catalog.render, title="KPI Catalog", url_path="kpi-catalog"),
                st.Page(dim_time.render, title="Dim Time", url_path="dim-time"),
            ],
            "Lineage": [
                st.Page(
                    manifest_viewer.render_manifest_viewer,
                    title="Manifest Viewer",
                    url_path="manifest-viewer",
                ),
            ],
            "System": [
                st.Page(
                    settings_diagnostics.render,
                    title="Settings & Diagnostics",
                    url_path="settings-diagnostics",
                ),
            ],
        }
    )
    nav.run()


if __name__ == "__main__":
    main()
