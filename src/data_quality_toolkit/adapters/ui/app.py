"""Streamlit dashboard app for Data Quality Toolkit."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.storage.connection import StorageError
from data_quality_toolkit.adapters.storage.reader import read_run_history
from data_quality_toolkit.adapters.ui.eda import (
    _bivariate_categorical_categorical,
    _bivariate_numeric_categorical,
    _bivariate_numeric_numeric,
    _build_overview_table,
    _build_trend_df,
    _categorical_top_values,
    _duplicate_row_count,
    _extract_latest_issues,
    _extract_trend_data,
    _high_cardinality_flags,
    _iqr_outlier_summary,
    _load_df_and_assess,
    _numeric_distribution,
    _numeric_summary,
    _plan_preprocessing,
)
from data_quality_toolkit.api import assess_csv as _assess_csv

_MIME_CSV = "text/csv"

_LARGE_MODE_BANNER: str = (
    "**Large-file mode (profile-only):** "
    "Approximate profile via chunked streaming — no full-DataFrame load. "
    "Assessment, EDA, export, preprocessing plan, unique counts, "
    "outlier detection, and correlation are disabled."
)


def _load_run_history(
    db_path_str: str, dataset_id: str
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Fetch run history records. Returns (records, None) or (None, error_message)."""
    try:
        records = read_run_history(Path(db_path_str.strip()), dataset_id.strip())
        return records, None
    except StorageError as exc:
        return None, str(exc)


def _run_assess_csv(path_str: str) -> tuple[dict[str, Any] | None, str | None]:
    """Call the public assess_csv API and return (result, None) or (None, error_message).

    Mirrors the _load_run_history pattern: thin wrapper that isolates exception
    handling so the Streamlit caller can stay free of bare try/except blocks.
    Routing through api.assess_csv gives the UI the same hardened load_csv path
    (row cap, max_rows_in_memory guard) that the CLI and Python API use.
    """
    try:
        result = _assess_csv(path_str.strip())
        return result, None
    except Exception as exc:
        return None, str(exc)


def _load_profile_chunked(
    path_str: str,
    chunksize: int,
) -> tuple[dict[str, Any] | None, str | None]:
    """Call profile_csv(chunksize=N) and return (envelope, None) or (None, error).

    No full-DataFrame load — stores only the returned profile envelope.
    """
    try:
        from data_quality_toolkit.api import profile_csv as _profile_csv_fn

        return _profile_csv_fn(path_str.strip(), chunksize=chunksize), None
    except Exception as exc:
        return None, str(exc)


def _run_kpi_validate(config_path: str) -> tuple[dict[str, Any] | None, str | None]:
    """Call kpi_validate workflow. Returns (result, None) or (None, error_message)."""
    try:
        from data_quality_toolkit.application.workflow.kpi import validate_kpi_catalog

        return validate_kpi_catalog(config_path.strip()), None
    except Exception as exc:
        return None, str(exc)


def _generate_dim_time_csv(
    start_date: str,
    end_date: str,
    week_start: int = 1,
    fiscal_year_start: int | None = None,
) -> tuple[str | None, int | None, str | None]:
    """Generate dim_time CSV string in memory (no disk writes).

    Returns (csv_str, row_count, None) or (None, None, error_message).
    """
    try:
        from data_quality_toolkit.adapters.exporters.time.dim_time_generator import (
            generate_dim_time,
        )

        df = generate_dim_time(
            start_date=start_date,
            end_date=end_date,
            week_start=week_start,
            fiscal_year_start=fiscal_year_start,
        )
        return df.to_csv(index=False), len(df), None
    except Exception as exc:
        return None, None, str(exc)


def _kpi_emit_to_bytes(
    config_path: str,
) -> tuple[bytes | None, bytes | None, str | None]:
    """Emit DAX and TMSL to a temp dir, read back bytes, discard temp files.

    Returns (dax_bytes, tmsl_bytes, None) or (None, None, error_message).
    No persistent writes — temp dir is deleted on context exit.
    """
    try:
        from data_quality_toolkit.application.workflow.kpi import emit_kpi_artifacts

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            emit_kpi_artifacts(
                config_path,
                tmp_path / "measures.dax",
                tmp_path / "model.tmsl.json",
            )
            dax_bytes = (tmp_path / "measures.dax").read_bytes()
            tmsl_bytes = (tmp_path / "model.tmsl.json").read_bytes()
        return dax_bytes, tmsl_bytes, None
    except Exception as exc:
        return None, None, str(exc)


