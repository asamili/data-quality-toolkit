"""Unit tests for dqt chart CLI command."""

from __future__ import annotations

from argparse import Namespace
from unittest.mock import patch

import pandas as pd
import pytest

from data_quality_toolkit.adapters.cli.main import cmd_chart
from data_quality_toolkit.domain.profiling.charts import compute_univariate_chart_data


@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {
            "num": [1, 2, 2, 3, 3, 3, 4, 4, 4, 4],
            "cat": ["A", "A", "B", "C", "C", "C", "D", "D", "D", "D"],
            "empty": [None] * 10,
        }
    )


def test_compute_univariate_chart_data_numeric(sample_df):
    result = compute_univariate_chart_data(sample_df, "num", bins=4)
    assert result["type"] == "numeric"
    assert len(result["data"]) <= 4
    assert result["column"] == "num"


def test_compute_univariate_chart_data_categorical(sample_df):
    result = compute_univariate_chart_data(sample_df, "cat")
    assert result["type"] == "categorical"
    assert ("D", 4) in result["data"]
    assert ("A", 2) in result["data"]


def test_compute_univariate_chart_data_empty(sample_df):
    result = compute_univariate_chart_data(sample_df, "empty")
    assert result["type"] == "empty"
    assert result["data"] == []


def test_compute_univariate_chart_data_missing_column(sample_df):
    with pytest.raises(ValueError, match="Column 'missing' not found"):
        compute_univariate_chart_data(sample_df, "missing")


@patch("data_quality_toolkit.adapters.loaders.file.csv_loader.load_csv")
@patch("data_quality_toolkit.adapters.cli.charts.render_univariate_chart")
def test_cmd_chart_success(mock_render, mock_load, sample_df):
    mock_load.return_value = (sample_df, {"dataset_id": "test_id"})
    args = Namespace(csv="test.csv", column="num", sep=None, encoding=None, no_json=True)

    # We need to mock _get_sample_size and _csv_kwargs_from_args if they are used
    with (
        patch("data_quality_toolkit.adapters.cli.main._get_sample_size", return_value=None),
        patch("data_quality_toolkit.adapters.cli.main._csv_kwargs_from_args", return_value={}),
    ):
        exit_code = cmd_chart(args)

    assert exit_code == 0
    mock_render.assert_called_once()


@patch("data_quality_toolkit.adapters.loaders.file.csv_loader.load_csv")
def test_cmd_chart_error(mock_load):
    mock_load.side_effect = Exception("Load failed")
    args = Namespace(csv="test.csv", column="num", sep=None, encoding=None, no_json=True)

    with (
        patch("data_quality_toolkit.adapters.cli.main._get_sample_size", return_value=None),
        patch("data_quality_toolkit.adapters.cli.main._csv_kwargs_from_args", return_value={}),
    ):
        exit_code = cmd_chart(args)

    assert exit_code == 1
