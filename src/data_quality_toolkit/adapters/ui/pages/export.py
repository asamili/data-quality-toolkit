"""Export page: CLI/API guidance plus optional server-side star-schema export."""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.services.export import _export_csv_to_dir
from data_quality_toolkit.adapters.ui.state.keys import (
    EXPORT_CSV_PATH,
    EXPORT_OUT_DIR,
    EXPORT_RUN_BTN,
)


def _render_export(st: Any) -> None:
    """Render the Export tab — CLI/API guidance and optional server-side write."""
    st.header("Export")
    st.caption("Run the full pipeline and export star schema artifacts.")
    st.markdown(
        "Use the CLI or Python API to run the full profile → assess → star schema pipeline "
        "and write artifacts to disk."
    )
    st.subheader("CLI")
    st.code("dqt export data.csv --outdir ./dist", language="bash")
    st.subheader("Python API")
    st.code(
        "from data_quality_toolkit import export_csv\n"
        'result = export_csv("data.csv", output_dir="./dist")',
        language="python",
    )
    st.markdown(
        "**Artifacts written to `./dist/`:**\n"
        "- `dqt.db` — run history database\n"
        "- `star/` — star schema CSV files\n"
        "- `star/quality_report.json` — latest run summary\n"
        "- `star/quality_history.jsonl` — full run history (used by `compare_runs`)"
    )
    st.info(
        "Use the **Data Overview** tab for browser-download quality reports. "
        "The server-write section below requires an absolute output directory path."
    )

    st.divider()
    st.subheader("Write Export Files to Server Directory")
    st.warning(
        "**Server-side write:** Files will be written to the server/local filesystem. "
        "Ensure the output directory is a safe absolute path and you have write permission."
    )
    export_csv_path = st.text_input(
        "CSV file path to export",
        placeholder="e.g., /data/dataset.csv",
        key=EXPORT_CSV_PATH,
    )
    export_out_dir = st.text_input(
        "Output directory (absolute path)",
        placeholder="e.g., /home/user/exports/dist",
        key=EXPORT_OUT_DIR,
    )
    confirmed = st.checkbox("I confirm: write export files to the directory above")
    if st.button("Run export and write to directory", key=EXPORT_RUN_BTN):
        if not export_csv_path or not export_out_dir:
            st.error("Both CSV file path and output directory are required.")
        elif not confirmed:
            st.error("Check the confirmation box to enable server-side writes.")
        else:
            result, err = _export_csv_to_dir(export_csv_path, export_out_dir)
            if err:
                st.error(f"Export failed: {err}")
            else:
                export_paths = (result or {}).get("export_paths") or {}
                st.success(
                    f"✓ Export complete — {len(export_paths)} file(s) written to {export_out_dir}"
                )
                if export_paths:
                    st.dataframe(
                        pd.DataFrame([{"artifact": k, "path": v} for k, v in export_paths.items()])
                    )


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_export(st)