def _kpi_graph_to_str(
    config_path: str,
    graph_format: str = "mermaid",
) -> tuple[str | None, str | None]:
    """Export KPI graph to a temp file, read back as string, discard temp file.

    Returns (graph_content, None) or (None, error_message).
    No persistent writes — temp dir is deleted on context exit.
    """
    try:
        from data_quality_toolkit.application.workflow.kpi import export_kpi_graph

        ext = ".dot" if graph_format == "graphviz" else ".mmd"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / f"graph{ext}"
            export_kpi_graph(config_path, out, graph_format=graph_format)  # type: ignore[arg-type]
            content = out.read_text(encoding="utf-8")
        return content, None
    except Exception as exc:
        return None, str(exc)


def _render_eda_univariate(st: Any, df: pd.DataFrame) -> None:
    """Render EDA Univariate Explorer: column selector, distribution chart, IQR outlier hint."""
    st.subheader("EDA — Univariate Explorer")
    cols = df.columns.tolist()
    if not cols:
        st.info("No columns to explore.")
        return
    col_name = st.selectbox("Select column", cols)
    if col_name is None:
        return
    is_numeric = pd.api.types.is_numeric_dtype(df[col_name])
    if is_numeric:
        dist = _numeric_distribution(df, col_name)
        if dist is not None:
            st.caption("Distribution")
            st.bar_chart(dist)
        else:
            st.info("Insufficient distinct values for distribution chart.")
        outlier_stats = _iqr_outlier_summary(df, col_name)
        if outlier_stats is not None:
            caption = (
                f"IQR: {outlier_stats['iqr']:.2f} | "
                f"Fences: [{outlier_stats['lower_fence']:.2f}, "
                f"{outlier_stats['upper_fence']:.2f}] | "
                f"Outliers: {outlier_stats['outlier_count']}"
            )
            st.caption(caption)
    else:
        top = _categorical_top_values(df, col_name)
        if top is not None:
            st.caption("Top values (up to 20)")
            st.dataframe(top)
            st.bar_chart(top)
        else:
            st.info("No usable values for this column.")


def _render_num_num(st: Any, df: pd.DataFrame, col1: str, col2: str) -> None:
    scatter_df, r = _bivariate_numeric_numeric(df, col1, col2)
    if scatter_df is None:
        st.info("Insufficient distinct values for scatter chart.")
        return
    st.caption(f"Scatter: {col1} vs {col2}")
    st.scatter_chart(scatter_df, x=col1, y=col2)
    if r is not None:
        st.caption(f"Pearson r: {r:.3f}")


def _render_num_cat(st: Any, df: pd.DataFrame, num_col: str, cat_col: str) -> None:
    grouped = _bivariate_numeric_categorical(df, num_col, cat_col)
    if grouped is None:
        st.info("No usable data for this column pair.")
        return
    st.caption(f"{num_col} by {cat_col}")
    st.dataframe(grouped)
    st.bar_chart(grouped[["mean"]].rename(columns={"mean": num_col}))


def _render_cat_cat(st: Any, df: pd.DataFrame, col1: str, col2: str) -> None:
    ct = _bivariate_categorical_categorical(df, col1, col2)
    if ct is None:
        st.info("No usable data for this column pair.")
        return
    st.caption(f"Crosstab: {col1} vs {col2}")
    st.dataframe(ct)


def _render_eda_bivariate(st: Any, df: pd.DataFrame) -> None:
    """Render EDA Bivariate Explorer: two-column selector, type-aware relationship view."""
    st.subheader("EDA — Bivariate Explorer")
    cols = df.columns.tolist()
    if len(cols) < 2:
        st.info("Need at least two columns for bivariate analysis.")
        return
    col1 = st.selectbox("First column", cols, key="biv_col1")
    col2 = st.selectbox("Second column", cols, key="biv_col2")
    if col1 == col2:
        st.info("Select two different columns.")
        return
    n1 = pd.api.types.is_numeric_dtype(df[col1])
    n2 = pd.api.types.is_numeric_dtype(df[col2])
    if n1 and n2:
        _render_num_num(st, df, col1, col2)
    elif n1:
        _render_num_cat(st, df, col1, col2)
    elif n2:
        _render_num_cat(st, df, col2, col1)
    else:
        _render_cat_cat(st, df, col1, col2)


def _render_preprocessing_plan(st: Any, df: pd.DataFrame) -> None:
    """Render Preprocessing Recommendations table: per-column issues and suggested transformations."""
    st.subheader("Preprocessing Recommendations")
    plan = _plan_preprocessing(df)
    if not plan:
        st.info("No columns to analyse.")
        return
    plan_df = pd.DataFrame(plan)
    st.dataframe(plan_df)
    st.download_button(
        "Download recommendations as CSV",
        data=plan_df.to_csv(index=False),
        file_name="preprocessing_recommendations.csv",
        mime=_MIME_CSV,
    )


