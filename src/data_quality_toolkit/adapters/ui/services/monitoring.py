"""Drift-monitoring service wrappers for the Drift Explorer UI page.

Streamlit-free seam between the page layer and the shared G2 monitoring
view-model (``application.monitoring.view_model``). Each loader returns an
``(result, err)`` tuple so the page can stay free of bare try/except blocks,
mirroring ``services.assessment``.

This module must not import streamlit, must not import ``adapters.storage``
directly, must not calculate drift, and must not write to SQLite. All data
access flows through the view-model builders, which themselves read only via
the root ``data_quality_toolkit.api`` seam.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data_quality_toolkit.api import (
    ColumnDrift,
    DistributionBin,
    MonitoringOverview,
    RunDetail,
    build_distribution_series,
    build_monitoring_overview,
    build_run_detail,
    evaluate_drift_rate_threshold,
    evaluate_psi_threshold,
)
from data_quality_toolkit.application.explanation import (
    Explanation,
    explain_drift_history_insufficient,
    explain_drift_threshold_fact,
    explain_run_drift_status,
)
from data_quality_toolkit.shared.error_contract import to_error_info


def redact_path_to_basename(path: str | None) -> str:
    """Return only the basename of a path (directories stripped).

    Platform-independent: strips both POSIX (``/``) and Windows (``\\``)
    separators regardless of the host OS. Returns an empty string for ``None``
    or a blank path.
    """
    if not path or not path.strip():
        return ""
    normalized = path.strip().replace("\\", "/")
    return normalized.rsplit("/", 1)[-1]


def _resolve_db_path(db_path_str: str) -> tuple[Path | None, str | None]:
    """Validate a user-supplied DB path. Returns (path, None) or (None, error)."""
    cleaned = db_path_str.strip()
    if not cleaned:
        return None, "No database path provided."
    path = Path(cleaned)
    if not path.exists():
        safe_name = redact_path_to_basename(cleaned) or "selected database"
        return None, f"Database not found: {safe_name}"
    return path, None


def _safe_error_message(exc: Exception, db_path_str: str) -> str:
    """Return a structured error message with the selected DB path redacted."""
    message = to_error_info(exc)["message"]
    cleaned = db_path_str.strip()
    safe_name = redact_path_to_basename(cleaned) or "selected database"
    candidates = {
        cleaned,
        cleaned.replace("\\", "/"),
        cleaned.replace("/", "\\"),
        str(Path(cleaned)),
    }
    for candidate in sorted(candidates, key=len, reverse=True):
        if candidate and candidate != safe_name:
            message = message.replace(candidate, safe_name)
    return message


def load_monitoring_overview(
    db_path_str: str,
    *,
    current_dataset_id: str | None = None,
    limit: int | None = None,
) -> tuple[MonitoringOverview | None, str | None]:
    """Load the top-level monitoring overview.

    Returns ``(overview, None)`` or ``(None, error_message)``. A valid but empty
    database yields an overview with a zeroed summary and no runs (not an error),
    because the view-model tolerates missing/empty data without raising.
    """
    path, err = _resolve_db_path(db_path_str)
    if err is not None:
        return None, err
    if path is None:
        return None, "No database path provided."
    try:
        overview = build_monitoring_overview(
            path,
            current_dataset_id=(current_dataset_id.strip() or None) if current_dataset_id else None,
            limit=limit,
        )
        return overview, None
    except Exception as exc:
        return None, _safe_error_message(exc, db_path_str)


def load_run_detail(
    db_path_str: str,
    run_id: str,
    *,
    include_distributions: bool = True,
) -> tuple[RunDetail | None, str | None]:
    """Load a single run's detail (run row, column drifts, distributions).

    Returns ``(detail, None)`` or ``(None, error_message)``.
    """
    path, err = _resolve_db_path(db_path_str)
    if err is not None:
        return None, err
    if path is None:
        return None, "No database path provided."
    cleaned_run = run_id.strip()
    if not cleaned_run:
        return None, "No run_id provided."
    try:
        detail = build_run_detail(path, cleaned_run, include_distributions=include_distributions)
        return detail, None
    except Exception as exc:
        return None, _safe_error_message(exc, db_path_str)


def load_distribution_series(
    db_path_str: str,
    run_id: str,
    column_name: str,
) -> tuple[list[DistributionBin] | None, str | None]:
    """Load distribution bins for one run+column.

    Returns ``(bins, None)`` (possibly an empty list) or ``(None, error_message)``.
    """
    path, err = _resolve_db_path(db_path_str)
    if err is not None:
        return None, err
    if path is None:
        return None, "No database path provided."
    cleaned_run = run_id.strip()
    cleaned_col = column_name.strip()
    if not cleaned_run or not cleaned_col:
        return None, "Both run_id and column are required."
    try:
        bins = build_distribution_series(path, cleaned_run, cleaned_col)
        return bins, None
    except Exception as exc:
        return None, _safe_error_message(exc, db_path_str)


# ----------------------------------------------------------------------------
# Dataclass -> plain dict/list converters for Streamlit display widgets.
# ----------------------------------------------------------------------------


def overview_to_dict(overview: MonitoringOverview) -> dict[str, Any]:
    """Return the overview as a plain JSON-ready dict."""
    return overview.to_dict()


def runs_to_dicts(overview: MonitoringOverview) -> list[dict[str, Any]]:
    """Return the overview's run rows as a list of plain dicts for tables."""
    return [r.to_dict() for r in overview.runs]


