"""Focused tests for the Artifact Center presentation boundary."""

from __future__ import annotations

import hashlib
import sys
from typing import Any
from unittest.mock import patch

import pytest

from data_quality_toolkit.adapters.ui.services.artifacts import (
    artifact_rows_from_manifest,
    artifact_rows_from_mapping,
    dataset_rows_from_manifest,
    group_artifact_rows,
    redact_path_to_basename,
)
from data_quality_toolkit.adapters.ui.state.export_context import ExportArtifactContext
from data_quality_toolkit.adapters.ui.state.keys import (
    EXPORT_ARTIFACT_CONTEXT,
    SRC_EXPORT_RUN_ID,
    SRC_SESSION_RUN_ID,
)
from data_quality_toolkit.shared.settings import settings

_CUSTOM_MANIFEST = "lineage_index.json"


class FakeSt:
    """Small Streamlit recorder for Artifact Center page tests."""

    def __init__(self, session_state: dict[str, Any] | None = None) -> None:
        self.session_state = session_state if session_state is not None else {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.text_values: dict[str, str] = {}
        self.checkbox_values: dict[str, bool] = {}
        self.clicked: set[str] = set()

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def __getattr__(self, name: str) -> Any:
        def recorder(*args: Any, **kwargs: Any) -> None:
            self._record(name, *args, **kwargs)

        return recorder

    def text_input(self, label: str, **kwargs: Any) -> str:
        self._record("text_input", label, **kwargs)
        return self.text_values.get(label, str(kwargs.get("value", "")))

    def checkbox(self, label: str, **kwargs: Any) -> bool:
        self._record("checkbox", label, **kwargs)
        return self.checkbox_values.get(label, False)

    def button(self, label: str, **kwargs: Any) -> bool:
        self._record("button", label, **kwargs)
        return label in self.clicked

    def expander(self, label: str, **kwargs: Any) -> FakeSt:
        self._record("expander", label, **kwargs)
        return self

    def dataframe_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for name, args, _kwargs in self.calls:
            if name == "dataframe" and args and isinstance(args[0], list):
                rows.extend(item for item in args[0] if isinstance(item, dict))
        return rows

    def rendered_text(self) -> str:
        return " ".join(
            str(value) for _, args, _ in self.calls for value in args if isinstance(value, str)
        )


def _all_display_text(rows: list[dict[str, str]]) -> str:
    return " ".join(str(value) for row in rows for value in row.values())


def test_redact_path_to_basename_strips_windows_and_posix_paths() -> None:
    assert redact_path_to_basename("C:\\Users\\example_user\\dist\\quality_report.json") == (
        "quality_report.json"
    )
    assert redact_path_to_basename("/home/example_user/dist/star/fact_issues.csv") == (
        "fact_issues.csv"
    )
    assert redact_path_to_basename("relative/report.md") == "report.md"


def test_artifact_rows_from_mapping_are_path_free_and_conservative() -> None:
    rows = artifact_rows_from_mapping(
        {
            "dim_dataset": "C:\\Users\\example_user\\dist\\star\\dim_dataset.csv",
            "quality_report": "/home/example_user/dist/star/quality_report.json",
            "dashboard": "/home/example_user/dist/dashboard.html",
            "plot": "/home/example_user/dist/plots/drift_rate.png",
            "manifest": "/home/example_user/dist/artifacts.json",
        },
        source="Export page",
        write_mode="server-side write",
    )

    display = [row.to_display_dict() for row in rows]
    text = _all_display_text(display)

    assert "C:\\Users\\example_user" not in text
    assert "/home/example_user" not in text
    assert "dim_dataset.csv" in text
    assert "quality_report.json" in text
    assert "review before sharing" in text
    assert "public-safe" not in text.lower()


def test_artifact_grouping_and_order_are_deterministic() -> None:
    rows = artifact_rows_from_mapping(
        {
            "z_other": "notes.bin",
            "plot": "psi_by_column.png",
            "quality_report": "quality_report.json",
            "dim_column": "dim_column.csv",
            "manifest": "artifacts.json",
        },
        source="test",
        write_mode="server-side write",
    )

    groups = [
        (category, [row.basename for row in items]) for category, items in group_artifact_rows(rows)
    ]

    assert groups == [
        ("data export", ["dim_column.csv"]),
        ("quality report", ["quality_report.json"]),
        ("visual evidence", ["psi_by_column.png"]),
        ("lineage/manifest", ["artifacts.json"]),
        ("other", ["notes.bin"]),
    ]


def test_default_manifest_file_is_recognised_by_basename() -> None:
    rows = artifact_rows_from_mapping(
        {"lineage_file": "/home/example_user/dist/artifacts.json"},
        source="test",
        write_mode="server-side write",
    )

    assert [(row.basename, row.category) for row in rows] == [
        ("artifacts.json", "lineage/manifest")
    ]


def test_configured_manifest_file_is_recognised_instead_of_the_literal_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "manifest_file", _CUSTOM_MANIFEST)

    rows = artifact_rows_from_mapping(
        {
            "lineage_file": f"/home/example_user/dist/{_CUSTOM_MANIFEST}",
            "stale_copy": "/home/example_user/dist/artifacts.json",
        },
        source="test",
        write_mode="server-side write",
    )

    assert {row.basename: row.category for row in rows} == {
        _CUSTOM_MANIFEST: "lineage/manifest",
        "artifacts.json": "other",
    }
    assert "/home/example_user" not in _all_display_text([row.to_display_dict() for row in rows])


