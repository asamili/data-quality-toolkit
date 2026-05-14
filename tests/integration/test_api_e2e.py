from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _orders_csv(tmp_path: Path) -> Path:
    p = tmp_path / "orders.csv"
    p.write_text(
        "order_id,customer,amount,region\n"
        "1,Alice,100.0,North\n"
        "2,Bob,,South\n"
        "3,,200.0,East\n"
        "4,Diana,150.0,\n",
        encoding="utf-8",
    )
    return p


def test_full_pipeline_via_public_api(tmp_path: Path) -> None:
    from data_quality_toolkit import assess_csv, compare_runs, export_csv, profile_csv

    csv = _orders_csv(tmp_path)

    prof = profile_csv(csv)
    assert prof["profile"]["rows"] == 4
    assert prof["profile"]["cols"] == 4

    asmt = assess_csv(csv)
    assert isinstance(asmt["assessment"]["score"], float)
    assert 0.0 <= asmt["assessment"]["score"] <= 1.0

    run1 = export_csv(csv, output_dir=tmp_path)
    run2 = export_csv(csv, output_dir=tmp_path)
    assert run1["run_id"] != run2["run_id"]

    cmp = compare_runs(csv, output_dir=tmp_path)
    assert "error" not in cmp
    assert cmp["current_run_id"] == run2["run_id"]
    assert cmp["previous_run_id"] == run1["run_id"]
    assert isinstance(cmp["score_delta"], float)
