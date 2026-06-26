# tests/unit/api/test_duckdb_export_api.py
"""Unit tests for the export_monitoring_duckdb API seam."""

from __future__ import annotations

import data_quality_toolkit
from data_quality_toolkit import api


def test_seam_present_and_callable() -> None:
    assert callable(api.export_monitoring_duckdb)


def test_seam_reexported_from_top_level() -> None:
    from data_quality_toolkit import export_monitoring_duckdb as _fn

    assert callable(_fn)
    assert "export_monitoring_duckdb" in data_quality_toolkit.__all__


def test_seam_delegates_to_exporter(monkeypatch, tmp_path) -> None:
    """api.export_monitoring_duckdb forwards args/kwargs to the exporter impl."""
    calls: list[tuple[tuple, dict]] = []

    def fake_impl(db_path, out_path, **kwargs):
        calls.append(((db_path, out_path), kwargs))
        return {
            "input_db_path": str(db_path),
            "output_path": str(out_path),
            "tables": [],
            "row_counts": {},
            "overwritten": kwargs.get("overwrite", False),
        }

    monkeypatch.setattr(
        "data_quality_toolkit.adapters.exporters.bi.duckdb_exporter.export_monitoring_duckdb",
        fake_impl,
    )

    out = tmp_path / "m.duckdb"
    result = api.export_monitoring_duckdb(tmp_path / "m.db", out, overwrite=True)
    assert result["output_path"] == str(out)
    assert set(result.keys()) == {
        "input_db_path",
        "output_path",
        "tables",
        "row_counts",
        "overwritten",
    }
    (_, _), kwargs = calls[0]
    assert kwargs == {"overwrite": True}


def test_seam_respects_overwrite_default(monkeypatch, tmp_path) -> None:
    """overwrite defaults to False when not passed."""
    seen: dict[str, object] = {}

    def fake_impl(db_path, out_path, **kwargs):
        seen.update(kwargs)
        return {
            "input_db_path": str(db_path),
            "output_path": str(out_path),
            "tables": [],
            "row_counts": {},
            "overwritten": False,
        }

    monkeypatch.setattr(
        "data_quality_toolkit.adapters.exporters.bi.duckdb_exporter.export_monitoring_duckdb",
        fake_impl,
    )

    api.export_monitoring_duckdb(tmp_path / "m.db", tmp_path / "m.duckdb")
    assert seen == {"overwrite": False}
