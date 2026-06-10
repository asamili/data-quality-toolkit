"""Smoke tests for the G1 UI restructure: page modules and the app shell router.

Verifies each feature page exposes a callable ``render`` entry point and that
``app.main`` registers all pages with ``st.navigation``/``st.Page`` — without
launching a live Streamlit server.
"""

from __future__ import annotations

import importlib.util
import sys
from unittest.mock import MagicMock

import pytest

_HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit [ui] extra not installed"),
]

_EXPECTED_PAGE_TITLES = {
    "Data Overview",
    "EDA Explorer",
    "Run History",
    "Export",
    "KPI Catalog",
    "Dim Time",
    "Manifest Viewer",
    "Pipeline Runner",
    "Settings & Diagnostics",
}


def test_all_page_modules_expose_callable_render() -> None:
    from data_quality_toolkit.adapters.ui.pages import (
        data_overview,
        dim_time,
        eda_explorer,
        export,
        kpi_catalog,
        pipeline_runner,
        run_history,
        settings_diagnostics,
    )

    for mod in (
        data_overview,
        eda_explorer,
        run_history,
        export,
        kpi_catalog,
        dim_time,
        pipeline_runner,
        settings_diagnostics,
    ):
        assert callable(mod.render), f"{mod.__name__}.render is not callable"


def test_manifest_viewer_render_callable() -> None:
    from data_quality_toolkit.adapters.ui.pages.manifest_viewer import render_manifest_viewer

    assert callable(render_manifest_viewer)


def test_app_main_is_callable() -> None:
    from data_quality_toolkit.adapters.ui.app import main

    assert callable(main)


def test_app_main_registers_all_pages_with_navigation() -> None:
    """main() must register every feature page via st.Page and run st.navigation."""
    from data_quality_toolkit.adapters.ui import app

    fake_st = MagicMock()
    real_st = sys.modules.get("streamlit")
    sys.modules["streamlit"] = fake_st
    try:
        app.main()
    finally:
        if real_st is not None:
            sys.modules["streamlit"] = real_st
        else:
            sys.modules.pop("streamlit", None)

    fake_st.navigation.assert_called_once()
    fake_st.navigation.return_value.run.assert_called_once()

    registered_titles = {call.kwargs.get("title") for call in fake_st.Page.call_args_list}
    assert registered_titles == _EXPECTED_PAGE_TITLES

    # Exactly one default page.
    defaults = [c for c in fake_st.Page.call_args_list if c.kwargs.get("default")]
    assert len(defaults) == 1
    assert defaults[0].kwargs.get("title") == "Data Overview"

    # url_path must be explicit and unique (page callables share the name `render`,
    # so Streamlit's derived url_paths would collide without it).
    url_paths = [c.kwargs.get("url_path") for c in fake_st.Page.call_args_list]
    assert all(url_paths), "every st.Page must set an explicit url_path"
    assert len(set(url_paths)) == len(url_paths), "url_paths must be unique"
