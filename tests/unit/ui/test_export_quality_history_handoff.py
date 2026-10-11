"""Focused tests for the Export → Quality History handoff.

A successful Export already returns ``quality_db_path``, ``dataset_id``, and
``run_id``. These tests pin the seed-only-if-blank handoff into the shared
``SRC_*`` source keys, operator-value preservation with a labels-only retained
notice, stale Dataset ID clearing on dataset context clear/replace, and the
corrected Quality History / Artifact Center guidance text.

Gate P5B splits run identity: the export's ``run_id`` is no longer seeded into
an operator field. It is recorded as export evidence in ``SRC_EXPORT_RUN_ID``,
while ``SRC_SESSION_RUN_ID`` -- a Sessions Root folder name -- is never written
by Export.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from data_quality_toolkit.adapters.ui.pages import artifact_center, export, run_history
from data_quality_toolkit.adapters.ui.state.context import (
    DatasetContext,
    clear_dataset_context,
    set_dataset_context,
)
from data_quality_toolkit.adapters.ui.state.keys import (
    EXPORT_CSV_PATH,
    EXPORT_OUT_DIR,
    EXPORT_RUN_BTN,
    SRC_DATASET_ID,
    SRC_EXPORT_OUT_DIR,
    SRC_EXPORT_RUN_ID,
    SRC_QUALITY_HISTORY_DB,
    SRC_SESSION_RUN_ID,
    SRC_SESSIONS_ROOT,
    SRC_WORKSPACE_ROOT,
)

_MOCK_EXPORT = "data_quality_toolkit.adapters.ui.pages.export._export_csv_to_dir"
_CONFIRM_LABEL = "I confirm: write export files to the directory above"

_PRIVATE_WIN_DIR = r"C:\Users\example_user\private"
_PRIVATE_POSIX_DIR = "/home/example_user/private"
_RESULT_DB_PATH = _PRIVATE_WIN_DIR + r"\dist\dqt.db"
_RESULT_DATASET_ID = "sha1:a3f2export"
_RESULT_RUN_ID = "run-20260710-0001"


class FakeSt:
    """Streamlit-like recorder with key-backed session state."""

    def __init__(self, session_state: dict[str, Any] | None = None) -> None:
        self.session_state = session_state if session_state is not None else {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.text_values: dict[str, str] = {}
        self.checkbox_values: dict[str, bool] = {}
        self.button_values: dict[str, bool] = {}

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def __getattr__(self, name: str) -> Any:
        def recorder(*args: Any, **kwargs: Any) -> None:
            self._record(name, *args, **kwargs)

        return recorder

    def columns(self, count: int) -> list[FakeSt]:
        self._record("columns", count)
        return [self for _ in range(count)]

    def expander(self, label: str, **kwargs: Any) -> FakeSt:
        self._record("expander", label, **kwargs)
        return self

    def text_input(self, label: str, **kwargs: Any) -> str:
        self._record("text_input", label, **kwargs)
        key = kwargs.get("key")
        if isinstance(key, str) and key in self.text_values:
            return self.text_values[key]
        if label in self.text_values:
            return self.text_values[label]
        if isinstance(key, str):
            return str(self.session_state.get(key, kwargs.get("value", "")))
        return str(kwargs.get("value", ""))

    def checkbox(self, label: str, **kwargs: Any) -> bool:
        self._record("checkbox", label, **kwargs)
        key = kwargs.get("key", label)
        if key in self.checkbox_values:
            return self.checkbox_values[key]
        return bool(kwargs.get("value", False))

    def button(self, label: str, **kwargs: Any) -> bool:
        self._record("button", label, **kwargs)
        key = kwargs.get("key", label)
        return bool(self.button_values.get(key, self.button_values.get(label, False)))

    def rendered_text(self) -> str:
        return " ".join(
            str(value) for _, args, _ in self.calls for value in args if isinstance(value, str)
        )


def _export_result(**overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "run_id": _RESULT_RUN_ID,
        "dataset_id": _RESULT_DATASET_ID,
        "quality_db_path": _RESULT_DB_PATH,
        "quality_db_status": "persisted",
        "quality_db_error": None,
        "export_paths": {
            "dim_dataset": _PRIVATE_WIN_DIR + r"\dist\star\dim_dataset.csv",
            "quality_db": _RESULT_DB_PATH,
        },
    }
    result.update(overrides)
    return result


def _confirmed_export_st(state: dict[str, Any] | None = None) -> FakeSt:
    """Return a FakeSt driving a confirmed Export run click."""
    st = FakeSt(state if state is not None else {})
    st.text_values[EXPORT_CSV_PATH] = _PRIVATE_WIN_DIR + r"\sales.csv"
    st.text_values[EXPORT_OUT_DIR] = _PRIVATE_WIN_DIR + r"\dist"
    st.checkbox_values[_CONFIRM_LABEL] = True
    st.button_values[EXPORT_RUN_BTN] = True
    return st


def _run_export(st: FakeSt, result: dict[str, Any] | None, err: str | None = None) -> None:
    with patch(_MOCK_EXPORT, return_value=(result, err)):
        export._render_export(st)


# ── Seed-only-if-blank ───────────────────────────────────────────────────────


def test_successful_export_seeds_all_blank_shared_values() -> None:
    st = _confirmed_export_st()

    _run_export(st, _export_result())

    assert st.session_state[SRC_QUALITY_HISTORY_DB] == _RESULT_DB_PATH
    assert st.session_state[SRC_DATASET_ID] == _RESULT_DATASET_ID
    # The export's run ID is evidence under its own key, not a seeded input.
    assert st.session_state[SRC_EXPORT_RUN_ID] == _RESULT_RUN_ID
    text = st.rendered_text()
    assert "Quality History inputs prefilled for this run" in text
    assert "Quality-history database" in text
    assert "Dataset ID" in text
    assert "Existing Quality History values were kept" not in text


def test_empty_string_destination_counts_as_blank_and_is_seeded() -> None:
    st = _confirmed_export_st({SRC_QUALITY_HISTORY_DB: "", SRC_DATASET_ID: "  "})

    _run_export(st, _export_result())

    assert st.session_state[SRC_QUALITY_HISTORY_DB] == _RESULT_DB_PATH
    assert st.session_state[SRC_DATASET_ID] == _RESULT_DATASET_ID
    assert st.session_state[SRC_EXPORT_RUN_ID] == _RESULT_RUN_ID


# ── Operator value preservation ──────────────────────────────────────────────


def test_existing_quality_history_db_value_is_preserved() -> None:
    operator_db = _PRIVATE_POSIX_DIR + "/older/dqt.db"
    st = _confirmed_export_st({SRC_QUALITY_HISTORY_DB: operator_db})

    _run_export(st, _export_result())

    assert st.session_state[SRC_QUALITY_HISTORY_DB] == operator_db
    assert st.session_state[SRC_DATASET_ID] == _RESULT_DATASET_ID
    assert st.session_state[SRC_EXPORT_RUN_ID] == _RESULT_RUN_ID
    text = st.rendered_text()
    assert "Existing Quality History values were kept: Quality-history database." in text


def test_existing_dataset_id_is_preserved() -> None:
    st = _confirmed_export_st({SRC_DATASET_ID: "sha1:operator"})

    _run_export(st, _export_result())

    assert st.session_state[SRC_DATASET_ID] == "sha1:operator"
    assert "Existing Quality History values were kept: Dataset ID." in st.rendered_text()


def test_operator_session_run_id_is_never_touched_by_export() -> None:
    st = _confirmed_export_st({SRC_SESSION_RUN_ID: "run-operator"})

    _run_export(st, _export_result())

    # The Sessions Root folder identity survives untouched ...
    assert st.session_state[SRC_SESSION_RUN_ID] == "run-operator"
    # ... and the export's own run ID lands in its own key, so the two can no
    # longer collide the way one shared src_run_id key allowed.
    assert st.session_state[SRC_EXPORT_RUN_ID] == _RESULT_RUN_ID


def test_latest_successful_export_run_id_wins() -> None:
    st = _confirmed_export_st({SRC_EXPORT_RUN_ID: "run-previous"})

    _run_export(st, _export_result())

    # Export evidence is not an operator input: the newest success replaces it.
    assert st.session_state[SRC_EXPORT_RUN_ID] == _RESULT_RUN_ID


def test_mixed_state_seeds_blanks_and_retains_nonblanks() -> None:
    st = _confirmed_export_st({SRC_DATASET_ID: "sha1:operator"})

    _run_export(st, _export_result())

    assert st.session_state[SRC_QUALITY_HISTORY_DB] == _RESULT_DB_PATH
    assert st.session_state[SRC_DATASET_ID] == "sha1:operator"
    text = st.rendered_text()
    assert "Quality History inputs prefilled for this run: Quality-history database." in text
    assert "Existing Quality History values were kept: Dataset ID." in text


def test_same_existing_values_report_neither_seeded_nor_kept() -> None:
    st = _confirmed_export_st(
        {
            SRC_QUALITY_HISTORY_DB: _RESULT_DB_PATH,
            SRC_DATASET_ID: _RESULT_DATASET_ID,
        }
    )

    _run_export(st, _export_result())

    assert st.session_state[SRC_QUALITY_HISTORY_DB] == _RESULT_DB_PATH
    assert st.session_state[SRC_DATASET_ID] == _RESULT_DATASET_ID
    text = st.rendered_text()
    assert "Quality History inputs prefilled" not in text
    assert "Existing Quality History values were kept" not in text


def test_retained_notice_names_fields_without_exposing_paths() -> None:
    st = _confirmed_export_st(
        {
            SRC_QUALITY_HISTORY_DB: _PRIVATE_POSIX_DIR + "/older/dqt.db",
            SRC_DATASET_ID: "sha1:operator",
        }
    )

    _run_export(st, _export_result())

    text = st.rendered_text()
    assert (
        "Existing Quality History values were kept: Quality-history database, Dataset ID." in text
    )
    assert _PRIVATE_WIN_DIR not in text
    assert _PRIVATE_POSIX_DIR not in text


# ── No seeding without a successful confirmed run ────────────────────────────


def test_export_failure_does_not_seed_values() -> None:
    st = _confirmed_export_st()

    _run_export(st, None, err="boom")

    for key in (SRC_QUALITY_HISTORY_DB, SRC_DATASET_ID, SRC_EXPORT_RUN_ID):
        assert key not in st.session_state
    assert "Quality History inputs prefilled" not in st.rendered_text()


def test_failed_export_preserves_the_previous_export_run_id() -> None:
    st = _confirmed_export_st()
    _run_export(st, _export_result())
    assert st.session_state[SRC_EXPORT_RUN_ID] == _RESULT_RUN_ID

    st2 = _confirmed_export_st(st.session_state)
    _run_export(st2, None, err="disk full")

    # A failure never manufactures, clears, or replaces export-run identity.
    assert st.session_state[SRC_EXPORT_RUN_ID] == _RESULT_RUN_ID


def test_successful_export_without_a_run_id_records_nothing() -> None:
    st = _confirmed_export_st()

    _run_export(st, _export_result(run_id=""))

    assert SRC_EXPORT_RUN_ID not in st.session_state


def test_unconfirmed_click_does_not_export_or_seed() -> None:
    st = _confirmed_export_st()
    st.checkbox_values[_CONFIRM_LABEL] = False

    with patch(_MOCK_EXPORT) as mock_export:
        export._render_export(st)

    mock_export.assert_not_called()
    for key in (SRC_QUALITY_HISTORY_DB, SRC_DATASET_ID, SRC_EXPORT_RUN_ID):
        assert key not in st.session_state


def test_no_click_does_not_export_or_seed() -> None:
    st = _confirmed_export_st()
    st.button_values[EXPORT_RUN_BTN] = False

    with patch(_MOCK_EXPORT) as mock_export:
        export._render_export(st)

    mock_export.assert_not_called()
    for key in (SRC_QUALITY_HISTORY_DB, SRC_DATASET_ID, SRC_EXPORT_RUN_ID):
        assert key not in st.session_state


def test_failed_db_persist_seeds_ids_but_not_db_path() -> None:
    st = _confirmed_export_st()
    result = _export_result(quality_db_status="failed", quality_db_error="cannot open database")

    _run_export(st, result)

    assert SRC_QUALITY_HISTORY_DB not in st.session_state
    assert st.session_state[SRC_DATASET_ID] == _RESULT_DATASET_ID
    assert st.session_state[SRC_EXPORT_RUN_ID] == _RESULT_RUN_ID


# ── Stale Dataset ID clearing on dataset context clear/replace ───────────────


def _context(path: str, size: int = 1) -> DatasetContext:
    return DatasetContext(source_path=path, display_name="data.csv", size_bytes=size, modified_ns=1)


def _unrelated_values() -> dict[str, Any]:
    return {
        SRC_QUALITY_HISTORY_DB: "./dist/dqt.db",
        SRC_SESSIONS_ROOT: "./sessions",
        SRC_SESSION_RUN_ID: "run-keep",
        SRC_WORKSPACE_ROOT: "./workspace",
        SRC_EXPORT_OUT_DIR: "./exports",
    }


def test_clearing_dataset_context_removes_stale_dataset_id_only() -> None:
    state: dict[str, Any] = {SRC_DATASET_ID: "sha1:stale", **_unrelated_values()}
    set_dataset_context(state, _context("C:/data/a.csv"))
    state[SRC_DATASET_ID] = "sha1:stale"

    clear_dataset_context(state)

    assert SRC_DATASET_ID not in state
    for key, value in _unrelated_values().items():
        assert state[key] == value


def test_replacing_dataset_context_removes_previous_dataset_id() -> None:
    state: dict[str, Any] = {**_unrelated_values()}
    set_dataset_context(state, _context("C:/data/a.csv"))
    state[SRC_DATASET_ID] = "sha1:previous"

    changed = set_dataset_context(state, _context("C:/data/b.csv", size=2))

    assert changed is True
    assert SRC_DATASET_ID not in state
    for key, value in _unrelated_values().items():
        assert state[key] == value


def test_same_dataset_context_keeps_dataset_id() -> None:
    state: dict[str, Any] = {}
    set_dataset_context(state, _context("C:/data/a.csv"))
    state[SRC_DATASET_ID] = "sha1:current"

    changed = set_dataset_context(state, _context("C:/data/a.csv"))

    assert changed is False
    assert state[SRC_DATASET_ID] == "sha1:current"


def test_first_load_keeps_operator_typed_dataset_id() -> None:
    state: dict[str, Any] = {SRC_DATASET_ID: "sha1:manual-lookup"}

    set_dataset_context(state, _context("C:/data/a.csv"))

    assert state[SRC_DATASET_ID] == "sha1:manual-lookup"


# ── Guidance accuracy ────────────────────────────────────────────────────────


def test_quality_history_guidance_describes_prefill_not_path_reuse() -> None:
    st = FakeSt({})

    run_history._render_run_history(st)

    text = st.rendered_text()
    assert "prefills the Quality-history database and Dataset ID" in text
    assert "values you entered yourself are kept" in text
    assert "`quality_report.json`" in text
    assert "actual `dqt.db` path shown by Export" not in text
    # There is no Run ID control on this page, so it must not claim to fill one.
    assert "and Run ID here when those" not in text


def test_quality_history_shows_export_run_id_as_read_only_evidence() -> None:
    st = FakeSt({SRC_EXPORT_RUN_ID: _RESULT_RUN_ID})

    run_history._render_run_history(st)

    text = st.rendered_text()
    assert f"Latest successful Export run ID: `{_RESULT_RUN_ID}`" in text
    assert "export evidence only" in text
    assert "not by run ID" in text
    # Evidence only: no Run ID control is rendered for it.
    labels = [args[0] for name, args, _ in st.calls if name == "text_input" and args]
    assert not any("Run ID" in str(label) for label in labels)


def test_quality_history_without_an_export_shows_no_run_evidence() -> None:
    st = FakeSt({})

    run_history._render_run_history(st)

    assert "Latest successful Export run ID" not in st.rendered_text()


def test_artifact_center_guidance_does_not_claim_export_manifests() -> None:
    st = FakeSt({})

    artifact_center._render_artifact_center(st)

    text = st.rendered_text()
    assert "Artifacts are produced by the **Export** page" not in text
    assert "previews its generated artifacts" in text
    assert "lineage manifest" in text
    assert "No files are created here" in text
