"""Start page: establish and inspect the shared local dataset context."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from data_quality_toolkit.adapters.ui import journey
from data_quality_toolkit.adapters.ui.components.dataset_context import (
    render_dataset_context_panel,
)
from data_quality_toolkit.adapters.ui.components.errors import redact_message_paths
from data_quality_toolkit.adapters.ui.components.managed_version_history import (
    render_managed_version_history,
    render_managed_version_lineage,
)
from data_quality_toolkit.adapters.ui.components.page_guidance import render_page_guidance
from data_quality_toolkit.adapters.ui.components.page_shell import render_page_header
from data_quality_toolkit.adapters.ui.components.source_context import (
    get_source_value,
    set_source_value,
)
from data_quality_toolkit.adapters.ui.components.source_hub import (
    WorkspaceInitializationResult,
    build_source_hub_sections,
    initialize_workspace_folders,
    render_source_hub_expanders,
    render_source_hub_heading,
    render_use_current_dataset_id,
    seed_workspace_defaults,
)
from data_quality_toolkit.adapters.ui.components.states import (
    render_empty_state,
    render_info_state,
)
from data_quality_toolkit.adapters.ui.services.dataset import build_dataset_context
from data_quality_toolkit.adapters.ui.services.dataset_discovery import (
    DiscoveryResult,
    discover_managed_versions,
)
from data_quality_toolkit.adapters.ui.services.lifecycle_maintenance import (
    LifecycleDiagnosticsReport,
    collect_lifecycle_diagnostics,
    execute_lifecycle_cleanup,
)
from data_quality_toolkit.adapters.ui.services.lifecycle_maintenance_view import (
    CLEANUP_SECTION_TITLE,
    ISSUE_SECTION_TITLE,
    CleanupResultView,
    MaintenanceView,
    blank_maintenance_view,
    project_cleanup_result,
    project_maintenance,
)
from data_quality_toolkit.adapters.ui.services.managed_version_history import (
    blank_workspace_view,
    project_history,
)
from data_quality_toolkit.adapters.ui.services.managed_version_lineage import (
    LineageState,
    empty_lineage,
    project_lineage,
)
from data_quality_toolkit.adapters.ui.services.managed_version_reopen import (
    ReopenOutcome,
    reopen_managed_version,
)
from data_quality_toolkit.adapters.ui.state.context import (
    DatasetContext,
    clear_dataset_context,
    get_dataset_context,
    set_dataset_context,
)
from data_quality_toolkit.adapters.ui.state.keys import (
    DATASET_ACTIVATE_BTN,
    DATASET_CLEAR_BTN,
    DATASET_LARGE_FILE_MODE,
    DATASET_PATH_INPUT,
    SRC_DATASET_ID,
    SRC_EXPORT_OUT_DIR,
    SRC_MONITORING_DB,
    SRC_PBI_OUT_DIR,
    SRC_QUALITY_HISTORY_DB,
    SRC_SESSIONS_ROOT,
    SRC_WORKSPACE_ROOT,
    SRC_WORKSPACE_ROOT_INPUT,
)

_WORKSPACE_ROOT_HELP = (
    "Local folder path used only to derive default source paths. Relative paths are "
    "accepted and normalized to absolute defaults for clarity. It does not create "
    "folders or files, does not grant write consent, and will not overwrite explicit "
    "values already entered below."
)
_WORKSPACE_DEFAULT_LABELS = {
    SRC_MONITORING_DB: "Local monitoring database",
    SRC_QUALITY_HISTORY_DB: "Quality-history database",
    SRC_SESSIONS_ROOT: "Sessions Root",
    SRC_EXPORT_OUT_DIR: "Export output directory",
    SRC_PBI_OUT_DIR: "Power BI package output directory",
}
# Widget keys for the explicit Initialize Workspace action. Defined locally (not in
# state/keys.py) because this gate does not edit the shared key module; they mirror the
# page-local button-key pattern used elsewhere in the UI adapters.
_WORKSPACE_INIT_CONFIRM = "src_workspace_init_confirm"
_WORKSPACE_INIT_BTN = "src_workspace_init_btn"
# Start-specific key for the "Use current dataset" Dataset ID action so it stays
# distinct from the Quality History page's button in the same session.
_START_DATASET_ID_BTN = "start_use_current_dataset_id"
_WORKSPACE_INIT_CONFIRM_HELP = (
    "Required before Initialize Workspace runs. Creating folders is opt-in and never "
    "grants write consent on other pages."
)
# Page-local widget keys for the explicit lifecycle-maintenance section, following
# the same page-local button-key pattern used above (this gate does not edit the
# shared key module).
_MAINT_SHOW = "lcm_show_diagnostics"
_MAINT_CONFIRM = "lcm_cleanup_confirm"
_MAINT_DELETE_BTN = "lcm_cleanup_delete_btn"
_MAINT_SELECT_PREFIX = "lcm_select_"
_MAINT_TITLE = "Lifecycle maintenance"
_MAINT_SHOW_HELP = (
    "Runs a read-only inspection of this workspace's managed-version location. Nothing "
    "is scanned until you turn this on, and nothing is repaired, activated, or deleted."
)
_MAINT_CONFIRM_HELP = (
    "Required before any temporary file is deleted. Only the entries you tick above are "
    "considered, and each one is re-checked immediately before it is removed."
)
_MAINT_SELECT_HELP = "Select this abandoned temporary staging file for explicit deletion."
_MAINT_DELETE_LABEL = "Delete selected temporary files"


def _render_start(st: Any, session_state: MutableMapping[str, Any]) -> None:
    """Render the testable Start / Load Dataset page body."""
    render_page_header(
        st,
        "Start / Load Dataset",
        "Choose a local CSV once, then review optional local sources for later pages.",
        step_label=journey.step_label("start"),
    )
    render_page_guidance(
        st,
        purpose="Load the required dataset and capture optional local source paths for later pages.",
        inputs="A local CSV path plus optional monitoring, history, session, and output sources.",
        workflow="Activate the dataset, then expand optional Source Hub sections as needed.",
        next_step="Data Overview",
        compact=True,
    )
    render_info_state(
        st,
        "DQT uses local paths for this Source Hub. The dataset source is required; "
        "monitoring, history, session, and output sources are optional and page-specific. "
        "Monitoring DB usually comes from Drift Monitoring. Quality-history DB and Dataset "
        "ID usually come from export outputs such as dist/dqt.db and "
        "dist/star/quality_report.json. Sessions Root plus Run ID identify session outputs. "
        "Output locations are defaults only and do not confirm writes.",
    )

    current = get_dataset_context(session_state)
    if DATASET_PATH_INPUT not in session_state:
        session_state[DATASET_PATH_INPUT] = current.source_path if current else ""
    if DATASET_LARGE_FILE_MODE not in session_state:
        session_state[DATASET_LARGE_FILE_MODE] = (
            current.large_file_mode if current is not None else False
        )

    path = st.text_input("CSV path", key=DATASET_PATH_INPUT)
    large_mode = st.checkbox(
        "Large-data mode (profile-only, chunked streaming)",
        key=DATASET_LARGE_FILE_MODE,
        help="Use chunked profiling for datasets that should not be fully loaded into memory.",
    )

    if st.button("Use dataset", key=DATASET_ACTIVATE_BTN, type="primary"):
        context, err = build_dataset_context(path, large_file_mode=large_mode)
        if err is not None:
            st.error(f"Dataset context error: {redact_message_paths(err)}")
        elif context is not None:
            set_dataset_context(session_state, context)
            current = context
            st.success(f"Dataset context ready: {context.display_name}")

    if st.button("Clear dataset", key=DATASET_CLEAR_BTN, disabled=current is None):
        clear_dataset_context(session_state)
        current = None
        st.success("Dataset context cleared.")

    if current is None:
        render_empty_state(
            st,
            "No dataset selected",
            "Enter a local CSV path above. For a deterministic demo, try `examples/demo.csv`.",
        )
    else:
        render_dataset_context_panel(st, current)
        _render_current_dataset_id(st, session_state, current)
        st.caption("Continue with Data Overview, then EDA Explorer.")

    _render_source_hub(st, session_state, current)
    _render_managed_version_history(st, session_state)
    _render_lifecycle_maintenance(st, session_state)


def _render_managed_version_history(st: Any, session_state: MutableMapping[str, Any]) -> None:
    """Render the bounded, privacy-safe managed-version history section.

    Reuses only the operator-entered Workspace Root; it never derives a workspace
    from the active CSV path and never creates the workspace or ``preprocessed``
    directory. No discovery runs when the Workspace Root is blank. When it is
    present, the discovery result is *immediately* converted through the safe
    projector and only the resulting ``ManagedVersionHistoryView`` reaches the
    renderer — the complete discovery object is never written, logged, serialized,
    or stored in session state.

    Reopening is explicit-only: rendering alone activates nothing. When the
    renderer reports exactly one clicked Set Active control, only the Workspace
    Root and that row's privacy-safe action reference are handed to the reopen
    service, which performs its own fresh discovery, revalidation, and atomic
    activation through the existing lifecycle contract and returns a generic
    outcome for feedback.
    """
    if hasattr(st, "divider"):
        st.divider()
    workspace_root = get_source_value(session_state, SRC_WORKSPACE_ROOT).strip()
    if not workspace_root:
        render_managed_version_history(st, blank_workspace_view())
        render_managed_version_lineage(st, empty_lineage(state=LineageState.EMPTY))
        return
    result = discover_managed_versions(workspace_root)
    view = project_history(result)
    clicked_reference = render_managed_version_history(st, view)
    if clicked_reference is not None:
        outcome = reopen_managed_version(session_state, workspace_root, clicked_reference)
        _render_reopen_feedback(st, outcome)
    _render_managed_version_lineage(st, session_state, result)


def _render_managed_version_lineage(
    st: Any, session_state: MutableMapping[str, Any], result: DiscoveryResult
) -> None:
    """Render the compact, read-only direct-lineage section for the selection.

    Reuses the *already-completed* discovery result (no second scan). The active
    reference is derived independently here — outside the pure projection service
    — from the accepted active-pointer accessor; selection never implies
    activation. The projector receives only privacy-safe short references and
    returns a safe ``LineageView`` for the renderer.
    """
    active_reference = _derive_active_reference(session_state, result)
    selected_reference = _derive_selected_reference(result, active_reference)
    lineage = project_lineage(result, selected_reference, active_reference=active_reference)
    render_managed_version_lineage(st, lineage)


def _derive_active_reference(
    session_state: MutableMapping[str, Any], result: DiscoveryResult
) -> str | None:
    """Independently derive the active managed version's short reference, or None.

    Uses only the accepted active-pointer accessor (``get_dataset_context``) and
    maps the active version identity to its privacy-safe short id within this
    discovery result. The pure lineage projector never reads session state; this
    derivation stays entirely outside it and activates nothing.
    """
    context = get_dataset_context(session_state)
    if context is None or not context.managed or not context.version_id:
        return None
    active_version_id = context.version_id
    for version in result.versions:
        if version.record.version_id == active_version_id:
            return version.display.short_version_id
    return None


def _derive_selected_reference(result: DiscoveryResult, active_reference: str | None) -> str:
    """Choose which version's direct lineage to show, independently of activation.

    Defaults to the active version when one is present in the current result,
    otherwise the most recent valid version (discovery order); blank when nothing is
    available. This is a display choice only — it does not couple selection to
    activation, which the projector keeps as independent states.
    """
    if active_reference is not None:
        return active_reference
    if result.versions:
        return result.versions[0].display.short_version_id
    return ""


def _render_reopen_feedback(st: Any, outcome: ReopenOutcome) -> None:
    """Show only the outcome's fixed generic message; never a path, id, or error."""
    if outcome.reopened:
        st.success(outcome.message)
    else:
        st.error(outcome.message)


