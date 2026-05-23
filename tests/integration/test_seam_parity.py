"""Cross-interface seam-parity test.

Proves that the SAME CSV produces matching assessment output through:
  * the public Python API (data_quality_toolkit.assess_csv)
  * the CLI subprocess path (python -m data_quality_toolkit.cli.main assess)

Both interfaces delegate to workflow.pipeline.run_assessment, so their core
results must agree. This test is the guardrail that catches silent drift if
either interface stops routing through the shared core.

Assertions are limited to deterministic, core fields (score, issue identity,
rows, cols, shape). Non-deterministic fields (run_id, ts, duration_secs) and
formatting-only output are intentionally ignored.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

pytestmark = pytest.mark.integration


def _orders_csv(tmp_path: Path) -> Path:
    """Small fixture with nulls in multiple columns so issues are produced."""
    p = tmp_path / "seam_orders.csv"
    p.write_text(
        "order_id,customer,amount,region\n"
        "1,Alice,100.0,North\n"
        "2,Bob,,South\n"
        "3,,200.0,East\n"
        "4,Diana,150.0,\n",
        encoding="utf-8",
    )
    return p


def _issue_identities(assessment: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """Stable, order-independent identity for each issue (no volatile fields)."""
    identities = [
        (
            str(issue.get("type", "")),
            str(issue.get("column", "")),
            str(issue.get("severity", "")),
            str(issue.get("category", "")),
        )
        for issue in assessment.get("issues", [])
    ]
    return sorted(identities)


def _run_cli_assess(csv: Path) -> dict[str, Any]:
    """Invoke the CLI assess path via module entry; return parsed stdout JSON.

    --log-level ERROR + --log-format json keep stdout as pure machine JSON
    (human summaries go to stderr), matching the existing CLI integration test.
    """
    cmd = [
        sys.executable,
        "-m",
        "data_quality_toolkit.cli.main",
        "--log-level",
        "ERROR",
        "--log-format",
        "json",
        "assess",
        str(csv),
    ]
    # shell=False; executable is sys.executable (trusted); args are test-controlled.
    proc = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    assert proc.returncode == 0, f"CLI assess failed: {proc.stderr}"
    return cast("dict[str, Any]", json.loads(proc.stdout))


def test_assess_parity_api_vs_cli(tmp_path: Path) -> None:
    csv = _orders_csv(tmp_path)

    from data_quality_toolkit import assess_csv

    api_out = assess_csv(csv)
    cli_out = _run_cli_assess(csv)

    # --- shape parity: both interfaces expose the same core keys ---
    expected_keys = {"run_id", "dataset_id", "ts", "meta", "profile", "assessment"}
    assert expected_keys <= set(api_out), f"API missing keys: {expected_keys - set(api_out)}"
    assert expected_keys <= set(cli_out), f"CLI missing keys: {expected_keys - set(cli_out)}"

    api_prof = api_out["profile"]
    cli_prof = cli_out["profile"]
    api_asmt = api_out["assessment"]
    cli_asmt = cli_out["assessment"]

    # --- rows / cols parity ---
    assert api_prof["rows"] == cli_prof["rows"] == 4
    assert api_prof["cols"] == cli_prof["cols"] == 4

    # --- score parity (exact; both compute via the same pipeline) ---
    assert isinstance(api_asmt["score"], float)
    assert api_asmt["score"] == pytest.approx(cli_asmt["score"])

    # --- issue parity: same count and same identities ---
    assert len(api_asmt["issues"]) == len(cli_asmt["issues"])
    assert _issue_identities(api_asmt) == _issue_identities(cli_asmt)

    # --- the fixture must actually exercise the issue path (guards a vacuous pass) ---
    assert len(api_asmt["issues"]) > 0
