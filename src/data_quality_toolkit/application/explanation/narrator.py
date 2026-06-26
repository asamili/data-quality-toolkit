"""StoryLens Level 0 — deterministic narrator (v2.9.0).

Pure functions: no file I/O, no DB access, no Streamlit, no storage imports,
no network, no datetime, no randomness. Same input → byte-identical output.

AI explanations are labeled as explanations of evidence, not validation.
DQT metrics/reports remain the source of truth.
"""

from __future__ import annotations

from typing import Literal

from data_quality_toolkit.application.explanation.models import Explanation
from data_quality_toolkit.application.explanation.provenance import (
    DRIFT_FEATURE,
    DRIFT_HISTORY_METRIC_KEYS,
    DRIFT_STATUS_METRIC_KEYS,
    ExplanationProvenance,
)

# Safety phrase required by the gate spec for every drift explanation.
_DRIFT_SAFETY = "Drift is a distribution change, not a defect or a cause."


def explain_quality_score(
    *,
    score: float,
    rows: int,
    columns: int,
    issues_total: int,
) -> Explanation:
    """Explain a DQT quality score result.

    ``score`` is a float in [0.0, 1.0] representing completeness-weighted
    quality. Severity: ok when score >= 0.90, warn otherwise.
    """
    pct = score * 100.0
    severity: Literal["ok", "warn"] = "ok" if score >= 0.90 else "warn"
    label = "good" if severity == "ok" else "below threshold"
    return Explanation(
        title=f"Quality score: {pct:.0f}% ({label})",
        summary=(
            f"Profiled {rows} rows × {columns} columns. "
            f"Quality score is {pct:.0f}% with {issues_total} issue(s) flagged."
        ),
        evidence=(
            f"score={score:.4f}",
            f"rows={rows}",
            f"columns={columns}",
            f"issues_total={issues_total}",
        ),
        why_it_matters=(
            "The quality score is the primary trust signal before data reaches "
            "a report or dashboard."
        ),
        recommended_action=(
            "Review the flagged issues. If score meets the publish threshold, "
            "proceed to EDA or export."
            if severity == "ok"
            else "Investigate flagged issues before publishing. Consider raising "
            "the null threshold or fixing upstream gaps."
        ),
        limitations=(
            "Score is completeness-weighted across all columns. "
            "It does not check business correctness, referential integrity, "
            "or values within expected ranges."
        ),
        severity=severity,
    )


def explain_missing_value_issue(
    *,
    column: str,
    null_pct: float,
    severity_label: str = "medium",
) -> Explanation:
    """Explain a missing-value issue on a specific column.

    Does not assert a root cause — explains only what was observed.
    """
    pct = null_pct * 100.0
    return Explanation(
        title=f"`{column}` has {pct:.0f}% missing values ({severity_label})",
        summary=(
            f"`{column}` is {pct:.0f}% empty. "
            f"DQT flagged this as a {severity_label}-severity completeness issue."
        ),
        evidence=(
            f"column={column}",
            f"null_pct={null_pct:.4f}",
            "issue_type=missing",
            f"severity={severity_label}",
        ),
        why_it_matters=(
            "Missing values can skew aggregates, break joins, and cause BI "
            "measures to under-count."
        ),
        recommended_action=(
            f"Confirm whether blanks in `{column}` are expected "
            "(e.g. an optional field) or indicate a load defect. "
            "If unexpected, investigate the upstream source."
        ),
        limitations=(
            "DQT reports the gap; it cannot determine why the values are absent. "
            "Absence may be intentional for this dataset."
        ),
        severity="warn",
    )


def explain_constant_column_issue(
    *,
    column: str,
) -> Explanation:
    """Explain a constant-column detection result.

    Notes that the detection may be legitimate for some datasets.
    """
    return Explanation(
        title=f"`{column}` is a constant column",
        summary=(
            f"Every row in `{column}` holds the same value. "
            "DQT flagged this as a constant-column issue."
        ),
        evidence=(
            f"column={column}",
            "issue_type=constant_column",
        ),
        why_it_matters=(
            "A constant column carries no analytic signal and may indicate "
            "a filtered extract or a placeholder field."
        ),
        recommended_action=(
            f"Confirm whether `{column}` being constant is expected "
            "(e.g. a single-currency export). If not, check the upstream filter. "
            "Consider dropping the column from analysis if it adds no value."
        ),
        limitations=(
            "A legitimately single-value column is not an error. "
            "DQT reports the structural observation; domain context determines "
            "whether remediation is needed."
        ),
        severity="info",
    )