def test_empty_artifacts_produce_safe_empty_rows() -> None:
    assert (
        artifact_rows_from_mapping({}, source="Export page", write_mode="server-side write") == []
    )
    assert artifact_rows_from_manifest({"artifacts": []}) == []


def test_browser_download_status_is_explicit() -> None:
    rows = artifact_rows_from_mapping(
        {"column_analysis": "column_analysis.csv"},
        source="Data Overview",
        write_mode="browser download",
    )
    assert rows[0].status == "browser download - review before sharing"


def test_manifest_projection_hides_paths_and_marks_private_evidence() -> None:
    manifest = {
        "datasets": [
            {"kind": "bronze", "path": "C:\\Users\\example_user\\sessions\\run-1\\raw.csv"}
        ],
        "artifacts": [
            {
                "kind": "report",
                "path": "/home/example_user/sessions/run-1/reports/quality_report.json",
            }
        ],
    }

    artifact_text = _all_display_text(
        [row.to_display_dict() for row in artifact_rows_from_manifest(manifest)]
    )
    dataset_text = _all_display_text(dataset_rows_from_manifest(manifest))

    assert "C:\\Users\\example_user" not in dataset_text
    assert "/home/example_user" not in artifact_text
    assert "raw.csv" in dataset_text
    assert "quality_report.json" in artifact_text
    assert "private evidence / local-only" in artifact_text
    assert "public-safe" not in (artifact_text + dataset_text).lower()


def test_export_success_uses_safe_artifact_center_display() -> None:
    from data_quality_toolkit.adapters.ui.pages.export import _render_export

    st = FakeSt()
    st.text_values["CSV file path to export"] = "C:\\Users\\example_user\\data\\input.csv"
    st.text_values["Output directory (absolute path)"] = "C:\\Users\\example_user\\dist"
    st.checkbox_values["I confirm: write export files to the directory above"] = True
    st.clicked.add("Run export and write to directory")
    fake_result = {
        "export_paths": {
            "dim_dataset": "C:\\Users\\example_user\\dist\\star\\dim_dataset.csv",
            "quality_report": "C:\\Users\\example_user\\dist\\star\\quality_report.json",
        }
    }

    with patch(
        "data_quality_toolkit.adapters.ui.pages.export._export_csv_to_dir",
        return_value=(fake_result, None),
    ):
        _render_export(st)

    rendered = st.rendered_text()
    display_rows = st.dataframe_rows()
    display_text = _all_display_text(display_rows)

    assert "written to `dist`" in rendered
    assert "C:\\Users\\example_user\\dist" not in rendered
    assert "C:\\Users\\example_user" not in display_text
    assert "dim_dataset.csv" in display_text
    assert "quality_report.json" in display_text
    assert "review before sharing" in display_text


