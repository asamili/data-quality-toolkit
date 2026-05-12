"""Pipeline-level tests: empty CSV error propagates cleanly from loader."""

from __future__ import annotations

import pytest

from data_quality_toolkit.workflow.pipeline import run_assessment, run_profile


def _empty_csv(tmp_path):
    f = tmp_path / "empty.csv"
    f.write_bytes(b"")
    return str(f)


def test_run_profile_empty_csv_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="empty or has no columns"):
        run_profile(_empty_csv(tmp_path))


def test_run_assessment_empty_csv_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="empty or has no columns"):
        run_assessment(_empty_csv(tmp_path))
