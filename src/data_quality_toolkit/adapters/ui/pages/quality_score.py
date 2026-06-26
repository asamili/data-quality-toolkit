"""Quality Score / Rule Breakdown page: explain how the overall score is reached.

Reads the existing assessment result (same hardened load path as Data Overview)
and the deterministic explainability helpers. Renders the completeness score,
the penalty-adjusted overall quality score, the formula, the severity-penalty
table, the caps/excluded rules, and a per-rule contribution table. It changes no
scoring logic — it only explains the published rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.components.dataset_context import (
    render_dataset_context_panel,
)
from data_quality_toolkit.adapters.ui.components.downloads import csv_download_button
from data_quality_toolkit.adapters.ui.components.errors import show_error
from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_metric_cards,
    render_page_header,
    render_section_header,
    render_status_chip,
)
from data_quality_toolkit.adapters.ui.components.states import render_warning_state
from data_quality_toolkit.adapters.ui.eda import _load_df_and_assess
from data_quality_toolkit.adapters.ui.services.quality_score import (
    formula_caption,
    penalty_breakdown,
    rule_contribution_rows,
    score_overview,
    severity_penalty_table,
)
from data_quality_toolkit.adapters.ui.state.context import get_dataset_context


def _format_pct(value: float | None) -> str:
    return f"{value:.2%}" if value is not None else "N/A"


def _render_score_cards(st: Any, overview: Mapping[str, Any]) -> None:
    completeness = overview["completeness_score"]
    quality = overview["quality_score"]
    headline = quality if quality is not None else completeness
    render_metric_cards(
        st,
        [
            {
                "label": "Quality Score",
                "value": _format_pct(headline),
                "help": (
                    "Overall score: completeness minus capped rule penalties."
                    if quality is not None
                    else "Penalty-adjusted score unavailable; showing completeness."
                ),
            },
            {
                "label": "Completeness",
                "value": _format_pct(completeness),
                "help": "Column-weighted share of non-missing cells.",
            },
            {"label": "Issues Flagged", "value": str(overview["issues_total"])},
        ],
    )
    if overview["meets_threshold"]:
        render_status_chip(
            st,
            f"Meets the {overview['publish_threshold']:.0%} publish threshold.",
            tone="ok",
        )
    else:
        render_status_chip(
            st,
            f"Below the {overview['publish_threshold']:.0%} publish threshold — review flagged rules.",
            tone="warn",
        )


def _render_penalty_breakdown(st: Any, breakdown: Mapping[str, Any]) -> None:
    render_section_header(st, "Penalty breakdown")
    rows = [
        {
            "bucket": "Schema",
            "raw_penalty": breakdown["schema_penalty_raw"],
            "applied_penalty": breakdown["schema_penalty_applied"],
            "cap": breakdown["schema_penalty_cap"],
        },
        {
            "bucket": "Distribution / other",
            "raw_penalty": breakdown["distribution_penalty_raw"],
            "applied_penalty": breakdown["distribution_penalty_applied"],
            "cap": breakdown["distribution_penalty_cap"],
        },
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.caption(
        f"Excluded from penalties (already in completeness): "
        f"{', '.join(breakdown['excluded_types'])}. "
        f"Null-issue threshold: {breakdown['null_threshold']:.0%}."
    )
    derived = breakdown["derived_quality_score"]
    reported = breakdown["reported_quality_score"]
    st.write(
        f"**Derived from these rules:** {derived:.2%} "
        f"(completeness {breakdown['completeness_score']:.2%} − schema "
        f"{breakdown['schema_penalty_applied']:.2%} − distribution "
        f"{breakdown['distribution_penalty_applied']:.2%})."
    )
    if reported is not None and abs(reported - derived) > 1e-9:
        st.caption(
            "The authoritative quality score differs from the value derived here; this "
            "is expected when per-column config (e.g. critical-column multipliers) applies."
        )


def _render_rule_table(st: Any, assessment: Mapping[str, Any]) -> None:
    render_section_header(st, "Per-rule contribution", "How each flagged issue affects the score.")
    rows = rule_contribution_rows(assessment)
    if not rows:
        st.info("No issues were flagged for this dataset, so no penalties were applied.")
        return
    table = pd.DataFrame(rows)
    st.dataframe(table, hide_index=True)
    csv_download_button(st, "Download rule breakdown as CSV", table, "quality_rule_breakdown.csv")


def _render_quality_score(st: Any, session_state: Mapping[str, Any] | None = None) -> None:
    """Render the Quality Score / Rule Breakdown page body."""
    render_page_header(
        st,
        "Quality Score / Rule Breakdown",
        "See how the overall quality score is calculated and which rules affected it.",
        step_label="Step 5 of 11 — Quality Score",
    )
    context = get_dataset_context(session_state or {})
    if context is not None:
        render_dataset_context_panel(st, context)
        if context.large_file_mode:
            render_warning_state(
                st,
                "Quality-score breakdown needs full analysis mode. Return to Start and "
                "select full analysis to see the rule contributions.",
            )
            return
        csv_path = context.source_path
    else:
        csv_path = st.text_input("CSV path", placeholder="e.g., ./data/my_dataset.csv")
    if not csv_path:
        st.info("💡 Start with a dataset context or enter a CSV path above to see the breakdown.")
        return

    df, result, err = _load_df_and_assess(csv_path)
    if err is not None:
        show_error(st, "Assessment Error", err)
        return
    if result is None:
        return

    assessment = result.get("assessment") or {}
    _render_score_cards(st, score_overview(assessment))

    render_section_header(st, "How the score is calculated")
    st.caption(formula_caption())

    st.write("**Severity penalties** (points subtracted per counted issue):")
    st.dataframe(pd.DataFrame(severity_penalty_table()), hide_index=True)

    _render_penalty_breakdown(st, penalty_breakdown(assessment))
    _render_rule_table(st, assessment)


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_quality_score(st, st.session_state)  # type: ignore[arg-type, unused-ignore]