def explain_drift_detected(
    *,
    column: str,
    metric: str,
    metric_value: float | None,
    breached: bool,
    run_id: str | None = None,
) -> Explanation:
    """Explain a drift-detected result for one column.

    Hard-codes the required safety phrase: drift is a distribution change,
    not a defect or a cause.
    """
    metric_str = f"{metric}={metric_value:.4f}" if metric_value is not None else f"{metric}=N/A"
    breach_label = "breach" if breached else "ok"
    sev: Literal["breach", "warn"] = "breach" if breached else "warn"
    run_fragment = f" (run {run_id})" if run_id else ""
    return Explanation(
        title=f"Drift detected on `{column}`{run_fragment} — {breach_label}",
        summary=(
            f"Statistical drift was detected on `{column}`. "
            f"{metric} indicates a distribution shift "
            f"({'threshold breached' if breached else 'no threshold breach'})."
        ),
        evidence=(
            f"column={column}",
            "drift_detected=true",
            metric_str,
            f"breached={breached}",
            *((f"run_id={run_id}",) if run_id else ()),
        ),
        why_it_matters=(
            "Drift signals that the current data distribution differs from the "
            "reference baseline, which may affect downstream model or report quality."
        ),
        recommended_action=(
            f"Inspect the reference-vs-current distribution chart for `{column}`. "
            "Determine whether the shift is expected (e.g. seasonal, new data source) "
            "or indicates an upstream data issue."
        ),
        limitations=(
            f"{_DRIFT_SAFETY} "
            "DQT reports the statistical observation; domain context is required "
            "to determine whether action is needed. "
            "Skipped columns carry a skip_reason and are not covered here."
        ),
        severity=sev,
    )


def explain_no_drift(
    *,
    drift_detected: bool = False,
    columns_tested: int | None = None,
    columns_skipped: int | None = None,
    run_id: str | None = None,
) -> Explanation:
    """Explain a no-drift / ok result.

    Notes that only tested columns are covered.
    """
    tested_str = str(columns_tested) if columns_tested is not None else "N/A"
    skipped_str = str(columns_skipped) if columns_skipped is not None else "N/A"
    run_fragment = f" (run {run_id})" if run_id else ""
    return Explanation(
        title=f"No drift detected{run_fragment} — ok",
        summary=(
            f"All tested columns are within drift thresholds{run_fragment}. "
            f"drift_detected={drift_detected}."
        ),
        evidence=(
            f"drift_detected={drift_detected}",
            f"columns_tested={tested_str}",
            f"columns_skipped={skipped_str}",
            *((f"run_id={run_id}",) if run_id else ()),
        ),
        why_it_matters=(
            "No drift means the current dataset is statistically consistent with "
            "the reference baseline for all tested columns."
        ),
        recommended_action=("No immediate action required. Continue monitoring with future runs."),
        limitations=(
            "Only tested columns are covered. "
            "Skipped columns carry a skip_reason and are excluded from this result. "
            f"{_DRIFT_SAFETY}"
        ),
        severity="ok",
    )


def explain_not_enough_runs(
    *,
    run_count: int = 0,
) -> Explanation:
    """Explain a not_enough_runs state (fewer than two runs for this dataset)."""
    return Explanation(
        title="Not enough history to compare",
        summary=(
            f"Fewer than two runs are available for this dataset "
            f"(current count: {run_count}). "
            "DQT requires at least two runs to produce a comparison."
        ),
        evidence=(
            f"run_count={run_count}",
            "state=not_enough_runs",
        ),
        why_it_matters=(
            "Run-to-run comparison and drift monitoring depend on having a "
            "reference run to compare against."
        ),
        recommended_action=(
            "Run `dqt export` at least twice for this dataset, then use "
            "`dqt compare` or the Run History page to see trends."
        ),
        limitations=(
            "No trend or drift conclusion can be drawn until at least two " "runs are available."
        ),
        severity="info",
    )


