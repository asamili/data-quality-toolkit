from __future__ import annotations

from pathlib import Path

import pytest

from data_quality_toolkit import create_manifest

pytestmark = pytest.mark.integration


def test_create_manifest_api_delegation(tmp_path: Path) -> None:
    # Setup
    run_id = "test-run"
    session_dir = tmp_path / run_id
    session_dir.mkdir()
    (session_dir / "meta").mkdir()
    (session_dir / "meta" / "gates.jsonl").write_text("", encoding="utf-8")

    # Act
    result = create_manifest(run_id=run_id, sessions_root=tmp_path)

    # Assert
    assert isinstance(result, dict)
    assert result["run_id"] == run_id

    # Check if file was written
    manifest_path = session_dir / "artifacts.json"
    assert manifest_path.exists()


def test_export_drift_history_xlsx_api_delegation(monkeypatch, tmp_path: Path) -> None:
    """The public export_drift_history_xlsx seam forwards to the exporter impl."""
    from data_quality_toolkit import export_drift_history_xlsx

    seen: dict[str, object] = {}

    def fake_impl(db_path, output_path, **kwargs):
        seen["output_path"] = str(output_path)
        seen.update(kwargs)
        return {"output_path": str(output_path), "sheets": ["runs"], "row_counts": {"runs": 0}}

    monkeypatch.setattr(
        "data_quality_toolkit.adapters.exporters.bi.xlsx_drift_exporter."
        "export_drift_history_xlsx",
        fake_impl,
    )

    out = tmp_path / "drift.xlsx"
    result = export_drift_history_xlsx(tmp_path / "m.db", out, limit=2, force=True)
    assert result["sheets"] == ["runs"]
    assert seen["output_path"] == str(out)
    assert seen["limit"] == 2
    assert seen["force"] is True


def test_export_drift_plots_api_delegation(monkeypatch, tmp_path: Path) -> None:
    """The public export_drift_plots seam forwards to the viz exporter impl."""
    from data_quality_toolkit import export_drift_plots

    seen: dict[str, object] = {}

    def fake_impl(db_path, out, **kwargs):
        seen["out"] = str(out)
        seen.update(kwargs)
        return {"output_dir": str(out), "charts": {}, "row_counts": {}}

    monkeypatch.setattr(
        "data_quality_toolkit.adapters.exporters.viz.drift_plots.export_drift_plots",
        fake_impl,
    )

    out = tmp_path / "plots"
    result = export_drift_plots(tmp_path / "m.db", out, chart="top-drifted", limit=2, force=True)
    assert result["output_dir"] == str(out)
    assert seen["out"] == str(out)
    assert seen["chart"] == "top-drifted"
    assert seen["limit"] == 2
    assert seen["force"] is True


def test_export_monitoring_duckdb_api_delegation(monkeypatch, tmp_path: Path) -> None:
    """The public export_monitoring_duckdb seam forwards to the exporter impl."""
    from data_quality_toolkit import export_monitoring_duckdb

    seen: dict[str, object] = {}

    def fake_impl(db_path, out_path, **kwargs):
        seen["out_path"] = str(out_path)
        seen.update(kwargs)
        return {
            "input_db_path": str(db_path),
            "output_path": str(out_path),
            "tables": ["drift_runs"],
            "row_counts": {"drift_runs": 0},
            "overwritten": kwargs.get("overwrite", False),
        }

    monkeypatch.setattr(
        "data_quality_toolkit.adapters.exporters.bi.duckdb_exporter.export_monitoring_duckdb",
        fake_impl,
    )

    out = tmp_path / "m.duckdb"
    result = export_monitoring_duckdb(tmp_path / "m.db", out, overwrite=True)
    assert result["tables"] == ["drift_runs"]
    assert seen["out_path"] == str(out)
    assert seen["overwrite"] is True


def test_send_drift_notification_api_dry_run_delegation(monkeypatch, tmp_path: Path) -> None:
    """The public send_drift_notification seam builds a payload without any network."""
    from data_quality_toolkit import api, send_drift_notification

    monkeypatch.setattr(
        api,
        "summarize_drift_trends_sqlite",
        lambda *a, **k: {
            "total_runs": 0,
            "drifted_runs": 0,
            "drift_rate": 0.0,
            "latest_run_id": None,
            "latest_created_at": None,
        },
    )

    result = send_drift_notification(
        tmp_path / "m.db", "https://hooks.example.com/x?token=secret", dry_run=True
    )
    assert result["sent"] is False
    assert result["status"] is None
    assert result["redacted_url"] == "https://hooks.example.com/x"
    assert result["payload"]["event"] == "drift_threshold_check"
    assert "secret" not in str(result["payload"])
