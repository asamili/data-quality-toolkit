"""Navigation contract for the P0 product spine.

Drives ``app.main`` with a MagicMock standing in for streamlit so the page
registry is verified without the [ui] extra installed and without launching a
server. Pins group order, the full set of page titles, a single Start default,
and unique url_paths.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import data_quality_toolkit
from data_quality_toolkit.adapters.ui import journey

_EXPECTED_GROUPS = ["Start", "Analyze", "Prepare", "Operate", "Deliver", "System"]

# Flattened registration order (P1B accepted journey) keyed by stable url_path.
# Pins both the order and route stability: `run-history` must never be renamed.
_EXPECTED_URL_PATH_ORDER = [
    "start",
    "data-overview",
    "eda-explorer",
    "statistics-lab",
    "quality-score",
    "preprocess-studio",
    "pipeline-runner",
    "drift-monitoring",
    "export",
    "run-history",
    "artifact-center",
    "kpi-catalog",
    "dim-time",
    "manifest-viewer",
    "settings-governance",
    "help-about",
]

# journey page_key -> url_path, used to prove the app registry and JOURNEY stay
# in lockstep without introducing a second registry in production code.
_KEY_TO_URL_PATH = {
    "start": "start",
    "data_overview": "data-overview",
    "eda_explorer": "eda-explorer",
    "statistics_lab": "statistics-lab",
    "quality_score": "quality-score",
    "preprocess_studio": "preprocess-studio",
    "pipeline_runner": "pipeline-runner",
    "drift_explorer": "drift-monitoring",
    "export": "export",
    "run_history": "run-history",
    "artifact_center": "artifact-center",
    "kpi_catalog": "kpi-catalog",
    "dim_time": "dim-time",
    "manifest_viewer": "manifest-viewer",
    "settings_diagnostics": "settings-governance",
    "help_about": "help-about",
}

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
    # st.Page returns the same mock for every call by default; return the kwargs
    # instead so the navigation mapping records each page's title/url_path per group.
    fake_st.Page.side_effect = lambda *args, **kwargs: dict(kwargs)
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


def _navigation_groups(fake_st: Any) -> dict[str, list[dict[str, Any]]]:
    return dict(fake_st.navigation.call_args.args[0])


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


def test_quality_history_in_deliver_not_operate() -> None:
    fake_st = _run_main_with_fake_st()
    groups = _navigation_groups(fake_st)
    titles_by_group = {name: [page["title"] for page in pages] for name, pages in groups.items()}
    assert titles_by_group["Operate"] == ["Pipeline Runner", "Drift Monitoring"]
    assert titles_by_group["Deliver"] == [
        "Export",
        "Quality History",
        "Artifact Center",
        "KPI Catalog",
        "Dim Time",
        "Manifest Viewer",
    ]
    all_titles = [title for titles in titles_by_group.values() for title in titles]
    assert all_titles.count("Quality History") == 1


def test_flattened_order_matches_journey_and_routes_stable() -> None:
    fake_st = _run_main_with_fake_st()
    url_paths = [c.kwargs["url_path"] for c in fake_st.Page.call_args_list]
    # Registration order equals the accepted P1B journey order.
    assert url_paths == _EXPECTED_URL_PATH_ORDER
    # The JOURNEY source of truth mirrors the app registry exactly.
    assert [_KEY_TO_URL_PATH[key] for key, _ in journey.JOURNEY] == url_paths
    # Route stability: the full route set is pinned; no url_path was renamed.
    assert set(url_paths) == set(_EXPECTED_URL_PATH_ORDER)


def test_current_docs_state_accepted_deliver_order() -> None:
    root = Path(data_quality_toolkit.__file__).resolve().parents[2]
    numbered_docs = [root / "README.md", root / "docs" / "capability_matrix.md"]
    for path in numbered_docs:
        text = path.read_text(encoding="utf-8")
        for expected in ("9. **Export**", "10. **Quality History**", "11. **Artifact Center**"):
            assert expected in text, f"{path.name} is missing {expected!r}"
        for stale in ("9. **Quality History**", "10. **Artifact Center**", "11. **Export**"):
            assert stale not in text, f"{path.name} still contains stale {stale!r}"

    flat_docs = [root / "docs" / "product.md", root / "docs" / "architecture.md"]
    for path in flat_docs:
        text = path.read_text(encoding="utf-8")
        assert (
            "Drift Monitoring, Export, Quality History, Artifact Center" in text
        ), f"{path.name} does not state the accepted flattened order"
        assert (
            "Quality History, Artifact Center, Export" not in text
        ), f"{path.name} still contains the stale flattened order"

    golden = (root / "docs" / "guides" / "golden_path.md").read_text(encoding="utf-8")
    for expected in ("Export (step 9)", "Quality History (step 10)", "Artifact Center (step 11)"):
        assert expected in golden, f"golden_path.md is missing {expected!r}"