def _render_lifecycle_maintenance(st: Any, session_state: MutableMapping[str, Any]) -> None:
    """Render the bounded, explicit lifecycle-maintenance section.

    Operator-invoked end to end. Nothing is inspected until the operator turns the
    section on, and turning it off stops all inspection: there is no startup,
    scheduled, timed, watched, or background scan or deletion anywhere in this
    flow. The read-only diagnostics run first, so the selection controls and the
    cleanup call in the same render always act on a scan taken in that render —
    no report is cached, stored in session state, or carried across a rerun.

    The page holds the report only to hand it back to the cleanup service; the
    renderer below receives exclusively the projected, privacy-safe view.
    """
    if hasattr(st, "divider"):
        st.divider()
    _heading(st, _MAINT_TITLE)
    for notice in blank_maintenance_view().notices:
        st.caption(notice)
    if not st.checkbox("Show lifecycle diagnostics", key=_MAINT_SHOW, help=_MAINT_SHOW_HELP):
        st.caption("Lifecycle diagnostics are off. Nothing is being inspected.")
        return
    workspace_root = get_source_value(session_state, SRC_WORKSPACE_ROOT).strip()
    if not workspace_root:
        st.caption(blank_maintenance_view().message)
        return
    report = collect_lifecycle_diagnostics(workspace_root)
    _render_maintenance_body(st, report, project_maintenance(report))


