# tests/integration/test_drift_plots_e2e.py
"""End-to-end: real SQLite monitoring DB -> PNG chart files.

Gated behind the optional [viz] extra (matplotlib). Reuses the same real-DB
seeding pattern as the other drift-history integration tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from data_quality_toolkit.adapters.storage.connection import connect
from data_quality_toolkit.adapters.storage.schema import ensure_db

pytestmark = pytest.mark.integration

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _seed(db) -> None:
    ensure_db(db)
    runs = [
        ("r1", "2026-06-13T00:00:01+00:00", 2, 1, 1),
        ("r2", "2026-06-13T00:00:02+00:00", 2, 0, 0),
    ]
    cols = [
        ("r1", "amount", 1, 0.30),
        ("r1", "region", 0, 0.05),
        ("r2", "amount", 0, 0.10),
    ]
    with connect(db) as con:
        for run_id, created_at, tested, drifted, detected in runs:
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
                    tested,
                    0,
                    drifted,
                    detected,
                    None,
                    "1",
                ),
            )
        for run_id, col, detected, psi in cols:
            con.execute(
                """
                INSERT INTO drift_columns(
                    run_id, column_name, kind, test, statistic, p_value,
                    drift_detected, reference_n, current_n, status, skip_reason,
                    psi, js_distance, wasserstein
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    col,
                    "numeric",
                    "ks",
                    0.1,
                    0.2,
                    detected,
                    10,
                    10,
                    "ok",
                    None,
                    psi,
                    None,
                    None,
                ),
            )
        con.commit()


def test_e2e_real_db_writes_pngs(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    from data_quality_toolkit import export_drift_plots

    db = tmp_path / "monitoring.db"
    _seed(db)
    out = tmp_path / "plots"

    result = export_drift_plots(db, out, chart="all")
    assert result["output_dir"] == str(out.resolve())
    assert set(result["charts"]) == {"drift-rate", "psi-by-column", "top-drifted"}
    assert result["row_counts"]["drift-rate"] == 2
    assert result["row_counts"]["psi-by-column"] == 2  # amount, region
    assert result["row_counts"]["top-drifted"] == 1  # only amount drifted

    for path in cast(dict[str, str], result["charts"]).values():
        p = Path(path)
        assert p.exists()
        assert p.read_bytes()[:8] == _PNG_MAGIC


def test_e2e_cli_api_parity_row_counts(tmp_path: Path) -> None:
    """API and CLI produce identical charts/row_counts for the same DB."""
    pytest.importorskip("matplotlib")
    import data_quality_toolkit.adapters.cli.main as cli
    from data_quality_toolkit import export_drift_plots

    db = tmp_path / "monitoring.db"
    _seed(db)

    api_out = tmp_path / "api_plots"
    api_result = export_drift_plots(db, api_out, chart="all")

    cli_out = tmp_path / "cli_plots"
    rc = cli.main(["drift-history", "plot", "--db", str(db), "--out", str(cli_out)])
    assert rc == 0

    cli_result = export_drift_plots(db, cli_out, chart="all", force=True)
    assert set(cli_result["charts"]) == set(api_result["charts"])
    assert cli_result["row_counts"] == api_result["row_counts"]
