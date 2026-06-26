# tests/unit/api/test_drift_xlsx_api.py
"""Unit tests for the export_drift_history_xlsx API seam."""

from __future__ import annotations

import data_quality_toolkit
from data_quality_toolkit import api


def test_seam_present_and_callable() -> None:
    assert callable(api.export_drift_history_xlsx)


def test_seam_reexported_from_top_level() -> None:
    from data_quality_toolkit import export_drift_history_xlsx as _fn

    assert callable(_fn)
    assert "export_drift_history_xlsx" in data_quality_toolkit.__all__


def test_seam_delegates_to_exporter(monkeypatch, tmp_path) -> None:
    """api.export_drift_history_xlsx forwards args/kwargs to the exporter impl."""
    calls: list[tuple[tuple, dict]] = []

    def fake_impl(db_path, output_path, **kwargs):
        calls.append(((db_path, output_path), kwargs))
        return {"output_path": str(output_path), "sheets": [], "row_counts": {}}

    monkeypatch.setattr(
        "data_quality_toolkit.adapters.exporters.bi.xlsx_drift_exporter."
        "export_drift_history_xlsx",
        fake_impl,
    )

    out = tmp_path / "drift.xlsx"
    result = api.export_drift_history_xlsx(
        tmp_path / "m.db",
        out,
        current_dataset_id="cd1",
        limit=3,
        include_columns=False,
        include_distributions=True,
        force=True,
    )
    assert result["output_path"] == str(out)
    (_, _), kwargs = calls[0]
    assert kwargs == {
        "current_dataset_id": "cd1",
        "limit": 3,
        "include_columns": False,
        "include_distributions": True,
        "force": True,
    }
