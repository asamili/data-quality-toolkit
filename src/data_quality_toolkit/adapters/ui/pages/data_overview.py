"""Data Overview page: CSV profiling and quality assessment (full and large-data modes)."""

from __future__ import annotations

import dataclasses
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
)
from data_quality_toolkit.adapters.ui.components.storylens import render_storylens_card
from data_quality_toolkit.adapters.ui.eda import (
    _build_overview_table,
    _duplicate_row_count,
    _high_cardinality_flags,
    _load_df_and_assess,
    _numeric_summary,
)
from data_quality_toolkit.adapters.ui.services.assessment import _load_profile_chunked
from data_quality_toolkit.adapters.ui.state.context import get_dataset_context
from data_quality_toolkit.application.explanation import (
    Explanation,
    ExplanationProvenance,
    explain_constant_column_issue,
    explain_missing_value_issue,
    explain_quality_score,
)
from data_quality_toolkit.application.explanation.ai_adapter.data_overview import (
    build_data_overview_facts,
)
from data_quality_toolkit.application.explanation.ai_adapter.fallback import try_explain

_DATA_OVERVIEW_PROVENANCE = ExplanationProvenance(
    source_feature="data_overview",
    source_metric_keys=("quality_score", "rows", "columns", "issues_total"),
    generation_mode="deterministic",
)

_MAX_ISSUE_EXPLANATIONS = 3

_LARGE_MODE_BANNER: str = (
    "**Large-file mode (profile-only):** "
    "Approximate profile via chunked streaming — no full-DataFrame load. "
    "Assessment, EDA, export, preprocessing plan, unique counts, "
    "outlier detection, and correlation are disabled."
)


def _render_large_data_profile_overview(st: Any, envelope: dict[str, Any]) -> None:
    """Render profile-only view for large-data mode.

    No DataFrame, no EDA, no assessment, no preprocessing plan.
    Shows: persistent warning banner, row/col counts, null table, dtype table.
    """
    st.warning(_LARGE_MODE_BANNER)
    profile = envelope.get("profile") or {}
    st.write(
        f"**Dataset Profile (approximate):** "
        f"{profile.get('rows', '?')} rows × {profile.get('cols', '?')} columns"
    )
    overview = _build_overview_table(profile)
    if not overview:
        st.info("No column data available.")
        return
    st.subheader("Column Analysis")
    overview_df = pd.DataFrame(overview)
    st.dataframe(overview_df)
    csv_download_button(st, "Download column analysis as CSV", overview_df, "column_analysis.csv")
    null_df = pd.DataFrame(
        {"null_pct": [r["null_pct"] for r in overview]},
        index=[r["column"] for r in overview],
    )
    if null_df["null_pct"].sum() > 0:
        st.caption("Null % by column")
        st.bar_chart(null_df)
    unsupported = envelope.get("unsupported_metrics") or []
    if unsupported:
        st.caption(f"Metrics unavailable in large-file mode: {', '.join(unsupported)}")


def _render_data_overview_large_mode(st: Any, csv_path: str) -> None:
    """Large-data mode branch: chunked profile-only, no full-DataFrame load."""
    chunksize = int(
        st.number_input(
            "Chunk size (rows per chunk)",
            min_value=1_000,
            max_value=1_000_000,
            value=100_000,
            step=10_000,
        )
    )
    envelope, err = _load_profile_chunked(csv_path, chunksize)
    if err is not None:
        show_error(st, "Profile Error", err)
        return
    if envelope is None:
        return
    _render_large_data_profile_overview(st, envelope)


def _issue_explanations(issues: list[dict[str, Any]]) -> list[Explanation]:
    """Map up to N supported issue dicts to deterministic Explanations.

    Preserves issues-list order. Skips any issue whose required facts are
    absent or whose type is unsupported. Never raises, never fabricates.
    Explanation only, not validation — DQT metrics remain the source of truth.
    """
    out: list[Explanation] = []
    for issue in issues:
        if len(out) >= _MAX_ISSUE_EXPLANATIONS:
            break
        itype = issue.get("type")
        column = issue.get("column")
        if not column:
            continue
        if itype == "missing":
            pct = issue.get("pct")
            # require a real numeric percentage; never fabricate one
            if not isinstance(pct, int | float) or isinstance(pct, bool):
                continue
            out.append(
                explain_missing_value_issue(
                    column=str(column),
                    null_pct=float(pct),
                    severity_label=str(issue.get("severity", "medium")),
                )
            )
        elif itype == "constant_column":
            out.append(explain_constant_column_issue(column=str(column)))
        # any other type → skip silently
    return out


