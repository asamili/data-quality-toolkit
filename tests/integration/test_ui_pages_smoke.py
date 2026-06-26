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
    "Start / Load Dataset",
    "Data Overview",
    "Statistics Lab",
    "EDA Explorer",
    "Quality Score / Rule Breakdown",
    "Preprocess Studio",
    "Pipeline Runner",
    "Drift Monitoring",
    "Quality History",
    "Artifact Center",
    "Export",
    "KPI Catalog",
    "Dim Time",
    "Manifest Viewer",
    "Settings / Governance",
    "Help / About",
}


def test_all_page_modules_expose_callable_render() -> None:
    from data_quality_toolkit.adapters.ui.pages import (
        artifact_center,
        data_overview,
        dim_time,
        drift_explorer,
        eda_explorer,
        export,
        help_about,
        kpi_catalog,
        pipeline_runner,
        preprocess_studio,
        quality_score,
        run_history,
        settings_diagnostics,
        start,
        statistics_lab,
    )

    for mod in (
        start,
        data_overview,
        statistics_lab,
        eda_explorer,
        quality_score,
        preprocess_studio,
        pipeline_runner,
        drift_explorer,
        run_history,
        artifact_center,
        export,
        kpi_catalog,
        dim_time,
        settings_diagnostics,
        help_about,
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
    assert defaults[0].kwargs.get("title") == "Start / Load Dataset"

    navigation = fake_st.navigation.call_args.args[0]
    assert list(navigation) == [
        "Start",
        "Analyze",
        "Prepare",
        "Operate",
        "Deliver",
        "System",
    ]

    # url_path must be explicit and unique (page callables share the name `render`,
    # so Streamlit's derived url_paths would collide without it).
    url_paths = [c.kwargs.get("url_path") for c in fake_st.Page.call_args_list]
    assert all(url_paths), "every st.Page must set an explicit url_path"
    assert len(set(url_paths)) == len(url_paths), "url_paths must be unique"


def test_render_storylens_card_warn_severity() -> None:
    from data_quality_toolkit.adapters.ui.components.storylens import render_storylens_card
    from data_quality_toolkit.application.explanation import explain_quality_score

    fake_st = MagicMock()
    exp = explain_quality_score(score=0.75, rows=100, columns=5, issues_total=10)
    render_storylens_card(fake_st, [exp])

    fake_st.subheader.assert_called_once()
    fake_st.warning.assert_called_once()


def test_render_storylens_card_empty_renders_nothing() -> None:
    from data_quality_toolkit.adapters.ui.components.storylens import render_storylens_card

    fake_st = MagicMock()
    render_storylens_card(fake_st, [])

    fake_st.subheader.assert_not_called()


def test_render_storylens_card_issue_level_explanations() -> None:
    """Missing-value (warn) and constant-column (info) issue cards both render."""
    from data_quality_toolkit.adapters.ui.components.storylens import render_storylens_card
    from data_quality_toolkit.application.explanation import (
        explain_constant_column_issue,
        explain_missing_value_issue,
    )

    fake_st = MagicMock()
    explanations = [
        explain_missing_value_issue(column="revenue", null_pct=0.3, severity_label="high"),
        explain_constant_column_issue(column="status"),
    ]
    render_storylens_card(fake_st, explanations)

    fake_st.subheader.assert_called_once()
    fake_st.warning.assert_called_once()  # missing-value card (warn severity)
    fake_st.info.assert_called_once()  # constant-column card (info severity)