def _render_maintenance_body(
    st: Any, report: LifecycleDiagnosticsReport, view: MaintenanceView
) -> None:
    """Render the projected view and run cleanup only on an explicit request."""
    st.caption(view.message)
    if not view.scanned:
        return
    _render_maintenance_counts(st, view)
    _render_maintenance_issues(st, view)
    selected = _render_cleanup_candidates(st, view)
    if not view.cleanup_rows:
        return
    confirmed = st.checkbox(
        "I confirm deleting the selected temporary files",
        key=_MAINT_CONFIRM,
        help=_MAINT_CONFIRM_HELP,
    )
    st.caption(f"Selected for deletion: {len(selected)}")
    if not st.button(_MAINT_DELETE_LABEL, key=_MAINT_DELETE_BTN):
        return
    outcome = execute_lifecycle_cleanup(report, selected, confirmed=bool(confirmed))
    _render_cleanup_outcome(st, project_cleanup_result(outcome))


def _render_maintenance_counts(st: Any, view: MaintenanceView) -> None:
    summary = " · ".join(f"{item.label}: {item.count}" for item in view.counts)
    if summary:
        st.caption(summary)


def _render_maintenance_issues(st: Any, view: MaintenanceView) -> None:
    """Render diagnostic-only findings. These never gain a destructive control."""
    if not view.issue_rows:
        st.caption(f"{ISSUE_SECTION_TITLE}: none found.")
        return
    st.caption(ISSUE_SECTION_TITLE)
    for row in view.issue_rows:
        _write(st, f"**{row.category_label}** · `{row.reference}` · {row.label}")
        st.caption(f"{row.reason_code} — {row.guidance}")
    if view.issue_omitted > 0:
        st.caption(f"… and {view.issue_omitted} more records not shown.")