def columns_to_dicts(columns: list[ColumnDrift]) -> list[dict[str, Any]]:
    """Return column-drift results as a list of plain dicts for tables."""
    return [c.to_dict() for c in columns]


def distributions_to_dicts(bins: list[DistributionBin]) -> list[dict[str, Any]]:
    """Return distribution bins as a list of plain dicts for tables/charts."""
    return [b.to_dict() for b in bins]


# ----------------------------------------------------------------------------
# Privacy / formatting helpers. Bounded, dependency-free display helpers that
# preserve unknown/unavailable values and never surface full local paths.
# ----------------------------------------------------------------------------


def format_probability(value: float | None) -> str:
    """Format a distribution probability for display.

    A missing probability is reported as ``"unavailable"`` — never coerced to an
    observed zero — preserving missing-probability semantics at the contract level.
    """
    if value is None:
        return "unavailable"
    return f"{value:.4f}"


def format_optional(value: Any, *, precision: int = 4) -> Any:
    """Return a friendly display value while preserving missing semantics."""
    if value is None or value == "":
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.{precision}f}"
    return value


def format_drift_state(value: bool | None) -> str:
    """Render a tri-state drift result without treating unknown as no drift."""
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return "Unknown"


def compact_identifier(value: str | None, *, max_length: int = 18) -> str:
    """Return a compact display label; callers retain the full internal value."""
    if not value:
        return "unavailable"
    if len(value) <= max_length:
        return value
    return f"{value[: max_length - 7]}…{value[-6:]}"


def runs_to_display_dicts(overview: MonitoringOverview) -> list[dict[str, Any]]:
    """Return run history with friendly, compact labels for secondary evidence."""
    return [
        {
            "Run": compact_identifier(run.run_id),
            "Created at": format_optional(run.created_at),
            "Dataset": compact_identifier(run.current_dataset_id),
            "Drift detected": format_drift_state(run.drift_detected),
            "Tested": format_optional(run.columns_tested),
            "Drifted": format_optional(run.columns_drifted),
            "Skipped": format_optional(run.columns_skipped),
            "Alpha": format_optional(run.alpha),
            "Status": format_optional(run.status),
        }
        for run in overview.runs
    ]