def explain_export_artifacts(
    *,
    artifact_basenames: tuple[str, ...],
    outdir_name: str | None = None,
) -> Explanation:
    """Explain the set of export artifacts produced by a DQT run.

    Accepts only basenames — never absolute paths.
    """
    outdir_fragment = f" to `{outdir_name}`" if outdir_name else ""
    return Explanation(
        title=f"Export complete{outdir_fragment}: {len(artifact_basenames)} artifact(s)",
        summary=(
            f"DQT wrote {len(artifact_basenames)} artifact(s){outdir_fragment}. "
            "Each artifact serves a specific downstream purpose."
        ),
        evidence=tuple(f"artifact={name}" for name in artifact_basenames),
        why_it_matters=(
            "Export artifacts are the handoff between DQT and downstream "
            "consumers: CI gates, BI tools, and pipeline sign-off workflows."
        ),
        recommended_action=(
            "Attach `quality_report.json` to a PR or CI step as the run summary. "
            "Load `fact_issues.csv` and `fact_quality_metrics.csv` into your BI tool. "
            "Use the star schema tables with `dqt build-pbi` for Power BI."
        ),
        limitations=(
            "Artifacts reflect this run only. "
            "Re-run `dqt export` to refresh after source data changes."
        ),
        severity="ok",
    )


# ----------------------------------------------------------------------------
# Drift-monitoring narrators (G27H-A). Pure + deterministic. Each attaches
# deterministic ExplanationProvenance and is specific to the Drift Explorer's
# drift-history workflow (distinct from generic Run-History/export advice).
# ----------------------------------------------------------------------------


def explain_drift_history_insufficient(
    *,
    run_count: int = 0,
    drifted_runs: int | None = None,
    dataset_id: str | None = None,
) -> Explanation:
    """Explain insufficient drift-monitoring *trend* history for the Drift Explorer.

    Two or more recorded monitoring runs are needed to interpret a drift trend
    over time. This is not about a single run's reference-vs-current comparison
    (each individual drift run already carries its own baseline-vs-current
    result); it is about having enough runs to read a history. ``drifted_runs``
    is included in evidence only when an authoritative count is supplied — it is
    never fabricated as zero.
    """
    drifted_evidence: tuple[str, ...]
    if drifted_runs is not None:
        drifted_evidence = (f"drifted_runs={drifted_runs}",)
        metric_keys = DRIFT_HISTORY_METRIC_KEYS
    else:
        drifted_evidence = ("drifted_runs=unavailable",)
        metric_keys = ("total_runs",)
    return Explanation(
        title="Not enough monitoring runs for a drift trend",
        summary=(
            f"Fewer than two monitoring runs are recorded for this dataset "
            f"(current run count: {run_count}). Two or more runs are needed to "
            "interpret a drift trend over time."
        ),
        evidence=(
            f"total_runs={run_count}",
            *drifted_evidence,
            "state=insufficient_trend_history",
        ),
        why_it_matters=(
            "A drift trend is read across runs. With a single run there is no "
            "history to compare against — though that one run still reports its "
            "own reference-vs-current drift result."
        ),
        recommended_action=(
            "Record at least two monitoring runs for this dataset (re-run the "
            "drift import or monitoring flow), then return to the Drift Explorer "
            "to read the drift trend. This is drift monitoring history, distinct "
            "from the Quality History trend."
        ),
        limitations=(
            "No drift trend can be read until at least two monitoring runs exist. "
            "Each individual run still carries its own reference-vs-current "
            f"result. {_DRIFT_SAFETY}"
        ),
        severity="info",
        provenance=ExplanationProvenance(
            source_feature=DRIFT_FEATURE,
            source_metric_keys=metric_keys,
            generation_mode="deterministic",
            dataset_id=dataset_id,
            run_id=None,
        ),
    )


