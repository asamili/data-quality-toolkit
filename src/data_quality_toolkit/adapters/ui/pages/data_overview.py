"""Data Overview page: CSV profiling and quality assessment (full and large-data modes)."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, MutableMapping
from typing import Any, cast

import pandas as pd

from data_quality_toolkit.adapters.ui import journey
from data_quality_toolkit.adapters.ui.components.active_dataset_identity import (
    FULL_ANALYSIS_MODE,
    LARGE_FILE_MODE,
    LEGACY_FALLBACK_LABEL,
    LEGACY_STATUS,
    MANAGED_STATUS,
    build_active_dataset_identity,
    short_version_id,
)
from data_quality_toolkit.adapters.ui.components.dataset_context import (
    render_dataset_context_panel,
)
from data_quality_toolkit.adapters.ui.components.downloads import csv_download_button
from data_quality_toolkit.adapters.ui.components.errors import show_error
from data_quality_toolkit.adapters.ui.components.page_guidance import render_page_guidance
from data_quality_toolkit.adapters.ui.components.page_shell import (
    render_metric_cards,
    render_page_header,
)
from data_quality_toolkit.adapters.ui.components.source_hub import render_dataset_source_callout
from data_quality_toolkit.adapters.ui.components.storylens import render_storylens_card
from data_quality_toolkit.adapters.ui.components.workspace_save_ui import render_analysis_csv_save
from data_quality_toolkit.adapters.ui.eda import (
    _build_overview_table,
    _duplicate_row_count,
    _high_cardinality_flags,
    _load_df_and_assess,
    _numeric_summary,
)
from data_quality_toolkit.adapters.ui.services.assessment import _load_profile_chunked
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
from data_quality_toolkit.adapters.ui.services.smart_data_overview import (
    ANALYSIS_FULL,
    ANALYSIS_SAMPLE,
    EVIDENCE_LABELS,
    MAX_CONTENT_ROWS,
    MAX_GROUP_COLUMNS,
    ROLE_TITLES,
    SEVERITY_LABELS,
    STRATEGY_DESCRIPTIONS,
    STRATEGY_TITLES,
    PreviewIdentity,
    RecordSelection,
    SmartOverview,
    build_smart_overview,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext, get_dataset_context
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

# Opt-in Save-to-Workspace for the column-analysis CSV (additive; browser download
# stays). Defined locally; this gate adds no shared source keys.
_SAVE_COLUMN_ANALYSIS_BTN = "data_overview_save_column_analysis_btn"
# Large-mode column analysis save button (distinct key from the full-mode one).
_SAVE_LARGE_COLUMN_ANALYSIS_BTN = "data_overview_large_save_column_analysis_btn"
# Full-mode flagged-issues save button.
_SAVE_FLAGGED_ISSUES_BTN = "data_overview_save_flagged_issues_btn"
_ANALYSIS_SAVE_CAPTION = (
    "Downloads stay in your browser. Optionally save the column analysis under your "
    "Workspace Root / analysis; existing files are not overwritten."
)
_FLAGGED_ISSUES_SAVE_CAPTION = (
    "Downloads stay in your browser. Optionally save the flagged issues under your "
    "Workspace Root / analysis; existing files are not overwritten."
)

_LARGE_MODE_BANNER: str = (
    "**Large-file mode (profile-only):** "
    "Approximate profile via chunked streaming — no full-DataFrame load. "
    "Assessment, EDA, export, preprocessing plan, unique counts, "
    "outlier detection, and correlation are disabled."
)

# Fixed, privacy-safe refusal shown when a managed-looking dataset context has
# no valid managed trust root (root-first authority, fail-closed).
_MANAGED_FAIL_CLOSED_MESSAGE = (
    "The managed dataset context is not backed by a valid managed trust root. "
    "Reopen the managed version explicitly to continue."
)

# --- Smart Data Preview (bounded, active-version-aware) ----------------------
# One compact preview built from the profile/frame the page already loaded. It
# never triggers a second read, assessment, or profiling pass, and it never
# claims a heuristic role is schema truth.

_SMART_PREVIEW_TITLE = "Smart Data Preview"
_SMART_PREVIEW_LEGEND = (
    "How to read this: **fact** = measured from this dataset · "
    "**bounded sample** = seen only in the inspected rows · "
    "**likely (heuristic)** = a suggestion to confirm, not the schema · "
    "**not evaluated** = unavailable in this mode."
)
_SMART_GROUPS_EMPTY = "No columns are available to group."
_SMART_CALLOUTS_EMPTY = "No shape or risk callouts for this dataset."
_SMART_RECORDS_CAPTION = (
    "Deterministic picks for orientation — not a statistically representative sample."
)
_SMART_ROLE_CAPTION = (
    "Likely roles are heuristic suggestions derived from type, name, and bounded "
    "content evidence. They are not a declared schema."
)


def _managed_preview_identity(root: ManagedTrustRoot) -> PreviewIdentity:
    """Build display-safe preview identity from a valid managed trust root.

    Only the locator's bare display name and the shortened version id are used;
    the operator-typed version label and the machine-side absolute path are
    deliberately excluded, so no free text or path can reach the preview.
    """
    return PreviewIdentity(
        status=MANAGED_STATUS,
        label=root.locator.display_name,
        short_version_id=short_version_id(root.version_id),
        mode_label=LARGE_FILE_MODE if root.large_file_mode else FULL_ANALYSIS_MODE,
    )


def _context_preview_identity(context: DatasetContext | None) -> PreviewIdentity:
    """Build preview identity from the active context via the shared identity model."""
    if context is None:
        return PreviewIdentity(
            status=LEGACY_STATUS,
            label=LEGACY_FALLBACK_LABEL,
            mode_label=FULL_ANALYSIS_MODE,
        )
    identity = build_active_dataset_identity(context)
    return PreviewIdentity(
        status=identity.status,
        label=identity.label,
        short_version_id=identity.short_version_id,
        mode_label=identity.mode_label,
    )


def _smart_shape_line(overview: SmartOverview) -> str:
    """Return the compact shape line, labelled with its evidence class."""
    rows = "unknown" if overview.rows is None else f"{overview.rows:,}"
    evidence = EVIDENCE_LABELS[overview.shape_evidence]
    return f"**Shape ({evidence}):** {rows} rows × {overview.columns:,} columns"


def _smart_signal_rows(overview: SmartOverview) -> list[dict[str, Any]]:
    """Flatten the bounded group signals into display rows."""
    return [
        {
            "column": signal.name,
            "type": signal.dtype,
            "likely_role": ROLE_TITLES[signal.role],
            "evidence": EVIDENCE_LABELS[signal.role_evidence],
            "missing_pct": signal.missing_pct,
            "non_null": signal.non_null,
            "distinct": signal.distinct,
            "unique_pct": signal.unique_pct,
        }
        for signal in overview.displayed_signals
    ]


def _render_smart_groups(st: Any, overview: SmartOverview) -> None:
    """Render the semantic column groups and their compact per-column signals."""
    if not overview.groups:
        st.caption(_SMART_GROUPS_EMPTY)
        return
    st.caption(overview.group_summary())
    st.caption(_SMART_ROLE_CAPTION)
    st.dataframe(pd.DataFrame(_smart_signal_rows(overview)))
    if overview.groups_truncated:
        st.caption(f"Showing at most {MAX_GROUP_COLUMNS} columns per group.")
    if overview.content_columns_inspected:
        st.caption(
            f"Content heuristics inspected up to {MAX_CONTENT_ROWS} rows across "
            f"{overview.content_columns_inspected} column(s)."
        )


def _smart_record_frame(df: pd.DataFrame, selection: RecordSelection) -> pd.DataFrame:
    """Build the bounded record-preview frame without mutating the source frame."""
    positions = [record.position for record in selection.records]
    columns = [name for name in selection.columns if name in df.columns]
    subset = df.iloc[positions]
    if columns:
        subset = subset.loc[:, columns]
    labels = pd.DataFrame(
        {
            "row_index": [str(index) for index in subset.index],
            "picked_by": [STRATEGY_TITLES[record.strategy] for record in selection.records],
        }
    )
    return pd.concat([labels, subset.reset_index(drop=True)], axis=1)


def _render_smart_records(st: Any, overview: SmartOverview, df: pd.DataFrame | None) -> None:
    """Render deterministic representative records, or a safe unavailable state."""
    selection = overview.selection
    st.caption("**Representative records**")
    if not selection.available or df is None:
        st.caption(selection.reason or "Representative records are not available here.")
        return
    st.dataframe(_smart_record_frame(df, selection))
    strategies = " · ".join(
        f"{STRATEGY_TITLES[name]}: {STRATEGY_DESCRIPTIONS[name]}" for name in selection.strategies
    )
    st.caption(f"{_SMART_RECORDS_CAPTION} {strategies}.")
    if selection.columns_truncated:
        st.caption(
            f"Showing the first {len(selection.columns)} of {selection.total_columns} columns."
        )
    if overview.sample_derived:
        st.caption("These rows come from the bounded analysis sample, not the whole dataset.")


def _render_smart_callouts(st: Any, overview: SmartOverview) -> None:
    """Render the ranked, capped shape and risk callouts."""
    st.caption("**What to check first**")
    if not overview.callouts:
        st.caption(_SMART_CALLOUTS_EMPTY)
        return
    for callout in overview.callouts:
        severity = SEVERITY_LABELS[callout.severity]
        evidence = EVIDENCE_LABELS[callout.evidence]
        st.write(f"- **{severity}** · _{evidence}_ — {callout.message}")


def _render_smart_preview(st: Any, overview: SmartOverview, df: pd.DataFrame | None = None) -> None:
    """Render the whole compact Smart Preview block for an already-loaded dataset."""
    st.subheader(_SMART_PREVIEW_TITLE)
    st.caption(overview.identity.line)
    st.caption(_SMART_PREVIEW_LEGEND)
    st.write(_smart_shape_line(overview))
    _render_smart_groups(st, overview)
    _render_smart_records(st, overview, df)
    _render_smart_callouts(st, overview)


def _assess_frame_for_overview(df: pd.DataFrame) -> dict[str, Any]:
    """Profile and assess an already-materialized managed DataFrame.

    Mirrors the legacy load/profile/assess envelope (``profile`` +
    ``assessment``) without re-reading the source; the managed frame loader
    owns source access and cache identity.
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


