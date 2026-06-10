import importlib.util
from unittest.mock import MagicMock, patch

import pytest

from data_quality_toolkit.adapters.ui.pages.manifest_viewer import render_manifest_viewer

_HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None


def test_manifest_viewer_import():
    # Verify the function is importable and callable
    assert callable(render_manifest_viewer)


@pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit [ui] extra not installed")
def test_render_manifest_viewer_smoke():
    # Mock streamlit
    with (
        patch("streamlit.header") as mock_header,
        patch("streamlit.columns") as mock_columns,
        patch("streamlit.text_input"),
        patch("streamlit.button") as mock_button,
    ):
        # Setup mocks
        mock_columns.return_value = (MagicMock(), MagicMock())
        mock_button.return_value = False  # Button not clicked

        # Act
        render_manifest_viewer()

        # Assert
        mock_header.assert_called_with("Lineage Manifest Viewer")
