"""Real-Streamlit contract for the canonical Artifact Center page factory.

``test_navigation_product_spine.py`` drives ``app.main()`` with a MagicMock
standing in for streamlit, so it only pins the *kwargs* passed to ``st.Page``
and can't distinguish a real ``StreamlitPage`` from a plain string. This
module proves the object export.py hands to ``st.page_link`` really is a
``StreamlitPage`` matching the Artifact Center registration, using the
installed Streamlit implementation.

``AppTest`` does not yet support switching between multipage
``st.navigation``/``st.Page`` routes, but it does fully execute a single
script with a real script-run context, which is all that's needed here: one
page object, constructed once, inspected afterward via ``session_state``.
"""

from __future__ import annotations

import importlib.util
from typing import Any
from unittest.mock import MagicMock

import pytest

_HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None

pytestmark = pytest.mark.skipif(not _HAS_STREAMLIT, reason="streamlit [ui] extra not installed")


def test_factory_calls_real_streamlit_page_with_the_registered_shape() -> None:
    import streamlit as st

    from data_quality_toolkit.adapters.ui.pages import artifact_center

    spy = MagicMock(side_effect=st.Page)
    original_page = st.Page
    st.Page = spy
    try:
        artifact_center.artifact_center_page(st)
    finally:
        st.Page = original_page

    spy.assert_called_once_with(
        artifact_center.render, title="Artifact Center", url_path="artifact-center"
    )


def _store_artifact_center_page() -> None:
    import streamlit as st

    from data_quality_toolkit.adapters.ui.pages import artifact_center

    st.session_state["_ac_page"] = artifact_center.artifact_center_page(st)


def test_factory_produces_a_real_streamlit_page_object() -> None:
    from streamlit.navigation.page import StreamlitPage
    from streamlit.testing.v1 import AppTest

    from data_quality_toolkit.adapters.ui.pages import artifact_center

    at = AppTest.from_function(_store_artifact_center_page)
    at.run()

    page: Any = at.session_state["_ac_page"]
    assert isinstance(page, StreamlitPage)
    assert page.title == "Artifact Center"
    assert page.icon == ""
    assert page.url_path == "artifact-center"
    # Same callable app.py registers under st.navigation — no drift possible.
    assert page._page is artifact_center.render
