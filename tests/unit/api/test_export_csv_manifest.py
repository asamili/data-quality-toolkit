from __future__ import annotations

import ast
import inspect
import uuid
from pathlib import Path
from unittest.mock import patch

from data_quality_toolkit import api
from data_quality_toolkit.api import export_csv, export_csv_managed
from data_quality_toolkit.shared.managed_export_source import (
    VerifiedManagedExportSource,
    managed_content_id_from_file,
)


def test_export_csv_emit_manifest_passthrough(tmp_path: Path) -> None:
    """export_csv(emit_manifest=True) passes emit_manifest=True to run_export_star."""
    from data_quality_toolkit.api import export_csv

    mock_return = {
        "run_id": "r1",
        "export_paths": {"manifest": str(tmp_path / "artifacts.json")},
        "profile": {},
        "assessment": {},
    }

    with patch(
        "data_quality_toolkit.application.workflow.pipeline.run_export_star",
        return_value=mock_return,
    ) as mock_fn:
        result = export_csv(tmp_path / "fake.csv", output_dir=str(tmp_path), emit_manifest=True)

    assert result is mock_return
    called_kwargs = mock_fn.call_args.kwargs
    assert called_kwargs.get("emit_manifest") is True


def test_export_csv_emit_manifest_default_false(tmp_path: Path) -> None:
    """export_csv() default does not pass emit_manifest=True."""
    from data_quality_toolkit.api import export_csv

    mock_return = {"run_id": "r1", "export_paths": {}, "profile": {}, "assessment": {}}

    with patch(
        "data_quality_toolkit.application.workflow.pipeline.run_export_star",
        return_value=mock_return,
    ) as mock_fn:
        export_csv(tmp_path / "fake.csv", output_dir=str(tmp_path))

    called_kwargs = mock_fn.call_args.kwargs
    assert called_kwargs.get("emit_manifest", False) is False


def test_export_csv_emit_manifest_with_null_threshold(tmp_path: Path) -> None:
    """emit_manifest passes through both code paths (with and without null_threshold)."""
    from data_quality_toolkit.api import export_csv

    mock_return = {"run_id": "r1", "export_paths": {}, "profile": {}, "assessment": {}}

    with patch(
        "data_quality_toolkit.application.workflow.pipeline.run_export_star",
        return_value=mock_return,
    ) as mock_fn:
        export_csv(
            tmp_path / "fake.csv",
            output_dir=str(tmp_path),
            null_threshold=0.1,
            emit_manifest=True,
        )

    called_kwargs = mock_fn.call_args.kwargs
    assert called_kwargs.get("emit_manifest") is True
    assert called_kwargs.get("null_threshold") == 0.1


# --- managed public-API sibling ---------------------------------------------


def _managed_source(**overrides: object) -> VerifiedManagedExportSource:
    values: dict[str, object] = {
        "version_id": str(uuid.uuid4()),
        "family_id": str(uuid.uuid4()),
        "content_id": "sha256:" + "a" * 64,
        "root_content_id": "sha256:" + "b" * 64,
        "parent_version_id": None,
        "version_label": "cleaned v2",
        "display_name": "customers.csv",
        "relative_posix": "preprocessed/customers.csv",
        "size_bytes": 2048,
        "modified_ns": 10,
        "large_file_mode": False,
        "source_path": "C:\\private\\ws\\preprocessed\\customers.csv",
    }
    values.update(overrides)
    return VerifiedManagedExportSource(**values)  # type: ignore[arg-type]


def test_managed_api_sibling_accepts_exactly_one_provenance_object() -> None:
    signature = inspect.signature(export_csv_managed)
    parameters = list(signature.parameters.values())

    assert [p.name for p in parameters] == ["source", "output_dir"]
    assert parameters[1].kind is inspect.Parameter.KEYWORD_ONLY
    forbidden = {
        "version_id",
        "family_id",
        "content_id",
        "root_content_id",
        "path",
        "df",
        "artifact_meta",
        "trust_root",
    }
    assert forbidden.isdisjoint(set(signature.parameters))


def test_legacy_export_csv_signature_is_unchanged() -> None:
    signature = inspect.signature(export_csv)

    assert list(signature.parameters) == [
        "path",
        "output_dir",
        "null_threshold",
        "sep",
        "encoding",
        "na_values",
        "sample_size",
        "emit_manifest",
        "artifact_meta",
    ]
    # No optional managed argument was added to the legacy public function.
    assert "source" not in signature.parameters
    assert "managed_source" not in signature.parameters


def test_managed_api_delegates_provenance_whole(tmp_path: Path) -> None:
    source = _managed_source()
    mock_return = {"run_id": "r1", "export_paths": {}, "managed_source": {}}

    with patch(
        "data_quality_toolkit.application.workflow.pipeline.run_managed_export_star",
        return_value=mock_return,
    ) as mock_fn:
        result = export_csv_managed(source, output_dir=str(tmp_path))

    assert result is mock_return
    assert mock_fn.call_args.args == (source,)
    assert mock_fn.call_args.kwargs == {"output_dir": str(tmp_path)}


def test_managed_api_defaults_output_dir_without_decomposing(tmp_path: Path) -> None:
    source = _managed_source()

    with patch(
        "data_quality_toolkit.application.workflow.pipeline.run_managed_export_star",
        return_value={},
    ) as mock_fn:
        export_csv_managed(source)

    assert mock_fn.call_args.args == (source,)
    assert "output_dir" in mock_fn.call_args.kwargs


def test_managed_api_returns_managed_export_metadata(tmp_path: Path) -> None:
    # A trust-valid managed source: written at the confined location its
    # ``relative_posix`` claims, carrying its real stat identity and its real
    # canonical content id. The hardened managed export path re-verifies all
    # three immediately before it consumes any bytes.
    directory = tmp_path / "preprocessed"
    directory.mkdir()
    csv = directory / "customers.csv"
    csv.write_text("id,age\n1,30\n2,40\n", encoding="utf-8")
    resolved = csv.resolve()
    st = resolved.stat()
    source = _managed_source(
        source_path=str(resolved),
        content_id=managed_content_id_from_file(resolved),
        size_bytes=int(st.st_size),
        modified_ns=int(st.st_mtime_ns),
    )

    result = export_csv_managed(source, output_dir=str(tmp_path / "out"))

    managed = result["managed_source"]
    assert managed["version_id"] == source.version_id
    assert managed["content_id"] == source.content_id
    assert managed["version_label"] == source.version_label
    assert managed["relative_posix"] == source.relative_posix
    assert "manifest" in result["export_paths"]


def test_api_module_imports_no_ui_layer() -> None:
    tree = ast.parse(inspect.getsource(api))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(m.startswith("data_quality_toolkit.adapters.ui") for m in modules)
    # Provenance comes from the shared kernel, never from a UI trust type.
    assert "data_quality_toolkit.shared.managed_export_source" in modules


def test_managed_provenance_type_is_shared_not_ui() -> None:
    assert VerifiedManagedExportSource.__module__ == (
        "data_quality_toolkit.shared.managed_export_source"
    )
    assert "adapters.ui" not in VerifiedManagedExportSource.__module__
