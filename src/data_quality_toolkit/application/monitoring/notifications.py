"""Pure drift-notification payload builder — no I/O, no network, no dependencies (v2.7.0).

Builds the minimal JSON payload posted to a webhook from an already-computed drift
trend summary and pre-evaluated threshold results. Deliberately contains no secrets,
no environment values, no webhook URL, and no full local DB path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# Cap the offender list so a pathological DB cannot produce an oversized payload.
MAX_OFFENDERS = 50


def build_drift_notification_payload(
    summary: dict[str, Any],
    *,
    version: str,
    max_drift_rate: float | None = None,
    max_psi: float | None = None,
    rate_result: dict[str, Any] | None = None,
    psi_result: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Return a JSON-ready webhook payload describing a drift threshold check.

    ``rate_result`` / ``psi_result`` are the dicts returned by
    ``evaluate_drift_rate_threshold`` / ``evaluate_psi_threshold`` (or None when the
    corresponding threshold was not requested). ``breached`` is true when either
    requested threshold is breached. ``generated_at`` defaults to the current UTC
    time and is injectable for deterministic tests. No I/O, no network.
    """
    breached_rate = bool(rate_result and rate_result.get("breached"))
    breached_psi = bool(psi_result and psi_result.get("breached"))
    breached = breached_rate or breached_psi

    offenders: list[dict[str, Any]] = []
    if psi_result:
        offenders = list(psi_result.get("offenders") or [])[:MAX_OFFENDERS]

    return {
        "tool": "data-quality-toolkit",
        "version": version,
        "event": "drift_threshold_check",
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "status": "breach" if breached else "ok",
        "breached": breached,
        "drift_summary": {
            "total_runs": summary.get("total_runs"),
            "drifted_runs": summary.get("drifted_runs"),
            "drift_rate": summary.get("drift_rate"),
            "latest_run_id": summary.get("latest_run_id"),
            "latest_created_at": summary.get("latest_created_at"),
        },
        "thresholds": {
            "max_drift_rate": max_drift_rate,
            "max_psi": max_psi,
        },
        "columns_breached": offenders,
    }
