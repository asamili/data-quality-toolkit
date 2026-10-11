"""Focused tests for confirmed UI Export manifest emission.

The UI seam opts in to the existing manifest producer (``emit_manifest=True``)
while the public API default and CLI opt-in stay unchanged. Emission is
disclosed before the existing confirmation, happens only inside the confirmed
output directory, and its failure warns without failing the data export.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from data_quality_toolkit.adapters.ui.pages import export
from data_quality_toolkit.adapters.ui.services.artifacts import artifact_rows_from_mapping
from data_quality_toolkit.adapters.ui.services.export import _export_csv_to_dir
from data_quality_toolkit.adapters.ui.state.export_context import get_export_artifact_context
from data_quality_toolkit.adapters.ui.state.keys import (
    EXPORT_CSV_PATH,
    EXPORT_OUT_DIR,
    EXPORT_RUN_BTN,
)
from data_quality_toolkit.shared.settings import settings

_MOCK_EXPORT = "data_quality_toolkit.adapters.ui.pages.export._export_csv_to_dir"
_CONFIRM_LABEL = "I confirm: write export files to the directory above"
_DISCLOSURE_SNIPPET = "A successful export also writes `artifacts.json`"
_FAILURE_SNIPPET = "could not be written for this export"


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


def _confirmed_export_st(out_dir: str = r"C:\Users\example_user\dist") -> FakeSt:
    st = FakeSt({})
    st.text_values[EXPORT_CSV_PATH] = r"C:\Users\example_user\sales.csv"
    st.text_values[EXPORT_OUT_DIR] = out_dir
    st.checkbox_values[_CONFIRM_LABEL] = True
    st.button_values[EXPORT_RUN_BTN] = True
    return st


def _result_with_manifest(out_dir: str) -> dict[str, Any]:
    manifest_path = str(Path(out_dir) / "artifacts.json")
    return {
        "run_id": "run-p1c",
        "dataset_id": "sha1:p1c",
        "ts": "2026-07-12T11:00:00Z",
        "quality_db_status": "persisted",
        "export_paths": {
            "dim_dataset": str(Path(out_dir) / "star" / "dim_dataset.csv"),
            "manifest": manifest_path,
        },
    }


# ── Service seam ─────────────────────────────────────────────────────────────


def test_ui_service_requests_manifest_emission(tmp_path: Path) -> None:
    with patch("data_quality_toolkit.api.export_csv", return_value={"export_paths": {}}) as api:
        result, err = _export_csv_to_dir(str(tmp_path / "in.csv"), str(tmp_path / "out"))

    assert err is None
    assert result == {"export_paths": {}}
    assert api.call_args.kwargs.get("emit_manifest") is True


# ── Disclosure before confirmation ───────────────────────────────────────────


def test_manifest_disclosure_renders_before_confirmation_checkbox() -> None:
    st = FakeSt({})

    with patch(_MOCK_EXPORT) as mock_export:
        export._render_export(st)

    mock_export.assert_not_called()
    disclosure_idx = next(
        i
        for i, (name, args, _) in enumerate(st.calls)
        if name == "caption" and args and _DISCLOSURE_SNIPPET in str(args[0])
    )
    confirm_idx = next(
        i
        for i, (name, args, _) in enumerate(st.calls)
        if name == "checkbox" and args and args[0] == _CONFIRM_LABEL
    )
    assert disclosure_idx < confirm_idx
    text = st.rendered_text()
    assert "inside the confirmed output directory" in text


def test_no_export_action_writes_nothing(tmp_path: Path) -> None:
    st = FakeSt({})
    st.text_values[EXPORT_CSV_PATH] = str(tmp_path / "in.csv")
    st.text_values[EXPORT_OUT_DIR] = str(tmp_path / "out")

    with patch(_MOCK_EXPORT) as mock_export:
        export._render_export(st)

    mock_export.assert_not_called()
    assert not (tmp_path / "out").exists()


# ── End-to-end: confirmed export emits a loadable manifest ──────────────────


def test_confirmed_export_emits_manifest_inside_output_dir(tmp_path: Path) -> None:
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("id,amount\n1,10\n2,20\n", encoding="utf-8")
    out_dir = tmp_path / "dist"

    result, err = _export_csv_to_dir(str(csv_path), str(out_dir))

    assert err is None
    assert result is not None
    manifest_path = Path(result["export_paths"]["manifest"])
    assert manifest_path.name == "artifacts.json"
    assert manifest_path.parent == out_dir.resolve()
    assert manifest_path.is_file()

    # The emitted file loads read-only through the P1B reader and keeps the
    # existing path semantics: artifact paths are relative to the output dir.
    from data_quality_toolkit.lineage.manifest import load_manifest

    mtime_before = manifest_path.stat().st_mtime_ns
    manifest = load_manifest(manifest_path)
    assert manifest.run_id == result["run_id"]
    relative_artifacts = [a.path for a in manifest.artifacts if not Path(a.path).is_absolute()]
    assert relative_artifacts, "expected artifact paths stored relative to the output directory"
    assert all((out_dir / rel).resolve().is_file() for rel in relative_artifacts)
    assert manifest_path.stat().st_mtime_ns == mtime_before


# ── Result plumbing and failure handling ─────────────────────────────────────


def test_manifest_path_flows_only_through_latest_export_context() -> None:
    out_dir = r"C:\Users\example_user\dist"
    st = _confirmed_export_st(out_dir)
    result = _result_with_manifest(out_dir)

    with patch(_MOCK_EXPORT, return_value=(result, None)):
        export._render_export(st)

    context = get_export_artifact_context(st.session_state)
    assert context is not None
    manifest_path = result["export_paths"]["manifest"]
    assert context.export_paths["manifest"] == manifest_path
    # No duplicate manifest-path state key: the only session value carrying the
    # manifest path is the typed context itself.
    holders = [key for key, value in st.session_state.items() if value == manifest_path]
    assert holders == []
    assert _FAILURE_SNIPPET not in st.rendered_text()


def test_manifest_emission_failure_warns_without_failing_export() -> None:
    out_dir = r"C:\Users\example_user\private_p1c\dist"
    st = _confirmed_export_st(out_dir)
    result = _result_with_manifest(out_dir)
    del result["export_paths"]["manifest"]

    with patch(_MOCK_EXPORT, return_value=(result, None)):
        export._render_export(st)

    text = st.rendered_text()
    assert "Export complete" in text
    assert _FAILURE_SNIPPET in text
    assert r"C:\Users\example_user\private_p1c" not in text
    # The export itself still succeeded, so the Latest Export context exists —
    # without any false manifest claim.
    context = get_export_artifact_context(st.session_state)
    assert context is not None
    assert "manifest" not in context.export_paths


# ── R7A3A2: a configured MANIFEST_FILE is the manifest reported and named ─────


def test_confirmed_export_reports_the_configured_manifest_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "manifest_file", "lineage_index.json")
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("id,amount\n1,10\n2,20\n", encoding="utf-8")
    out_dir = tmp_path / "dist"

    result, err = _export_csv_to_dir(str(csv_path), str(out_dir))

    assert err is None
    assert result is not None
    manifest_path = Path(result["export_paths"]["manifest"])
    assert manifest_path.name == "lineage_index.json"
    assert manifest_path.parent == out_dir.resolve()
    assert manifest_path.is_file()
    assert not (out_dir / "artifacts.json").exists()
    rows = artifact_rows_from_mapping(
        result["export_paths"], source="Export page", write_mode="server-side write"
    )
    assert [(row.basename, row.category) for row in rows if row.artifact == "manifest"] == [
        ("lineage_index.json", "lineage/manifest")
    ]


def test_manifest_disclosure_and_failure_name_the_configured_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "manifest_file", "lineage_index.json")
    st = FakeSt({})
    with patch(_MOCK_EXPORT):
        export._render_export(st)
    disclosure = st.rendered_text()
    assert "A successful export also writes `lineage_index.json`" in disclosure
    assert "artifacts.json" not in disclosure

    out_dir = r"C:\Users\example_user\private_r7a3a2\dist"
    failed = _confirmed_export_st(out_dir)
    result = _result_with_manifest(out_dir)
    del result["export_paths"]["manifest"]
    with patch(_MOCK_EXPORT, return_value=(result, None)):
        export._render_export(failed)

    text = failed.rendered_text()
    assert "The lineage manifest (`lineage_index.json`) could not be written" in text
    assert "artifacts.json" not in text
    assert r"C:\Users\example_user\private_r7a3a2" not in text
