"""Focused tests for Operate/Deliver Source Hub consumption."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from data_quality_toolkit.adapters.ui.pages import (
    artifact_center,
    drift_explorer,
    export,
    manifest_viewer,
    pipeline_runner,
    run_history,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import (
    DATASET_CONTEXT,
    DRIFT_DATASET_FILTER,
    EXPORT_CSV_PATH,
    EXPORT_OUT_DIR,
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
)


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


def test_drift_monitoring_consumes_monitoring_db_and_keeps_filter_local(
    monkeypatch: Any,
) -> None:
    source_path = r"C:\Users\example_user\private\monitoring.db"
    st = FakeSt({SRC_MONITORING_DB: source_path})
    captured: dict[str, Any] = {}

    def load(db_path: str, **kwargs: Any) -> tuple[None, None]:
        captured["db_path"] = db_path
        captured.update(kwargs)
        return None, None

    monkeypatch.setattr(drift_explorer, "load_monitoring_overview", load)

    drift_explorer._render_drift_explorer(st)

    text = st.rendered_text()
    assert captured["db_path"] == source_path
    assert "Using monitoring source from Start" in text
    assert "monitoring.db" in text
    assert r"C:\Users\example_user\private" not in text
    assert any(
        kwargs.get("key") == DRIFT_DATASET_FILTER for _, kwargs in st.calls_named("text_input")
    )
    assert "distinct from the Source Hub Dataset ID" in text


def test_quality_history_consumes_history_db_and_dataset_id(monkeypatch: Any) -> None:
    db_path = r"C:\Users\example_user\private\dqt.db"
    st = FakeSt({SRC_QUALITY_HISTORY_DB: db_path, SRC_DATASET_ID: "sha1:any-value"})
    captured: dict[str, str] = {}

    def load(db: str, dataset_id: str) -> tuple[list[dict[str, Any]], None]:
        captured["db"] = db
        captured["dataset_id"] = dataset_id
        return [], None

    monkeypatch.setattr(run_history, "_load_run_history", load)

    run_history._render_run_history(st)

    text = st.rendered_text()
    assert captured == {"db": db_path, "dataset_id": "sha1:any-value"}
    assert "Using Quality History sources from Start" in text
    assert "dqt.db" in text
    assert r"C:\Users\example_user\private" not in text


def test_artifact_and_manifest_pages_summarize_session_source() -> None:
    state = {
        SRC_SESSIONS_ROOT: r"C:\Users\example_user\private\sessions",
        SRC_SESSION_RUN_ID: "run-123",
    }

    artifact_st = FakeSt(dict(state))
    artifact_center._render_artifact_center(artifact_st)
    artifact_text = artifact_st.rendered_text()

    manifest_st = FakeSt(dict(state))
    manifest_viewer._render_manifest_viewer(manifest_st)
    manifest_text = manifest_st.rendered_text()

    assert "Using session source from Start" in artifact_text
    assert "Using manifest source from Start" in manifest_text
    assert "sessions" in artifact_text
    assert "run-123" in manifest_text
    assert r"C:\Users\example_user\private" not in artifact_text + manifest_text


def test_pipeline_runner_consumes_session_source_for_gated_scaffold() -> None:
    state = {
        DATASET_CONTEXT: DatasetContext(
            source_path=r"C:\Users\example_user\data\sales.csv",
            display_name="sales.csv",
            size_bytes=4096,
            modified_ns=1,
        ),
        SRC_SESSIONS_ROOT: "sessions",
        SRC_SESSION_RUN_ID: "run-123",
    }
    st = FakeSt(state)
    st.checkbox_values[PIPE_CONFIRM_EXEC] = True
    st.button_values[PIPE_RUN_BTN] = True

    with patch(
        "data_quality_toolkit.adapters.ui.pages.pipeline_runner._run_elt_pipeline",
        return_value=({"status": "success"}, None),
    ) as run_pipeline:
        pipeline_runner._render_pipeline_runner(st, state)

    run_pipeline.assert_called_once_with("run-123", "sessions")
    assert "Using pipeline session source from Start" in st.rendered_text()


def test_export_seeds_page_defaults_from_source_hub() -> None:
    state = {
        DATASET_CONTEXT: DatasetContext(
            source_path=r"C:\Users\example_user\data\sales.csv",
            display_name="sales.csv",
            size_bytes=4096,
            modified_ns=1,
        ),
        SRC_EXPORT_OUT_DIR: r"C:\Users\example_user\private\dist",
        SRC_PBI_OUT_DIR: r"C:\Users\example_user\private\powerbi",
    }
    st = FakeSt(state)

    export._render_export(st)

    text = st.rendered_text()
    assert str(state[EXPORT_CSV_PATH]).endswith(r"data\sales.csv")
    assert str(state[EXPORT_OUT_DIR]).endswith(r"private\dist")
    assert str(state[PBI_OUT_DIR]).endswith(r"private\powerbi")
    assert "Export source values" in text
    assert "Power BI output value" in text
    assert "sales.csv" in text
    assert "dist" in text
    assert "powerbi" in text
    assert "defaults only" in text
    assert r"C:\Users\example_user\private" not in text
