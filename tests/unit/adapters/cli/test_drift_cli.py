from __future__ import annotations

import argparse
from unittest.mock import patch

from data_quality_toolkit.adapters.cli.main import cmd_drift


def test_cmd_drift_no_drift_exit_code_zero() -> None:
    args = argparse.Namespace(
        baseline="a.csv",
        current="b.csv",
        alpha=0.05,
        min_samples=30,
        max_categories=20,
        sep=None,
        encoding=None,
        na_values=None,
        sample_size=None,
        fail_on_drift=True,
        no_json=True,
    )

    mock_result = {"status": "ok", "summary": {"columns_tested": 2, "columns_drifted": 0}}

    with (
        patch("data_quality_toolkit.adapters.cli.main.run_drift", return_value=mock_result),
        patch("data_quality_toolkit.adapters.cli.main._safe_text", return_value="✓"),
    ):
        exit_code = cmd_drift(args)

    assert exit_code == 0


def test_cmd_drift_detected_without_fail_on_drift_exit_code_zero() -> None:
    args = argparse.Namespace(
        baseline="a.csv",
        current="b.csv",
        alpha=0.05,
        min_samples=30,
        max_categories=20,
        sep=None,
        encoding=None,
        na_values=None,
        sample_size=None,
        fail_on_drift=False,
        no_json=True,
    )

    mock_result = {"status": "ok", "summary": {"columns_tested": 2, "columns_drifted": 1}}

    with (
        patch("data_quality_toolkit.adapters.cli.main.run_drift", return_value=mock_result),
        patch("data_quality_toolkit.adapters.cli.main._safe_text", return_value="✓"),
    ):
        exit_code = cmd_drift(args)

    assert exit_code == 0


def test_cmd_drift_detected_with_fail_on_drift_exit_code_two() -> None:
    args = argparse.Namespace(
        baseline="a.csv",
        current="b.csv",
        alpha=0.05,
        min_samples=30,
        max_categories=20,
        sep=None,
        encoding=None,
        na_values=None,
        sample_size=None,
        fail_on_drift=True,
        no_json=True,
    )

    mock_result = {"status": "ok", "summary": {"columns_tested": 2, "columns_drifted": 1}}

    with (
        patch("data_quality_toolkit.adapters.cli.main.run_drift", return_value=mock_result),
        patch("data_quality_toolkit.adapters.cli.main._safe_text", return_value="✓"),
    ):
        exit_code = cmd_drift(args)

    assert exit_code == 2


def test_cmd_drift_detected_with_no_json_and_fail_on_drift_exit_code_two() -> None:
    args = argparse.Namespace(
        baseline="a.csv",
        current="b.csv",
        alpha=0.05,
        min_samples=30,
        max_categories=20,
        sep=None,
        encoding=None,
        na_values=None,
        sample_size=None,
        fail_on_drift=True,
        no_json=True,
    )

    mock_result = {"status": "ok", "summary": {"columns_tested": 2, "columns_drifted": 1}}

    with (
        patch("data_quality_toolkit.adapters.cli.main.run_drift", return_value=mock_result),
        patch("data_quality_toolkit.adapters.cli.main._safe_text", return_value="✓"),
    ):
        exit_code = cmd_drift(args)

    assert exit_code == 2