def _build_headline_storylens(
    score: float, profile: dict[str, Any], issues: list[dict[str, Any]]
) -> list[Explanation]:
    """Build the headline StoryLens entry.

    Always returns the deterministic fallback if the AI-adapter wrapper fails.
    Returns [] only if even the deterministic narrator cannot run (malformed profile).
    """
    try:
        deterministic = explain_quality_score(
            score=score,
            rows=int(profile["rows"]),
            columns=int(profile["cols"]),
            issues_total=len(issues),
        )
        deterministic = dataclasses.replace(deterministic, provenance=_DATA_OVERVIEW_PROVENANCE)
    except Exception:
        return []

    try:
        _memory_mb: float | None = None
        try:
            _memory_mb = float(profile["memory_mb"])
        except (KeyError, TypeError, ValueError):
            pass
        _facts = build_data_overview_facts(
            score=score,
            rows=int(profile["rows"]),
            columns=int(profile["cols"]),
            issues=issues,
            deterministic_fallback=deterministic,
            memory_mb=_memory_mb,
        )
        result = try_explain(_facts)
        return [dataclasses.replace(result, provenance=_DATA_OVERVIEW_PROVENANCE)]
    except Exception:
        return [deterministic]


def _render_overview_metrics(
    st: Any,
    *,
    completeness: float,
    quality_score: float | None,
    issues_count: int,
) -> None:
    """Render the headline score cards, labeling completeness and quality distinctly."""
    cards: list[dict[str, Any]] = []
    if quality_score is not None:
        cards.append(
            {
                "label": "Quality Score",
                "value": f"{quality_score:.2%}",
                "help": "Overall score: completeness minus capped rule penalties.",
            }
        )
    cards.append(
        {
            "label": "Completeness",
            "value": f"{completeness:.2%}",
            "help": "Column-weighted share of non-missing cells.",
        }
    )
    cards.append({"label": "Issues Flagged", "value": str(issues_count)})
    render_metric_cards(st, cards)
    if quality_score is not None:
        st.caption(
            "Quality Score = completeness − capped rule penalties. See the "
            "Quality Score / Rule Breakdown page for the full formula."
        )


def _render_data_overview(st: Any, session_state: Mapping[str, Any] | None = None) -> None:
    """Render the Data Overview section: shape, per-column table, stats, duplicates."""
    render_page_header(
        st,
        "Data Overview",
        "Perform automated quality assessment on a CSV file.",
        step_label="Step 2 of 11 — Data Overview",
    )
    context = get_dataset_context(session_state or {})
    if context is not None:
        render_dataset_context_panel(st, context)
        overview_csv = context.source_path
    else:
        overview_csv = st.text_input("CSV path", placeholder="e.g., ./data/my_dataset.csv")
    if not overview_csv:
        st.info("💡 Start with a dataset context or enter a CSV path above to begin profiling.")
        return

    large_mode = (
        context.large_file_mode
        if context is not None
        else st.checkbox(
            "Large-data mode (profile-only, chunked streaming)",
            help=(
                "Enable for files too large to load into memory. "
                "Uses chunked streaming — no full-DataFrame load. "
                "Assessment, EDA, export, and preprocessing plan are disabled."
            ),
        )
    )
    if large_mode:
        _render_data_overview_large_mode(st, overview_csv)
        return

    df, out, err = _load_df_and_assess(overview_csv)
    if err is not None:
        show_error(st, "Assessment Error", err)
        return
    if df is None or out is None:
        return

    profile = out["profile"]
    assessment = out["assessment"]
    score = float(assessment["score"])
    quality_raw = assessment.get("quality_score")
    quality_score = (
        float(quality_raw)
        if isinstance(quality_raw, int | float) and not isinstance(quality_raw, bool)
        else None
    )
    issues = list(assessment.get("issues") or [])

    st.divider()
    _render_overview_metrics(
        st, completeness=score, quality_score=quality_score, issues_count=len(issues)
    )

    if issues:
        issues_df = pd.DataFrame(issues)
        with st.expander("View Flagged Issues"):
            st.dataframe(issues_df)
            csv_download_button(st, "Download issues as CSV", issues_df, "flagged_issues.csv")

    storylens = _build_headline_storylens(score, profile, issues)
    storylens.extend(_issue_explanations(issues))
    render_storylens_card(st, storylens)

    st.write(
        f"**Dataset Profile**: {profile['rows']} rows × {profile['cols']} columns | {profile['memory_mb']:.2f} MB"
    )

    st.subheader("Column Analysis")
    overview = _build_overview_table(profile)
    overview_df = pd.DataFrame(overview)
    st.dataframe(overview_df)
    csv_download_button(st, "Download column analysis as CSV", overview_df, "column_analysis.csv")
    null_df = pd.DataFrame(
        {"null_pct": [r["null_pct"] for r in overview]},
        index=[r["column"] for r in overview],
    )
    if null_df["null_pct"].sum() > 0:
        st.caption("Null % by column")
        st.bar_chart(null_df)
    numeric = _numeric_summary(df)
    if numeric is not None:
        st.subheader("Numeric Summary")
        st.dataframe(numeric)
    st.write(f"Duplicate rows: {_duplicate_row_count(df)}")
    flags = _high_cardinality_flags(profile)
    if flags:
        st.warning(f"High-cardinality columns: {', '.join(flags)}")


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_data_overview(st, st.session_state)  # type: ignore[arg-type, unused-ignore]