def columns_to_display_dicts(
    columns: list[ColumnDrift], *, alpha: float | None
) -> list[dict[str, Any]]:
    """Return scan-friendly column evidence with explicit unavailable values."""
    return [
        {
            "Column": format_optional(column.column_name),
            "Drift detected": format_drift_state(column.drift_detected),
            "Column type": format_optional(column.kind),
            "Test type": format_optional(column.test),
            "Statistic": format_optional(column.statistic),
            "p-value": format_optional(column.p_value),
            "Alpha": format_optional(alpha),
            "PSI": format_optional(column.psi),
            "JS distance": format_optional(column.js_distance),
            "Wasserstein": format_optional(column.wasserstein),
            "Reference samples": format_optional(column.reference_n),
            "Current samples": format_optional(column.current_n),
            "Status": format_optional(column.status),
            "Skip reason": format_optional(column.skip_reason),
        }
        for column in columns
    ]


def distributions_to_display_dicts(bins: list[DistributionBin]) -> list[dict[str, Any]]:
    """Return distribution evidence without coercing missing probabilities to zero."""
    return [
        {
            "Bin": format_optional(item.bin_label or item.bin_index),
            "Reference probability": format_probability(item.reference_prob),
            "Current probability": format_probability(item.current_prob),
        }
        for item in bins
    ]


def evaluate_drift_rate_for_display(
    overview: MonitoringOverview, *, threshold: float
) -> dict[str, Any]:
    """Evaluate the displayed drift-rate threshold using the authoritative evaluator."""
    return dict(evaluate_drift_rate_threshold(overview.summary.to_dict(), max_drift_rate=threshold))


def evaluate_psi_for_display(columns: list[ColumnDrift], *, threshold: float) -> dict[str, Any]:
    """Evaluate PSI only from authoritative per-column PSI observations."""
    return dict(evaluate_psi_threshold(columns_to_dicts(columns), max_psi=threshold))


# ----------------------------------------------------------------------------
# Bounded deterministic StoryLens card builder (G27H-A). At most two cards:
#   1. run/status (insufficient drift history, or latest-run drift status)
#   2. one optional threshold/metric fact
# db_path and other paths are never read into these facts.
# ----------------------------------------------------------------------------


def build_drift_storylens_cards(
    overview: MonitoringOverview,
    *,
    threshold_metric: str | None = None,
    threshold_value: float | None = None,
    threshold_metric_value: float | None = None,
) -> list[Explanation]:
    """Build the deterministic drift-monitoring StoryLens cards for an overview.

    Returns at most two cards and never reads ``overview.db_path`` (or any path)
    into the facts. Returns an empty list on malformed input.

    Threshold card (card 2) is created only when its metric value is
    authoritative: ``summary.drift_rate`` is used **only** when
    ``threshold_metric == "drift_rate"``. For any other metric (e.g. ``psi``) an
    explicit ``threshold_metric_value`` must be supplied — the summary's
    drift-rate is never silently rebound to a different metric.
    """
    try:
        summary = overview.summary
        dataset_id = overview.current_dataset_id or None
        cards: list[Explanation] = []

        total = int(summary.total_runs)
        if total < 2:
            cards.append(
                explain_drift_history_insufficient(
                    run_count=total,
                    drifted_runs=summary.drifted_runs,
                    dataset_id=dataset_id,
                )
            )
        else:
            latest = overview.runs[0] if overview.runs else None
            # Preserve unknown (None) status — do not coerce to no-drift.
            cards.append(
                explain_run_drift_status(
                    drift_detected=summary.latest_drift_detected,
                    columns_tested=(latest.columns_tested if latest else None),
                    columns_drifted=(latest.columns_drifted if latest else None),
                    columns_skipped=(latest.columns_skipped if latest else None),
                    run_id=summary.latest_run_id or None,
                    dataset_id=dataset_id,
                )
            )

        if threshold_metric and threshold_value is not None:
            if threshold_metric == "drift_rate":
                metric_value: float | None = summary.drift_rate
            else:
                metric_value = threshold_metric_value
            # Only emit the card when the metric value is authoritative for the
            # named metric; otherwise omit it rather than mislabel.
            if metric_value is not None:
                cards.append(
                    explain_drift_threshold_fact(
                        metric=threshold_metric,
                        metric_value=metric_value,
                        threshold=threshold_value,
                        run_id=summary.latest_run_id or None,
                        dataset_id=dataset_id,
                    )
                )

        return cards[:2]
    except Exception:
        return []