def test_export_write_confirmation_still_required() -> None:
    from data_quality_toolkit.adapters.ui.pages.export import _render_export

    st = FakeSt()
    st.text_values["CSV file path to export"] = "C:\\Users\\example_user\\data\\input.csv"
    st.text_values["Output directory (absolute path)"] = "C:\\Users\\example_user\\dist"
    st.clicked.add("Run export and write to directory")

    with patch("data_quality_toolkit.adapters.ui.pages.export._export_csv_to_dir") as mock_export:
        _render_export(st)

    mock_export.assert_not_called()
    assert "Check the confirmation box" in st.rendered_text()


def test_manifest_viewer_safe_projection_and_raw_warning() -> None:
    from data_quality_toolkit.adapters.ui.pages.manifest_viewer import _render_manifest_viewer

    st = FakeSt()
    st.text_values["Session Run ID"] = "run-1"
    st.text_values["Sessions Root"] = "."
    st.clicked.add("Load Manifest")
    manifest = {
        "summary": {"rows_in": 10},
        "datasets": [
            {"kind": "bronze", "path": "C:\\Users\\example_user\\sessions\\run-1\\raw.csv"}
        ],
        "artifacts": [
            {"kind": "manifest", "path": "C:\\Users\\example_user\\sessions\\run-1\\artifacts.json"}
        ],
        "gates": {"failures": []},
    }

    with patch(
        "data_quality_toolkit.adapters.ui.pages.manifest_viewer.load_manifest_dict",
        return_value=(manifest, None),
    ):
        _render_manifest_viewer(st)

    display_text = _all_display_text(st.dataframe_rows())
    rendered = st.rendered_text()

    assert "C:\\Users\\example_user" not in display_text
    assert "raw.csv" in display_text
    assert "artifacts.json" in display_text
    assert "Local/private evidence" in rendered
    assert "public-safe" not in rendered.lower()


def _latest_export_context(**overrides: Any) -> ExportArtifactContext:
    values: dict[str, Any] = {
        "export_paths": {
            "dim_dataset": "C:\\Users\\example_user\\dist\\star\\dim_dataset.csv",
            "quality_report": "C:\\Users\\example_user\\dist\\star\\quality_report.json",
        },
        "output_dir": "C:\\Users\\example_user\\dist",
        "run_id": "run-le-1",
        "dataset_id": "sha1:le",
        "exported_at": "2026-07-12T10:00:00Z",
        "quality_db_status": "persisted",
    }
    values.update(overrides)
    return ExportArtifactContext(**values)


def test_latest_export_renders_without_manual_session_inputs() -> None:
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center

    st = FakeSt({EXPORT_ARTIFACT_CONTEXT: _latest_export_context()})

    _render_artifact_center(st)

    rendered = st.rendered_text()
    display_text = _all_display_text(st.dataframe_rows())
    assert "Latest Export artifacts" in rendered
    assert "run-le-1" in rendered
    assert "sha1:le" in rendered
    assert "`dist`" in rendered
    assert "C:\\Users\\example_user" not in rendered
    assert "C:\\Users\\example_user" not in display_text
    assert "dim_dataset.csv" in display_text
    assert "quality_report.json" in display_text
    # Session-manifest mode remains available separately.
    assert "Load artifacts from a lineage manifest" in rendered


def test_latest_export_without_active_dataset_says_so() -> None:
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center

    st = FakeSt({EXPORT_ARTIFACT_CONTEXT: _latest_export_context()})

    _render_artifact_center(st)

    assert "Source match: No active dataset for comparison" in st.rendered_text()


def test_latest_export_older_context_reports_match_unavailable() -> None:
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center
    from data_quality_toolkit.adapters.ui.state.context import DatasetContext
    from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT

    active = DatasetContext(
        source_path="C:\\Users\\example_user\\data\\input.csv",
        display_name="input.csv",
        size_bytes=1,
        modified_ns=1,
    )
    # A context stored before source linkage existed carries no source_status.
    st = FakeSt({DATASET_CONTEXT: active, EXPORT_ARTIFACT_CONTEXT: _latest_export_context()})

    _render_artifact_center(st)

    assert "Source match: Source match unavailable for this older export" in st.rendered_text()