def explain_run_drift_status(
    *,
    drift_detected: bool | None,
    columns_tested: int | None = None,
    columns_drifted: int | None = None,
    columns_skipped: int | None = None,
    run_id: str | None = None,
    dataset_id: str | None = None,
) -> Explanation:
    """Explain the drift status of a single (selected/latest) run.

    Branches deterministically on ``drift_detected``: drift present (``warn``),
    no drift (``ok``), or — when ``drift_detected`` is ``None`` — an *unknown*
    card (``info``). An unknown status is never converted into a no-drift
    reassurance. Counts render as ``N/A`` when missing — never coerced to zero.
    """
    tested_str = str(columns_tested) if columns_tested is not None else "N/A"
    drifted_str = str(columns_drifted) if columns_drifted is not None else "N/A"
    skipped_str = str(columns_skipped) if columns_skipped is not None else "N/A"
    status_str = "unknown" if drift_detected is None else str(drift_detected)
    run_fragment = f" (run {run_id})" if run_id else ""
    provenance = ExplanationProvenance(
        source_feature=DRIFT_FEATURE,
        source_metric_keys=DRIFT_STATUS_METRIC_KEYS,
        generation_mode="deterministic",
        dataset_id=dataset_id,
        run_id=run_id,
    )
    evidence = (
        f"drift_detected={status_str}",
        f"columns_tested={tested_str}",
        f"columns_drifted={drifted_str}",
        f"columns_skipped={skipped_str}",
        *((f"run_id={run_id}",) if run_id else ()),
    )
    if drift_detected is None:
        return Explanation(
            title=f"Drift status unknown for latest run{run_fragment}",
            summary=(
                f"The drift status of the latest run is unavailable{run_fragment}. "
                "No drift conclusion can be drawn for this run."
            ),
            evidence=evidence,
            why_it_matters=(
                "Acting on an unknown status as if it were 'no drift' would be "
                "false reassurance. The status must be resolved before relying on it."
            ),
            recommended_action=(
                "Open this run in the Drift Explorer to confirm whether its drift "
                "result was recorded, or re-run the monitoring flow for this dataset."
            ),
            limitations=(
                "Drift status is unavailable for this run; this is not a no-drift "
                f"result. {_DRIFT_SAFETY}"
            ),
            severity="info",
            provenance=provenance,
        )
    if drift_detected:
        return Explanation(
            title=f"Drift present in latest run{run_fragment} — review",
            summary=(
                f"The latest run reports drift{run_fragment}: "
                f"{drifted_str} of {tested_str} tested columns drifted."
            ),
            evidence=evidence,
            why_it_matters=(
                "Drift means the current distribution differs from the reference "
                "baseline for one or more tested columns, which may affect "
                "downstream model or report quality."
            ),
            recommended_action=(
                "Open the drifted columns in the Drift Explorer and inspect each "
                "reference-vs-current distribution. Decide whether each shift is "
                "expected (e.g. seasonal, new source) or an upstream data issue."
            ),
            limitations=(
                f"{_DRIFT_SAFETY} Only tested columns are covered; skipped columns "
                "carry a skip_reason and are excluded."
            ),
            severity="warn",
            provenance=provenance,
        )
    return Explanation(
        title=f"No drift in latest run{run_fragment} — ok",
        summary=(
            f"The latest run reports no drift{run_fragment}. All tested columns "
            f"({tested_str}) are within drift thresholds."
        ),
        evidence=evidence,
        why_it_matters=(
            "No drift means the current dataset is statistically consistent with "
            "the reference baseline for all tested columns."
        ),
        recommended_action=(
            "No immediate action required. Continue recording drift runs to extend "
            "the drift-history comparison."
        ),
        limitations=(
            "Only tested columns are covered; skipped columns carry a skip_reason "
            f"and are excluded. {_DRIFT_SAFETY}"
        ),
        severity="ok",
        provenance=provenance,
    )


def explain_drift_threshold_fact(
    *,
    metric: str,
    metric_value: float | None,
    threshold: float,
    run_id: str | None = None,
    dataset_id: str | None = None,
) -> Explanation:
    """Explain one metric-vs-threshold fact for drift monitoring.

    Breach uses strictly-greater (``metric_value > threshold``); equality is not
    a breach, mirroring the drift threshold evaluators. A missing metric value
    renders as ``N/A`` and is never treated as an observed zero or a breach.
    """
    breached = metric_value is not None and metric_value > threshold
    value_str = f"{metric_value:.4f}" if metric_value is not None else "N/A"
    run_fragment = f" (run {run_id})" if run_id else ""
    sev: Literal["breach", "ok"] = "breach" if breached else "ok"
    breach_label = "breach" if breached else "within threshold"
    return Explanation(
        title=f"{metric} {breach_label}{run_fragment}",
        summary=(
            f"{metric}={value_str} against threshold {threshold:.4f}. "
            f"{'Threshold breached' if breached else 'No threshold breach'} "
            "(breach requires strictly greater than the threshold)."
        ),
        evidence=(
            f"metric={metric}",
            f"{metric}={value_str}",
            f"threshold={threshold:.4f}",
            f"breached={breached}",
            *((f"run_id={run_id}",) if run_id else ()),
        ),
        why_it_matters=(
            "Threshold facts turn a raw drift metric into an actionable signal "
            "without overstating significance."
        ),
        recommended_action=(
            "Review this metric for the affected run in the Drift Explorer."
            if breached
            else "No action required for this metric; continue monitoring."
        ),
        limitations=(
            "A missing metric value is reported as unavailable, not as zero. " f"{_DRIFT_SAFETY}"
        ),
        severity=sev,
        provenance=ExplanationProvenance(
            source_feature=DRIFT_FEATURE,
            source_metric_keys=(metric,),
            generation_mode="deterministic",
            dataset_id=dataset_id,
            run_id=run_id,
        ),
    )
