"""Pure Source Hub metadata, validation, and grouped render helpers.

The helpers in this module are intentionally framework-thin. They prepare field
metadata and display-safe summary rows for a future Start-page Source Hub, but
they do not wire that page or change current page behavior.

``basename_first_display`` is surface formatting, not a second redaction policy:
it is stricter than the shared value-form redactor (it preserves ``.``/``..`` and
returns a relative value unchanged) because a Source Hub field shows a location
the user typed. The ``[path redacted]`` marker it falls back to is imported from
:mod:`data_quality_toolkit.shared.text_redaction` so the two surfaces cannot
drift to different wording.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from data_quality_toolkit.adapters.ui.components.source_context import (
    DATASET_ID_HELP,
    EXPORT_OUT_DIR_HELP,
    MONITORING_DB_HELP,
    PBI_OUT_DIR_HELP,
    QUALITY_HISTORY_DB_HELP,
    SESSION_RUN_ID_HELP,
    SESSIONS_ROOT_HELP,
    get_source_value,
    render_dataset_id_input,
    render_export_out_dir_input,
    render_monitoring_db_input,
    render_pbi_out_dir_input,
    render_quality_history_db_input,
    render_session_run_id_input,
    render_sessions_root_input,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    ManagedTrustRoot,
    TrustAuthority,
    resolve_trust_authority,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext, get_dataset_context
from data_quality_toolkit.adapters.ui.state.keys import (
    DATASET_CONTEXT,
    SRC_DATASET_ID,
    SRC_EXPORT_OUT_DIR,
    SRC_MONITORING_DB,
    SRC_PBI_OUT_DIR,
    SRC_QUALITY_HISTORY_DB,
    SRC_SESSION_RUN_ID,
    SRC_SESSIONS_ROOT,
    SRC_WORKSPACE_ROOT,
)
from data_quality_toolkit.shared.text_redaction import PATH_REDACTED_DISPLAY

BadgeStatus = Literal["ok", "warning", "missing", "info"]
PathExpectation = Literal["file", "directory"]
SourceValueKind = Literal["dataset_context", "path", "identifier"]

SECTION_MONITORING_HISTORY = "Monitoring & History"
SECTION_SESSIONS_RUNS = "Sessions & Runs"
SECTION_OUTPUT_LOCATIONS = "Output locations"
SECTION_SOURCE_SUMMARY = "Source summary"

UNSET_DISPLAY = "Not set"
SQLITE_EXTENSIONS = (".db", ".sqlite", ".sqlite3")
# Only folder locations are derived from Workspace Root. The monitoring database
# (monitoring.db) and quality-history database (dqt.db) are intentionally excluded:
# those fields stay blank until the user enters them or a workflow creates/provides
# them, so downstream Drift/Quality-History pages never show a source the user never
# set. Derivation only fills blank fields and never touches disk.
WORKSPACE_DERIVED_DEFAULTS = (
    (SRC_SESSIONS_ROOT, "sessions"),
    (SRC_EXPORT_OUT_DIR, "exports"),
    (SRC_PBI_OUT_DIR, "powerbi"),
)
# Standard folders the explicit Initialize Workspace action may create. Database
# files (monitoring.db, dqt.db) are intentionally excluded and never created.
WORKSPACE_INIT_FOLDERS = ("inputs", "exports", "powerbi", "sessions")


@dataclass(frozen=True, slots=True)
class WorkspaceInitializationResult:
    """Basename-only result of an Initialize Workspace action.

    ``created``, ``existing``, and ``failed`` hold folder basenames only (never
    absolute local paths). ``message`` carries a no-op notice for a blank root.
    """

    created: tuple[str, ...] = ()
    existing: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True, slots=True)
class SourceHubBadge:
    """Display-safe validation badge data."""

    label: str
    status: BadgeStatus
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SourceHubField:
    """A shared source field definition for the Source Hub."""

    id: str
    label: str
    key: str
    help: str
    placeholder: str
    section: str
    value_kind: SourceValueKind
    expected_path: PathExpectation | None = None
    advisory_extensions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceHubSummaryItem:
    """A basename-first summary row or chip.

    ``raw_value`` may hold the full path for later internal use, but rendering
    helpers must use ``primary`` for display.
    """

    label: str
    primary: str
    raw_value: str = ""
    detail: str = ""
    badges: tuple[SourceHubBadge, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceHubSection:
    """Grouped Source Hub section data."""

    title: str
    description: str = ""
    fields: tuple[SourceHubField, ...] = ()
    summary_items: tuple[SourceHubSummaryItem, ...] = ()


SOURCE_HUB_FIELDS = (
    SourceHubField(
        id="dataset_source",
        label="Dataset source",
        key=DATASET_CONTEXT,
        help="Active DatasetContext metadata from Load Dataset.",
        placeholder="No dataset selected yet",
        section=SECTION_SOURCE_SUMMARY,
        value_kind="dataset_context",
    ),
    SourceHubField(
        id="monitoring_db",
        label="Local monitoring database",
        key=SRC_MONITORING_DB,
        help=MONITORING_DB_HELP,
        placeholder="e.g., ./monitoring.db",
        section=SECTION_MONITORING_HISTORY,
        value_kind="path",
        expected_path="file",
        advisory_extensions=SQLITE_EXTENSIONS,
    ),
    SourceHubField(
        id="quality_history_db",
        label="Quality-history database",
        key=SRC_QUALITY_HISTORY_DB,
        help=QUALITY_HISTORY_DB_HELP,
        placeholder=r"e.g., C:\Users\example_user\Documents\dqt_exports\dqt.db",
        section=SECTION_MONITORING_HISTORY,
        value_kind="path",
        expected_path="file",
        advisory_extensions=SQLITE_EXTENSIONS,
    ),
    SourceHubField(
        id="sessions_root",
        label="Sessions Root",
        key=SRC_SESSIONS_ROOT,
        help=SESSIONS_ROOT_HELP,
        placeholder="e.g., ./sessions",
        section=SECTION_SESSIONS_RUNS,
        value_kind="path",
        expected_path="directory",
    ),
    SourceHubField(
        id="session_run_id",
        label="Session Run ID",
        key=SRC_SESSION_RUN_ID,
        help=SESSION_RUN_ID_HELP,
        placeholder="e.g., 2025-01-01T000000Z",
        section=SECTION_SESSIONS_RUNS,
        value_kind="identifier",
    ),
    SourceHubField(
        id="dataset_id",
        label="Dataset ID",
        key=SRC_DATASET_ID,
        help=DATASET_ID_HELP,
        placeholder="e.g., sha1:a3f2...",
        section=SECTION_SESSIONS_RUNS,
        value_kind="identifier",
    ),
    SourceHubField(
        id="export_out_dir",
        label="Export output directory",
        key=SRC_EXPORT_OUT_DIR,
        help=EXPORT_OUT_DIR_HELP,
        placeholder=r"e.g., C:\Users\example_user\Documents\dqt_exports",
        section=SECTION_OUTPUT_LOCATIONS,
        value_kind="path",
        expected_path="directory",
    ),
    SourceHubField(
        id="pbi_out_dir",
        label="Power BI package output directory",
        key=SRC_PBI_OUT_DIR,
        help=PBI_OUT_DIR_HELP,
        placeholder=r"e.g., C:\Users\example_user\Documents\dqt_exports\powerbi",
        section=SECTION_OUTPUT_LOCATIONS,
        value_kind="path",
        expected_path="directory",
    ),
)


def get_source_hub_fields() -> tuple[SourceHubField, ...]:
    """Return the immutable Source Hub field definitions."""
    return SOURCE_HUB_FIELDS


def source_hub_values_from_state(state: Mapping[str, Any]) -> dict[str, str]:
    """Extract string-backed Source Hub values from session-like state."""
    values: dict[str, str] = {}
    for field in SOURCE_HUB_FIELDS:
        if field.value_kind != "dataset_context":
            values[field.key] = get_source_value(state, field.key)
    return values


def source_value_from_streamlit(st: Any, key: str) -> str:
    """Read a shared source value from ``st.session_state`` when available."""
    try:
        state = st.session_state
        return get_source_value(state, key)
    except Exception:
        return ""


def seed_session_value(st: Any, key: str, value: str) -> None:
    """Seed a Streamlit session-state key without overwriting user input."""
    if not value:
        return
    try:
        state = st.session_state
        if key not in state:
            state[key] = value
    except Exception:
        return


def seed_widget_from_source(st: Any, target_key: str, source_key: str) -> str:
    """Seed a page-local widget key from a shared Source Hub key."""
    value = source_value_from_streamlit(st, source_key)
    seed_session_value(st, target_key, value)
    return value


def derive_workspace_defaults(workspace_root: str) -> dict[str, str]:
    """Return source defaults derived from Workspace Root without touching disk.

    Workspace-derived values are suggestions only. They do not create folders,
    read databases or manifests, or grant write consent on export/pipeline pages.
    The root is normalized to an absolute path string so write-capable downstream
    flows receive clear defaults even when the user enters a relative workspace.
    """
    root = str(workspace_root).strip()
    if not root:
        return {}
    normalized_root = _normalize_workspace_root(root)
    return {
        key: _join_path_text(normalized_root, child) for key, child in WORKSPACE_DERIVED_DEFAULTS
    }


def seed_workspace_defaults(
    state: MutableMapping[str, Any], workspace_root: str | None = None
) -> tuple[str, ...]:
    """Fill missing source values from Workspace Root defaults only.

    Existing explicit values always win, and folder initialization is
    intentionally outside this helper.
    """
    root = (
        get_source_value(state, SRC_WORKSPACE_ROOT)
        if workspace_root is None
        else str(workspace_root)
    )
    seeded: list[str] = []
    for key, value in derive_workspace_defaults(root).items():
        current = state.get(key)
        if not isinstance(current, str) or not current.strip():
            state[key] = value
            seeded.append(key)
    return tuple(seeded)


def initialize_workspace_folders(workspace_root: str) -> WorkspaceInitializationResult:
    """Create only the standard workspace folders under a normalized Workspace Root.

    This is an explicit, opt-in action. It creates only the four admitted folders
    (``inputs``, ``exports``, ``powerbi``, ``sessions``) and nothing else: it never
    creates ``monitoring.db``/``dqt.db``, manifests, reports, exports, Power BI
    packages, or pipeline artifacts, and it never opens a database or runs
    export/Power BI/pipeline logic. A blank root is a no-op. Existing folders are
    treated as already-initialized (success). Results report folder basenames only,
    never absolute local paths.
    """
    root = str(workspace_root).strip()
    if not root:
        return WorkspaceInitializationResult(
            message="Enter a Workspace Root before initializing folders."
        )

    normalized = _normalize_workspace_root(root)
    created: list[str] = []
    existing: list[str] = []
    failed: list[str] = []
    for name in WORKSPACE_INIT_FOLDERS:
        folder = Path(normalized) / name
        try:
            if folder.is_dir():
                existing.append(name)
            elif folder.exists():
                failed.append(name)
            else:
                folder.mkdir(parents=True, exist_ok=True)
                created.append(name)
        except (OSError, RuntimeError, ValueError):
            failed.append(name)

    return WorkspaceInitializationResult(
        created=tuple(created),
        existing=tuple(existing),
        failed=tuple(failed),
    )


def basename_first_display(value: str, *, fallback: str = UNSET_DISPLAY) -> str:
    """Return a basename-first display label without exposing absolute paths."""
    raw = str(value).strip()
    if not raw:
        return fallback
    if raw in {".", ".."}:
        return raw

    trimmed = raw.rstrip("/\\")
    if not trimmed:
        return PATH_REDACTED_DISPLAY

    windows_name = PureWindowsPath(trimmed).name
    posix_name = PurePosixPath(trimmed).name
    for name in (windows_name, posix_name):
        if name and name != trimmed:
            return name

    if _looks_like_absolute_or_drive_path(trimmed):
        return PATH_REDACTED_DISPLAY
    return trimmed


def path_validation_badges(
    value: str,
    *,
    expected_path: PathExpectation | None = None,
    advisory_extensions: tuple[str, ...] = (),
) -> tuple[SourceHubBadge, ...]:
    """Return no-write path badges using only existence/type metadata checks."""
    raw = str(value).strip()
    if not raw:
        return (SourceHubBadge("Not provided", "missing", "Enter a local path when needed."),)

    path = Path(raw).expanduser()
    exists = _safe_path_check(path.exists)
    badges: list[SourceHubBadge] = []

    if exists is True:
        badges.append(SourceHubBadge("Path exists", "ok"))
    elif exists is False:
        badges.append(SourceHubBadge("Path missing", "missing"))
    else:
        badges.append(SourceHubBadge("Path check unavailable", "warning"))

    if exists is True and expected_path:
        badges.append(_path_kind_badge(path, expected_path))

    extension_badge = advisory_extension_badge(raw, advisory_extensions)
    if extension_badge is not None:
        badges.append(extension_badge)

    return tuple(badges)


def advisory_extension_badge(
    value: str, advisory_extensions: tuple[str, ...]
) -> SourceHubBadge | None:
    """Return an advisory-only extension badge for path-like values."""
    if not advisory_extensions:
        return None

    suffix = PureWindowsPath(str(value).strip()).suffix.lower()
    expected = _normalized_extensions(advisory_extensions)
    if suffix in expected:
        return SourceHubBadge("Extension looks right", "ok")
    return SourceHubBadge(
        "Extension advisory",
        "warning",
        f"Expected {', '.join(expected)}.",
    )


def identifier_validation_badges(
    value: str, *, dataset_id: bool = False
) -> tuple[SourceHubBadge, ...]:
    """Return non-empty identifier badges; dataset IDs are hints, not format gates."""
    if str(value).strip():
        detail = "Any non-empty value is accepted." if dataset_id else ""
        return (SourceHubBadge("Value provided", "ok", detail),)
    return (SourceHubBadge("Not provided", "missing", "Enter a value when needed."),)


def source_field_badges(field: SourceHubField, value: str) -> tuple[SourceHubBadge, ...]:
    """Return validation badges appropriate for a Source Hub field."""
    if field.value_kind == "path":
        return path_validation_badges(
            value,
            expected_path=field.expected_path,
            advisory_extensions=field.advisory_extensions,
        )
    if field.value_kind == "identifier":
        return identifier_validation_badges(value, dataset_id=field.key == SRC_DATASET_ID)
    return ()


MANAGED_TRUST_REQUIRED_DISPLAY = "Managed trust required"
MANAGED_TRUST_REQUIRED_DETAIL = (
    "The active managed context has no valid managed trust root. Reopen the "
    "managed version explicitly."
)


def build_source_summary_items(
    state: Mapping[str, Any], dataset_context: DatasetContext | None = None
) -> tuple[SourceHubSummaryItem, ...]:
    """Build basename-first summary rows for the current Source Hub values.

    The dataset row is resolved root-first: a valid managed trust root names the
    active dataset even when ``dataset_context`` (or ``DATASET_CONTEXT``) is
    stale or manually overridden, and a managed-looking context with no valid
    trust reports a fail-closed row instead of the unverified mirror identity.
    """
    values = source_hub_values_from_state(state)

    items = [_active_dataset_summary_item(state, dataset_context)]
    for field in SOURCE_HUB_FIELDS:
        if field.value_kind == "dataset_context":
            continue
        value = values.get(field.key, "")
        items.append(_summary_item_for_field(field, value))
        if field.key == SRC_SESSION_RUN_ID:
            items.append(_manifest_summary_item(values))

    return tuple(items)


def build_source_hub_sections(
    state: Mapping[str, Any], dataset_context: DatasetContext | None = None
) -> tuple[SourceHubSection, ...]:
    """Build grouped Source Hub section data without wiring any page."""
    return (
        SourceHubSection(
            title=SECTION_MONITORING_HISTORY,
            description=(
                "Optional local SQLite paths. The monitoring database comes from "
                "Drift Monitoring; the quality-history database is commonly "
                "created by export workflows."
            ),
            fields=_fields_for_section(SECTION_MONITORING_HISTORY),
        ),
        SourceHubSection(
            title=SECTION_SESSIONS_RUNS,
            description=(
                "Sessions Root is the folder of DQT session/run outputs. Session "
                "Run ID selects one session folder under it, and Dataset ID is the "
                "value from star/quality_report.json."
            ),
            fields=_fields_for_section(SECTION_SESSIONS_RUNS),
        ),
        SourceHubSection(
            title=SECTION_OUTPUT_LOCATIONS,
            description=(
                "Default output folders only. Export and Power BI writes still "
                "require their own page-level confirmation."
            ),
            fields=_fields_for_section(SECTION_OUTPUT_LOCATIONS),
        ),
        SourceHubSection(
            title=SECTION_SOURCE_SUMMARY,
            description="Basename-first source summary; local paths are not primary display.",
            summary_items=build_source_summary_items(state, dataset_context),
        ),
    )


def render_source_hub_section(st: Any, section: SourceHubSection) -> None:
    """Render one Source Hub section with a Streamlit-like object."""
    render_source_hub_heading(st, section.title)
    render_source_hub_section_body(st, section)


def render_source_hub_section_body(st: Any, section: SourceHubSection) -> None:
    """Render Source Hub section content without an outer title."""
    if section.description:
        st.caption(section.description)

    for field in section.fields:
        value = render_source_hub_field(st, field)
        render_validation_badges(st, source_field_badges(field, value))

    for item in section.summary_items:
        _render_text(st, f"**{item.label}:** `{item.primary}`")
        if item.detail:
            st.caption(item.detail)
        render_validation_badges(st, item.badges)


def render_source_hub_expanders(st: Any, sections: tuple[SourceHubSection, ...]) -> None:
    """Render Source Hub sections as collapsed expanders."""
    for section in sections:
        expander = getattr(st, "expander", None)
        if not callable(expander):
            render_source_hub_section(st, section)
            continue

        container = expander(section.title, expanded=False)
        if hasattr(container, "__enter__") and hasattr(container, "__exit__"):
            with container:
                render_source_hub_section_body(st, section)
        else:
            render_source_hub_section_body(st, section)


def render_source_hub_sections(
    st: Any, state: Mapping[str, Any], dataset_context: DatasetContext | None = None
) -> tuple[SourceHubSection, ...]:
    """Render grouped Source Hub sections and return the rendered data."""
    sections = build_source_hub_sections(state, dataset_context)
    for section in sections:
        render_source_hub_section(st, section)
    return sections


def render_source_hub_field(st: Any, field: SourceHubField) -> str:
    """Render one shared source input using existing source-context helpers."""
    renderer = _FIELD_RENDERERS.get(field.key)
    if renderer is None:
        return ""
    return renderer(st)


def render_validation_badges(st: Any, badges: tuple[SourceHubBadge, ...]) -> None:
    """Render compact validation badge labels without exposing raw local paths."""
    if not badges:
        return
    st.caption(" | ".join(badge.label for badge in badges))


def render_source_hub_heading(st: Any, text: str) -> None:
    """Render a Source Hub heading on Streamlit or a minimal test recorder."""
    subheader = getattr(st, "subheader", None)
    if callable(subheader):
        subheader(text)
        return

    header = getattr(st, "header", None)
    if callable(header):
        header(text)
        return

    st.caption(text)


def _render_text(st: Any, text: str) -> None:
    writer = getattr(st, "write", None)
    if callable(writer):
        writer(text)
        return

    st.caption(text)


def render_source_hub_callout(
    st: Any,
    label: str,
    value: str,
    *,
    present_text: str,
    missing_text: str,
) -> None:
    """Render a concise downstream Source Hub source summary or missing callout."""
    if str(value).strip():
        st.caption(f"{present_text}: {label} `{basename_first_display(value)}`")
    else:
        st.info(missing_text)


def render_dataset_source_callout(
    st: Any,
    context: DatasetContext | None,
    *,
    session_state: Mapping[str, Any] | None = None,
) -> None:
    """Render the Analyze/Prepare dataset source status for downstream pages.

    Describes only the *active* dataset, using the shared identity model so this
    callout and the Start panel stay consistent. A managed version is named by its
    operator label and short version id; a legacy dataset by its basename.

    When ``session_state`` is supplied the identity is resolved root-first: a
    valid managed trust root names the dataset even against a stale mirror or a
    manually entered path, and a managed-looking context without valid trust
    renders a fail-closed notice rather than the unverified identity. Omitting
    it preserves the legacy caller contract exactly.
    """
    if session_state is not None:
        decision = resolve_trust_authority(dict(session_state))
        if decision.authority is TrustAuthority.FAIL_CLOSED:
            st.caption(MANAGED_TRUST_REQUIRED_DETAIL)
            return
        if decision.managed and decision.root is not None:
            root = decision.root
            st.caption(
                "Using trusted managed version: "
                f"`{basename_first_display(root.version_label)}` · "
                f"source `{root.locator.display_name}` · "
                f"{'large-file' if root.large_file_mode else 'full analysis'} mode."
            )
            return

    if context is None:
        st.caption(
            "Set the dataset source in Start / Load Dataset. Advanced/manual CSV "
            "path override remains available below."
        )
        return

    # Imported here because the identity model reuses this module's
    # ``basename_first_display``; a module-level import would be circular. Mirrors
    # the same cycle-breaking pattern used in ``state.context``.
    from data_quality_toolkit.adapters.ui.components.active_dataset_identity import (
        build_active_dataset_identity,
    )

    identity = build_active_dataset_identity(context)
    details = [identity.descriptor]
    if identity.show_basename:
        details.append(f"source `{identity.basename}`")
    details.append(identity.mode_label)
    st.caption(
        f"Using dataset source from Start: `{identity.label}` · " + " · ".join(details) + "."
    )


def render_use_current_dataset_id(
    st: Any,
    context: DatasetContext | None = None,
    *,
    button_key: str = "qh_use_current_dataset_id",
) -> str | None:
    """Offer a one-click Dataset ID hand-off from the current dataset context.

    When a dataset is loaded (via Start / Load Dataset), this renders a "Use
    current dataset" button so the operator does not have to paste an opaque
    ``sha1:`` Dataset ID. On an explicit click it computes the canonical
    content-hash Dataset ID from the current dataset file — the same value
    ``dqt export`` writes to ``quality_report.json`` and keys the quality-history
    database by — and seeds the shared ``SRC_DATASET_ID`` key so the manual input
    below picks it up. Manual entry/override stays fully available.

    Privacy: the button shows only the basename display name, never the absolute
    ``source_path``; the full opaque ID is stored in state (not echoed
    prominently). Nothing is read on render — the file is only opened on click.
    Returns the computed Dataset ID on a successful click, else ``None``.
    """
    ctx = context if context is not None else _current_dataset_context(st)
    if ctx is None:
        st.caption(
            "Tip: load a dataset in Start / Load Dataset to fill the Dataset ID "
            "automatically instead of pasting it."
        )
        return None

    label = basename_first_display(ctx.display_name or ctx.source_path, fallback="current dataset")
    if not st.button(
        f"Use current dataset ({label})",
        key=button_key,
        help="Fill the Dataset ID from the dataset loaded in Start / Load Dataset.",
    ):
        return None

    from data_quality_toolkit.adapters.loaders.file.csv_loader import dataset_id_from_file

    try:
        dataset_id = dataset_id_from_file(Path(ctx.source_path))
    except (OSError, RuntimeError, ValueError):
        st.warning("Could not read the current dataset to compute its Dataset ID.")
        return None

    try:
        st.session_state[SRC_DATASET_ID] = dataset_id
    except Exception:
        return dataset_id
    st.caption("Dataset ID set from the current dataset.")
    return dataset_id


def _current_dataset_context(st: Any) -> DatasetContext | None:
    """Return the active DatasetContext from session state (never raises)."""
    try:
        return get_dataset_context(st.session_state)
    except Exception:
        return None


def render_source_hub_source_summary(
    st: Any,
    items: tuple[tuple[str, str], ...],
    *,
    present_text: str,
    missing_text: str,
) -> None:
    """Render basename-first summaries for present values and a Start callout for gaps."""
    present = [
        f"{label} `{basename_first_display(value)}`" for label, value in items if str(value).strip()
    ]
    missing = [label for label, value in items if not str(value).strip()]
    if present:
        st.caption(f"{present_text}: " + " · ".join(present))
    if missing:
        st.info(f"{missing_text}: {', '.join(missing)}.")


def _summary_item_for_field(field: SourceHubField, value: str) -> SourceHubSummaryItem:
    raw_value = str(value).strip()
    if field.value_kind == "identifier":
        primary = raw_value or UNSET_DISPLAY
    else:
        primary = basename_first_display(raw_value)
    return SourceHubSummaryItem(
        label=field.label,
        primary=primary,
        raw_value=raw_value,
        badges=source_field_badges(field, raw_value),
    )


def _active_dataset_summary_item(
    state: Mapping[str, Any], dataset_context: DatasetContext | None
) -> SourceHubSummaryItem:
    """Resolve the dataset summary row root-first, failing closed on bad trust."""
    decision = resolve_trust_authority(dict(state))
    if decision.authority is TrustAuthority.FAIL_CLOSED:
        return SourceHubSummaryItem(
            label="Dataset source",
            primary=MANAGED_TRUST_REQUIRED_DISPLAY,
            detail=MANAGED_TRUST_REQUIRED_DETAIL,
            badges=(SourceHubBadge("Managed trust missing", "missing"),),
        )
    if decision.managed and decision.root is not None:
        return _managed_summary_item(decision.root)
    context = dataset_context if dataset_context is not None else get_dataset_context(state)
    return _dataset_summary_item(context)


def _managed_summary_item(root: ManagedTrustRoot) -> SourceHubSummaryItem:
    """Name the active managed version from verified trust, privacy-safely.

    ``raw_value`` deliberately carries the workspace-relative POSIX locator, not
    the absolute managed path: the Source Hub never holds absolute managed
    provenance, even in non-display fields. The operator-typed ``version_label``
    is free text, so it is rendered through the same basename-first display as
    every other location-bearing field rather than raw; the stored label itself
    is never rewritten.
    """
    return SourceHubSummaryItem(
        label="Dataset source",
        primary=basename_first_display(
            root.locator.display_name, fallback="Managed version selected"
        ),
        raw_value=root.locator.relative_posix,
        detail=f"Managed version `{basename_first_display(root.version_label)}` (trusted).",
        badges=(SourceHubBadge("Managed version active", "ok"),),
    )


def _dataset_summary_item(context: DatasetContext | None) -> SourceHubSummaryItem:
    if context is None:
        return SourceHubSummaryItem(
            label="Dataset source",
            primary="No dataset selected",
            badges=(SourceHubBadge("Dataset not loaded", "missing"),),
        )

    display = context.display_name.strip() or context.source_path
    return SourceHubSummaryItem(
        label="Dataset source",
        primary=basename_first_display(display, fallback="Dataset selected"),
        raw_value=context.source_path,
        badges=(SourceHubBadge("Dataset selected", "ok"),),
    )


def _manifest_summary_item(values: Mapping[str, str]) -> SourceHubSummaryItem:
    sessions_root = values.get(SRC_SESSIONS_ROOT, "").strip()
    run_id = values.get(SRC_SESSION_RUN_ID, "").strip()
    if not sessions_root or not run_id:
        return SourceHubSummaryItem(
            label="Manifest source",
            primary=UNSET_DISPLAY,
            detail="Derived from Sessions Root and Session Run ID.",
            badges=(SourceHubBadge("Not derived", "missing"),),
        )

    return SourceHubSummaryItem(
        label="Manifest source",
        primary=run_id,
        raw_value=_join_path_text(sessions_root, run_id),
        detail="Derived from Sessions Root and Session Run ID.",
        badges=(SourceHubBadge("Derived source", "info"),),
    )


def _fields_for_section(section: str) -> tuple[SourceHubField, ...]:
    return tuple(field for field in SOURCE_HUB_FIELDS if field.section == section)


def _path_kind_badge(path: Path, expected_path: PathExpectation) -> SourceHubBadge:
    if expected_path == "file":
        is_expected = _safe_path_check(path.is_file)
        label = "File path" if is_expected is True else "Expected file"
    else:
        is_expected = _safe_path_check(path.is_dir)
        label = "Folder path" if is_expected is True else "Expected folder"

    if is_expected is True:
        return SourceHubBadge(label, "ok")
    if is_expected is False:
        return SourceHubBadge(label, "warning")
    return SourceHubBadge("Path type unavailable", "warning")


def _safe_path_check(check: Any) -> bool | None:
    try:
        return bool(check())
    except (OSError, RuntimeError, ValueError):
        return None


def _normalized_extensions(extensions: tuple[str, ...]) -> tuple[str, ...]:
    normalized = []
    for extension in extensions:
        value = extension.lower()
        normalized.append(value if value.startswith(".") else f".{value}")
    return tuple(normalized)


def _looks_like_absolute_or_drive_path(value: str) -> bool:
    windows_path = PureWindowsPath(value)
    return bool(
        windows_path.drive or windows_path.is_absolute() or PurePosixPath(value).is_absolute()
    )


def _normalize_workspace_root(root: str) -> str:
    path = Path(root).expanduser()
    try:
        return str(path.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return str(path.absolute())


def _join_path_text(root: str, child: str) -> str:
    clean_child = child.lstrip("/\\")
    if PureWindowsPath(root).drive:
        return str(PureWindowsPath(root) / clean_child)
    return str(Path(root) / clean_child)


_FIELD_RENDERERS: dict[str, Callable[[Any], str]] = {
    SRC_MONITORING_DB: render_monitoring_db_input,
    SRC_QUALITY_HISTORY_DB: render_quality_history_db_input,
    SRC_SESSIONS_ROOT: render_sessions_root_input,
    SRC_SESSION_RUN_ID: render_session_run_id_input,
    SRC_DATASET_ID: render_dataset_id_input,
    SRC_EXPORT_OUT_DIR: render_export_out_dir_input,
    SRC_PBI_OUT_DIR: render_pbi_out_dir_input,
}
