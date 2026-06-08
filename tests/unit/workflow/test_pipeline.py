"""Tests for run_assessment DB persistence bridge."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_prof(**kw):
    base = {
        "run_id": "run-1",
        "dataset_id": "ds-1",
        "ts": "2026-01-01T00:00:00",
        "rows": 10,
        "cols": 2,
        "memory_mb": 0.5,
        "columns": [{"name": "a", "dtype": "int64"}],
    }
    base.update(kw)
    return base


def _make_assessment(**kw):
    base = {"score": 0.9, "completeness_score": 0.9, "quality_score": 0.9, "issues": []}
    base.update(kw)
    return base


_META = {"dataset_id": "ds-1", "source_path": "a.csv"}


@patch("data_quality_toolkit.application.workflow.pipeline.persist_export_run")
@patch("data_quality_toolkit.application.workflow.pipeline.connect")
@patch("data_quality_toolkit.application.workflow.pipeline.ensure_db")
@patch("data_quality_toolkit.application.workflow.pipeline.assess")
@patch("data_quality_toolkit.application.workflow.pipeline.run_profiling")
@patch("data_quality_toolkit.application.workflow.pipeline.load_csv")
def test_run_assessment_without_db_path_does_not_persist(
    mock_load, mock_profile, mock_assess, mock_ensure, mock_connect, mock_persist
):
    mock_load.return_value = (MagicMock(), _META)
    mock_profile.return_value = _make_prof()
    mock_assess.return_value = _make_assessment()

    from data_quality_toolkit.application.workflow.pipeline import run_assessment

    out = run_assessment("a.csv")

    mock_ensure.assert_not_called()
    mock_connect.assert_not_called()
    mock_persist.assert_not_called()
    assert "duration_secs" in out


@patch("data_quality_toolkit.application.workflow.pipeline.persist_export_run")
@patch("data_quality_toolkit.application.workflow.pipeline.connect")
@patch("data_quality_toolkit.application.workflow.pipeline.ensure_db")
@patch("data_quality_toolkit.application.workflow.pipeline.assess")
@patch("data_quality_toolkit.application.workflow.pipeline.run_profiling")
@patch("data_quality_toolkit.application.workflow.pipeline.load_csv")
def test_run_assessment_with_db_path_calls_persist(
    mock_load, mock_profile, mock_assess, mock_ensure, mock_connect, mock_persist, tmp_path
):
    mock_load.return_value = (MagicMock(), _META)
    mock_profile.return_value = _make_prof()
    mock_assess.return_value = _make_assessment()
    mock_con = MagicMock()
    mock_connect.return_value = mock_con

    db = tmp_path / "test.db"
    from data_quality_toolkit.application.workflow.pipeline import run_assessment

    run_assessment("a.csv", db_path=db)

    mock_ensure.assert_called_once_with(db)
    mock_connect.assert_called_once_with(db)
    mock_persist.assert_called_once()
    mock_con.close.assert_called_once()


@patch("data_quality_toolkit.application.workflow.pipeline.persist_export_run")
@patch("data_quality_toolkit.application.workflow.pipeline.connect")
@patch("data_quality_toolkit.application.workflow.pipeline.ensure_db")
@patch("data_quality_toolkit.application.workflow.pipeline.assess")
@patch("data_quality_toolkit.application.workflow.pipeline.run_profiling")
@patch("data_quality_toolkit.application.workflow.pipeline.load_csv")
def test_run_assessment_persist_payload_fields(
    mock_load, mock_profile, mock_assess, mock_ensure, mock_connect, mock_persist, tmp_path
):
    """persist_export_run receives correct dashboard-required fields."""
    issues = [{"column": "x", "severity": "high", "category": "Completeness", "message": "m"}]
    mock_load.return_value = (MagicMock(), _META)
    mock_profile.return_value = _make_prof()
    mock_assess.return_value = _make_assessment(score=0.8, issues=issues)
    mock_connect.return_value = MagicMock()

    db = tmp_path / "test.db"
    from data_quality_toolkit.application.workflow.pipeline import run_assessment

    run_assessment("a.csv", db_path=db)

    _args, kwargs = mock_persist.call_args
    assert kwargs["run_id"] == "run-1"
    assert kwargs["dataset_id"] == "ds-1"
    assert kwargs["source_path"] == "a.csv"
    assert kwargs["score"] == 0.8
    assert kwargs["issues_total"] == 1
    assert kwargs["issues_by_severity"] == {"high": 1}
    assert kwargs["issues_by_category"] == {"Completeness": 1}
    assert kwargs["quality_metrics"] == []
    assert "duration_secs" in kwargs


@patch("data_quality_toolkit.application.workflow.pipeline.assess")
@patch("data_quality_toolkit.application.workflow.pipeline.run_profiling")
@patch("data_quality_toolkit.application.workflow.pipeline.load_csv")
def test_run_assessment_output_includes_duration_secs(mock_load, mock_profile, mock_assess):
    mock_load.return_value = (MagicMock(), _META)
    mock_profile.return_value = _make_prof()
    mock_assess.return_value = _make_assessment()

    from data_quality_toolkit.application.workflow.pipeline import run_assessment

    out = run_assessment("a.csv")
    assert "duration_secs" in out
    assert isinstance(out["duration_secs"], float)
