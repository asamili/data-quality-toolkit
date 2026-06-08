"""Plan parity guardrail: API vs CLI vs UI/core.

Proves that plan_csv (Python API), dqt plan (CLI), and the UI preprocessing
helper all return the same column set and recommendation structure for an
identical CSV input.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _sample_csv(tmp_path: Path) -> Path:
    p = tmp_path / "plan_parity.csv"
    p.write_text(
        "id,name,amount,region\n"
        "1,Alice,100.0,North\n"
        "2,Bob,,South\n"
        "3,,200.0,East\n"
        "4,Diana,150.0,\n"
        "5,Eve,175.0,West\n",
        encoding="utf-8",
    )
    return p


def _column_names(plan_result: dict) -> list[str]:
    return sorted(c["column"] for c in plan_result["columns"])


def test_plan_parity_api_vs_cli(tmp_path: Path) -> None:
    csv = _sample_csv(tmp_path)

    from data_quality_toolkit import plan_csv

    api_out = plan_csv(csv)

    cmd = [
        sys.executable,
        "-m",
        "data_quality_toolkit.adapters.cli.main",
        "--log-level",
        "ERROR",
        "--log-format",
        "json",
        "plan",
        str(csv),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    assert proc.returncode == 0, f"CLI plan failed: {proc.stderr}"
    cli_out = json.loads(proc.stdout)

    assert _column_names(api_out) == _column_names(cli_out)
    assert len(api_out["columns"]) == len(cli_out["columns"])
    assert api_out["dataset_id"] == cli_out["dataset_id"]

    for api_col, cli_col in zip(
        sorted(api_out["columns"], key=lambda c: c["column"]),
        sorted(cli_out["columns"], key=lambda c: c["column"]),
    ):
        assert api_col["column"] == cli_col["column"]
        assert api_col["dtype"] == cli_col["dtype"]
        assert api_col["issues"] == cli_col["issues"]
        assert api_col["recommendations"] == cli_col["recommendations"]


def test_plan_parity_api_vs_ui_helper(tmp_path: Path) -> None:
    csv = _sample_csv(tmp_path)

    from data_quality_toolkit import plan_csv
    from data_quality_toolkit.adapters.loaders.file.csv_loader import load_csv
    from data_quality_toolkit.adapters.ui.eda import _plan_preprocessing

    api_out = plan_csv(csv)

    df, _ = load_csv(str(csv))
    ui_columns = _plan_preprocessing(df)

    assert _column_names(api_out) == sorted(c["column"] for c in ui_columns)
    for api_col, ui_col in zip(
        sorted(api_out["columns"], key=lambda c: c["column"]),
        sorted(ui_columns, key=lambda c: c["column"]),
    ):
        assert api_col["column"] == ui_col["column"]
        assert api_col["issues"] == ui_col["issues"]
        assert api_col["recommendations"] == ui_col["recommendations"]
