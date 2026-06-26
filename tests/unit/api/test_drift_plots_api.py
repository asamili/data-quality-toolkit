# tests/unit/api/test_drift_plots_api.py
"""Unit tests for the public ``export_drift_plots`` API seam.

The seam is a thin lazy wrapper over the viz exporter; tests assert the import
seam exists and that it forwards args/kwargs to the exporter impl.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_api_seam_import() -> None:
    from data_quality_toolkit import export_drift_plots as root_seam
    from data_quality_toolkit.api import export_drift_plots as api_seam

    assert callable(root_seam)
    assert callable(api_seam)


def test_api_delegates_to_exporter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from data_quality_toolkit import export_drift_plots

    seen: dict[str, object] = {}

    def fake_impl(db_path, out, **kwargs):
        seen["db_path"] = str(db_path)
        seen["out"] = str(out)
        seen.update(kwargs)
        return {"output_dir": str(out), "charts": {}, "row_counts": {}}

    monkeypatch.setattr(
        "data_quality_toolkit.adapters.exporters.viz.drift_plots.export_drift_plots",
        fake_impl,
    )

    out = tmp_path / "plots"
    result = export_drift_plots(
        tmp_path / "m.db", out, chart="drift-rate", limit=3, current_dataset_id="cd1", force=True
    )
    assert result["output_dir"] == str(out)
    assert seen["out"] == str(out)
    assert seen["chart"] == "drift-rate"
    assert seen["limit"] == 3
    assert seen["current_dataset_id"] == "cd1"
    assert seen["force"] is True