def test_latest_export_matching_active_dataset_is_marked_as_a_match() -> None:
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center
    from data_quality_toolkit.adapters.ui.services.export_alignment import (
        ExportSourceStatus,
        normalize_source_binding,
    )
    from data_quality_toolkit.adapters.ui.state.context import DatasetContext
    from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT

    source = "C:\\Users\\example_user\\data\\input.csv"
    active = DatasetContext(
        source_path=source, display_name="input.csv", size_bytes=1, modified_ns=1
    )
    context = _latest_export_context(
        source_status=ExportSourceStatus.ACTIVE_LEGACY.value,
        source_display_name="input.csv",
        source_binding=normalize_source_binding(source),
    )
    st = FakeSt({DATASET_CONTEXT: active, EXPORT_ARTIFACT_CONTEXT: context})

    _render_artifact_center(st)

    assert "Source match: Matches active dataset" in st.rendered_text()


def test_latest_export_from_another_dataset_is_preserved_and_marked_mismatching() -> None:
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center
    from data_quality_toolkit.adapters.ui.services.export_alignment import (
        ExportSourceStatus,
        normalize_source_binding,
    )
    from data_quality_toolkit.adapters.ui.state.context import DatasetContext
    from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT

    exported_source = "C:\\Users\\example_user\\data\\exported.csv"
    active = DatasetContext(
        source_path="C:\\Users\\example_user\\data\\now_active.csv",
        display_name="now_active.csv",
        size_bytes=1,
        modified_ns=1,
    )
    context = _latest_export_context(
        source_status=ExportSourceStatus.ACTIVE_LEGACY.value,
        source_display_name="exported.csv",
        source_binding=normalize_source_binding(exported_source),
    )
    state: dict[str, Any] = {DATASET_CONTEXT: active, EXPORT_ARTIFACT_CONTEXT: context}
    st = FakeSt(state)

    _render_artifact_center(st)

    rendered = st.rendered_text()
    assert "Source match: Exported from another dataset" in rendered
    # The mismatching export is labelled, never cleared or relabelled as active.
    assert state[EXPORT_ARTIFACT_CONTEXT] is context
    assert "Latest Export artifacts" in rendered
    assert "run-le-1" in rendered


def test_latest_export_match_status_leaks_no_path_or_technical_identity() -> None:
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center
    from data_quality_toolkit.adapters.ui.services.export_alignment import (
        ExportSourceStatus,
        normalize_source_binding,
    )
    from data_quality_toolkit.adapters.ui.state.context import DatasetContext
    from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT

    version_id = "3f1c9a2e-5b6d-4e7f-8a9b-0c1d2e3f4a5b"
    content_id = "sha256:" + "a" * 64
    source = "C:\\Users\\example_user\\private\\managed.csv"
    active = DatasetContext(
        source_path=source,
        display_name="managed.csv",
        size_bytes=1,
        modified_ns=1,
        managed=True,
        version_id=version_id,
        family_id="8b7a6c5d-4e3f-4a2b-9c8d-7e6f5a4b3c2d",
        content_id=content_id,
        root_content_id="sha256:" + "c" * 64,
        version_label="cleaned v2",
    )
    context = _latest_export_context(
        source_status=ExportSourceStatus.ACTIVE_MANAGED.value,
        source_display_name="managed.csv",
        source_binding=normalize_source_binding(source),
        source_version_id=version_id,
        source_family_id="8b7a6c5d-4e3f-4a2b-9c8d-7e6f5a4b3c2d",
        source_content_id=content_id,
    )
    st = FakeSt({DATASET_CONTEXT: active, EXPORT_ARTIFACT_CONTEXT: context})

    _render_artifact_center(st)

    rendered = st.rendered_text()
    assert "Source match: Matches active dataset" in rendered
    # Neither the internal binding nor any lifecycle identity reaches the page.
    assert "C:\\Users\\example_user" not in rendered
    assert normalize_source_binding(source) not in rendered
    assert version_id not in rendered
    assert content_id not in rendered
    assert "sha256" not in rendered


def test_latest_export_absent_context_shows_guidance_only() -> None:
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center

    st = FakeSt({})

    _render_artifact_center(st)

    rendered = st.rendered_text()
    assert "No successful Export in this session yet" in rendered
    assert "Latest Export artifacts" not in rendered