def _managed_load_and_assess(
    session_state: MutableMapping[str, Any],
) -> tuple[pd.DataFrame | None, dict[str, Any] | None, str | None]:
    """Managed FULL load + assessment through the root-first dispatcher.

    Every refusal surfaces the loader's fixed privacy-safe message; no path or
    trust detail ever reaches the page.
    """
    try:
        df = get_managed_frame(session_state)
        out = get_managed_assessment(session_state, assessor=_assess_frame_for_overview)
    except ManagedFrameLoadError as exc:
        return None, None, str(exc)
    return df, out, None


def _render_managed_overview(
    st: Any, session_state: MutableMapping[str, Any], root: ManagedTrustRoot
) -> None:
    """Render the overview for a trusted managed version (root-first).

    Managed LARGE stays profile-only (chunked streaming from the trusted
    source; no DataFrame is ever materialized). Managed FULL dispatches
    through the managed frame loader under exact canonical cache identity.
    """
    identity = _managed_preview_identity(root)
    if root.large_file_mode:
        _render_data_overview_large_mode(st, root.locator.absolute_path, identity=identity)
        return
    df, out, err = _managed_load_and_assess(session_state)
    if err is not None:
        show_error(st, "Managed Dataset Error", err)
        return
    if df is None or out is None:
        return
    _render_full_overview_body(
        st, df, out, dataset_name=root.locator.display_name, identity=identity
    )


