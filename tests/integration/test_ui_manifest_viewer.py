import hashlib
import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from data_quality_toolkit.adapters.ui.pages.manifest_viewer import render_manifest_viewer

_HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None


def test_manifest_viewer_import():
    # Verify the function is importable and callable
    assert callable(render_manifest_viewer)


class _FakeSt:
    """Minimal Streamlit recorder for driving both Deliver manifest pages."""

    def __init__(self, session_state: dict[str, Any] | None = None) -> None:
        self.session_state = session_state if session_state is not None else {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.text_values: dict[str, str] = {}
        self.button_values: dict[str, bool] = {}

    def __enter__(self) -> "_FakeSt":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def __getattr__(self, name: str) -> Any:
        def recorder(*args: Any, **kwargs: Any) -> None:
            self._record(name, *args, **kwargs)

        return recorder

    def expander(self, label: str, **kwargs: Any) -> "_FakeSt":
        self._record("expander", label, **kwargs)
        return self

    def text_input(self, label: str, **kwargs: Any) -> str:
        self._record("text_input", label, **kwargs)
        return self.text_values.get(label, "")

    def checkbox(self, label: str, **kwargs: Any) -> bool:
        self._record("checkbox", label, **kwargs)
        return False

    def button(self, label: str, **kwargs: Any) -> bool:
        self._record("button", label, **kwargs)
        key = kwargs.get("key", label)
        return bool(self.button_values.get(key, self.button_values.get(label, False)))

    def dataframe_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for name, args, _ in self.calls:
            if name == "dataframe" and args and isinstance(args[0], list):
                rows.extend(item for item in args[0] if isinstance(item, dict))
        return rows


def test_artifact_center_and_manifest_viewer_share_read_only_contract(tmp_path: Path) -> None:
    """Both Deliver pages parse the same existing manifest fixture identically, read-only."""
    from data_quality_toolkit.adapters.ui.pages import artifact_center, manifest_viewer
    from data_quality_toolkit.lineage.manifest.builder import build_and_write
    from data_quality_toolkit.lineage.manifest.schemas import Artifact, Dataset

    session_dir = tmp_path / "sessions" / "run-shared"
    build_and_write(
        run_id="run-shared",
        session_dir=session_dir,
        datasets=[Dataset(kind="bronze", path="raw/input.csv", rows=1, bytes=4, content_hash="")],
        artifacts=[Artifact(kind="star", path="star/dim_dataset.csv", bytes=4)],
    )
    manifest_path = session_dir / "artifacts.json"
    mtime_before = manifest_path.stat().st_mtime_ns

    def _drive(page_render: Any, button: str) -> set[str]:
        st = _FakeSt()
        st.text_values["Sessions Root"] = str(tmp_path / "sessions")
        st.text_values["Session Run ID"] = "run-shared"
        st.button_values[button] = True
        page_render(st)
        return {
            row["File"]
            for row in st.dataframe_rows()
            if row.get("Write mode") == "manifest evidence" and "File" in row
        }

    artifact_files = _drive(artifact_center._render_artifact_center, "Load existing manifest")
    viewer_files = _drive(manifest_viewer._render_manifest_viewer, "Load Manifest")

    assert artifact_files == viewer_files == {"dim_dataset.csv"}
    # Shared contract is read-only: the fixture file was not rewritten by either page.
    assert manifest_path.stat().st_mtime_ns == mtime_before


def test_manifest_viewer_missing_manifest_is_informational_not_error(tmp_path: Path) -> None:
    """An existing session directory without artifacts.json is a safe empty state."""
    from data_quality_toolkit.adapters.ui.pages import manifest_viewer

    sessions_root = tmp_path / "sessions"
    session_dir = sessions_root / "run-empty"
    session_dir.mkdir(parents=True)

    st = _FakeSt()
    st.text_values["Sessions Root"] = str(sessions_root)
    st.text_values["Session Run ID"] = "run-empty"
    st.button_values["Load Manifest"] = True

    manifest_viewer._render_manifest_viewer(st)

    info_messages = [args[0] for name, args, _ in st.calls if name == "info" and args]
    error_calls = [c for c in st.calls if c[0] == "error"]
    assert any(
        "No existing" in msg and "artifacts.json" in msg for msg in info_messages
    ), "missing manifest should surface guidance via st.info"
    assert not error_calls, "missing manifest must not be treated as an error"
    assert not (session_dir / "artifacts.json").exists()
    assert list(session_dir.iterdir()) == []


def test_manifest_viewer_blank_inputs_show_guidance() -> None:
    from data_quality_toolkit.adapters.ui.pages import manifest_viewer

    st = _FakeSt()
    manifest_viewer._load_existing_manifest(st, "", "")

    error_messages = [args[0] for name, args, _ in st.calls if name == "error" and args]
    assert any("Please enter both" in msg for msg in error_messages)


def test_manifest_viewer_invalid_json_is_bounded_error(tmp_path: Path) -> None:
    from data_quality_toolkit.adapters.ui.pages import manifest_viewer

    sessions_root = tmp_path / "sessions"
    session_dir = sessions_root / "run-bad"
    session_dir.mkdir(parents=True)
    (session_dir / "artifacts.json").write_text("{not valid json", encoding="utf-8")

    st = _FakeSt()
    manifest_viewer._load_existing_manifest(st, str(sessions_root), "run-bad")

    info_calls = [c for c in st.calls if c[0] == "info"]
    error_calls = [c for c in st.calls if c[0] == "error"]
    assert error_calls, "invalid manifest content must remain a bounded error"
    assert not info_calls, "invalid content is not the same as a missing file"


class _ConfirmingFakeSt(_FakeSt):
    """Recorder whose confirmation checkboxes are ticked."""

    def checkbox(self, label: str, **kwargs: Any) -> bool:
        self._record("checkbox", label, **kwargs)
        return True


def test_manifest_viewer_refused_rebuild_keeps_evidence_and_reports_no_success(
    tmp_path: Path,
) -> None:
    """Real producer, no mock: a lineage-less rebuild must not replace recorded evidence."""
    from data_quality_toolkit.adapters.ui.pages import manifest_viewer
    from data_quality_toolkit.lineage.manifest.builder import build_and_write
    from data_quality_toolkit.lineage.manifest.schemas import Artifact, Dataset

    sessions_root = tmp_path / "sessions"
    session_dir = sessions_root / "run-refused"
    build_and_write(
        run_id="run-refused",
        session_dir=session_dir,
        datasets=[Dataset(kind="bronze", path="raw/input.csv", rows=1, bytes=4, content_hash="")],
        artifacts=[Artifact(kind="star", path="star/dim_dataset.csv", bytes=4)],
    )
    manifest_path = session_dir / "artifacts.json"
    before = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    st = _ConfirmingFakeSt()
    st.text_values["Sessions Root"] = str(sessions_root)
    st.text_values["Session Run ID"] = "run-refused"
    st.button_values["Rebuild artifacts.json"] = True
    manifest_viewer._render_manifest_viewer(st)

    error_messages = [args[0] for name, args, _ in st.calls if name == "error" and args]
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == before
    assert not [c for c in st.calls if c[0] == "success"], "a refused rebuild must not succeed"
    assert any("Manifest rebuild refused" in msg for msg in error_messages)
    assert all(str(tmp_path) not in msg for msg in error_messages)


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit [ui] extra not installed")
def test_render_manifest_viewer_smoke():
    # Mock streamlit
    with (
        patch("streamlit.header") as mock_header,
        patch("streamlit.columns") as mock_columns,
        patch("streamlit.text_input"),
        patch("streamlit.button") as mock_button,
    ):
        # Setup mocks
        mock_columns.return_value = (MagicMock(), MagicMock())
        mock_button.return_value = False  # Button not clicked

        # Act
        render_manifest_viewer()

        # Assert
        mock_header.assert_called_with("Lineage Manifest Viewer")
