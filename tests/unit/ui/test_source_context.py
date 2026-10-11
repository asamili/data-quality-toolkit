"""Focused tests for the shared cross-page source-input helpers."""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.ui.components.source_context import (
    DATASET_ID_HELP,
    EXPORT_OUT_DIR_HELP,
    MONITORING_DB_HELP,
    PBI_OUT_DIR_HELP,
    QUALITY_HISTORY_DB_HELP,
    SESSION_RUN_ID_HELP,
    export_run_id_evidence,
    get_source_value,
    render_dataset_id_input,
    render_export_out_dir_input,
    render_monitoring_db_input,
    render_pbi_out_dir_input,
    render_quality_history_db_input,
    render_session_run_id_input,
    render_sessions_root_input,
    set_source_value,
)
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


class RecordingSt:
    """Records text_input calls; optionally exposes a dict-backed session_state."""

    def __init__(self, session_state: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        if session_state is not None:
            self.session_state = session_state

    def text_input(self, label: str, **kwargs: Any) -> str:
        self.calls.append((label, kwargs))
        return ""


# ── pure get/set ─────────────────────────────────────────────────────────────


def test_set_and_get_source_value() -> None:
    state: dict[str, Any] = {}
    set_source_value(state, SRC_SESSION_RUN_ID, "run-1")
    assert get_source_value(state, SRC_SESSION_RUN_ID) == "run-1"


def test_get_source_value_default_and_non_string() -> None:
    assert get_source_value({}, SRC_SESSION_RUN_ID, "fallback") == "fallback"
    assert get_source_value({SRC_SESSION_RUN_ID: 5}, SRC_SESSION_RUN_ID, "fallback") == "fallback"


# ── render helpers: labels / keys / help ─────────────────────────────────────


def test_monitoring_input_label_key_help() -> None:
    st = RecordingSt()
    render_monitoring_db_input(st)
    label, kwargs = st.calls[0]
    assert label == "Local monitoring database"
    assert kwargs["key"] == SRC_MONITORING_DB
    assert kwargs["help"] == MONITORING_DB_HELP


def test_quality_history_input_label_key_help() -> None:
    st = RecordingSt()
    render_quality_history_db_input(st)
    label, kwargs = st.calls[0]
    assert label == "Quality-history database"
    assert kwargs["key"] == SRC_QUALITY_HISTORY_DB
    assert kwargs["help"] == QUALITY_HISTORY_DB_HELP


def test_session_run_id_and_dataset_id_use_shared_keys() -> None:
    st = RecordingSt()
    render_session_run_id_input(st)
    render_dataset_id_input(st)
    assert st.calls[0][0] == "Session Run ID"
    assert st.calls[0][1]["key"] == SRC_SESSION_RUN_ID
    assert st.calls[1][0] == "Dataset ID"
    assert st.calls[1][1]["key"] == SRC_DATASET_ID
    assert st.calls[1][1]["help"] == DATASET_ID_HELP


def test_session_run_id_input_describes_a_sessions_root_folder() -> None:
    st = RecordingSt()
    render_session_run_id_input(st)
    _label, kwargs = st.calls[0]
    help_text = kwargs["help"]
    assert help_text == SESSION_RUN_ID_HELP
    assert "Sessions Root" in help_text
    # The help must actively disclaim the Export meaning, not merely omit it.
    assert "not the run ID of an Export execution" in help_text


def test_session_run_id_input_never_touches_the_export_run_key() -> None:
    st = RecordingSt()
    render_session_run_id_input(st)
    assert st.calls[0][1]["key"] != SRC_EXPORT_RUN_ID


def test_export_run_id_evidence_reads_only_the_export_key() -> None:
    assert export_run_id_evidence({}) == ""
    assert export_run_id_evidence({SRC_EXPORT_RUN_ID: "run-export-1"}) == "run-export-1"
    # A session-run value must never leak through the export-evidence accessor.
    assert export_run_id_evidence({SRC_SESSION_RUN_ID: "run-session-1"}) == ""


def test_output_dir_inputs_use_source_hub_keys() -> None:
    st = RecordingSt()
    render_export_out_dir_input(st)
    render_pbi_out_dir_input(st)
    assert st.calls[0][0] == "Export output directory"
    assert st.calls[0][1]["key"] == SRC_EXPORT_OUT_DIR
    assert st.calls[0][1]["help"] == EXPORT_OUT_DIR_HELP
    assert st.calls[1][0] == "Power BI package output directory"
    assert st.calls[1][1]["key"] == SRC_PBI_OUT_DIR
    assert st.calls[1][1]["help"] == PBI_OUT_DIR_HELP


# ── seeding behaviour ────────────────────────────────────────────────────────


def test_sessions_root_default_is_blank_for_a_new_session() -> None:
    state: dict[str, Any] = {}
    st = RecordingSt(session_state=state)
    render_sessions_root_input(st)
    # A new session must not silently point session actions at ".".
    assert SRC_SESSIONS_ROOT not in state
    assert st.calls[0][1]["key"] == SRC_SESSIONS_ROOT


def test_sessions_root_explicit_default_still_seeds() -> None:
    state: dict[str, Any] = {}
    render_sessions_root_input(RecordingSt(session_state=state), default="./sessions")
    assert state[SRC_SESSIONS_ROOT] == "./sessions"


def test_sessions_root_does_not_overwrite_existing() -> None:
    state: dict[str, Any] = {SRC_SESSIONS_ROOT: "existing"}
    render_sessions_root_input(RecordingSt(session_state=state))
    assert state[SRC_SESSIONS_ROOT] == "existing"


def test_sessions_root_preserves_operator_entered_dot() -> None:
    state: dict[str, Any] = {SRC_SESSIONS_ROOT: "."}
    render_sessions_root_input(RecordingSt(session_state=state))
    assert state[SRC_SESSIONS_ROOT] == "."


def test_monitoring_env_default_seeds_only_when_nonempty() -> None:
    state: dict[str, Any] = {}
    render_monitoring_db_input(RecordingSt(session_state=state), env_default="./m.db")
    assert state[SRC_MONITORING_DB] == "./m.db"

    empty_state: dict[str, Any] = {}
    render_monitoring_db_input(RecordingSt(session_state=empty_state), env_default="")
    assert SRC_MONITORING_DB not in empty_state


def test_seed_is_safe_without_session_state() -> None:
    # RecordingSt without session_state must not raise when seeding is attempted.
    render_sessions_root_input(RecordingSt())