def _render_cleanup_candidates(st: Any, view: MaintenanceView) -> list[str]:
    """Render one explicit selection control per eligible artifact.

    Returns only the references the operator actually ticked. Rendering alone
    selects nothing and deletes nothing.
    """
    if not view.cleanup_rows:
        st.caption(f"{CLEANUP_SECTION_TITLE}: none found.")
        return []
    st.caption(CLEANUP_SECTION_TITLE)
    selected: list[str] = []
    for row in view.cleanup_rows:
        ticked = st.checkbox(
            f"{row.label} · {row.reference}",
            key=f"{_MAINT_SELECT_PREFIX}{row.reference}",
            help=_MAINT_SELECT_HELP,
        )
        if ticked:
            selected.append(row.reference)
    if view.cleanup_omitted > 0:
        st.caption(f"… and {view.cleanup_omitted} more temporary files not shown.")
    return selected


def _render_cleanup_outcome(st: Any, outcome: CleanupResultView) -> None:
    """Show the fixed outcome message and per-item fixed labels only."""
    if not outcome.completed:
        st.info(outcome.message)
        return
    if outcome.failed_count:
        st.warning(outcome.message)
    else:
        st.success(outcome.message)
    for row in outcome.rows:
        st.caption(f"{row.outcome_label} · {row.reference} · {row.label} · {row.reason_code}")


def _heading(st: Any, text: str) -> None:
    subheader = getattr(st, "subheader", None)
    if callable(subheader):
        subheader(text)
        return
    st.caption(text)


def _write(st: Any, text: str) -> None:
    writer = getattr(st, "write", None)
    if callable(writer):
        writer(text)
        return
    st.caption(text)


def _render_current_dataset_id(
    st: Any, session_state: MutableMapping[str, Any], current: DatasetContext
) -> None:
    """Offer the Dataset ID hand-off and show the current ID when available.

    The ID is only computed through the existing explicit "Use current dataset"
    action (nothing is hashed on render). Once available it is displayed in
    full — it is a content hash, not a path — in a read-only, copyable block.
    The dataset source path is never shown here.
    """
    derived = render_use_current_dataset_id(st, current, button_key=_START_DATASET_ID_BTN)
    if derived:
        set_source_value(session_state, SRC_DATASET_ID, derived)
    dataset_id = get_source_value(session_state, SRC_DATASET_ID).strip()
    if not dataset_id:
        return
    st.caption("Current Dataset ID (shared with Quality History):")
    code = getattr(st, "code", None)
    if callable(code):
        code(dataset_id, language=None)
    else:
        st.caption(dataset_id)


