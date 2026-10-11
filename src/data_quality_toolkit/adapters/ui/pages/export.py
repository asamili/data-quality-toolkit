"""Export page: CLI/API guidance plus optional server-side star-schema export."""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.ui import journey
from data_quality_toolkit.adapters.ui.components.artifacts import render_artifact_center
from data_quality_toolkit.adapters.ui.components.diagrams import relationships_to_rows
from data_quality_toolkit.adapters.ui.components.errors import redact_message_paths
from data_quality_toolkit.adapters.ui.components.page_guidance import render_page_guidance
from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_metric_cards,
    render_page_header,
    render_section_header,
    render_status_chip,
)
from data_quality_toolkit.adapters.ui.components.source_context import (
    get_source_value,
    set_source_value,
)
from data_quality_toolkit.adapters.ui.components.source_hub import (
    render_source_hub_source_summary,
    seed_session_value,
    seed_widget_from_source,
)
from data_quality_toolkit.adapters.ui.components.storylens import render_storylens_card
from data_quality_toolkit.adapters.ui.pages import artifact_center
from data_quality_toolkit.adapters.ui.services.artifact_previews import (
    human_size,
    preview_file,
    read_bounded_bytes,
)
from data_quality_toolkit.adapters.ui.services.artifacts import (
    artifact_rows_from_mapping,
    manifest_file_name,
    redact_path_to_basename,
)
from data_quality_toolkit.adapters.ui.services.export import (
    _export_csv_to_dir,
    _export_managed_source_to_dir,
)
from data_quality_toolkit.adapters.ui.services.export_alignment import (
    ExportSourceAlignment,
    classify_export_source,
    classify_verified_managed_export_source,
    export_source_warning,
    managed_manifest_metadata,
)
from data_quality_toolkit.adapters.ui.services.managed_export_gateway import (
    ManagedExportRefusedError,
    build_verified_managed_export_source,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import resolve_trust_authority
from data_quality_toolkit.adapters.ui.services.powerbi_package import (
    generate_package,
    lifecycle_label,
    package_file_rows,
    validate_generated_package,
)
from data_quality_toolkit.adapters.ui.state.context import get_dataset_context
from data_quality_toolkit.adapters.ui.state.export_context import (
    export_artifact_context_from_result,
    set_export_artifact_context,
)
from data_quality_toolkit.adapters.ui.state.keys import (
    EXPORT_CSV_PATH,
    EXPORT_OUT_DIR,
    EXPORT_RUN_BTN,
    PBI_BASE_FOLDER,
    PBI_CONFIRM,
    PBI_DIM_TIME,
    PBI_GEN_BTN,
    PBI_OUT_DIR,
    PBI_STAR_DIR,
    SRC_DATASET_ID,
    SRC_EXPORT_OUT_DIR,
    SRC_EXPORT_RUN_ID,
    SRC_PBI_OUT_DIR,
    SRC_QUALITY_HISTORY_DB,
)
from data_quality_toolkit.application.explanation import explain_export_artifacts
from data_quality_toolkit.shared.managed_export_source import VerifiedManagedExportSource

_PBI_BANNER = (
    "Server-side write: generating a package creates files in the output directory. "
    "Basenames only are shown; the original files are never sent anywhere."
)

# One-line operator flow map shown under the page guidance so the numbered stage
# headers below read as a single guided sequence.
_FLOW_MAP = (
    "Flow: 1 Choose export route → 2 Export star schema (server write) → "
    "3 Power BI package (optional)"
)

# Successful-export values handed off to the shared Quality History *inputs*:
# (export result key, shared source key, operator-facing field label). These are
# fields Quality History actually reads, so seed-only-if-blank applies — an
# operator-entered value always wins.
#
# The export's run ID is deliberately absent: it is not a Quality History input
# and not a session folder name, so it is recorded separately as export evidence
# by ``_record_export_run_id`` rather than seeded into an operator field.
_QH_HANDOFF_FIELDS = (
    ("quality_db_path", SRC_QUALITY_HISTORY_DB, "Quality-history database"),
    ("dataset_id", SRC_DATASET_ID, "Dataset ID"),
)


def _seed_quality_history_handoff(
    st: Any, result: dict[str, Any] | None
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Seed blank shared Quality History inputs from a successful export.

    Seed-only-if-blank: an operator-entered value is never overwritten, and a
    destination already holding the same value is left untouched. Returns
    ``(seeded_labels, retained_labels)`` — field labels only, never values or
    local paths, so notices stay redaction-safe.
    """
    payload = result or {}
    try:
        state = st.session_state
    except Exception:
        return (), ()

    seeded: list[str] = []
    retained: list[str] = []
    for result_key, source_key, label in _QH_HANDOFF_FIELDS:
        if result_key == "quality_db_path" and payload.get("quality_db_status") != "persisted":
            continue
        raw = payload.get(result_key)
        value = raw.strip() if isinstance(raw, str) else ""
        if not value:
            continue
        current = get_source_value(state, source_key).strip()
        if not current:
            set_source_value(state, source_key, value)
            seeded.append(label)
        elif current != value:
            retained.append(label)
    return tuple(seeded), tuple(retained)


def _record_export_run_id(st: Any, result: dict[str, Any] | None) -> str:
    """Record this successful Export's own run ID as shared export evidence.

    Writes ``SRC_EXPORT_RUN_ID`` only, and only from a successful run's real
    result — no ID is ever manufactured. The latest success wins, matching
    ``ExportArtifactContext``: this is evidence of what just happened, not an
    operator input to preserve. ``SRC_SESSION_RUN_ID`` is never touched here, so
    Export can no longer overwrite a Sessions Root folder identity. Best-effort;
    never raises. Returns the recorded ID, or ``""``.
    """
    raw = (result or {}).get("run_id")
    value = raw.strip() if isinstance(raw, str) else ""
    if not value:
        return ""
    try:
        set_source_value(st.session_state, SRC_EXPORT_RUN_ID, value)
    except Exception:
        return ""
    return value


def _render_handoff_notices(
    st: Any, seeded: tuple[str, ...], retained: tuple[str, ...], export_run_id: str = ""
) -> None:
    """Report the Quality History handoff outcome using field labels only."""
    if seeded:
        st.caption("Quality History inputs prefilled for this run: " + ", ".join(seeded) + ".")
    if retained:
        st.info("Existing Quality History values were kept: " + ", ".join(retained) + ".")
    if export_run_id:
        st.caption(
            f"Export run ID recorded for this run: `{export_run_id}`. This identifies the "
            "Export execution as evidence — it is not a Session Run ID and does not name a "
            "folder under Sessions Root."
        )


def _store_export_artifact_context(
    st: Any,
    result: dict[str, Any] | None,
    output_dir: str,
    alignment: ExportSourceAlignment | None = None,
) -> None:
    """Record the latest successful Export for the Artifact Center handoff.

    Best-effort and never raises; a run without artifacts stores nothing, so a
    prior successful context is never erased here. ``alignment`` records which
    dataset the export actually came from — the source verdict is taken from the
    path the export really used, so a manual override is stored as an override.
    """
    context = export_artifact_context_from_result(result, output_dir, alignment)
    if context is None:
        return
    try:
        set_export_artifact_context(st.session_state, context)
    except Exception:  # noqa: S110
        return


def _active_dataset_context(st: Any) -> Any:
    """Return the active DatasetContext from session state (never raises)."""
    try:
        return get_dataset_context(st.session_state)
    except Exception:
        return None


def _managed_export_decision(
    st: Any,
) -> tuple[VerifiedManagedExportSource | None, str | None]:
    """Resolve trusted managed export provenance root-first.

    Returns ``(source, None)`` when managed trust is valid and the version is
    exportable, and ``(None, message)`` when a *valid* trust root exists but
    refuses export (managed LARGE, or a source above the shared size ceiling) —
    a real refusal that must never silently degrade to an unmanaged export.

    Returns ``(None, None)`` when no valid managed trust exists at all, which
    includes a managed-looking ``DATASET_CONTEXT`` with no trust behind it. That
    mirror can never mint verified provenance or reach the managed export
    siblings — the gateway fails closed on it — so it keeps exactly the legacy
    unmanaged treatment it had before trusted activation existed.
    """
    try:
        state = st.session_state
    except Exception:
        return None, None
    try:
        decision = resolve_trust_authority(state)
    except Exception:
        return None, None
    if not decision.managed:
        # No valid managed trust (including an untrusted managed mirror):
        # unmanaged behavior stays exactly unchanged.
        return None, None
    try:
        return build_verified_managed_export_source(state), None
    except ManagedExportRefusedError as exc:
        return None, str(exc)


def _run_managed_export(
    source: VerifiedManagedExportSource, output_dir: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Run one managed export, converting a failure into a redactable message.

    The provenance object crosses to the managed UI sibling whole; nothing is
    decomposed and no unmanaged fallback is attempted on failure.
    """
    try:
        return _export_managed_source_to_dir(source, output_dir), None
    except Exception as exc:
        return None, str(exc)


def _render_export_success(
    st: Any,
    result: dict[str, Any] | None,
    export_out_dir: str,
    alignment: ExportSourceAlignment,
) -> None:
    """Render the post-export surface; shared by the managed and legacy paths."""
    export_paths = (result or {}).get("export_paths") or {}
    outdir_name = redact_path_to_basename(export_out_dir) or "selected directory"
    st.success(f"✓ Export complete — {len(export_paths)} file(s) written to `{outdir_name}`")
    st.caption(
        "Full local paths are kept out of the primary UI. Review generated files "
        "before sharing them outside this machine."
    )
    _render_quality_db_result(st, result, export_out_dir, export_paths)
    _render_manifest_emission_outcome(st, export_paths)
    seeded, retained = _seed_quality_history_handoff(st, result)
    export_run_id = _record_export_run_id(st, result)
    _render_handoff_notices(st, seeded, retained, export_run_id)
    rows = artifact_rows_from_mapping(
        export_paths,
        source="Export page",
        write_mode="server-side write",
    )
    render_artifact_center(st, rows, title="Artifact Center")
    _render_export_storylens(st, export_paths, export_out_dir)
    _store_export_artifact_context(st, result, export_out_dir, alignment)
    _render_artifact_center_next_action(st)


def _export_source_alignment(st: Any, export_csv_path: str) -> ExportSourceAlignment:
    """Classify the source the export will actually use, root-first.

    A verified managed version is classified from its own provenance, so a
    manually entered CSV path can never relabel or override the managed
    identity. Without managed authority the legacy path-based classification is
    unchanged.
    """
    source, _refusal = _managed_export_decision(st)
    if source is not None:
        return classify_verified_managed_export_source(source)
    return classify_export_source(export_csv_path, _active_dataset_context(st))


def _render_export_source_warning(st: Any, alignment: ExportSourceAlignment) -> None:
    """Warn, by basename only, when the export will not use the active dataset.

    Advisory only: an otherwise valid override stays runnable, and no extra
    confirmation is introduced.
    """
    message = export_source_warning(alignment)
    if message:
        st.warning(message)


def _render_manifest_emission_outcome(st: Any, export_paths: dict[str, Any]) -> None:
    """Report the lineage-manifest outcome truthfully after a successful export.

    Emission failure never fails the data export; it only produces a bounded,
    path-free warning instead of a false availability claim.
    """
    if export_paths.get("manifest"):
        return
    st.warning(
        f"The lineage manifest (`{manifest_file_name()}`) could not be written for this "
        "export. The exported data files above are unaffected, and the Latest Export "
        "handoff still works from session state."
    )


def _render_artifact_center_next_action(st: Any) -> None:
    """Offer the explicit Open Artifact Center next action (never auto-navigates)."""
    st.caption(
        "Artifact Center can now show this export in its Latest Export section — "
        "no manual path or ID entry needed."
    )
    st.page_link(artifact_center.artifact_center_page(st), label="Open Artifact Center")


def _seed_export_defaults(st: Any) -> tuple[str, str, str]:
    """Seed page-local export controls from Source Hub defaults when available.

    ``seed_session_value`` only fills a *missing* key, so a manual override
    survives every same-binding rerun. A genuine dataset switch clears
    ``EXPORT_CSV_PATH`` through the shared dataset-derived invalidation contract,
    which is exactly what lets this reseed the source from the newly active
    context instead of leaving the previous dataset's path in place.
    """
    dataset_source = ""
    try:
        context = get_dataset_context(st.session_state)
        dataset_source = context.source_path if context is not None else ""
    except Exception:
        dataset_source = ""
    seed_session_value(st, EXPORT_CSV_PATH, dataset_source)
    export_out_default = seed_widget_from_source(st, EXPORT_OUT_DIR, SRC_EXPORT_OUT_DIR)
    pbi_out_default = seed_widget_from_source(st, PBI_OUT_DIR, SRC_PBI_OUT_DIR)
    return dataset_source, export_out_default, pbi_out_default


def _render_export_storylens(st: Any, export_paths: dict[str, Any], outdir: str) -> None:
    """Render deterministic StoryLens card after a successful export. Never raises."""
    try:
        basenames = tuple(redact_path_to_basename(v) for v in export_paths.values() if v)
        basenames = tuple(name for name in basenames if name)
        outdir_bn = redact_path_to_basename(outdir)
        if basenames:
            render_storylens_card(
                st, [explain_export_artifacts(artifact_basenames=basenames, outdir_name=outdir_bn)]
            )
    except Exception:  # noqa: S110
        return


def _basename_safe_child_path(parent_path: object, child_path: object) -> str:
    """Display a child artifact path without exposing local directories."""
    parent_name = redact_path_to_basename(parent_path)
    child_name = redact_path_to_basename(child_path)
    if parent_name and child_name:
        return f"{parent_name}/{child_name}"
    return child_name or parent_name or "dqt.db"


def _render_quality_db_result(
    st: Any,
    result: dict[str, Any] | None,
    export_out_dir: str,
    export_paths: dict[str, Any],
) -> None:
    """Show the Quality History DB outcome from a completed export."""
    payload = result or {}
    db_path = payload.get("quality_db_path") or export_paths.get("quality_db") or ""
    status = str(payload.get("quality_db_status") or "").strip().lower()
    if not db_path and not status:
        return

    safe_db_path = _basename_safe_child_path(export_out_dir, db_path)
    if status == "failed":
        detail = (
            redact_message_paths(payload.get("quality_db_error")) or "SQLite persistence failed"
        )
        st.warning(f"Quality History database was not updated at `{safe_db_path}`: {detail}")
        return

    if status == "persisted":
        st.info(
            "Quality History database path used: "
            f"`{safe_db_path}`. The Quality History page inputs are prefilled from "
            "this run when they are blank."
        )
        return

    st.caption(f"Quality History database path attempted: `{safe_db_path}`.")


def _render_pbi_validation(st: Any, validation: dict[str, Any]) -> None:
    """Render the package validation summary chip and bounded error/warning list."""
    valid = bool(validation.get("valid"))
    render_status_chip(
        st,
        f"Package validation: {'valid' if valid else 'invalid'} · "
        f"{validation.get('file_count', '?')} files · {validation.get('csv_count', '?')} CSVs · "
        f"{validation.get('relationships_count', '?')} relationships",
        tone="ok" if valid else "error",
    )
    for error in (validation.get("errors") or [])[:10]:
        st.caption(f"❌ {error}")
    for warning in (validation.get("warnings") or [])[:10]:
        st.caption(f"⚠️ {warning}")


def _render_pbi_previews(st: Any, files_map: dict[str, str]) -> None:
    """Preview parameters/relationships JSON and star CSV heads (bounded, basename-safe)."""
    render_section_header(st, "Package previews", "Bounded, path-safe previews of key files.")
    for name in ("parameters.json", "relationships.json"):
        path = files_map.get(name)
        if not path:
            continue
        with st.expander(f"Preview: {name}"):
            preview = preview_file(path)
            if preview["kind"] == "json":
                st.json(preview["data"])
                if name == "relationships.json":
                    rows = relationships_to_rows(preview["data"])
                    if rows:
                        st.caption("Relationships")
                        st.dataframe(rows, use_container_width=True)
            else:
                st.caption(preview.get("error") or "preview unavailable")
    star_csvs = sorted((n, p) for n, p in files_map.items() if n.lower().endswith(".csv"))
    for name, path in star_csvs:
        with st.expander(f"Preview: {name}"):
            preview = preview_file(path)
            if preview["kind"] == "csv" and preview.get("error") is None:
                st.dataframe(preview["data"], use_container_width=True)
                st.caption(f"First {preview.get('rows', '?')} rows.")
            else:
                st.caption(preview.get("error") or "preview unavailable")


def _render_pbi_downloads(st: Any, files_map: dict[str, str]) -> None:
    """Offer per-file downloads for generated package files (basenames only)."""
    render_section_header(st, "Downloads", "Download individual package files (basenames only).")
    for name, path in sorted(files_map.items()):
        basename = redact_path_to_basename(path) or str(name)
        data, err = read_bounded_bytes(path)
        if err is not None or data is None:
            st.caption(f"{basename}: {err or 'unavailable'}")
            continue
        st.download_button(
            f"Download {basename}", data=data, file_name=basename, key=f"pbi_dl_{name}"
        )


def _render_pbi_result(
    st: Any,
    result: dict[str, Any],
    validation: dict[str, Any] | None,
    verr: str | None,
) -> None:
    """Render lifecycle cards, validation, file table, previews, and downloads."""
    files_map = {str(k): str(v) for k, v in (result.get("files") or {}).items()}
    rows = package_file_rows(files_map)
    valid = None if validation is None else bool(validation.get("valid"))
    outdir_name = redact_path_to_basename(result.get("output_dir", "")) or "selected directory"
    st.success(f"✓ Package generated — {len(rows)} file(s) in `{outdir_name}`")
    render_metric_cards(
        st,
        [
            {"label": "Lifecycle", "value": lifecycle_label(generated=True, valid=valid)},
            {"label": "Artifacts", "value": str(len(rows))},
            {"label": "Star tables", "value": str(result.get("star_count", "—"))},
            {
                "label": "Validation",
                "value": ("valid" if valid else "invalid") if valid is not None else "—",
            },
        ],
    )
    if verr is not None:
        st.warning(f"Validation unavailable: {redact_message_paths(verr)}")
    elif validation is not None:
        _render_pbi_validation(st, validation)
    display_rows = [{**row, "Size": human_size(row["Size"])} for row in rows]
    st.dataframe(display_rows, use_container_width=True)
    st.caption("Basenames only. Review generated files before sharing them outside this machine.")
    _render_pbi_previews(st, files_map)
    _render_pbi_downloads(st, files_map)


def _render_powerbi_package(st: Any) -> None:
    """Render the Power BI zero-config package generate → validate → preview flow."""
    st.divider()
    render_section_header(
        st,
        "3 · Power BI package (optional, server-side write)",
        "Generate a Power BI zero-config package from an existing star-schema directory — "
        "typically the `star/` folder produced by the export in stage 2.",
    )
    render_status_chip(st, _PBI_BANNER, tone="warn")
    star_dir = st.text_input(
        "Star schema directory",
        placeholder=r"e.g., C:\Users\example_user\Documents\dqt_exports\star",
        key=PBI_STAR_DIR,
    )
    out_dir = st.text_input(
        "Package output directory (absolute path)",
        placeholder=r"e.g., C:\Users\example_user\Documents\dqt_exports\powerbi",
        key=PBI_OUT_DIR,
    )
    render_source_hub_source_summary(
        st,
        (("Power BI package output directory", out_dir),),
        present_text="Power BI output value",
        missing_text="Set Power BI package output directory in Start / Load Dataset",
    )
    st.caption(
        "A Power BI output location configured on Start is only a default; generation "
        "still requires the confirmation checkbox below."
    )
    base_folder = st.text_input(
        "BaseFolder parameter",
        value="./dist",
        key=PBI_BASE_FOLDER,
        help=(
            "Use the folder Power BI should read from. Choose a local folder path "
            r"appropriate for your OS, such as C:\Users\example_user\Documents\dqt_exports "
            "on Windows."
        ),
    )
    dim_time = st.text_input(
        "dim_time.csv path (optional)",
        placeholder=r"e.g., C:\Users\example_user\Documents\dqt_exports\time\dim_time.csv",
        key=PBI_DIM_TIME,
    )
    confirmed = st.checkbox(
        "I confirm: generate package files into the directory above", key=PBI_CONFIRM
    )
    if not st.button("Generate Power BI package", key=PBI_GEN_BTN):
        render_status_chip(
            st, f"Lifecycle: {lifecycle_label(generated=False, valid=None)}", tone="info"
        )
        st.caption("No star-schema directory yet? Run the export in stage 2 first.")
        return
    if not star_dir or not out_dir:
        st.error("Star schema directory and output directory are required.")
        return
    if not confirmed:
        st.error("Check the confirmation box to enable server-side package generation.")
        return
    result, err = generate_package(star_dir, out_dir, base_folder, dim_time or None)
    if err is not None or result is None:
        st.error(f"Package generation failed: {redact_message_paths(err)}")
        return
    validation, verr = validate_generated_package(str(result.get("output_dir", out_dir)))
    _render_pbi_result(st, result, validation, verr)


def _render_export(st: Any) -> None:
    """Render the Export tab — CLI/API guidance and optional server-side write."""
    _seed_export_defaults(st)
    render_page_header(
        st,
        "Export",
        "Run the full pipeline and export star schema artifacts.",
        step_label=journey.step_label("export"),
    )
    render_page_guidance(
        st,
        purpose="Generate local star-schema and Power BI package deliverables.",
        inputs="A CSV/star-schema path and an output directory.",
        workflow="1 Choose an export route, 2 confirm and run the star-schema export, "
        "3 optionally generate the Power BI package from that output.",
        safety="Server-side writes require explicit confirmation; outputs are shown basename-first.",
        next_step="Quality History — review run history and trends "
        "(inputs prefilled from a successful export)",
    )
    st.caption(_FLOW_MAP)

    render_section_header(
        st,
        "1 · Choose your export route",
        "Use the CLI or Python API for automation and scheduled runs, or the in-app "
        "server-side write in stage 2 below. All routes produce the same artifacts.",
    )
    st.markdown(
        "Use the CLI or Python API to run the full profile → assess → star schema pipeline "
        "and write artifacts to disk."
    )
    st.subheader("CLI")
    st.code(
        r"dqt export C:\Users\example_user\Documents\sales.csv "
        r"--outdir C:\Users\example_user\Documents\dqt_exports",
        language="bash",
    )
    st.subheader("Python API")
    st.code(
        "from data_quality_toolkit import export_csv\n"
        "result = export_csv(\n"
        r'    r"C:\Users\example_user\Documents\sales.csv",'
        "\n"
        r'    output_dir=r"C:\Users\example_user\Documents\dqt_exports",'
        "\n"
        ")",
        language="python",
    )
    st.markdown(
        r"**Artifacts written to `C:\Users\example_user\Documents\dqt_exports`:**"
        "\n"
        "- `dqt.db` — Quality History run-history database\n"
        "- `star/` — star schema CSV files\n"
        "- `star/quality_report.json` — latest run summary\n"
        "- `star/quality_history.jsonl` — full run history (used by `compare_runs`)"
    )
    st.info(
        "Use the **Data Overview** tab for browser-download quality reports. "
        "The server-write section below requires an absolute output directory path."
    )

    st.divider()
    render_section_header(
        st,
        "2 · Export star schema (server-side write)",
        "Creates or updates `dqt.db` in the selected output directory, plus the "
        "`star/` CSV files and quality report/history.",
    )
    st.warning(
        "**Server-side write:** Files will be written to the server/local filesystem. "
        "Ensure the output directory is a safe absolute path and you have write permission."
    )
    export_csv_path = st.text_input(
        "CSV file path to export",
        placeholder=r"e.g., C:\Users\example_user\Documents\sales.csv",
        key=EXPORT_CSV_PATH,
    )
    export_out_dir = st.text_input(
        "Output directory (absolute path)",
        placeholder=r"e.g., C:\Users\example_user\Documents\dqt_exports",
        key=EXPORT_OUT_DIR,
    )
    render_source_hub_source_summary(
        st,
        (
            ("Dataset CSV", export_csv_path),
            ("Export output directory", export_out_dir),
        ),
        present_text="Export source values",
        missing_text="Set Export source defaults in Start / Load Dataset",
    )
    alignment = _export_source_alignment(st, export_csv_path)
    _render_export_source_warning(st, alignment)
    st.caption(
        "Output locations configured on Start are defaults only; server-side writes still "
        "require the confirmation checkbox below."
    )
    st.caption(
        "Nothing is written until you check the confirmation box **and** click the run button."
    )
    st.caption(
        f"A successful export also writes `{manifest_file_name()}` — private/local lineage "
        "metadata for the export — inside the confirmed output directory above. The "
        "confirmation below covers this same-directory metadata file."
    )
    confirmed = st.checkbox("I confirm: write export files to the directory above")
    if st.button("Run export and write to directory", key=EXPORT_RUN_BTN):
        managed_source, managed_refusal = _managed_export_decision(st)
        if managed_refusal is not None:
            # Fail closed: a managed-looking context without exportable managed
            # trust never falls back to an unmanaged export.
            st.error(f"Export refused: {managed_refusal}")
        elif not export_out_dir or (managed_source is None and not export_csv_path):
            st.error("Both CSV file path and output directory are required.")
        elif not confirmed:
            st.error("Check the confirmation box to enable server-side writes.")
        elif managed_source is not None:
            # Root-first: the verified managed provenance is the export source,
            # passed whole to the managed sibling. A manually entered CSV path
            # cannot redirect or relabel a trusted managed export.
            result, err = _run_managed_export(managed_source, export_out_dir)
            if err:
                st.error(f"Export failed: {redact_message_paths(err)}")
            else:
                _render_export_success(st, result, export_out_dir, alignment)
        else:
            # Lifecycle metadata follows the alignment of the source the export
            # will actually use, so a manual override records nothing even while
            # a managed version is active.
            result, err = _export_csv_to_dir(
                export_csv_path,
                export_out_dir,
                artifact_meta=managed_manifest_metadata(alignment),
            )
            if err:
                st.error(f"Export failed: {redact_message_paths(err)}")
            else:
                _render_export_success(st, result, export_out_dir, alignment)

    _render_powerbi_package(st)


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_export(st)
