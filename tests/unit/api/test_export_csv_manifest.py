from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


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