def _render_source_hub(
    st: Any, session_state: MutableMapping[str, Any], current: DatasetContext | None
) -> None:
    """Render optional Source Hub sections after the required dataset flow."""
    if hasattr(st, "divider"):
        st.divider()
    render_source_hub_heading(st, "Source Hub")
    st.caption(
        "Optional shared sources are stored as local path or identifier strings only. "
        "Validation checks path metadata and never opens databases, reads manifests, "
        "creates directories, or writes files."
    )
    _render_workspace_source(st, session_state)
    sections = build_source_hub_sections(session_state, current)
    render_source_hub_expanders(st, sections)


def _render_workspace_source(st: Any, session_state: MutableMapping[str, Any]) -> None:
    """Render Workspace Root as a defaults-only meta-source."""
    expander = getattr(st, "expander", None)
    if not callable(expander):
        render_source_hub_heading(st, "Workspace")
        _render_workspace_source_body(st, session_state)
        return

    container = expander("Workspace", expanded=False)
    if hasattr(container, "__enter__") and hasattr(container, "__exit__"):
        with container:
            _render_workspace_source_body(st, session_state)
    else:
        _render_workspace_source_body(st, session_state)


def _render_workspace_source_body(st: Any, session_state: MutableMapping[str, Any]) -> None:
    # Re-seed the page-local widget from the canonical shared key so a saved
    # root reappears after navigating away and back (Streamlit cleans up
    # widget-backed keys when their page is not rendered).
    canonical = get_source_value(session_state, SRC_WORKSPACE_ROOT)
    if SRC_WORKSPACE_ROOT_INPUT not in session_state and canonical:
        session_state[SRC_WORKSPACE_ROOT_INPUT] = canonical
    workspace_root = st.text_input(
        "Workspace Root",
        key=SRC_WORKSPACE_ROOT_INPUT,
        help=_WORKSPACE_ROOT_HELP,
        placeholder="e.g., ./dqt-workspace",
    )
    set_source_value(session_state, SRC_WORKSPACE_ROOT, str(workspace_root))
    seeded = seed_workspace_defaults(session_state, str(workspace_root))
    if str(workspace_root).strip():
        if seeded:
            labels = ", ".join(_WORKSPACE_DEFAULT_LABELS[key] for key in seeded)
            st.caption(f"Derived defaults filled for blank fields: {labels}.")
        else:
            st.caption("Workspace Root saved. Existing source values below were kept.")
    else:
        st.caption(
            "Optional meta-source: enter a local folder to derive defaults for blank source fields."
        )
    st.caption(
        "Defaults only: no folders or files are created, and writes still require "
        "page-level confirmation."
    )
    _render_initialize_workspace(st, session_state, str(workspace_root))


def _render_initialize_workspace(
    st: Any, session_state: MutableMapping[str, Any], workspace_root: str
) -> None:
    """Render the explicit, confirmation-gated Initialize Workspace action."""
    st.caption(
        "Initialize Workspace creates only standard folders: inputs, exports, powerbi, sessions."
    )
    st.caption(
        "It does not create monitoring.db or dqt.db, and does not run export, Power "
        "BI, or pipeline actions."
    )
    st.caption("It does not grant write consent on other pages.")

    confirm = st.checkbox(
        "I confirm creating standard workspace folders",
        key=_WORKSPACE_INIT_CONFIRM,
        help=_WORKSPACE_INIT_CONFIRM_HELP,
    )
    initialize = st.button("Initialize Workspace", key=_WORKSPACE_INIT_BTN)
    if not initialize:
        return

    if not workspace_root.strip():
        st.info("Enter a Workspace Root above before initializing folders.")
        return
    if not confirm:
        st.info("Confirm the checkbox before initializing workspace folders.")
        return

    result = initialize_workspace_folders(workspace_root)
    _render_workspace_init_result(st, result)


def _render_workspace_init_result(st: Any, result: WorkspaceInitializationResult) -> None:
    """Render a concise, basename-only Initialize Workspace result summary."""
    if result.message:
        st.info(result.message)
        return
    if result.created:
        st.success(f"Created folders: {', '.join(result.created)}.")
    if result.existing:
        st.caption(f"Already present: {', '.join(result.existing)}.")
    if result.failed:
        st.error(f"Could not create: {', '.join(result.failed)}.")
    if not (result.created or result.existing or result.failed):
        st.info("No folders to initialize.")


def render() -> None:
    """Streamlit navigation entry point."""
    import streamlit as st

    _render_start(st, st.session_state)  # type: ignore[arg-type, unused-ignore]