def test_latest_export_never_uses_session_run_id_as_directory(tmp_path: Any) -> None:
    from data_quality_toolkit.adapters.ui.pages import artifact_center

    bogus_dir = tmp_path / "bogus-run-dir"
    st = FakeSt(
        {
            SRC_SESSION_RUN_ID: str(bogus_dir),
            EXPORT_ARTIFACT_CONTEXT: _latest_export_context(),
        }
    )

    with patch.object(artifact_center, "create_manifest") as mock_manifest:
        artifact_center._render_artifact_center(st)

    mock_manifest.assert_not_called()
    assert not bogus_dir.exists()


def test_session_lookup_never_uses_the_export_run_id_as_a_folder(tmp_path: Any) -> None:
    """An export-run ID in shared state must not become a session directory."""
    from data_quality_toolkit.adapters.ui.pages import artifact_center

    bogus_dir = tmp_path / "export-run-not-a-folder"
    st = FakeSt({SRC_EXPORT_RUN_ID: str(bogus_dir)})
    st.clicked.add("Load existing manifest")

    with patch.object(artifact_center, "load_manifest_dict") as loader:
        artifact_center._render_artifact_center(st)

    # Session lookup reads the Session Run ID input only; the export-run ID is
    # never consulted, so the lookup is blank and refuses rather than resolving.
    loader.assert_not_called()
    assert "Please enter both Session Run ID and Sessions Root." in st.rendered_text()
    assert not bogus_dir.exists()


def test_latest_export_rendering_creates_no_files_or_directories(tmp_path: Any) -> None:
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center

    missing_out = tmp_path / "never_created"
    context = _latest_export_context(
        export_paths={"quality_report": str(missing_out / "star" / "quality_report.json")},
        output_dir=str(missing_out),
    )
    st = FakeSt({EXPORT_ARTIFACT_CONTEXT: context})

    _render_artifact_center(st)

    assert not missing_out.exists()
    assert list(tmp_path.iterdir()) == []
    assert "file not available locally" in st.rendered_text()


# ── P1B: read-only manifest loading, explicit rebuild, path resolution ───────


def _write_session_manifest(session_dir: Any) -> Any:
    """Write a real manifest fixture via the existing producer; returns its path."""
    from data_quality_toolkit.lineage.manifest.builder import build_and_write
    from data_quality_toolkit.lineage.manifest.schemas import Artifact, Dataset

    build_and_write(
        run_id="run-p1b",
        session_dir=session_dir,
        datasets=[Dataset(kind="bronze", path="raw/input.csv", rows=2, bytes=8, content_hash="")],
        artifacts=[
            Artifact(kind="star", path="star/dim_dataset.csv", bytes=5),
            Artifact(kind="report", path="../outside/quality_report.json", bytes=5),
            Artifact(kind="report", path="star/missing_report.json", bytes=0),
        ],
    )
    return session_dir / "artifacts.json"


def _session_inputs_st(sessions_root: str, run_id: str) -> FakeSt:
    st = FakeSt({})
    st.text_values["Sessions Root"] = sessions_root
    st.text_values["Session Run ID"] = run_id
    return st


