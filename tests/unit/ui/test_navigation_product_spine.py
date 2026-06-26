"""Navigation contract for the P0 product spine.

Drives ``app.main`` with a MagicMock standing in for streamlit so the page
registry is verified without the [ui] extra installed and without launching a
server. Pins group order, the full set of page titles, a single Start default,
and unique url_paths.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock

_EXPECTED_GROUPS = ["Start", "Analyze", "Prepare", "Operate", "Deliver", "System"]

_EXPECTED_TITLES = {
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

_NEW_P0_PAGES = {
    "Statistics Lab",
    "Quality Score / Rule Breakdown",
    "Preprocess Studio",
    "Artifact Center",
    "Help / About",
}


def _run_main_with_fake_st() -> Any:
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
    return fake_st


def test_navigation_groups_match_product_spine() -> None:
    fake_st = _run_main_with_fake_st()
    fake_st.navigation.assert_called_once()
    fake_st.navigation.return_value.run.assert_called_once()
    navigation = fake_st.navigation.call_args.args[0]
    assert list(navigation) == _EXPECTED_GROUPS


def test_all_spine_pages_registered() -> None:
    fake_st = _run_main_with_fake_st()
    titles = {c.kwargs.get("title") for c in fake_st.Page.call_args_list}
    assert titles == _EXPECTED_TITLES


def test_new_p0_pages_present() -> None:
    fake_st = _run_main_with_fake_st()
    titles = {c.kwargs.get("title") for c in fake_st.Page.call_args_list}
    assert _NEW_P0_PAGES <= titles


def test_single_default_page_is_start() -> None:
    fake_st = _run_main_with_fake_st()
    defaults = [c for c in fake_st.Page.call_args_list if c.kwargs.get("default")]
    assert len(defaults) == 1
    assert defaults[0].kwargs.get("title") == "Start / Load Dataset"


def test_url_paths_are_explicit_and_unique() -> None:
    fake_st = _run_main_with_fake_st()
    url_paths = [c.kwargs.get("url_path") for c in fake_st.Page.call_args_list]
    assert all(url_paths), "every st.Page must set an explicit url_path"
    assert len(set(url_paths)) == len(url_paths), "url_paths must be unique"
