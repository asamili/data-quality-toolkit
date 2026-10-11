"""Journey tests: Start's Source Hub populates one shared state dict consumed downstream.

Unlike the per-page consumption tests, these render ``pages.start._render_start``
first and then render downstream pages against the SAME session-state dict, so the
cross-page key continuity is exercised at runtime rather than only via shared
constants. The fake widgets read but never write ``session_state`` (matching the
reference fakes), so SRC_* values are pre-seeded as "user typed values" — the
realistic simulation of Streamlit's persisted widget state. The journey signal is
every write the page code itself performs on the shared dict.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd

from data_quality_toolkit.adapters.ui.pages import (
    artifact_center,
    data_overview,
    drift_explorer,
    export,
    manifest_viewer,
    pipeline_runner,
    run_history,
    start,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import (
    DATASET_ACTIVATE_BTN,
    DATASET_CONTEXT,
    DATASET_PATH_INPUT,
    DRIFT_DATASET_FILTER,
    EXPORT_CSV_PATH,
    EXPORT_OUT_DIR,
    EXPORT_RUN_BTN,
    PBI_OUT_DIR,
    PIPE_CONFIRM_EXEC,
    PIPE_RUN_BTN,
    SRC_DATASET_ID,
    SRC_EXPORT_OUT_DIR,
    SRC_MONITORING_DB,
    SRC_PBI_OUT_DIR,
    SRC_QUALITY_HISTORY_DB,
    SRC_SESSION_RUN_ID,
    SRC_SESSIONS_ROOT,
    SRC_WORKSPACE_ROOT,
    SRC_WORKSPACE_ROOT_INPUT,
)

_PRIVATE_DIR = r"C:\Users\example_user\private"
_CSV_PATH = _PRIVATE_DIR + r"\customers.csv"
_MONITORING_DB = _PRIVATE_DIR + r"\monitoring.db"
_HISTORY_DB = _PRIVATE_DIR + r"\dqt.db"
_SESSIONS_ROOT = _PRIVATE_DIR + r"\sessions"
_EXPORT_DIR = _PRIVATE_DIR + r"\dist"
_PBI_DIR = _PRIVATE_DIR + r"\powerbi"
_RUN_ID = "run-123"
_DATASET_ID = "sha1:any-value"


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

    def selectbox(self, label: str, options: list[Any], **kwargs: Any) -> Any:
        self._record("selectbox", label, options, **kwargs)
        return options[0] if options else None

    def multiselect(self, label: str, options: list[Any], **kwargs: Any) -> list[Any]:
        self._record("multiselect", label, options, **kwargs)
        return []

    def number_input(self, label: str, **kwargs: Any) -> int | float:
        self._record("number_input", label, **kwargs)
        value = kwargs.get("value", kwargs.get("min_value", 0))
        return value if isinstance(value, int | float) else 0

    def rendered_text(self) -> str:
        return " ".join(
            str(value) for _, args, _ in self.calls for value in args if isinstance(value, str)
        )

    def calls_named(self, name: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        return [(args, kwargs) for kind, args, kwargs in self.calls if kind == name]


def _journey_state() -> dict[str, Any]:
    return {
        DATASET_PATH_INPUT: _CSV_PATH,
        SRC_MONITORING_DB: _MONITORING_DB,
        SRC_QUALITY_HISTORY_DB: _HISTORY_DB,
        SRC_SESSIONS_ROOT: _SESSIONS_ROOT,
        SRC_SESSION_RUN_ID: _RUN_ID,
        SRC_DATASET_ID: _DATASET_ID,
        SRC_EXPORT_OUT_DIR: _EXPORT_DIR,
        SRC_PBI_OUT_DIR: _PBI_DIR,
    }


def _render_journey_start() -> tuple[dict[str, Any], DatasetContext, FakeSt]:
    """Render Start against a pre-typed state dict and activate the dataset."""
    state = _journey_state()
    st = FakeSt(state)
    st.button_values[DATASET_ACTIVATE_BTN] = True
    context = DatasetContext(
        source_path=_CSV_PATH,
        display_name="customers.csv",
        size_bytes=4096,
        modified_ns=1,
    )
    with patch(
        "data_quality_toolkit.adapters.ui.pages.start.build_dataset_context",
        return_value=(context, None),
    ) as build:
        start._render_start(st, state)
    build.assert_called_once_with(_CSV_PATH, large_file_mode=False)
    assert state[DATASET_CONTEXT] == context
    return state, context, st


def _render_workspace_start(
    workspace_root: str,
) -> tuple[dict[str, Any], DatasetContext, FakeSt]:
    """Render Start with Workspace Root deriving blank Source Hub defaults."""
    state = {
        DATASET_PATH_INPUT: _CSV_PATH,
        SRC_WORKSPACE_ROOT: workspace_root,
        SRC_SESSION_RUN_ID: _RUN_ID,
        SRC_DATASET_ID: _DATASET_ID,
    }
    st = FakeSt(state)
    st.button_values[DATASET_ACTIVATE_BTN] = True
    context = DatasetContext(
        source_path=_CSV_PATH,
        display_name="customers.csv",
        size_bytes=4096,
        modified_ns=1,
    )
    with patch(
        "data_quality_toolkit.adapters.ui.pages.start.build_dataset_context",
        return_value=(context, None),
    ) as build:
        start._render_start(st, state)
    build.assert_called_once_with(_CSV_PATH, large_file_mode=False)
    assert state[DATASET_CONTEXT] == context
    return state, context, st


def _manifest() -> dict[str, Any]:
    return {
        "summary": {"run_id": _RUN_ID},
        "datasets": [],
        "artifacts": [
            {"path": _SESSIONS_ROOT + r"\run-123\quality_report.json", "kind": "quality_report"}
        ],
        "gates": {"failures": []},
    }


def _assessment_result() -> tuple[pd.DataFrame, dict[str, Any], None]:
    df = pd.DataFrame({"amount": [10, 20], "segment": ["a", "b"]})
    result = {
        "profile": {
            "rows": 2,
            "cols": 2,
            "memory_mb": 0.01,
            "columns": [
                {
                    "name": "amount",
                    "dtype": "int64",
                    "nulls": 0,
                    "unique": 2,
                    "min": 10,
                    "max": 20,
                },
                {"name": "segment", "dtype": "object", "nulls": 0, "unique": 2},
            ],
        },
        "assessment": {"score": 1.0, "quality_score": 1.0, "issues": []},
    }
    return df, result, None


def test_journey_start_populates_shared_state() -> None:
    state, context, st = _render_journey_start()

    assert state[SRC_MONITORING_DB] == _MONITORING_DB
    assert state[SRC_QUALITY_HISTORY_DB] == _HISTORY_DB
    assert state[SRC_SESSIONS_ROOT] == _SESSIONS_ROOT
    assert state[SRC_SESSION_RUN_ID] == _RUN_ID
    assert state[SRC_DATASET_ID] == _DATASET_ID
    assert state[SRC_EXPORT_OUT_DIR] == _EXPORT_DIR
    assert state[SRC_PBI_OUT_DIR] == _PBI_DIR
    assert state[DATASET_CONTEXT] == context

    rendered_keys = {kwargs.get("key") for _, kwargs in st.calls_named("text_input")}
    assert {
        DATASET_PATH_INPUT,
        SRC_WORKSPACE_ROOT_INPUT,
        SRC_MONITORING_DB,
        SRC_QUALITY_HISTORY_DB,
        SRC_SESSIONS_ROOT,
        SRC_SESSION_RUN_ID,
        SRC_DATASET_ID,
        SRC_EXPORT_OUT_DIR,
        SRC_PBI_OUT_DIR,
    } <= rendered_keys

    text = st.rendered_text()
    assert "Dataset context ready: customers.csv" in text
    assert "Output locations are defaults only" in text
    assert "customers.csv" in text
    assert "monitoring.db" in text
    assert "run-123" in text
    assert _PRIVATE_DIR not in text


def test_journey_workspace_defaults_flow_to_downstream_consumers(
    tmp_path: Any, monkeypatch: Any
) -> None:
    # The env default would otherwise seed the monitoring DB; keep it unset so the
    # blank-until-exists behavior is deterministic.
    monkeypatch.delenv("DQT_UI_DB", raising=False)

    workspace_path = tmp_path / "station-workspace"
    workspace_root = str(workspace_path)
    expected_sessions_root = str(workspace_path / "sessions")
    expected_export_dir = str(workspace_path / "exports")
    expected_pbi_dir = str(workspace_path / "powerbi")
    state, context, start_st = _render_workspace_start(workspace_root)

    assert state[SRC_WORKSPACE_ROOT] == workspace_root
    # Database fields are never derived from Workspace Root: they stay blank until the
    # user enters them or a workflow creates them.
    assert SRC_MONITORING_DB not in state
    assert SRC_QUALITY_HISTORY_DB not in state
    # Folder locations are still derived and flow to downstream consumers.
    assert state[SRC_SESSIONS_ROOT] == expected_sessions_root
    assert state[SRC_EXPORT_OUT_DIR] == expected_export_dir
    assert state[SRC_PBI_OUT_DIR] == expected_pbi_dir
    assert state[SRC_SESSION_RUN_ID] == _RUN_ID
    assert state[SRC_DATASET_ID] == _DATASET_ID
    assert state[DATASET_PATH_INPUT] == _CSV_PATH
    assert DRIFT_DATASET_FILTER not in state
    assert not workspace_path.exists()

    drift_capture: dict[str, Any] = {}

    def load_monitoring(db_path: str, **kwargs: Any) -> tuple[None, None]:
        drift_capture["db_path"] = db_path
        drift_capture.update(kwargs)
        return None, None

    monkeypatch.setattr(drift_explorer, "load_monitoring_overview", load_monitoring)

    history_capture: dict[str, str] = {}

    def load_history(db: str, dataset_id: str) -> tuple[list[dict[str, Any]], None]:
        history_capture["db"] = db
        history_capture["dataset_id"] = dataset_id
        return [], None

    monkeypatch.setattr(run_history, "_load_run_history", load_history)
    artifact_rebuild = MagicMock(return_value=_manifest())
    viewer_rebuild = MagicMock(return_value=_manifest())
    artifact_loader = MagicMock(return_value=(_manifest(), None))
    viewer_loader = MagicMock(return_value=(_manifest(), None))
    run_pipeline = MagicMock(return_value=({"status": "success"}, None))
    export_write = MagicMock()
    pbi_write = MagicMock()
    monkeypatch.setattr(artifact_center, "create_manifest", artifact_rebuild)
    monkeypatch.setattr(manifest_viewer, "create_manifest", viewer_rebuild)
    monkeypatch.setattr(artifact_center, "load_manifest_dict", artifact_loader)
    monkeypatch.setattr(manifest_viewer, "load_manifest_dict", viewer_loader)
    monkeypatch.setattr(pipeline_runner, "_run_elt_pipeline", run_pipeline)
    monkeypatch.setattr(export, "_export_csv_to_dir", export_write)
    monkeypatch.setattr(export, "generate_package", pbi_write)

    texts = [start_st.rendered_text()]

    # Drift Monitoring: the monitoring DB is blank, so the page stays in its empty
    # state, points back to Start, and never calls the loader or renders the filter.
    drift_st = FakeSt(state)
    drift_explorer._render_drift_explorer(drift_st)
    texts.append(drift_st.rendered_text())
    assert drift_capture == {}
    assert "Set Local monitoring database in Start / Load Dataset" in drift_st.rendered_text()
    assert not any(
        kwargs.get("key") == DRIFT_DATASET_FILTER
        for _, kwargs in drift_st.calls_named("text_input")
    )
    assert DRIFT_DATASET_FILTER not in state

    # Quality History: the quality-history DB is blank, so the page stays inert and
    # never calls the history loader.
    history_st = FakeSt(state)
    run_history._render_run_history(history_st)
    texts.append(history_st.rendered_text())
    assert history_capture == {}

    expected_manifest_path = str(Path(expected_sessions_root) / _RUN_ID / "artifacts.json")

    artifact_st = FakeSt(state)
    artifact_st.button_values[artifact_center._LOAD_BTN] = True
    artifact_center._render_artifact_center(artifact_st)
    texts.append(artifact_st.rendered_text())
    artifact_loader.assert_called_once_with(expected_manifest_path)
    artifact_rebuild.assert_not_called()

    manifest_st = FakeSt(state)
    manifest_st.button_values["Load Manifest"] = True
    manifest_viewer._render_manifest_viewer(manifest_st)
    texts.append(manifest_st.rendered_text())
    viewer_loader.assert_called_once_with(expected_manifest_path)
    viewer_rebuild.assert_not_called()

    pipeline_st = FakeSt(state)
    pipeline_st.checkbox_values[PIPE_CONFIRM_EXEC] = True
    pipeline_st.button_values[PIPE_RUN_BTN] = True
    pipeline_runner._render_pipeline_runner(pipeline_st, state)
    texts.append(pipeline_st.rendered_text())
    run_pipeline.assert_called_once_with(_RUN_ID, expected_sessions_root)

    export_st = FakeSt(state)
    export._render_export(export_st)
    texts.append(export_st.rendered_text())
    assert state[EXPORT_CSV_PATH] == context.source_path
    assert state[EXPORT_OUT_DIR] == expected_export_dir
    assert state[PBI_OUT_DIR] == expected_pbi_dir
    export_write.assert_not_called()
    pbi_write.assert_not_called()

    combined = " ".join(texts)
    assert workspace_root not in combined
    # The derived folder defaults reach downstream consumers basename-first. The DB
    # fields are blank, so no derived DB source value is displayed.
    for basename in ("sessions", "exports", "powerbi"):
        assert basename in combined
    assert not workspace_path.exists()


def test_journey_drift_explorer_consumes_start_monitoring_db(monkeypatch: Any) -> None:
    state, _, _ = _render_journey_start()
    st = FakeSt(state)
    captured: dict[str, Any] = {}

    def load(db_path: str, **kwargs: Any) -> tuple[None, None]:
        captured["db_path"] = db_path
        captured.update(kwargs)
        return None, None

    monkeypatch.setattr(drift_explorer, "load_monitoring_overview", load)

    drift_explorer._render_drift_explorer(st)

    text = st.rendered_text()
    assert captured["db_path"] == _MONITORING_DB
    # The Source Hub Dataset ID must never become the page-local drift filter.
    assert captured["current_dataset_id"] is None
    assert any(
        kwargs.get("key") == DRIFT_DATASET_FILTER for _, kwargs in st.calls_named("text_input")
    )
    assert "Using monitoring source from Start" in text
    assert "distinct from the Source Hub Dataset ID" in text
    assert "monitoring.db" in text
    assert _DATASET_ID not in text
    assert _PRIVATE_DIR not in text


def test_journey_run_history_consumes_start_history_db_and_dataset_id(monkeypatch: Any) -> None:
    state, _, _ = _render_journey_start()
    st = FakeSt(state)
    captured: dict[str, str] = {}

    def load(db: str, dataset_id: str) -> tuple[list[dict[str, Any]], None]:
        captured["db"] = db
        captured["dataset_id"] = dataset_id
        return [], None

    monkeypatch.setattr(run_history, "_load_run_history", load)

    run_history._render_run_history(st)

    text = st.rendered_text()
    assert captured == {"db": _HISTORY_DB, "dataset_id": _DATASET_ID}
    assert "Using Quality History sources from Start" in text
    assert "dqt.db" in text
    assert _PRIVATE_DIR not in text


def test_journey_artifact_center_derives_manifest_from_start_session(monkeypatch: Any) -> None:
    state, _, _ = _render_journey_start()
    create = MagicMock(return_value=_manifest())
    loader = MagicMock(return_value=(_manifest(), None))
    monkeypatch.setattr(artifact_center, "create_manifest", create)
    monkeypatch.setattr(artifact_center, "load_manifest_dict", loader)

    idle_st = FakeSt(state)
    artifact_center._render_artifact_center(idle_st)
    create.assert_not_called()
    loader.assert_not_called()
    idle_text = idle_st.rendered_text()
    assert "Using session source from Start" in idle_text
    assert "sessions" in idle_text
    assert "run-123" in idle_text

    loaded_st = FakeSt(state)
    loaded_st.button_values[artifact_center._LOAD_BTN] = True
    artifact_center._render_artifact_center(loaded_st)
    loader.assert_called_once_with(str(Path(_SESSIONS_ROOT) / _RUN_ID / "artifacts.json"))
    create.assert_not_called()
    loaded_text = loaded_st.rendered_text()
    assert "quality_report.json" in loaded_text
    assert _PRIVATE_DIR not in idle_text + loaded_text


def test_journey_manifest_viewer_derives_manifest_from_start_session(monkeypatch: Any) -> None:
    state, _, _ = _render_journey_start()
    create = MagicMock(return_value=_manifest())
    loader = MagicMock(return_value=(_manifest(), None))
    monkeypatch.setattr(manifest_viewer, "create_manifest", create)
    monkeypatch.setattr(manifest_viewer, "load_manifest_dict", loader)

    st = FakeSt(state)
    st.button_values["Load Manifest"] = True
    manifest_viewer._render_manifest_viewer(st)

    loader.assert_called_once_with(str(Path(_SESSIONS_ROOT) / _RUN_ID / "artifacts.json"))
    create.assert_not_called()
    text = st.rendered_text()
    assert "Using manifest source from Start" in text
    assert "Manifest Summary" in text
    assert "run-123" in text
    assert _PRIVATE_DIR not in text


def test_journey_export_seeds_defaults_and_writes_nothing_without_confirm(
    monkeypatch: Any,
) -> None:
    state, context, _ = _render_journey_start()
    export_write = MagicMock()
    pbi_write = MagicMock()
    monkeypatch.setattr(export, "_export_csv_to_dir", export_write)
    monkeypatch.setattr(export, "generate_package", pbi_write)

    st = FakeSt(state)
    export._render_export(st)

    text = st.rendered_text()
    assert state[EXPORT_CSV_PATH] == context.source_path
    assert state[EXPORT_OUT_DIR] == _EXPORT_DIR
    assert state[PBI_OUT_DIR] == _PBI_DIR
    export_write.assert_not_called()
    pbi_write.assert_not_called()
    assert "Export source values" in text
    assert "Power BI output value" in text
    assert "defaults only" in text
    assert "dist" in text
    assert "powerbi" in text
    assert _PRIVATE_DIR not in text


def test_journey_data_overview_loads_start_dataset_context_path() -> None:
    state, context, _ = _render_journey_start()
    st = FakeSt(state)
    captured: dict[str, str] = {}

    def load(csv_path: str) -> tuple[pd.DataFrame, dict[str, Any], None]:
        captured["csv_path"] = csv_path
        return _assessment_result()

    with patch(
        "data_quality_toolkit.adapters.ui.pages.data_overview._load_df_and_assess",
        side_effect=load,
    ):
        data_overview._render_data_overview(st, state)

    text = st.rendered_text()
    assert captured["csv_path"] == context.source_path
    assert "Using dataset source from Start" in text
    assert "customers.csv" in text
    assert _PRIVATE_DIR not in text
    assert not st.calls_named("text_input")


def test_journey_pipeline_runner_scaffold_uses_start_session_values(monkeypatch: Any) -> None:
    state, _, _ = _render_journey_start()
    st = FakeSt(state)
    st.checkbox_values[PIPE_CONFIRM_EXEC] = True
    st.button_values[PIPE_RUN_BTN] = True
    run_pipeline = MagicMock(return_value=({"status": "success"}, None))
    monkeypatch.setattr(pipeline_runner, "_run_elt_pipeline", run_pipeline)

    pipeline_runner._render_pipeline_runner(st, state)

    run_pipeline.assert_called_once_with(_RUN_ID, _SESSIONS_ROOT)
    text = st.rendered_text()
    assert "Using pipeline session source from Start" in text
    assert _PRIVATE_DIR not in text


def test_journey_full_sequence_never_leaks_private_paths(monkeypatch: Any) -> None:
    state, _, _ = _render_journey_start()

    monkeypatch.setattr(drift_explorer, "load_monitoring_overview", lambda *a, **k: (None, None))
    monkeypatch.setattr(run_history, "_load_run_history", lambda *a: ([], None))
    monkeypatch.setattr(artifact_center, "create_manifest", MagicMock(return_value=_manifest()))
    monkeypatch.setattr(manifest_viewer, "create_manifest", MagicMock(return_value=_manifest()))
    monkeypatch.setattr(
        artifact_center, "load_manifest_dict", MagicMock(return_value=(_manifest(), None))
    )
    monkeypatch.setattr(
        manifest_viewer, "load_manifest_dict", MagicMock(return_value=(_manifest(), None))
    )
    monkeypatch.setattr(export, "_export_csv_to_dir", MagicMock())
    monkeypatch.setattr(export, "generate_package", MagicMock())
    monkeypatch.setattr(pipeline_runner, "_run_elt_pipeline", MagicMock())

    texts: list[str] = []

    overview_st = FakeSt(state)
    with patch(
        "data_quality_toolkit.adapters.ui.pages.data_overview._load_df_and_assess",
        return_value=_assessment_result(),
    ):
        data_overview._render_data_overview(overview_st, state)
    texts.append(overview_st.rendered_text())

    drift_st = FakeSt(state)
    drift_explorer._render_drift_explorer(drift_st)
    texts.append(drift_st.rendered_text())

    history_st = FakeSt(state)
    run_history._render_run_history(history_st)
    texts.append(history_st.rendered_text())

    pipeline_st = FakeSt(state)
    pipeline_runner._render_pipeline_runner(pipeline_st, state)
    texts.append(pipeline_st.rendered_text())

    artifact_st = FakeSt(state)
    artifact_st.button_values[artifact_center._LOAD_BTN] = True
    artifact_center._render_artifact_center(artifact_st)
    texts.append(artifact_st.rendered_text())

    manifest_st = FakeSt(state)
    manifest_st.button_values["Load Manifest"] = True
    manifest_viewer._render_manifest_viewer(manifest_st)
    texts.append(manifest_st.rendered_text())

    export_st = FakeSt(state)
    export._render_export(export_st)
    texts.append(export_st.rendered_text())

    combined = " ".join(texts)
    assert _PRIVATE_DIR not in combined
    for basename in (
        "customers.csv",
        "monitoring.db",
        "dqt.db",
        "sessions",
        "run-123",
        "dist",
        "powerbi",
    ):
        assert basename in combined


def test_start_dataset_id_action_uses_start_specific_key(tmp_path: Any) -> None:
    csv = tmp_path / "customers.csv"
    csv.write_text("id,name\n1,alice\n", encoding="utf-8")
    state: dict[str, Any] = {DATASET_PATH_INPUT: str(csv)}
    st = FakeSt(state)
    st.button_values[DATASET_ACTIVATE_BTN] = True

    start._render_start(st, state)

    button_keys = {kwargs.get("key") for _, kwargs in st.calls_named("button")}
    assert "start_use_current_dataset_id" in button_keys
    assert "qh_use_current_dataset_id" not in button_keys


def test_start_hides_dataset_id_display_without_context_or_value(tmp_path: Any) -> None:
    # No dataset context: neither the action button nor the ID display renders.
    empty_state: dict[str, Any] = {}
    empty_st = FakeSt(empty_state)
    start._render_start(empty_st, empty_state)
    empty_keys = {kwargs.get("key") for _, kwargs in empty_st.calls_named("button")}
    assert "start_use_current_dataset_id" not in empty_keys
    assert not empty_st.calls_named("code")

    # Context loaded but no Dataset ID yet: the action is offered, no ID shown.
    csv = tmp_path / "customers.csv"
    csv.write_text("id,name\n1,alice\n", encoding="utf-8")
    state: dict[str, Any] = {DATASET_PATH_INPUT: str(csv)}
    st = FakeSt(state)
    st.button_values[DATASET_ACTIVATE_BTN] = True
    start._render_start(st, state)
    loaded_keys = {kwargs.get("key") for _, kwargs in st.calls_named("button")}
    assert "start_use_current_dataset_id" in loaded_keys
    assert not st.calls_named("code")
    assert SRC_DATASET_ID not in state


def test_start_click_shows_full_canonical_dataset_id_without_source_path(
    tmp_path: Any,
) -> None:
    from data_quality_toolkit.adapters.loaders.file.csv_loader import dataset_id_from_file

    csv = tmp_path / "customers.csv"
    csv.write_text("id,name\n1,alice\n", encoding="utf-8")
    state: dict[str, Any] = {DATASET_PATH_INPUT: str(csv)}
    st = FakeSt(state)
    st.button_values[DATASET_ACTIVATE_BTN] = True
    st.button_values["start_use_current_dataset_id"] = True

    start._render_start(st, state)

    expected = dataset_id_from_file(csv)
    assert state[SRC_DATASET_ID] == expected
    code_calls = st.calls_named("code")
    assert any(args and args[0] == expected for args, _ in code_calls)
    text = st.rendered_text()
    assert "Current Dataset ID" in text
    assert str(tmp_path) not in text


def test_journey_export_success_prefills_quality_history_inputs(monkeypatch: Any) -> None:
    state, context, _ = _render_journey_start()
    # The operator left the Quality History inputs blank before exporting.
    for key in (SRC_QUALITY_HISTORY_DB, SRC_DATASET_ID):
        state.pop(key, None)

    export_db_path = _PRIVATE_DIR + r"\dist\dqt.db"
    export_result = {
        "run_id": "run-export-1",
        "dataset_id": "sha1:from-export",
        "quality_db_path": export_db_path,
        "quality_db_status": "persisted",
        "quality_db_error": None,
        "export_paths": {"quality_db": export_db_path},
    }
    monkeypatch.setattr(export, "_export_csv_to_dir", MagicMock(return_value=(export_result, None)))
    monkeypatch.setattr(export, "generate_package", MagicMock())

    export_st = FakeSt(state)
    export_st.checkbox_values["I confirm: write export files to the directory above"] = True
    export_st.button_values[EXPORT_RUN_BTN] = True
    export._render_export(export_st)

    assert state[SRC_QUALITY_HISTORY_DB] == export_db_path
    assert state[SRC_DATASET_ID] == "sha1:from-export"

    history_capture: dict[str, str] = {}

    def load_history(db: str, dataset_id: str) -> tuple[list[dict[str, Any]], None]:
        history_capture["db"] = db
        history_capture["dataset_id"] = dataset_id
        return [], None

    monkeypatch.setattr(run_history, "_load_run_history", load_history)
    history_st = FakeSt(state)
    run_history._render_run_history(history_st)

    assert history_capture == {"db": export_db_path, "dataset_id": "sha1:from-export"}
    combined = export_st.rendered_text() + " " + history_st.rendered_text()
    assert _PRIVATE_DIR not in combined


def test_journey_empty_state_pages_stay_inert_and_point_to_start(monkeypatch: Any) -> None:
    # The env default would otherwise seed the monitoring DB and drive the loader.
    monkeypatch.delenv("DQT_UI_DB", raising=False)

    drift_load = MagicMock()
    history_load = MagicMock()
    artifact_create = MagicMock()
    manifest_create = MagicMock()
    export_write = MagicMock()
    pbi_write = MagicMock()
    run_pipeline = MagicMock()
    monkeypatch.setattr(drift_explorer, "load_monitoring_overview", drift_load)
    monkeypatch.setattr(run_history, "_load_run_history", history_load)
    monkeypatch.setattr(artifact_center, "create_manifest", artifact_create)
    monkeypatch.setattr(manifest_viewer, "create_manifest", manifest_create)
    monkeypatch.setattr(export, "_export_csv_to_dir", export_write)
    monkeypatch.setattr(export, "generate_package", pbi_write)
    monkeypatch.setattr(pipeline_runner, "_run_elt_pipeline", run_pipeline)

    drift_st = FakeSt({})
    drift_explorer._render_drift_explorer(drift_st)
    assert "Set Local monitoring database in Start / Load Dataset." in drift_st.rendered_text()

    history_st = FakeSt({})
    run_history._render_run_history(history_st)
    history_text = history_st.rendered_text()
    assert "Set Quality History source values in Start / Load Dataset" in history_text
    assert "Enter a database path and dataset ID" in history_text

    # Sessions Root no longer self-seeds to "." — a new session starts blank, so
    # both session inputs are reported missing until the operator sets them.
    artifact_st = FakeSt({})
    artifact_center._render_artifact_center(artifact_st)
    assert (
        "Set Sessions Root and Session Run ID in Start / Load Dataset: "
        "Sessions Root, Session Run ID." in artifact_st.rendered_text()
    )

    manifest_st = FakeSt({})
    manifest_viewer._render_manifest_viewer(manifest_st)
    assert (
        "Set Sessions Root and Session Run ID in Start / Load Dataset: "
        "Sessions Root, Session Run ID." in manifest_st.rendered_text()
    )

    pipeline_state: dict[str, Any] = {}
    pipeline_st = FakeSt(pipeline_state)
    pipeline_runner._render_pipeline_runner(pipeline_st, pipeline_state)
    assert (
        "Set Sessions Root and Session Run ID in Start / Load Dataset: "
        "Sessions Root, Session Run ID." in pipeline_st.rendered_text()
    )

    export_state: dict[str, Any] = {}
    export_st = FakeSt(export_state)
    export._render_export(export_st)
    export_text = export_st.rendered_text()
    assert "Set Export source defaults in Start / Load Dataset" in export_text
    assert "Set Power BI package output directory in Start / Load Dataset" in export_text
    # Empty Source Hub values must not seed page-local write targets.
    assert EXPORT_CSV_PATH not in export_state

    for loader_or_writer in (
        drift_load,
        history_load,
        artifact_create,
        manifest_create,
        export_write,
        pbi_write,
        run_pipeline,
    ):
        loader_or_writer.assert_not_called()
