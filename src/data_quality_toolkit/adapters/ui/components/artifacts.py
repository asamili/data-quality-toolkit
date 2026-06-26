"""Artifact Center presentation helpers for Streamlit pages."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from data_quality_toolkit.adapters.ui.services.artifacts import (
    ArtifactDisplayRow,
    group_artifact_rows,
)


def render_artifact_center(
    st: Any,
    rows: Iterable[ArtifactDisplayRow],
    *,
    title: str = "Artifact Center",
) -> None:
    """Render safe, grouped artifact rows.

    All row data is expected to come from ``services.artifacts`` so no full path
    columns are accepted or displayed here.
    """
    items = list(rows)
    st.subheader(title)
    st.caption(
        "Only artifact basenames are shown here. Local files and generated reports "
        "should be reviewed before sharing."
    )
    if not items:
        st.info("No generated artifacts are available yet.")
        return

    for category, category_rows in group_artifact_rows(items):
        st.write(f"**{category.title()}**")
        st.dataframe(
            [row.to_display_dict() for row in category_rows],
            use_container_width=True,
        )