def _render_large_data_profile_overview(st: Any, envelope: dict[str, Any]) -> None:
    """Render profile-only view for large-data mode.

    No DataFrame, no EDA, no assessment, no preprocessing plan.
    Shows: persistent warning banner, row/col counts, null table, dtype table.
    """
    st.warning(_LARGE_MODE_BANNER)
    profile = envelope.get("profile") or {}
    st.write(
        f"**Dataset Profile (approximate):** "
        f"{profile.get('rows', '?')} rows × {profile.get('cols', '?')} columns"
    )
    overview = _build_overview_table(profile)
    if not overview:
        st.info("No column data available.")
        return
    st.subheader("Column Analysis")
    overview_df = pd.DataFrame(overview)
    st.dataframe(overview_df)
    st.download_button(
        "Download column analysis as CSV",
        data=overview_df.to_csv(index=False),
        file_name="column_analysis.csv",
        mime=_MIME_CSV,
    )
    null_df = pd.DataFrame(
        {"null_pct": [r["null_pct"] for r in overview]},
        index=[r["column"] for r in overview],
    )
    if null_df["null_pct"].sum() > 0:
        st.caption("Null % by column")
        st.bar_chart(null_df)
    unsupported = envelope.get("unsupported_metrics") or []
    if unsupported:
        st.caption(f"Metrics unavailable in large-file mode: {', '.join(unsupported)}")


def _render_data_overview_large_mode(st: Any, csv_path: str) -> None:
    """Large-data mode branch: chunked profile-only, no full-DataFrame load."""
    chunksize = int(
        st.number_input(
            "Chunk size (rows per chunk)",
            min_value=1_000,
            max_value=1_000_000,
            value=100_000,
            step=10_000,
        )
    )
    envelope, err = _load_profile_chunked(csv_path, chunksize)
    if err is not None:
        st.error(f"⚠️ Profile Error: {err}")
        return
    if envelope is None:
        return
    _render_large_data_profile_overview(st, envelope)


def _render_data_overview(st: Any) -> None:
    """Render the Data Overview section: shape, per-column table, stats, duplicates."""
    st.header("Data Overview")
    st.caption("Perform automated quality assessment on a CSV file.")
    overview_csv = st.text_input("CSV path", placeholder="e.g., ./data/my_dataset.csv")
    if not overview_csv:
        st.info("💡 Enter a CSV path above to start profiling.")
        return

    large_mode = st.checkbox(
        "Large-data mode (profile-only, chunked streaming)",
        help=(
            "Enable for files too large to load into memory. "
            "Uses chunked streaming — no full-DataFrame load. "
            "Assessment, EDA, export, and preprocessing plan are disabled."
        ),
    )
    if large_mode:
        _render_data_overview_large_mode(st, overview_csv)
        return

    df, out, err = _load_df_and_assess(overview_csv)
    if err is not None:
        st.error(f"⚠️ Assessment Error: {err}")
        return
    if df is None or out is None:
        return

    profile = out["profile"]
    assessment = out["assessment"]
    score = float(assessment["score"])
    issues = list(assessment.get("issues") or [])

    st.divider()
    metric_col1, metric_col2 = st.columns(2)
    with metric_col1:
        st.metric("Quality Score", f"{score:.2%}")
    with metric_col2:
        st.metric("Issues Flagged", len(issues))

    if issues:
        issues_df = pd.DataFrame(issues)
        with st.expander("View Flagged Issues"):
            st.dataframe(issues_df)
            st.download_button(
                "Download issues as CSV",
                data=issues_df.to_csv(index=False),
                file_name="flagged_issues.csv",
                mime=_MIME_CSV,
            )

    st.write(
        f"**Dataset Profile**: {profile['rows']} rows × {profile['cols']} columns | {profile['memory_mb']:.2f} MB"
    )

    st.subheader("Column Analysis")
    overview = _build_overview_table(profile)
    overview_df = pd.DataFrame(overview)
    st.dataframe(overview_df)
    st.download_button(
        "Download column analysis as CSV",
        data=overview_df.to_csv(index=False),
        file_name="column_analysis.csv",
        mime=_MIME_CSV,
    )
    null_df = pd.DataFrame(
        {"null_pct": [r["null_pct"] for r in overview]},
        index=[r["column"] for r in overview],
    )
    if null_df["null_pct"].sum() > 0:
        st.caption("Null % by column")
        st.bar_chart(null_df)
    numeric = _numeric_summary(df)
    if numeric is not None:
        st.subheader("Numeric Summary")
        st.dataframe(numeric)
    st.write(f"Duplicate rows: {_duplicate_row_count(df)}")
    flags = _high_cardinality_flags(profile)
    if flags:
        st.warning(f"High-cardinality columns: {', '.join(flags)}")
    _render_eda_univariate(st, df)
    _render_eda_bivariate(st, df)
    _render_preprocessing_plan(st, df)


