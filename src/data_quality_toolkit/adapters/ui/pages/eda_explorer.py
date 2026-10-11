"""EDA Explorer page: dataset loading and tab orchestration."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any, cast

import pandas as pd

from data_quality_toolkit.adapters.ui import journey
from data_quality_toolkit.adapters.ui.components.dataset_context import (
    render_dataset_context_panel,
)
from data_quality_toolkit.adapters.ui.components.errors import show_error
from data_quality_toolkit.adapters.ui.components.page_guidance import render_page_guidance
from data_quality_toolkit.adapters.ui.components.page_shell import render_page_header
from data_quality_toolkit.adapters.ui.components.source_hub import render_dataset_source_callout
from data_quality_toolkit.adapters.ui.components.states import render_warning_state
from data_quality_toolkit.adapters.ui.eda import _load_df_and_assess
from data_quality_toolkit.adapters.ui.eda_sections import (
    _SAVE_CATEGORIES_BTN,
    _SAVE_CORRELATION_BTN,
    _SAVE_CROSSTAB_BTN,
    _SAVE_DISTRIBUTION_BTN,
    _SAVE_MISSINGNESS_BTN,
    _SAVE_NUMERIC_BY_CATEGORY_BTN,
    _SAVE_OUTLIERS_BTN,
    _SAVE_SKEW_KURTOSIS_BTN,
    _SAVE_TIME_AGGREGATION_BTN,
    _SAVE_TIME_CATEGORIES_BTN,
    _eda_storylens,
    _render_correlation_matrix,
    _render_dataset_profile,
    _render_datetime_trend,
    _render_dtype_distribution,
    _render_duplicate_rows,
    _render_eda_bivariate,
    _render_eda_univariate,
    _render_missingness,
    _render_outlier_summary,
    render_advanced_tab,
    render_columns_tab,
    render_overview_tab,
    render_relationships_tab,
    render_time_tab,
)
from data_quality_toolkit.adapters.ui.services.managed_frame_loader import (
    ManagedFrameLoadError,
    get_managed_assessment,
    get_managed_frame,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    ManagedTrustRoot,
    TrustAuthority,
    resolve_trust_authority,
)
from data_quality_toolkit.adapters.ui.state.context import get_dataset_context

_EDA_TAB_LABELS = ["Overview", "Columns", "Relationships", "Time", "Advanced"]

# Fixed, privacy-safe refusal shown when a managed-looking dataset context has
# no valid managed trust root (root-first authority, fail-closed).
_MANAGED_FAIL_CLOSED_MESSAGE = (
    "The managed dataset context is not backed by a valid managed trust root. "
    "Reopen the managed version explicitly to continue."
)

_MANAGED_LARGE_EDA_MESSAGE = (
    "EDA is unavailable for the active managed large-file version. "
    "Reopen a full-analysis managed version to use EDA."
)

__all__ = [
    "_EDA_TAB_LABELS",
    "_SAVE_CATEGORIES_BTN",
    "_SAVE_CORRELATION_BTN",
    "_SAVE_CROSSTAB_BTN",
    "_SAVE_DISTRIBUTION_BTN",
    "_SAVE_MISSINGNESS_BTN",
    "_SAVE_NUMERIC_BY_CATEGORY_BTN",
    "_SAVE_OUTLIERS_BTN",
    "_SAVE_SKEW_KURTOSIS_BTN",
    "_SAVE_TIME_AGGREGATION_BTN",
    "_SAVE_TIME_CATEGORIES_BTN",
    "_eda_storylens",
    "_render_correlation_matrix",
    "_render_dataset_profile",
    "_render_datetime_trend",
    "_render_dtype_distribution",
    "_render_duplicate_rows",
    "_render_eda_bivariate",
    "_render_eda_explorer",
    "_render_eda_univariate",
    "_render_missingness",
    "_render_outlier_summary",
    "render",
]


def _assess_frame_for_eda(df: pd.DataFrame) -> dict[str, Any]:
    """Profile and assess an already-materialized managed DataFrame for EDA.

    Produces the same ``profile`` + ``assessment`` envelope the legacy loader
    returns, without re-reading the source; the managed frame loader owns
    source access and exact cache identity.
    """
    from data_quality_toolkit.domain.assessment.quality_checker import assess as _assess
    from data_quality_toolkit.domain.profiling.profiling_orchestrator import (
        run_profiling as _run_prof,
    )

    prof = _run_prof(df, "managed")
    assessment = _assess(cast(dict[str, Any], prof))
    return {
        "profile": {
            "rows": prof["rows"],
            "cols": prof["cols"],
            "memory_mb": prof["memory_mb"],
            "columns": prof["columns"],
        },
        "assessment": assessment,
    }


def _render_eda_tabs(
    st: Any, df: pd.DataFrame, result: dict[str, Any] | None, dataset_name: str | None
) -> None:
    """Render the five EDA tabs from a loaded frame (shared by both flows)."""
    profile = result.get("profile") if result is not None else None
    overview_tab, columns_tab, relationships_tab, time_tab, advanced_tab = st.tabs(_EDA_TAB_LABELS)
    with overview_tab:
        render_overview_tab(st, df, result, profile, dataset_name=dataset_name)
    with columns_tab:
        render_columns_tab(st, df, dataset_name=dataset_name)
    with relationships_tab:
        render_relationships_tab(st, df, dataset_name=dataset_name)
    with time_tab:
        render_time_tab(st, df)
    with advanced_tab:
        render_advanced_tab(st, df, dataset_name=dataset_name)


def _render_managed_eda(
    st: Any, session_state: MutableMapping[str, Any], root: ManagedTrustRoot
) -> None:
    """Render EDA for a trusted managed version (root-first, exact cache identity)."""
    if root.large_file_mode:
        render_warning_state(st, _MANAGED_LARGE_EDA_MESSAGE)
        return
    try:
        df = get_managed_frame(session_state)
        result = get_managed_assessment(session_state, assessor=_assess_frame_for_eda)
    except ManagedFrameLoadError as exc:
        show_error(st, "Managed Dataset Error", str(exc))
        return
    _render_eda_tabs(st, df, result, root.locator.display_name)


def _render_eda_explorer(st: Any, session_state: Mapping[str, Any] | None = None) -> None:
    """Render the EDA Explorer page: source selection, load, then tabbed sections."""
    render_page_header(
        st,
        "EDA Explorer",
        "Explore column distributions, relationships, and preprocessing recommendations.",
        step_label=journey.step_label("eda_explorer"),
    )
    render_page_guidance(
        st,
        purpose="Explore distributions, shape, outliers, correlations, and bivariate relationships.",
        inputs="The shared dataset (full analysis mode).",
        workflow="Review missingness and distributions, then correlations and bivariate views; "
        "download chart data where useful.",
        next_step="Preprocess Studio or Statistics Lab",
        compact=True,
    )
    session = cast(MutableMapping[str, Any], session_state if session_state is not None else {})
    context = get_dataset_context(session)
    dataset_name = context.display_name if context is not None else None
    decision = resolve_trust_authority(session)

    # The shared identity callout always renders exactly once (accepted discovery/history
    # contract). Trust governs data dispatch and provenance below it, never the
    # identity surface itself.
    if decision.managed and decision.root is not None:
        # Root-first: valid managed trust governs even over a stale mirror or
        # a manually entered path.
        render_dataset_source_callout(st, context, session_state=session)
        _render_managed_eda(st, session, decision.root)
        return
    render_dataset_source_callout(st, context)
    if decision.authority is TrustAuthority.FAIL_CLOSED:
        show_error(st, "Managed Dataset Error", _MANAGED_FAIL_CLOSED_MESSAGE)
        return

    if context is not None:
        render_dataset_context_panel(st, context)
        if context.large_file_mode:
            render_warning_state(
                st,
                "EDA is unavailable for the active large-file profile context. "
                "Return to Start and select full analysis mode to use EDA.",
            )
            return
        eda_csv = context.source_path
    else:
        st.caption("Advanced/manual CSV path override.")
        eda_csv = st.text_input("CSV path", placeholder="e.g., ./data/my_dataset.csv")
    if not eda_csv:
        st.info("💡 Start with a dataset context or enter a CSV path above to begin exploring.")
        return

    df, result, err = _load_df_and_assess(eda_csv)
    if err is not None:
        show_error(st, "Load Error", err)
        return
    if df is None:
        return

    _render_eda_tabs(st, df, result, dataset_name)


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_eda_explorer(st, st.session_state)  # type: ignore[arg-type, unused-ignore]
