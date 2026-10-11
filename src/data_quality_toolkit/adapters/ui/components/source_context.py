"""Shared, cross-page source-input widgets and helpers.

Unifies the repeated source/input fields — monitoring DB, quality-history DB,
sessions root, session run ID, dataset ID — so a value entered on one page
persists to others through a single shared Streamlit session-state key per
concept. Render helpers take the streamlit module (or a test double) as their
first argument, keep display basename-first, and never surface absolute paths as
primary output.

This layer changes no backend semantics: it only unifies widget identity, labels,
and helper text. Concepts that merely sound alike are kept deliberately distinct,
each with its own key and help text: the two databases (drift monitoring vs.
quality history), and the two run identities (a Sessions Root folder name vs. an
Export execution's ID). Only the session run ID has an input here — an export-run
ID is produced by a successful Export and is read back as evidence, never typed.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

from data_quality_toolkit.adapters.ui.state.keys import (
    SRC_DATASET_ID,
    SRC_EXPORT_OUT_DIR,
    SRC_EXPORT_RUN_ID,
    SRC_MONITORING_DB,
    SRC_PBI_OUT_DIR,
    SRC_QUALITY_HISTORY_DB,
    SRC_SESSION_RUN_ID,
    SRC_SESSIONS_ROOT,
)

MONITORING_DB_HELP = (
    "Local SQLite database of drift-monitoring runs (e.g., ./monitoring.db). "
    "Separate from the quality-history database."
)
QUALITY_HISTORY_DB_HELP = (
    r"Local SQLite quality-history database written by `dqt export`, such as "
    r"C:\Users\example_user\Documents\dqt_exports\dqt.db on Windows. Separate "
    "from the drift-monitoring database."
)
SESSIONS_ROOT_HELP = (
    "Folder that contains DQT session/run outputs (lineage manifests and artifacts)."
)
SESSION_RUN_ID_HELP = (
    "Name of a session folder under the Sessions Root. This is the workflow "
    "session to read, not the run ID of an Export execution."
)
DATASET_ID_HELP = (
    "The `dataset_id` field inside quality_report.json (e.g., sha1:a3f2…), "
    "produced by `dqt export`."
)
EXPORT_OUT_DIR_HELP = (
    r"Default output folder for export artifacts, such as "
    r"C:\Users\example_user\Documents\dqt_exports on Windows. Entering a path "
    "here does not grant server-write consent."
)
PBI_OUT_DIR_HELP = (
    r"Default output folder for Power BI package artifacts, such as "
    r"C:\Users\example_user\Documents\dqt_exports\powerbi on Windows. Entering "
    "a path here does not grant server-write consent."
)


def get_source_value(state: Mapping[str, Any], key: str, default: str = "") -> str:
    """Return a shared source value from session state, ignoring non-string entries."""
    value = state.get(key, default)
    return value if isinstance(value, str) else default


def set_source_value(state: MutableMapping[str, Any], key: str, value: str) -> None:
    """Store a shared source value in session state."""
    state[key] = value


def _seed(st: Any, key: str, default: str) -> None:
    """Seed a shared session-state key once when unset (best-effort; never raises).

    Seeding the state (rather than passing ``value=`` to the widget) avoids the
    Streamlit warning that fires when a keyed widget is given a default while its
    session-state key is already populated by another page.
    """
    if not default:
        return
    try:
        state = st.session_state
        if key not in state:
            state[key] = default
    except Exception:
        return


def render_monitoring_db_input(
    st: Any, *, label: str = "Local monitoring database", env_default: str = ""
) -> str:
    """Render the shared drift-monitoring database path input."""
    _seed(st, SRC_MONITORING_DB, env_default)
    value = st.text_input(
        label, key=SRC_MONITORING_DB, help=MONITORING_DB_HELP, placeholder="e.g., ./monitoring.db"
    )
    return str(value)


def render_quality_history_db_input(st: Any) -> str:
    """Render the shared quality-history database path input."""
    value = st.text_input(
        "Quality-history database",
        key=SRC_QUALITY_HISTORY_DB,
        help=QUALITY_HISTORY_DB_HELP,
        placeholder=r"e.g., C:\Users\example_user\Documents\dqt_exports\dqt.db",
    )
    return str(value)


def render_sessions_root_input(st: Any, *, default: str = "") -> str:
    """Render the shared sessions-root input (folder of DQT session/run outputs).

    A new session starts blank on purpose: the previous ``"."`` default silently
    pointed write-capable session actions at the current working directory. An
    operator-entered value (including an explicit ``"."``) is never overwritten.
    """
    _seed(st, SRC_SESSIONS_ROOT, default)
    return str(st.text_input("Sessions Root", key=SRC_SESSIONS_ROOT, help=SESSIONS_ROOT_HELP))


def render_session_run_id_input(st: Any) -> str:
    """Render the shared *session*-run input naming a folder under Sessions Root.

    Reads and writes ``SRC_SESSION_RUN_ID`` only. There is deliberately no
    equivalent input for the export-run ID: that value is produced by a
    successful Export, never typed, so the two can never be entered into the same
    control.
    """
    return str(st.text_input("Session Run ID", key=SRC_SESSION_RUN_ID, help=SESSION_RUN_ID_HELP))


def export_run_id_evidence(state: Mapping[str, Any]) -> str:
    """Return the latest successful Export's run ID from shared state, or ``""``.

    Read-only accessor for ``SRC_EXPORT_RUN_ID``. This is export evidence, not a
    query filter and not a session folder name.
    """
    return get_source_value(state, SRC_EXPORT_RUN_ID)


def render_dataset_id_input(st: Any) -> str:
    """Render the shared dataset-ID input."""
    value = st.text_input(
        "Dataset ID",
        key=SRC_DATASET_ID,
        help=DATASET_ID_HELP,
        placeholder="e.g., sha1:a3f2… (from dist/star/quality_report.json)",
    )
    return str(value)


def render_export_out_dir_input(st: Any) -> str:
    """Render the shared export output-directory input."""
    value = st.text_input(
        "Export output directory",
        key=SRC_EXPORT_OUT_DIR,
        help=EXPORT_OUT_DIR_HELP,
        placeholder=r"e.g., C:\Users\example_user\Documents\dqt_exports",
    )
    return str(value)


def render_pbi_out_dir_input(st: Any) -> str:
    """Render the shared Power BI output-directory input."""
    value = st.text_input(
        "Power BI package output directory",
        key=SRC_PBI_OUT_DIR,
        help=PBI_OUT_DIR_HELP,
        placeholder=r"e.g., C:\Users\example_user\Documents\dqt_exports\powerbi",
    )
    return str(value)