def test_load_existing_manifest_is_read_only(tmp_path: Any) -> None:
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center

    session_dir = tmp_path / "sessions" / "run-p1b"
    manifest_path = _write_session_manifest(session_dir)
    (session_dir / "star").mkdir()
    (session_dir / "star" / "dim_dataset.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    mtime_before = manifest_path.stat().st_mtime_ns

    st = _session_inputs_st(str(tmp_path / "sessions"), "run-p1b")
    st.clicked.add("Load existing manifest")
    _render_artifact_center(st)

    display_text = _all_display_text(st.dataframe_rows())
    rendered = st.rendered_text()
    assert "dim_dataset.csv" in display_text
    assert "Artifact Center (Safe View)" in rendered
    assert manifest_path.stat().st_mtime_ns == mtime_before
    assert str(tmp_path) not in rendered
    assert str(tmp_path) not in display_text


def test_missing_manifest_shows_guidance_and_creates_nothing(tmp_path: Any) -> None:
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center

    sessions_root = tmp_path / "sessions"
    st = _session_inputs_st(str(sessions_root), "run-nonexistent")
    st.clicked.add("Load existing manifest")

    _render_artifact_center(st)

    rendered = st.rendered_text()
    assert "No existing `artifacts.json` was found for this session" in rendered
    assert "Nothing was created" in rendered
    assert not sessions_root.exists()
    assert list(tmp_path.iterdir()) == []


def test_blank_session_inputs_prevent_loading() -> None:
    from data_quality_toolkit.adapters.ui.pages import artifact_center

    st = _session_inputs_st("", "")
    st.clicked.add("Load existing manifest")

    with patch.object(artifact_center, "load_manifest_dict") as loader:
        artifact_center._render_artifact_center(st)

    loader.assert_not_called()
    assert "Please enter both Session Run ID and Sessions Root." in st.rendered_text()


def test_rebuild_requires_confirmation(tmp_path: Any) -> None:
    from data_quality_toolkit.adapters.ui.pages import artifact_center

    session_dir = tmp_path / "sessions" / "run-p1b"
    session_dir.mkdir(parents=True)
    st = _session_inputs_st(str(tmp_path / "sessions"), "run-p1b")
    st.clicked.add("Rebuild artifacts.json")

    with patch.object(artifact_center, "create_manifest") as producer:
        artifact_center._render_artifact_center(st)

    producer.assert_not_called()
    assert "Check the rebuild confirmation box" in st.rendered_text()


def test_rebuild_refused_for_nonexistent_session_directory(tmp_path: Any) -> None:
    from data_quality_toolkit.adapters.ui.pages import artifact_center

    st = _session_inputs_st(str(tmp_path / "sessions"), "run-nonexistent")
    st.checkbox_values[
        "I confirm: scan the existing session directory and write artifacts.json"
    ] = True
    st.clicked.add("Rebuild artifacts.json")

    with patch.object(artifact_center, "create_manifest") as producer:
        artifact_center._render_artifact_center(st)

    producer.assert_not_called()
    assert "Session directory not found under Sessions Root" in st.rendered_text()
    assert not (tmp_path / "sessions").exists()


def test_confirmed_rebuild_calls_producer_and_loads_read_only(tmp_path: Any) -> None:
    from data_quality_toolkit.adapters.ui.pages import artifact_center

    sessions_root = tmp_path / "sessions"
    session_dir = sessions_root / "run-p1b"
    session_dir.mkdir(parents=True)
    (session_dir / "keep.txt").write_text("keep", encoding="utf-8")

    def _fake_producer(run_id: str, root: str) -> dict[str, Any]:
        _write_session_manifest(session_dir)
        return {}

    st = _session_inputs_st(str(sessions_root), "run-p1b")
    st.checkbox_values[
        "I confirm: scan the existing session directory and write artifacts.json"
    ] = True
    st.clicked.add("Rebuild artifacts.json")

    with patch.object(artifact_center, "create_manifest", side_effect=_fake_producer) as producer:
        artifact_center._render_artifact_center(st)

    producer.assert_called_once_with("run-p1b", str(sessions_root))
    # Only artifacts.json was written into the selected existing session.
    assert sorted(p.name for p in session_dir.iterdir()) == ["artifacts.json", "keep.txt"]
    display_text = _all_display_text(st.dataframe_rows())
    assert "dim_dataset.csv" in display_text
    assert "artifacts.json was rebuilt" in st.rendered_text()


def test_refused_rebuild_keeps_populated_manifest_and_reports_no_success(tmp_path: Any) -> None:
    """Real producer, no mock: a lineage-less rebuild must not replace recorded evidence."""
    from data_quality_toolkit.adapters.ui.pages import artifact_center

    sessions_root = tmp_path / "sessions"
    manifest_path = _write_session_manifest(sessions_root / "run-p1b")
    before = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    st = _session_inputs_st(str(sessions_root), "run-p1b")
    st.checkbox_values[
        "I confirm: scan the existing session directory and write artifacts.json"
    ] = True
    st.clicked.add("Rebuild artifacts.json")
    artifact_center._render_artifact_center(st)

    rendered = st.rendered_text()
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == before
    assert "artifacts.json was rebuilt" not in rendered
    assert not [call for call in st.calls if call[0] == "success"]
    assert "Manifest rebuild failed: Manifest rebuild refused" in rendered
    assert "left unchanged" in rendered
    assert str(tmp_path) not in rendered


def test_manifest_relative_paths_resolve_against_manifest_directory(tmp_path: Any) -> None:
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center

    session_dir = tmp_path / "sessions" / "run-p1b"
    _write_session_manifest(session_dir)
    (session_dir / "star").mkdir()
    (session_dir / "star" / "dim_dataset.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    st = _session_inputs_st(str(tmp_path / "sessions"), "run-p1b")
    st.clicked.add("Load existing manifest")
    _render_artifact_center(st)

    rendered = st.rendered_text()
    # The file exists relative to the manifest directory (not the CWD), so its
    # preview reports available local evidence rather than a missing file.
    assert "local evidence" in rendered
    downloads = [args for name, args, _ in st.calls if name == "download_button"]
    assert any("dim_dataset.csv" in str(args[0]) for args in downloads)
    assert str(tmp_path) not in rendered


def test_path_traversal_outside_manifest_directory_is_unavailable(tmp_path: Any) -> None:
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center

    session_dir = tmp_path / "sessions" / "run-p1b"
    _write_session_manifest(session_dir)
    outside = tmp_path / "sessions" / "outside"
    outside.mkdir()
    (outside / "quality_report.json").write_text("{}", encoding="utf-8")

    st = _session_inputs_st(str(tmp_path / "sessions"), "run-p1b")
    st.clicked.add("Load existing manifest")
    _render_artifact_center(st)

    rendered = st.rendered_text()
    assert "outside the manifest directory" in rendered
    # The traversal target is never read for preview/download.
    downloads = [args for name, args, _ in st.calls if name == "download_button"]
    assert not any("quality_report.json" in str(args[0]) for args in downloads)


def test_missing_manifest_artifact_stays_visible_as_missing(tmp_path: Any) -> None:
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center

    session_dir = tmp_path / "sessions" / "run-p1b"
    _write_session_manifest(session_dir)

    st = _session_inputs_st(str(tmp_path / "sessions"), "run-p1b")
    st.clicked.add("Load existing manifest")
    _render_artifact_center(st)

    display_text = _all_display_text(st.dataframe_rows())
    rendered = st.rendered_text()
    assert "missing_report.json" in display_text
    assert "file not available locally" in rendered


def test_session_manifest_seam_helpers(tmp_path: Any) -> None:
    from pathlib import Path

    from data_quality_toolkit.adapters.ui.services.artifacts import (
        load_manifest_dict,
        resolve_manifest_artifact_path,
        session_directory_exists,
        session_manifest_path,
    )

    assert session_manifest_path("", "run") is None
    assert session_manifest_path("root", " ") is None
    assert session_manifest_path("root", "run") == str(Path("root") / "run" / "artifacts.json")
    assert session_directory_exists(str(tmp_path), "nope") is False

    missing, err = load_manifest_dict(tmp_path / "artifacts.json")
    assert missing is None and err is None

    corrupt = tmp_path / "artifacts.json"
    corrupt.write_text("{broken", encoding="utf-8")
    manifest, err = load_manifest_dict(corrupt)
    assert manifest is None
    assert err is not None
    assert str(tmp_path) not in err

    manifest_path = tmp_path / "run" / "artifacts.json"
    absolute = str(tmp_path / "abs.csv")
    assert resolve_manifest_artifact_path(manifest_path, absolute) == absolute
    assert resolve_manifest_artifact_path(manifest_path, "") is None
    assert resolve_manifest_artifact_path(manifest_path, "../escape.csv") is None
    resolved = resolve_manifest_artifact_path(manifest_path, "star/x.csv")
    assert resolved == str((tmp_path / "run" / "star" / "x.csv").resolve())


# ── R7A3A2: the configured MANIFEST_FILE is the manifest the UI names and reads ──


def test_artifact_center_loads_the_configured_manifest_file(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center

    monkeypatch.setattr(settings, "manifest_file", _CUSTOM_MANIFEST)
    session_dir = tmp_path / "sessions" / "run-custom"
    _write_session_manifest(session_dir)
    assert sorted(p.name for p in session_dir.iterdir()) == [_CUSTOM_MANIFEST]

    st = _session_inputs_st(str(tmp_path / "sessions"), "run-custom")
    st.clicked.add("Load existing manifest")
    _render_artifact_center(st)

    rendered = st.rendered_text()
    assert "dim_dataset.csv" in _all_display_text(st.dataframe_rows())
    assert "No existing" not in rendered
    assert f"Rebuild {_CUSTOM_MANIFEST}" in rendered
    assert "artifacts.json" not in rendered
    assert str(tmp_path) not in rendered


def test_artifact_center_missing_and_rebuilt_manifest_use_the_configured_name(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real producer, no mock: first creation writes the configured file only."""
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center

    monkeypatch.setattr(settings, "manifest_file", _CUSTOM_MANIFEST)
    sessions_root = tmp_path / "sessions"
    session_dir = sessions_root / "run-new"
    session_dir.mkdir(parents=True)

    missing = _session_inputs_st(str(sessions_root), "run-new")
    missing.clicked.add("Load existing manifest")
    _render_artifact_center(missing)
    assert f"No existing `{_CUSTOM_MANIFEST}` was found" in missing.rendered_text()
    assert list(session_dir.iterdir()) == []

    st = _session_inputs_st(str(sessions_root), "run-new")
    st.checkbox_values[
        f"I confirm: scan the existing session directory and write {_CUSTOM_MANIFEST}"
    ] = True
    st.clicked.add(f"Rebuild {_CUSTOM_MANIFEST}")
    _render_artifact_center(st)

    rendered = st.rendered_text()
    assert (session_dir / _CUSTOM_MANIFEST).is_file()
    assert not (session_dir / "artifacts.json").exists()
    assert f"{_CUSTOM_MANIFEST} was rebuilt for this session." in rendered
    assert "artifacts.json" not in rendered
    assert str(tmp_path) not in rendered


def test_latest_export_shows_the_reported_configured_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from data_quality_toolkit.adapters.ui.pages.artifact_center import _render_artifact_center

    monkeypatch.setattr(settings, "manifest_file", _CUSTOM_MANIFEST)
    context = _latest_export_context(
        export_paths={
            "dim_dataset": "C:\\Users\\example_user\\dist\\star\\dim_dataset.csv",
            "manifest": f"C:\\Users\\example_user\\dist\\{_CUSTOM_MANIFEST}",
        }
    )
    st = FakeSt({EXPORT_ARTIFACT_CONTEXT: context})

    _render_artifact_center(st)

    manifest_rows = [row for row in st.dataframe_rows() if row.get("Artifact") == "manifest"]
    assert [(row["File"], row["Category"]) for row in manifest_rows] == [
        (_CUSTOM_MANIFEST, "lineage/manifest")
    ]
    assert "C:\\Users\\example_user" not in _all_display_text(st.dataframe_rows())


def test_manifest_viewer_names_and_loads_the_configured_manifest_file(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from data_quality_toolkit.adapters.ui.pages.manifest_viewer import _render_manifest_viewer

    monkeypatch.setattr(settings, "manifest_file", _CUSTOM_MANIFEST)
    _write_session_manifest(tmp_path / "sessions" / "run-custom")

    st = _session_inputs_st(str(tmp_path / "sessions"), "run-custom")
    st.clicked.add("Load Manifest")
    _render_manifest_viewer(st)

    rendered = st.rendered_text()
    assert "dim_dataset.csv" in _all_display_text(st.dataframe_rows())
    assert f"existing `{_CUSTOM_MANIFEST}`" in rendered
    assert f"Rebuild {_CUSTOM_MANIFEST}" in rendered
    assert "No existing" not in rendered
    assert "artifacts.json" not in rendered
    assert str(tmp_path) not in rendered


def test_artifact_ui_imports_do_not_load_optional_ai() -> None:
    import data_quality_toolkit.adapters.ui.components.artifacts  # noqa: F401
    import data_quality_toolkit.adapters.ui.pages.export  # noqa: F401
    import data_quality_toolkit.adapters.ui.pages.manifest_viewer  # noqa: F401
    import data_quality_toolkit.adapters.ui.services.artifacts  # noqa: F401

    loaded = set(sys.modules)
    for module in {
        "torch",
        "transformers",
        "tokenizers",
        "safetensors",
        "sentence_transformers",
        "huggingface_hub",
    }:
        assert module not in loaded
