"""Single source of truth for the Streamlit UI journey (navigation) order.

The ordered ``JOURNEY`` list mirrors the page registry built in ``app.main``'s
``st.navigation`` call (groups Start -> Analyze -> Prepare -> Operate -> Deliver
-> System). It drives the per-page ``Step N of M`` labels so the count and the
ordering stay in lockstep with the real page surface and can never silently
drift (previously each page hard-coded its own smaller count while the registry
grew to 16 pages). Pure data plus a string helper: no Streamlit import, no I/O.
"""

from __future__ import annotations

# Ordered ``(page_key, short journey name)`` pairs. Order mirrors app.main's
# st.navigation registry. ``page_key`` is a stable slug each page uses to look up
# its own label; the short name is operator-friendly and may differ from the
# longer navigation title (e.g. "Quality Score" vs "Quality Score / Rule
# Breakdown").
JOURNEY: tuple[tuple[str, str], ...] = (
    ("start", "Start / Load Dataset"),
    ("data_overview", "Data Overview"),
    ("eda_explorer", "EDA Explorer"),
    ("statistics_lab", "Statistics Lab"),
    ("quality_score", "Quality Score"),
    ("preprocess_studio", "Preprocess Studio"),
    ("pipeline_runner", "Pipeline Runner"),
    ("drift_explorer", "Drift Monitoring"),
    ("export", "Export"),
    ("run_history", "Quality History"),
    ("artifact_center", "Artifact Center"),
    ("kpi_catalog", "KPI Catalog"),
    ("dim_time", "Dim Time"),
    ("manifest_viewer", "Manifest Viewer"),
    ("settings_diagnostics", "Settings / Governance"),
    ("help_about", "Help / About"),
)

JOURNEY_STEP_COUNT: int = len(JOURNEY)

_POSITION: dict[str, int] = {key: index + 1 for index, (key, _) in enumerate(JOURNEY)}
_NAME: dict[str, str] = dict(JOURNEY)


def step_label(page_key: str) -> str:
    """Return the canonical ``Step N of M — <Name>`` journey label for a page.

    ``page_key`` must be one of the keys in :data:`JOURNEY`; an unknown key
    raises :class:`KeyError` so a mis-wired page fails loudly in tests rather
    than shipping a silently wrong label.
    """
    return f"Step {_POSITION[page_key]} of {JOURNEY_STEP_COUNT} — {_NAME[page_key]}"
