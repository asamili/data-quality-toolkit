"""Focused tests for the G27I Artifact Center presentation boundary."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import patch

from data_quality_toolkit.adapters.ui.services.artifacts import (
    artifact_rows_from_manifest,
    artifact_rows_from_mapping,
    dataset_rows_from_manifest,
    group_artifact_rows,
    redact_path_to_basename,
)


class FakeSt:
    """Small Streamlit recorder for Artifact Center page tests."""

    def __init__(self) -> None:
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
    st.text_values["Run ID"] = "run-1"
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
        "data_quality_toolkit.adapters.ui.pages.manifest_viewer.create_manifest",
        return_value=manifest,
    ):
        _render_manifest_viewer(st)

    display_text = _all_display_text(st.dataframe_rows())
    rendered = st.rendered_text()

    assert "C:\\Users\\example_user" not in display_text
    assert "raw.csv" in display_text
    assert "artifacts.json" in display_text
    assert "Local/private evidence" in rendered
    assert "public-safe" not in rendered.lower()


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