def _render_large_data_profile_overview(
    st: Any, envelope: dict[str, Any], *, identity: PreviewIdentity | None = None
) -> None:
    """Render profile-only view for large-data mode.

    No DataFrame, no EDA, no assessment, no preprocessing plan.
    Shows: persistent warning banner, row/col counts, the Smart Preview built
    from the same approximate profile, null table, and dtype table. The preview
    never forces a full materialization: it reads the chunked profile only and
    declares every reading as bounded-sample.
    """
    st.warning(_LARGE_MODE_BANNER)
    profile = envelope.get("profile") or {}
    st.write(
        f"**Dataset Profile (approximate):** "
        f"{profile.get('rows', '?')} rows × {profile.get('cols', '?')} columns"
    )
    _render_smart_preview(
        st,
        build_smart_overview(identity=identity, profile=profile, analysis_mode=ANALYSIS_SAMPLE),
    )
    overview = _build_overview_table(profile)
    if not overview:
        st.info("No column data available.")
        return
    st.subheader("Column Analysis")
    overview_df = pd.DataFrame(overview)
    st.dataframe(overview_df)
    csv_download_button(st, "Download column analysis as CSV", overview_df, "column_analysis.csv")
    render_analysis_csv_save(
        st,
        button_label="Save column analysis to workspace",
        key=_SAVE_LARGE_COLUMN_ANALYSIS_BTN,
        artifact="column_analysis",
        dataframe=overview_df,
        caption=_ANALYSIS_SAVE_CAPTION,
    )
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


