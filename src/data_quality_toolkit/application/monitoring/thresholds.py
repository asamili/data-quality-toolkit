"""Pure drift threshold evaluators — no I/O, no network, no dependencies (v2.6.1)."""

from __future__ import annotations

from typing import Any


def evaluate_drift_rate_threshold(
    summary: dict[str, Any],
    *,
    max_drift_rate: float,
) -> dict[str, Any]:
    """Return a JSON-ready result dict for a drift-rate threshold check.

    Reads drift_rate from summary. Missing or None is treated as 0.0.
    Breached only when drift_rate > max_drift_rate (strictly greater than;
    equality is not a breach).
    """
    rate = float(summary.get("drift_rate") or 0.0)
    return {
        "breached": rate > max_drift_rate,
        "drift_rate": rate,
        "threshold": max_drift_rate,
    }


def evaluate_psi_threshold(
    columns: list[dict[str, Any]],
    *,
    max_psi: float,
) -> dict[str, Any]:
    """Return a JSON-ready result dict for a per-column PSI threshold check.

    Skips rows where psi is None. Breached only when any psi > max_psi
    (strictly greater than; equality is not a breach). Offender ordering
    matches input order.
    """
    offenders = [
        {"column_name": row["column_name"], "psi": row["psi"]}
        for row in columns
        if row.get("psi") is not None and row["psi"] > max_psi
    ]
    return {
        "breached": bool(offenders),
        "threshold": max_psi,
        "offenders": offenders,
    }