def _render_run_history(st: Any) -> None:
    """Render the Run History section: trend chart and latest issues breakdown."""
    st.header("Run History")
    st.caption("Load historical audit data from the DQT database.")
    st.info(
        "**How to generate run history:** run `dqt export <file.csv> --outdir <dir>` at least once. "
        "This writes `<dir>/dqt.db` and `<dir>/star/quality_report.json`. "
        "The **Dataset ID** is the `dataset_id` field inside `quality_report.json` "
        "(example: `sha1:a3f2...`). Run export again to accumulate trend data."
    )
    db_path_str = st.text_input("Database path", placeholder="e.g., ./dist/dqt.db")
    dataset_id = st.text_input(
        "Dataset ID",
        placeholder="e.g., sha1:a3f2… (from dist/star/quality_report.json)",
    )

    if not db_path_str or not dataset_id:
        st.info("💡 Enter a database path and dataset ID above to load run history.")
        return

    records, err = _load_run_history(db_path_str, dataset_id)
    if err is not None:
        st.error(f"Storage error: {err}")
        return

    if not records:
        st.warning("No run history found for this dataset.")
        return

    trend = _extract_trend_data(records)
    if len(trend) >= 2:
        st.subheader("Score Trend")
        df = _build_trend_df(trend)
        if df is not None:
            st.line_chart(df[["Score"]])
        else:
            st.line_chart({"Score": [r["score"] for r in trend]})

    sev, cat = _extract_latest_issues(records)
    if sev or cat:
        st.subheader("Latest Run — Issues Breakdown")
        col1, col2 = st.columns(2)
        with col1:
            st.caption("By severity")
            st.table(sev)
        with col2:
            st.caption("By category")
            st.table(cat)

    st.dataframe(records)


def _export_csv_to_dir(
    csv_path: str,
    output_dir: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate output_dir with path guard, then call export_csv. Returns (result, None) or (None, error)."""
    try:
        from data_quality_toolkit.shared.path_guard import ensure_safe_output_dir

        safe_dir = ensure_safe_output_dir(output_dir.strip(), create=True)
    except Exception as exc:
        return None, str(exc)
    try:
        from data_quality_toolkit.api import export_csv

        result = export_csv(csv_path.strip(), output_dir=safe_dir)
        return result, None
    except Exception as exc:
        return None, str(exc)


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
        key="export_csv_path",
    )
    export_out_dir = st.text_input(
        "Output directory (absolute path)",
        placeholder="e.g., /home/user/exports/dist",
        key="export_out_dir",
    )
    confirmed = st.checkbox("I confirm: write export files to the directory above")
    if st.button("Run export and write to directory", key="export_run_btn"):
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
        st.error(f"⚠️ Validation error: {err}")
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


def _render_dim_time(st: Any) -> None:
    """Render the Dim Time tab — generate and download time dimension CSV in memory."""
    st.header("Dim Time")
    st.caption("Generate a time dimension table and download as CSV.")

    start_date = st.text_input("Start date (YYYY-MM-DD)", value="2018-01-01")
    end_date = st.text_input("End date (YYYY-MM-DD)", value="2030-12-31")
    week_start = st.number_input(
        "Week start day (1=Mon … 7=Sun)", min_value=1, max_value=7, value=1, step=1
    )

    use_fiscal = st.checkbox("Custom fiscal year start month")
    fiscal_year_start: int | None = None
    if use_fiscal:
        fiscal_year_start = st.number_input(
            "Fiscal year start month (1–12)", min_value=1, max_value=12, value=7, step=1
        )

    if not start_date or not end_date:
        st.info("💡 Enter start and end dates above.")
        return

    csv_str, row_count, err = _generate_dim_time_csv(
        start_date=start_date,
        end_date=end_date,
        week_start=int(week_start),
        fiscal_year_start=int(fiscal_year_start) if fiscal_year_start is not None else None,
    )
    if err:
        st.error(f"⚠️ Generation error: {err}")
        return

    st.success(f"✓ {row_count:,} rows — {start_date} to {end_date}")
    st.download_button(
        "Download dim_time.csv",
        data=(csv_str or "").encode(),
        file_name="dim_time.csv",
        mime=_MIME_CSV,
    )


def main() -> None:
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError(
            "Streamlit is not installed. "
            "Install the UI extra when available: pip install data-quality-toolkit[ui]"
        ) from exc

    st.title("Data Quality Toolkit Dashboard")

    tab_overview, tab_history, tab_export, tab_kpi, tab_time = st.tabs(
        ["Data Overview", "Run History", "Export", "KPI Catalog", "Dim Time"]
    )

    with tab_overview:
        _render_data_overview(st)

    with tab_history:
        _render_run_history(st)

    with tab_export:
        _render_export(st)

    with tab_kpi:
        _render_kpi_catalog(st)

    with tab_time:
        _render_dim_time(st)


if __name__ == "__main__":
    main()
