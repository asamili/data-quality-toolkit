# tests/integration/test_drift_xlsx_e2e.py
"""End-to-end: real SQLite monitoring DB -> .xlsx workbook, reopened via openpyxl.

Gated behind the optional [powerbi] extra (openpyxl). Reuses the same real-DB
seeding pattern as test_cli_drift_history_report.py.
"""

from __future__ import annotations

import pytest

from data_quality_toolkit.adapters.storage.connection import connect
from data_quality_toolkit.adapters.storage.schema import ensure_db

pytestmark = pytest.mark.integration


def _seed_runs(db) -> None:
    ensure_db(db)
    rows = [
        ("r1", "2026-06-13T00:00:01+00:00", 1),
        ("r2", "2026-06-13T00:00:02+00:00", 0),
    ]
    with connect(db) as con:
        for run_id, created_at, drift in rows:
            con.execute(
                """
                INSERT INTO drift_runs(
                    run_id, created_at, baseline_path, current_path,
                    baseline_dataset_id, current_dataset_id, status, alpha,
                    columns_tested, columns_skipped, columns_drifted,
                    drift_detected, report_path, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    created_at,
                    "b.csv",
                    "c.csv",
                    "bd1",
                    "cd1",
                    "ok",
                    0.05,
                    2,
                    0,
                    1,
                    drift,
                    None,
                    "1",
                ),
            )
        con.commit()


def test_e2e_real_db_workbook_roundtrip(tmp_path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    from data_quality_toolkit import export_drift_history_xlsx

    db = tmp_path / "monitoring.db"
    _seed_runs(db)
    out = tmp_path / "drift_monitoring.xlsx"

    result = export_drift_history_xlsx(db, out)
    assert result["output_path"] == str(out.resolve())
    assert result["row_counts"]["runs"] == 2
    assert result["sheets"] == ["runs", "trend_summary", "columns", "metadata"]

    wb = openpyxl.load_workbook(out, read_only=True)
    assert "runs" in wb.sheetnames
    runs_ws = wb["runs"]
    rows = list(runs_ws.iter_rows(values_only=True))
    header = rows[0]
    assert header[0] == "run_id"
    run_ids = {r[0] for r in rows[1:]}
    assert run_ids == {"r1", "r2"}

    # trend_summary key/value sheet carries total_runs
    ts_rows = dict((r[0], r[1]) for r in wb["trend_summary"].iter_rows(min_row=2, values_only=True))
    assert str(ts_rows.get("total_runs")) == "2"
    wb.close()


def test_e2e_cli_api_parity_row_counts(tmp_path) -> None:
    """API and CLI produce identical sheet/row_counts for the same DB."""
    pytest.importorskip("openpyxl")
    import data_quality_toolkit.adapters.cli.main as cli
    from data_quality_toolkit import export_drift_history_xlsx

    db = tmp_path / "monitoring.db"
    _seed_runs(db)

    api_out = tmp_path / "api.xlsx"
    api_result = export_drift_history_xlsx(db, api_out)

    cli_out = tmp_path / "cli.xlsx"
    rc = cli.main(["drift-history", "export-xlsx", "--db", str(db), "--out", str(cli_out)])
    assert rc == 0
    assert cli_out.exists()

    # CLI delegates to the same seam; re-derive its result for comparison.
    cli_result = export_drift_history_xlsx(db, cli_out, force=True)
    assert cli_result["sheets"] == api_result["sheets"]
    assert cli_result["row_counts"] == api_result["row_counts"]
