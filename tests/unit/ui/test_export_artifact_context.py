"""Focused tests for the latest-export context handoff.

Pins the typed session-only ``ExportArtifactContext``: created only by a
confirmed successful Export, replaced by a later success, preserved across a
failed Export and across dataset replacement, and offered to the operator as an
explicit (never automatic) Open Artifact Center next action.

Gate P5A extends this with the export's *source* linkage: which dataset the run
was produced from, recorded additively so older contexts stay readable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

from data_quality_toolkit.adapters.ui.pages import artifact_center, export
from data_quality_toolkit.adapters.ui.services.dataset_activation import make_managed_context
from data_quality_toolkit.adapters.ui.services.dataset_versions import (
    CreationMechanism,
    DatasetFormat,
    DatasetVersionRecord,
    ParentRef,
    RecipeRef,
    new_family_id,
    new_version_id,
)
from data_quality_toolkit.adapters.ui.services.export_alignment import ExportSourceStatus
from data_quality_toolkit.adapters.ui.state.context import DatasetContext, set_dataset_context
from data_quality_toolkit.adapters.ui.state.export_context import (
    ExportArtifactContext,
    export_artifact_context_from_result,
    get_export_artifact_context,
    set_export_artifact_context,
)
from data_quality_toolkit.adapters.ui.state.keys import (
    DATASET_CONTEXT,
    EXPORT_ARTIFACT_CONTEXT,
    EXPORT_CSV_PATH,
    EXPORT_OUT_DIR,
    EXPORT_RUN_BTN,
    SRC_SESSION_RUN_ID,
    SRC_SESSIONS_ROOT,
)

_MOCK_EXPORT = "data_quality_toolkit.adapters.ui.pages.export._export_csv_to_dir"
_CONFIRM_LABEL = "I confirm: write export files to the directory above"

_PRIVATE_DIR = r"C:\Users\example_user\private"
_OUT_DIR = _PRIVATE_DIR + r"\dist"


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

    def call_names(self) -> list[str]:
        return [name for name, _, _ in self.calls]


def _export_result(**overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "run_id": "run-20260712-0001",
        "dataset_id": "sha1:a3f2export",
        "ts": "2026-07-12T10:00:00Z",
        "quality_db_path": _OUT_DIR + r"\dqt.db",
        "quality_db_status": "persisted",
        "quality_db_error": None,
        "export_paths": {
            "dim_dataset": _OUT_DIR + r"\star\dim_dataset.csv",
            "quality_report": _OUT_DIR + r"\star\quality_report.json",
            "quality_db": _OUT_DIR + r"\dqt.db",
        },
    }
    result.update(overrides)
    return result


def _confirmed_export_st(state: dict[str, Any] | None = None) -> FakeSt:
    st = FakeSt(state if state is not None else {})
    st.text_values[EXPORT_CSV_PATH] = _PRIVATE_DIR + r"\sales.csv"
    st.text_values[EXPORT_OUT_DIR] = _OUT_DIR
    st.checkbox_values[_CONFIRM_LABEL] = True
    st.button_values[EXPORT_RUN_BTN] = True
    return st


def _run_export(st: FakeSt, result: dict[str, Any] | None, err: str | None = None) -> None:
    with patch(_MOCK_EXPORT, return_value=(result, err)):
        export._render_export(st)


# ── Context creation ─────────────────────────────────────────────────────────


def test_context_absent_before_any_successful_export() -> None:
    st = _confirmed_export_st()
    st.button_values[EXPORT_RUN_BTN] = False

    with patch(_MOCK_EXPORT) as mock_export:
        export._render_export(st)

    mock_export.assert_not_called()
    assert EXPORT_ARTIFACT_CONTEXT not in st.session_state
    assert get_export_artifact_context(st.session_state) is None


def test_successful_export_creates_context_with_result_values() -> None:
    st = _confirmed_export_st()

    _run_export(st, _export_result())

    context = get_export_artifact_context(st.session_state)
    assert context is not None
    assert dict(context.export_paths) == _export_result()["export_paths"]
    assert context.output_dir == _OUT_DIR
    assert context.run_id == "run-20260712-0001"
    assert context.dataset_id == "sha1:a3f2export"
    assert context.exported_at == "2026-07-12T10:00:00Z"
    assert context.quality_db_status == "persisted"


def test_second_successful_export_replaces_previous_context() -> None:
    st = _confirmed_export_st()
    _run_export(st, _export_result())

    st2 = _confirmed_export_st(st.session_state)
    second = _export_result(
        run_id="run-20260712-0002",
        export_paths={"dim_dataset": _OUT_DIR + r"\star\dim_dataset.csv"},
    )
    _run_export(st2, second)

    context = get_export_artifact_context(st.session_state)
    assert context is not None
    assert context.run_id == "run-20260712-0002"
    assert dict(context.export_paths) == second["export_paths"]


# ── Failure paths ────────────────────────────────────────────────────────────


def test_failed_export_creates_no_context_and_no_success_notice() -> None:
    st = _confirmed_export_st()

    _run_export(st, None, err="boom")

    assert EXPORT_ARTIFACT_CONTEXT not in st.session_state
    text = st.rendered_text()
    assert "Latest Export section" not in text
    assert "page_link" not in st.call_names()


def test_failed_export_preserves_previous_successful_context() -> None:
    st = _confirmed_export_st()
    _run_export(st, _export_result())
    prior = get_export_artifact_context(st.session_state)
    assert prior is not None

    st2 = _confirmed_export_st(st.session_state)
    _run_export(st2, None, err="disk full")

    assert get_export_artifact_context(st.session_state) is prior
    assert "page_link" not in st2.call_names()


def test_unconfirmed_click_creates_no_context() -> None:
    st = _confirmed_export_st()
    st.checkbox_values[_CONFIRM_LABEL] = False

    with patch(_MOCK_EXPORT) as mock_export:
        export._render_export(st)

    mock_export.assert_not_called()
    assert EXPORT_ARTIFACT_CONTEXT not in st.session_state


def test_result_without_artifacts_creates_no_context() -> None:
    st = _confirmed_export_st()

    _run_export(st, _export_result(export_paths={}))

    assert EXPORT_ARTIFACT_CONTEXT not in st.session_state


# ── Context survives dataset replacement ─────────────────────────────────────


def _dataset(path: str, size: int = 1) -> DatasetContext:
    return DatasetContext(source_path=path, display_name="data.csv", size_bytes=size, modified_ns=1)


def test_dataset_replacement_keeps_completed_export_context() -> None:
    state: dict[str, Any] = {}
    context = ExportArtifactContext(
        export_paths={"quality_report": _OUT_DIR + r"\star\quality_report.json"},
        output_dir=_OUT_DIR,
        run_id="run-1",
        dataset_id="sha1:a",
    )
    set_export_artifact_context(state, context)
    set_dataset_context(state, _dataset("C:/data/a.csv"))
    set_dataset_context(state, _dataset("C:/data/b.csv", size=2))

    assert get_export_artifact_context(state) is context


# ── Explicit next action ─────────────────────────────────────────────────────


def test_success_offers_open_artifact_center_next_action() -> None:
    st = _confirmed_export_st()

    _run_export(st, _export_result())

    page_links = [(args, kwargs) for name, args, kwargs in st.calls if name == "page_link"]
    assert len(page_links) == 1
    (page_arg,), link_kwargs = page_links[0]
    assert not isinstance(page_arg, str)
    assert link_kwargs == {"label": "Open Artifact Center"}

    # The link target comes from the same canonical factory app.py registers
    # Artifact Center with, so the two can never drift apart.
    page_calls = [(args, kwargs) for name, args, kwargs in st.calls if name == "Page"]
    assert page_calls == [
        ((artifact_center.render,), {"title": "Artifact Center", "url_path": "artifact-center"})
    ]

    assert "Latest Export section" in st.rendered_text()
    # Explicit action only — nothing auto-navigates.
    assert "switch_page" not in st.call_names()


# ── Session-manifest state is not seeded from the context ────────────────────


def test_context_does_not_seed_or_overwrite_session_manifest_state() -> None:
    operator_root = r"C:\Users\example_user\sessions"
    st = _confirmed_export_st(
        {SRC_SESSIONS_ROOT: operator_root, SRC_SESSION_RUN_ID: "run-operator"}
    )

    _run_export(st, _export_result())

    assert st.session_state[SRC_SESSIONS_ROOT] == operator_root
    # Export writes only the export-run key; the operator's session identity is
    # never touched.
    assert st.session_state[SRC_SESSION_RUN_ID] == "run-operator"
    assert get_export_artifact_context(st.session_state) is not None


# ── Pure builder/accessor behavior ───────────────────────────────────────────


def test_builder_returns_none_without_result_or_artifacts() -> None:
    assert export_artifact_context_from_result(None, _OUT_DIR) is None
    assert export_artifact_context_from_result({}, _OUT_DIR) is None
    assert export_artifact_context_from_result({"export_paths": "bad"}, _OUT_DIR) is None
    assert export_artifact_context_from_result({"export_paths": {}}, _OUT_DIR) is None
    assert export_artifact_context_from_result({"export_paths": {"a": "  "}}, _OUT_DIR) is None


def test_builder_keeps_only_nonblank_string_paths_and_strips_fields() -> None:
    context = export_artifact_context_from_result(
        {
            "run_id": " run-1 ",
            "dataset_id": 42,
            "export_paths": {"a": " x.csv ", "b": 7, "c": ""},
        },
        "  " + _OUT_DIR + "  ",
    )

    assert context is not None
    assert dict(context.export_paths) == {"a": "x.csv"}
    assert context.run_id == "run-1"
    assert context.dataset_id == ""
    assert context.output_dir == _OUT_DIR


def test_accessor_ignores_malformed_session_value() -> None:
    assert get_export_artifact_context({EXPORT_ARTIFACT_CONTEXT: "not-a-context"}) is None


# ── P5A: source linkage recorded from the effective Export source ────────────

_SOURCE_PATH = _PRIVATE_DIR + r"\sales.csv"
_CONTENT_A = "sha256:" + "a" * 64
_ROOT = "sha256:" + "c" * 64


def _managed_context(source_path: str = _SOURCE_PATH) -> DatasetContext:
    record = DatasetVersionRecord(
        schema_version=1,
        version_id=new_version_id(),
        family_id=new_family_id(),
        root_content_id=_ROOT,
        content_id=_CONTENT_A,
        dataset_id="sha1:" + "d" * 40,
        label="cleaned v2",
        file_relative_path="versions/v1/data.csv",
        format=DatasetFormat.CSV,
        size_bytes=2048,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        created_by=CreationMechanism.PREPROCESS_RECIPE,
        parent=ParentRef(version_id=None, content_id=_ROOT),
        recipe=RecipeRef(digest="sha256:" + "e" * 64, relative_path="recipes/v1.json"),
    )
    return make_managed_context(
        record,
        source_path=source_path,
        display_name="sales.csv",
        size_bytes=2048,
        modified_ns=10,
    )


def test_old_context_construction_without_source_linkage_remains_valid() -> None:
    context = ExportArtifactContext(
        export_paths={"quality_report": _OUT_DIR + r"\star\quality_report.json"},
        output_dir=_OUT_DIR,
        run_id="run-old",
        dataset_id="sha1:old",
    )

    assert context.source_status == ""
    assert context.source_version_id == ""
    assert context.source_binding == ""


def test_export_from_active_managed_version_records_lifecycle_linkage() -> None:
    active = _managed_context()
    st = _confirmed_export_st({DATASET_CONTEXT: active})

    _run_export(st, _export_result())

    context = get_export_artifact_context(st.session_state)
    assert context is not None
    assert context.source_status == ExportSourceStatus.ACTIVE_MANAGED.value
    assert context.source_version_id == active.version_id
    assert context.source_family_id == active.family_id
    assert context.source_content_id == active.content_id
    # No override warning when the export really is the active version.
    assert "is not the active dataset" not in st.rendered_text()


def test_export_from_active_legacy_dataset_records_no_lifecycle_ids() -> None:
    active = DatasetContext(
        source_path=_SOURCE_PATH, display_name="sales.csv", size_bytes=2048, modified_ns=10
    )
    st = _confirmed_export_st({DATASET_CONTEXT: active})

    _run_export(st, _export_result())

    context = get_export_artifact_context(st.session_state)
    assert context is not None
    assert context.source_status == ExportSourceStatus.ACTIVE_LEGACY.value
    assert context.source_version_id == ""
    assert context.source_family_id == ""
    assert context.source_content_id == ""
    assert "is not the active dataset" not in st.rendered_text()


def test_manual_override_export_warns_and_attaches_no_active_lifecycle_ids() -> None:
    active = _managed_context(_PRIVATE_DIR + r"\managed_version.csv")
    st = _confirmed_export_st({DATASET_CONTEXT: active})

    _run_export(st, _export_result())

    context = get_export_artifact_context(st.session_state)
    assert context is not None
    assert context.source_status == ExportSourceStatus.EXPLICIT_OVERRIDE.value
    assert context.source_version_id == ""
    assert context.source_family_id == ""
    assert context.source_content_id == ""
    # The export still reports the dataset it genuinely exported.
    assert context.dataset_id == "sha1:a3f2export"

    rendered = st.rendered_text()
    assert "is not the active dataset" in rendered
    assert "not the active managed version" in rendered
    # The override is warned about, never blocked.
    assert "Export complete" in rendered


def test_override_warning_names_a_basename_and_leaks_no_path() -> None:
    st = _confirmed_export_st({DATASET_CONTEXT: _managed_context(_PRIVATE_DIR + r"\managed.csv")})

    _run_export(st, _export_result())

    warnings = [args for name, args, _ in st.calls if name == "warning"]
    override = [str(args[0]) for args in warnings if "is not the active dataset" in str(args[0])]
    assert len(override) == 1
    message = override[0]
    assert "sales.csv" in message
    assert _PRIVATE_DIR not in message
    assert _SOURCE_PATH not in message


def test_export_source_seeds_from_the_newly_active_context_after_a_switch() -> None:
    state: dict[str, Any] = {}
    set_dataset_context(state, _dataset("C:/data/a.csv"))
    state[EXPORT_CSV_PATH] = "C:/data/a.csv"

    # A genuine switch invalidates the stale auto-seeded source ...
    set_dataset_context(state, _dataset("C:/data/b.csv", size=2))
    assert EXPORT_CSV_PATH not in state

    # ... and the next Export render seeds it from the new active context.
    st = FakeSt(state)
    export._seed_export_defaults(st)
    assert state[EXPORT_CSV_PATH] == "C:/data/b.csv"


def test_export_source_seeding_never_overwrites_a_manual_override() -> None:
    state: dict[str, Any] = {}
    set_dataset_context(state, _dataset("C:/data/a.csv"))
    state[EXPORT_CSV_PATH] = "C:/data/manual.csv"

    st = FakeSt(state)
    export._seed_export_defaults(st)

    assert state[EXPORT_CSV_PATH] == "C:/data/manual.csv"


def test_failed_export_preserves_prior_context_source_linkage() -> None:
    active = _managed_context()
    st = _confirmed_export_st({DATASET_CONTEXT: active})
    _run_export(st, _export_result())
    prior = get_export_artifact_context(st.session_state)
    assert prior is not None
    assert prior.source_version_id == active.version_id

    st2 = _confirmed_export_st(st.session_state)
    _run_export(st2, None, err="disk full")

    assert get_export_artifact_context(st.session_state) is prior


def test_context_source_linkage_survives_a_dataset_switch() -> None:
    active = _managed_context()
    st = _confirmed_export_st({DATASET_CONTEXT: active})
    _run_export(st, _export_result())
    stored = get_export_artifact_context(st.session_state)
    assert stored is not None

    set_dataset_context(st.session_state, _dataset("C:/data/elsewhere.csv"))

    # Historical evidence is preserved verbatim, still linked to the version it
    # was actually exported from.
    survivor = get_export_artifact_context(st.session_state)
    assert survivor is stored
    assert survivor.source_version_id == active.version_id
