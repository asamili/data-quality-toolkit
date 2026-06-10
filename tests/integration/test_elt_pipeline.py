from pathlib import Path
from unittest.mock import patch

from data_quality_toolkit import create_elt_pipeline
from data_quality_toolkit.application.workflow.elt_pipeline import ELTPipeline


def test_elt_pipeline_creation_and_fluent_api():
    pipeline = create_elt_pipeline("test-run-123", "/tmp/sessions")

    assert isinstance(pipeline, ELTPipeline)
    assert pipeline.run_id == "test-run-123"

    # Test fluent API
    pipeline.extract("data.csv").transform("cleaning").load("output.csv").assess(
        "quality"
    ).manifest()

    assert len(pipeline.steps) == 5
    assert pipeline.steps[0].type == "extract"
    assert pipeline.steps[1].type == "transform"
    assert pipeline.steps[2].type == "load"
    assert pipeline.steps[3].type == "assess"
    assert pipeline.steps[4].type == "manifest"


@patch("data_quality_toolkit.api.create_manifest")
def test_elt_pipeline_run_with_manifest(mock_create_manifest):
    mock_create_manifest.return_value = {"manifest": "data"}
    pipeline = create_elt_pipeline("test-run-123", "/tmp/sessions")
    pipeline.manifest()

    result = pipeline.run()

    assert result.run_id == "test-run-123"
    assert result.status == "success"
    assert result.manifest == {"manifest": "data"}
    mock_create_manifest.assert_called_once_with("test-run-123", str(Path("/tmp/sessions")))


@patch("data_quality_toolkit.api.create_manifest")
def test_elt_pipeline_run_without_manifest(mock_create_manifest):
    pipeline = create_elt_pipeline("test-run-123", "/tmp/sessions")

    result = pipeline.run()

    assert result.run_id == "test-run-123"
    assert result.status == "success"
    assert result.manifest is None
    mock_create_manifest.assert_not_called()
