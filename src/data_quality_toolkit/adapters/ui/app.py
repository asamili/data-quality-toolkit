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
        artifact_center,
        data_overview,
        dim_time,
        drift_explorer,
        eda_explorer,
        export,
        help_about,
        kpi_catalog,
        manifest_viewer,
        pipeline_runner,
        preprocess_studio,
        quality_score,
        run_history,
        settings_diagnostics,
        start,
        statistics_lab,
    )

    st.title("Data Quality Toolkit Dashboard")

    nav = st.navigation(
        {
            "Start": [
                st.Page(
                    start.render,
                    title="Start / Load Dataset",
                    url_path="start",
                    default=True,
                ),
            ],
            "Analyze": [
                st.Page(
                    data_overview.render,
                    title="Data Overview",
                    url_path="data-overview",
                ),
                st.Page(
                    statistics_lab.render,
                    title="Statistics Lab",
                    url_path="statistics-lab",
                ),
                st.Page(eda_explorer.render, title="EDA Explorer", url_path="eda-explorer"),
                st.Page(
                    quality_score.render,
                    title="Quality Score / Rule Breakdown",
                    url_path="quality-score",
                ),
            ],
            "Prepare": [
                st.Page(
                    preprocess_studio.render,
                    title="Preprocess Studio",
                    url_path="preprocess-studio",
                ),
            ],
            "Operate": [
                st.Page(
                    pipeline_runner.render,
                    title="Pipeline Runner",
                    url_path="pipeline-runner",
                ),
                st.Page(
                    drift_explorer.render,
                    title="Drift Monitoring",
                    url_path="drift-monitoring",
                ),
                st.Page(run_history.render, title="Quality History", url_path="run-history"),
            ],
            "Deliver": [
                st.Page(
                    artifact_center.render,
                    title="Artifact Center",
                    url_path="artifact-center",
                ),
                st.Page(export.render, title="Export", url_path="export"),
                st.Page(kpi_catalog.render, title="KPI Catalog", url_path="kpi-catalog"),
                st.Page(dim_time.render, title="Dim Time", url_path="dim-time"),
                st.Page(
                    manifest_viewer.render_manifest_viewer,
                    title="Manifest Viewer",
                    url_path="manifest-viewer",
                ),
            ],
            "System": [
                st.Page(
                    settings_diagnostics.render,
                    title="Settings / Governance",
                    url_path="settings-governance",
                ),
                st.Page(help_about.render, title="Help / About", url_path="help-about"),
            ],
        }
    )
    nav.run()


if __name__ == "__main__":
    main()
