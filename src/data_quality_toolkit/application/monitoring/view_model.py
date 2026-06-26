"""Shared, presentation-agnostic monitoring view-model (v2.6.0).

This module is the single source of truth for the *shape* of drift-monitoring
data handed to presentation layers (the static HTML dashboard today, the
Streamlit Drift Explorer later). It performs no rendering and owns no storage.

Data access rule (enforced by the v2.6.0 gate, not just convention):
the view-model reaches the SQLite monitoring database **only** through the root
public seam ``data_quality_toolkit.api`` -- never directly from
``adapters.storage.queries`` / ``adapters.storage.trends``. It imports nothing
from Streamlit and nothing from the dashboard/report renderers. Those API reads
remain the authoritative source of truth; this layer only normalizes their
JSON-ready dicts into frozen, typed value objects.

Normalization performed here, once, for every consumer:
* ``drift_detected`` integers (0/1) become ``bool``; ``None`` is preserved.
* missing numeric fields are preserved as ``None`` (not coerced to zero);
* missing run / column / distribution result sets become empty lists, mirroring
  the stable empty/zero behavior the storage APIs already guarantee for a
  missing or empty database (so building a view-model never raises on its own).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ----------------------------------------------------------------------------
# Coercion helpers (normalization happens here so consumers never re-implement).
# ----------------------------------------------------------------------------


def _to_bool(value: Any) -> bool | None:
    """Normalize a stored 0/1 (or bool) flag to ``bool``; preserve ``None``."""
    if value is None:
        return None
    return bool(value)


def _to_int(value: Any) -> int | None:
    """Coerce to ``int``; preserve ``None`` and tolerate already-int values."""
    if value is None:
        return None
    return int(value)


def _to_float(value: Any) -> float | None:
    """Coerce to ``float``; preserve ``None``."""
    if value is None:
        return None
    return float(value)


def _utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (seconds resolution)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


# ----------------------------------------------------------------------------
# Value objects. Each is frozen + slotted and exposes ``to_dict`` for JSON/CLI
# parity and for handing plain dicts to the dependency-free HTML renderer.
# ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrendSummary:
    """Aggregate drift-history trend summary (mirrors ``summarize_drift_trends``)."""

    total_runs: int
    drifted_runs: int
    non_drifted_runs: int
    drift_rate: float
    latest_run_id: str | None
    latest_created_at: str | None
    latest_drift_detected: bool | None
    columns_tested_total: int
    columns_tested_average: float
    columns_drifted_total: int
    columns_drifted_average: float

    @classmethod
    def from_summary(cls, summary: dict[str, Any]) -> TrendSummary:
        """Build from the ``summarize_drift_trends_sqlite`` dict (tolerant of partials)."""
        return cls(
            total_runs=int(summary.get("total_runs", 0) or 0),
            drifted_runs=int(summary.get("drifted_runs", 0) or 0),
            non_drifted_runs=int(summary.get("non_drifted_runs", 0) or 0),
            drift_rate=float(summary.get("drift_rate", 0.0) or 0.0),
            latest_run_id=summary.get("latest_run_id"),
            latest_created_at=summary.get("latest_created_at"),
            latest_drift_detected=_to_bool(summary.get("latest_drift_detected")),
            columns_tested_total=int(summary.get("columns_tested_total", 0) or 0),
            columns_tested_average=float(summary.get("columns_tested_average", 0.0) or 0.0),
            columns_drifted_total=int(summary.get("columns_drifted_total", 0) or 0),
            columns_drifted_average=float(summary.get("columns_drifted_average", 0.0) or 0.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_runs": self.total_runs,
            "drifted_runs": self.drifted_runs,
            "non_drifted_runs": self.non_drifted_runs,
            "drift_rate": self.drift_rate,
            "latest_run_id": self.latest_run_id,
            "latest_created_at": self.latest_created_at,
            "latest_drift_detected": self.latest_drift_detected,
            "columns_tested_total": self.columns_tested_total,
            "columns_tested_average": self.columns_tested_average,
            "columns_drifted_total": self.columns_drifted_total,
            "columns_drifted_average": self.columns_drifted_average,
        }


@dataclass(frozen=True, slots=True)
class RunRow:
    """One run-level drift row (a projection of ``read_drift_runs`` output)."""

    run_id: str | None
    created_at: str | None
    current_dataset_id: str | None
    status: str | None
    drift_detected: bool | None
    columns_tested: int | None
    columns_drifted: int | None
    columns_skipped: int | None
    # Additive (G27H-A): per-run significance level when authoritative storage
    # rows provide it. None when missing/invalid (never fabricated). Path fields
    # (baseline/current/report) remain excluded by design.
    alpha: float | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> RunRow:
        # Alpha is additive and best-effort: keep None on missing/invalid rather
        # than fabricating a value or raising.
        try:
            alpha = _to_float(row.get("alpha"))
        except (TypeError, ValueError):
            alpha = None
        return cls(
            run_id=row.get("run_id"),
            created_at=row.get("created_at"),
            current_dataset_id=row.get("current_dataset_id"),
            status=row.get("status"),
            drift_detected=_to_bool(row.get("drift_detected")),
            columns_tested=_to_int(row.get("columns_tested")),
            columns_drifted=_to_int(row.get("columns_drifted")),
            columns_skipped=_to_int(row.get("columns_skipped")),
            alpha=alpha,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "current_dataset_id": self.current_dataset_id,
            "status": self.status,
            "drift_detected": self.drift_detected,
            "columns_tested": self.columns_tested,
            "columns_drifted": self.columns_drifted,
            "columns_skipped": self.columns_skipped,
            "alpha": self.alpha,
        }


@dataclass(frozen=True, slots=True)
class ColumnDrift:
    """One per-column drift result (a projection of ``read_drift_columns`` output)."""

    column_name: str | None
    kind: str | None
    test: str | None
    drift_detected: bool | None
    statistic: float | None
    p_value: float | None
    psi: float | None
    js_distance: float | None
    wasserstein: float | None
    reference_n: int | None
    current_n: int | None
    status: str | None
    skip_reason: str | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ColumnDrift:
        return cls(
            column_name=row.get("column_name"),
            kind=row.get("kind"),
            test=row.get("test"),
            drift_detected=_to_bool(row.get("drift_detected")),
            statistic=_to_float(row.get("statistic")),
            p_value=_to_float(row.get("p_value")),
            psi=_to_float(row.get("psi")),
            js_distance=_to_float(row.get("js_distance")),
            wasserstein=_to_float(row.get("wasserstein")),
            reference_n=_to_int(row.get("reference_n")),
            current_n=_to_int(row.get("current_n")),
            status=row.get("status"),
            skip_reason=row.get("skip_reason"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "column_name": self.column_name,
            "kind": self.kind,
            "test": self.test,
            "drift_detected": self.drift_detected,
            "statistic": self.statistic,
            "p_value": self.p_value,
            "psi": self.psi,
            "js_distance": self.js_distance,
            "wasserstein": self.wasserstein,
            "reference_n": self.reference_n,
            "current_n": self.current_n,
            "status": self.status,
            "skip_reason": self.skip_reason,
        }


@dataclass(frozen=True, slots=True)
class DistributionBin:
    """One distribution bin (a projection of ``read_drift_distributions`` output)."""

    column_name: str | None
    kind: str | None
    bin_index: int | None
    bin_label: str | None
    reference_prob: float | None
    current_prob: float | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DistributionBin:
        return cls(
            column_name=row.get("column_name"),
            kind=row.get("kind"),
            bin_index=_to_int(row.get("bin_index")),
            bin_label=row.get("bin_label"),
            reference_prob=_to_float(row.get("reference_prob")),
            current_prob=_to_float(row.get("current_prob")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "column_name": self.column_name,
            "kind": self.kind,
            "bin_index": self.bin_index,
            "bin_label": self.bin_label,
            "reference_prob": self.reference_prob,
            "current_prob": self.current_prob,
        }


@dataclass(frozen=True, slots=True)
class RunDetail:
    """A single run with its per-column drift results and distribution bins."""

    run: RunRow
    columns: list[ColumnDrift]
    distributions: list[DistributionBin]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": self.run.to_dict(),
            "columns": [c.to_dict() for c in self.columns],
            "distributions": [d.to_dict() for d in self.distributions],
        }


@dataclass(frozen=True, slots=True)
class MonitoringOverview:
    """Top-level monitoring view: trend summary plus the recent run rows."""

    summary: TrendSummary
    runs: list[RunRow]
    db_path: str
    current_dataset_id: str | None
    limit: int | None
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary.to_dict(),
            "runs": [r.to_dict() for r in self.runs],
            "db_path": self.db_path,
            "current_dataset_id": self.current_dataset_id,
            "limit": self.limit,
            "generated_at": self.generated_at,
        }


# ----------------------------------------------------------------------------
# Builders. All SQLite access flows through the root ``data_quality_toolkit.api``
# seam, imported lazily at call time so test monkeypatches on the api module are
# observed and no import cycle is introduced.
# ----------------------------------------------------------------------------


def build_monitoring_overview(
    db_path: str | Path,
    *,
    current_dataset_id: str | None = None,
    limit: int | None = None,
) -> MonitoringOverview:
    """Build the top-level monitoring overview (trend summary + recent runs).

    Reads via ``summarize_drift_trends_sqlite`` and ``read_drift_runs_sqlite``.
    A missing or empty database yields a zeroed ``TrendSummary`` and an empty
    ``runs`` list rather than raising.
    """
    import data_quality_toolkit.api as api

    summary = api.summarize_drift_trends_sqlite(
        db_path, current_dataset_id=current_dataset_id, limit=limit
    )
    runs = api.read_drift_runs_sqlite(db_path, current_dataset_id=current_dataset_id, limit=limit)
    return MonitoringOverview(
        summary=TrendSummary.from_summary(summary),
        runs=[RunRow.from_row(r) for r in runs],
        db_path=str(db_path),
        current_dataset_id=current_dataset_id,
        limit=limit,
        generated_at=_utc_now_iso(),
    )


def list_run_rows(
    db_path: str | Path,
    *,
    current_dataset_id: str | None = None,
    limit: int | None = None,
) -> list[RunRow]:
    """Return the run-level drift rows (newest first), normalized to ``RunRow``."""
    import data_quality_toolkit.api as api

    runs = api.read_drift_runs_sqlite(db_path, current_dataset_id=current_dataset_id, limit=limit)
    return [RunRow.from_row(r) for r in runs]


def build_column_drift(db_path: str | Path, run_id: str) -> list[ColumnDrift]:
    """Return per-column drift results for one run, normalized to ``ColumnDrift``."""
    import data_quality_toolkit.api as api

    rows = api.read_drift_columns_sqlite(db_path, run_id=run_id)
    return [ColumnDrift.from_row(c) for c in rows]


def build_distribution_series(
    db_path: str | Path, run_id: str, column_name: str
) -> list[DistributionBin]:
    """Return the distribution bins for one run+column, as ``DistributionBin``."""
    import data_quality_toolkit.api as api

    rows = api.read_drift_distributions_sqlite(db_path, run_id=run_id, column_name=column_name)
    return [DistributionBin.from_row(d) for d in rows]


def build_run_detail(
    db_path: str | Path,
    run_id: str,
    *,
    include_distributions: bool = True,
) -> RunDetail:
    """Build a single run's detail: its run row, column drifts, and distributions.

    The run row is located among ``read_drift_runs_sqlite`` results (which has no
    run-id filter); if absent, a minimal ``RunRow`` carrying just ``run_id`` is
    returned. Distribution bins (all columns for the run) are included only when
    ``include_distributions`` is true.
    """
    import data_quality_toolkit.api as api

    run_dicts = api.read_drift_runs_sqlite(db_path)
    run_row = next(
        (RunRow.from_row(r) for r in run_dicts if r.get("run_id") == run_id),
        RunRow(
            run_id=run_id,
            created_at=None,
            current_dataset_id=None,
            status=None,
            drift_detected=None,
            columns_tested=None,
            columns_drifted=None,
            columns_skipped=None,
        ),
    )
    columns = build_column_drift(db_path, run_id)
    distributions: list[DistributionBin] = []
    if include_distributions:
        rows = api.read_drift_distributions_sqlite(db_path, run_id=run_id)
        distributions = [DistributionBin.from_row(d) for d in rows]
    return RunDetail(run=run_row, columns=columns, distributions=distributions)