def _render_data_overview_large_mode(
    st: Any, csv_path: str, *, identity: PreviewIdentity | None = None
) -> None:
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
    _render_large_data_profile_overview(st, envelope, identity=identity)


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
        step_label=journey.step_label("data_overview"),
    )
    render_page_guidance(
        st,
        purpose="Inspect structure, missingness, duplicates, data types, and the quality score.",
        inputs="The shared dataset context (or a CSV path fallback).",
        workflow="Review column health before deeper analysis.",
        next_step="EDA Explorer",
        compact=True,
    )
    session = cast(MutableMapping[str, Any], session_state if session_state is not None else {})
    context = get_dataset_context(session)
    decision = resolve_trust_authority(session)

    # The shared identity callout always renders exactly once (accepted discovery/history
    # contract). Trust governs data dispatch and provenance below it, never the
    # identity surface itself.
    if decision.managed and decision.root is not None:
        # Root-first: valid managed trust governs even over a stale mirror or
        # a manually entered path.
        render_dataset_source_callout(st, context, session_state=session)
        _render_managed_overview(st, session, decision.root)
        return
    render_dataset_source_callout(st, context)
    if decision.authority is TrustAuthority.FAIL_CLOSED:
        show_error(st, "Managed Dataset Error", _MANAGED_FAIL_CLOSED_MESSAGE)
        return

    if context is not None:
        render_dataset_context_panel(st, context)
        overview_csv = context.source_path
    else:
        st.caption("Advanced/manual CSV path override.")
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
    identity = _context_preview_identity(context)
    if large_mode:
        _render_data_overview_large_mode(st, overview_csv, identity=identity)
        return

    df, out, err = _load_df_and_assess(overview_csv)
    if err is not None:
        show_error(st, "Assessment Error", err)
        return
    if df is None or out is None:
        return
    _render_full_overview_body(
        st,
        df,
        out,
        dataset_name=context.display_name if context is not None else None,
        identity=identity,
    )


def _render_full_overview_body(
    st: Any,
    df: pd.DataFrame,
    out: dict[str, Any],
    *,
    dataset_name: str | None,
    identity: PreviewIdentity | None = None,
) -> None:
    """Render the FULL-mode overview body from a loaded frame and envelope.

    Shared verbatim by the legacy path-based flow and the managed root-first
    flow; rendering behavior is identical for both.
    """
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
            render_analysis_csv_save(
                st,
                button_label="Save flagged issues to workspace",
                key=_SAVE_FLAGGED_ISSUES_BTN,
                artifact="flagged_issues",
                dataframe=issues_df,
                dataset_name=dataset_name,
                caption=_FLAGGED_ISSUES_SAVE_CAPTION,
            )

    storylens = _build_headline_storylens(score, profile, issues)
    storylens.extend(_issue_explanations(issues))
    render_storylens_card(st, storylens)

    # Duplicate-row count is computed once and shared by the Smart Preview and
    # the detailed section below — the page never counts duplicates twice.
    duplicate_rows = _duplicate_row_count(df)
    _render_smart_preview(
        st,
        build_smart_overview(
            identity=identity,
            profile=profile,
            frame=df,
            duplicate_rows=duplicate_rows,
            analysis_mode=ANALYSIS_FULL,
        ),
        df,
    )

    st.write(
        f"**Dataset Profile**: {profile['rows']} rows × {profile['cols']} columns | {profile['memory_mb']:.2f} MB"
    )

    st.subheader("Column Analysis")
    overview = _build_overview_table(profile)
    overview_df = pd.DataFrame(overview)
    st.dataframe(overview_df)
    csv_download_button(st, "Download column analysis as CSV", overview_df, "column_analysis.csv")
    render_analysis_csv_save(
        st,
        button_label="Save column analysis to workspace",
        key=_SAVE_COLUMN_ANALYSIS_BTN,
        artifact="column_analysis",
        dataframe=overview_df,
        dataset_name=dataset_name,
        caption=_ANALYSIS_SAVE_CAPTION,
    )
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
    st.write(f"Duplicate rows: {duplicate_rows}")
    flags = _high_cardinality_flags(profile)
    if flags:
        st.warning(f"High-cardinality columns: {', '.join(flags)}")


def render() -> None:
    """st.navigation entry point."""
    import streamlit as st

    _render_data_overview(st, st.session_state)  # type: ignore[arg-type, unused-ignore]
