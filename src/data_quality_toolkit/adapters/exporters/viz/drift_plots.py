"""Drift-history Matplotlib PNG plot export (v2.6.1).

Local, opt-in PNG export behind the existing ``[viz]`` extra. Reads an existing
drift-monitoring SQLite database through the public ``data_quality_toolkit.api``
seam and writes static ``.png`` chart files. No schema changes, no network, no
cloud, no remote image fetching, no GUI backend.

The module splits a pure, matplotlib-free **model builder**
(``build_plot_model``) from a lazy **render layer** that imports matplotlib only
when writing PNGs. Matplotlib is imported lazily and the non-interactive ``Agg``
backend is forced *before* ``pyplot`` is imported.

Charts implemented in this slice: ``drift-rate``, ``psi-by-column``,
``top-drifted``. The ``distribution`` (reference-vs-current) chart is **deferred**
to a later gate: it requires per-column selection and produces a noisy fan-out of
one figure per column, which is out of scope for this narrowed slice.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from data_quality_toolkit.shared.exceptions import DQTError
from data_quality_toolkit.shared.path_guard import PathGuardError, validate_output_dir
from data_quality_toolkit.utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "PlotExportError",
    "build_plot_model",
    "export_drift_plots",
    "SUPPORTED_CHARTS",
]

_MPL_HINT = (
    "matplotlib is not installed; install the viz extra: " "pip install data-quality-toolkit[viz]"
)

# Charts implemented in this slice (drift "distribution" is deferred — see module docstring).
SUPPORTED_CHARTS: tuple[str, ...] = ("drift-rate", "psi-by-column", "top-drifted")

# Stable, fixed output file names (no user input flows into a filename → path safe).
_CHART_FILENAMES: dict[str, str] = {
    "drift-rate": "drift_rate.png",
    "psi-by-column": "psi_by_column.png",
    "top-drifted": "top_drifted.png",
}

# Max columns shown in the top-drifted bar chart.
_TOP_N = 15


class PlotExportError(DQTError):
    """Raised when the drift-history PNG plot export fails."""


def _import_matplotlib() -> Any:
    """Return the ``pyplot`` module, forcing the Agg backend before import.

    Isolated so callers and tests can simulate the missing-dependency path. The
    non-interactive ``Agg`` backend is selected *before* ``pyplot`` is imported so
    no GUI/display backend is ever required. Raises PlotExportError with an
    install hint when matplotlib is absent.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")  # non-interactive backend — set before pyplot import
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch in tests
        raise PlotExportError(_MPL_HINT, hint=_MPL_HINT) from exc
    return plt


def _resolve_charts(chart: str) -> tuple[str, ...]:
    """Resolve a ``chart`` selector to a concrete tuple of supported chart names."""
    if chart == "all":
        return SUPPORTED_CHARTS
    if chart in SUPPORTED_CHARTS:
        return (chart,)
    supported = ", ".join(("all", *SUPPORTED_CHARTS))
    raise PlotExportError(f"Unknown chart '{chart}'. Supported: {supported}.")


def _drift_rate_model(runs: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    """Per-run drift fraction (columns_drifted / columns_tested) over time, oldest first."""
    ordered = list(reversed(runs))  # read_drift_runs is newest-first; plot oldest→newest
    labels: list[str] = []
    values: list[float] = []
    for r in ordered:
        tested = int(r.get("columns_tested") or 0)
        drifted = int(r.get("columns_drifted") or 0)
        labels.append(str(r.get("created_at") or ""))
        values.append((drifted / tested) if tested else 0.0)
    drift_rate = float(summary.get("drift_rate") or 0.0)
    return {
        "title": f"Drift fraction per run (overall drift rate: {drift_rate:.2f})",
        "labels": labels,
        "values": values,
        "drift_rate": drift_rate,
        "ylabel": "drifted columns / tested columns",
        "count": len(ordered),
    }


def _psi_by_column_model(columns: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean PSI per column across all runs, descending. None PSI values are skipped."""
    acc: dict[str, list[float]] = defaultdict(list)
    for c in columns:
        psi = c.get("psi")
        if psi is not None:
            acc[str(c.get("column_name") or "")].append(float(psi))
    means = {name: sum(vals) / len(vals) for name, vals in acc.items()}
    items = sorted(means.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "title": "Mean PSI by column",
        "labels": [name for name, _ in items],
        "values": [val for _, val in items],
        "ylabel": "mean PSI",
        "count": len(items),
    }


def _top_drifted_model(columns: list[dict[str, Any]]) -> dict[str, Any]:
    """Top-N columns by number of runs in which the column drifted (drift_detected=1)."""
    counts: dict[str, int] = defaultdict(int)
    for c in columns:
        if c.get("drift_detected"):
            counts[str(c.get("column_name") or "")] += 1
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:_TOP_N]
    return {
        "title": f"Top {_TOP_N} drifted columns (drift count)",
        "labels": [name for name, _ in items],
        "values": [val for _, val in items],
        "ylabel": "times drifted",
        "count": len(items),
    }


def build_plot_model(
    *,
    runs: list[dict[str, Any]],
    summary: dict[str, Any],
    columns: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build the pure, matplotlib-free plot model (chart name -> series/labels/title).

    Every supported chart is built from the supplied data; charts whose source
    data is empty yield a zero-state model (``count == 0``) rather than raising.
    The render layer draws a "No data available" placeholder for those.
    """
    return {
        "drift-rate": _drift_rate_model(runs, summary),
        "psi-by-column": _psi_by_column_model(columns),
        "top-drifted": _top_drifted_model(columns),
    }


def _validate_output_dir(out: str | Path) -> Path:
    """Validate the output directory via path_guard and create it. Returns resolved Path."""
    raw = str(out).strip()
    if not raw:
        raise PlotExportError("Output directory path must not be empty.")
    try:
        resolved = validate_output_dir(out, must_be_absolute=False)
    except PathGuardError as exc:
        raise PlotExportError(str(exc)) from exc
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PlotExportError(f"Failed to create output directory {resolved}: {exc}") from exc
    return resolved


def _render_chart(plt: Any, chart: str, data: dict[str, Any], path: Path) -> None:
    """Render a single chart model to a PNG file, always closing the figure."""
    fig, ax = plt.subplots(figsize=(8.0, 4.5))
    try:
        if data["count"] == 0:
            ax.text(0.5, 0.5, "No data available", ha="center", va="center")
            ax.set_axis_off()
        elif chart == "drift-rate":
            xs = range(len(data["values"]))
            ax.plot(list(xs), data["values"], marker="o")
            ax.axhline(data["drift_rate"], linestyle="--", color="grey")
            ax.set_xticks(list(xs))
            ax.set_xticklabels(data["labels"], rotation=45, ha="right", fontsize=7)
            ax.set_ylabel(data["ylabel"])
            ax.set_ylim(bottom=0.0)
        else:  # psi-by-column, top-drifted — categorical bar charts
            xs = range(len(data["values"]))
            ax.bar(list(xs), data["values"])
            ax.set_xticks(list(xs))
            ax.set_xticklabels(data["labels"], rotation=45, ha="right", fontsize=7)
            ax.set_ylabel(data["ylabel"])
        ax.set_title(data["title"])
        fig.tight_layout()
        try:
            fig.savefig(str(path), format="png", dpi=100)
        except OSError as exc:
            raise PlotExportError(f"Failed to write plot to {path}: {exc}") from exc
    finally:
        plt.close(fig)  # close figure to bound memory across many charts


def export_drift_plots(
    db_path: str | Path,
    out: str | Path,
    *,
    chart: str = "all",
    current_dataset_id: str | None = None,
    limit: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Export drift-history monitoring data to local PNG chart files.

    Reads an existing monitoring SQLite database through the
    ``data_quality_toolkit.api`` seam (no schema changes) and writes one PNG per
    requested chart into the *out* directory. Supported charts: ``drift-rate``,
    ``psi-by-column``, ``top-drifted`` (or ``all``, the default). A missing or
    empty database yields valid zero-state PNGs rather than raising.

    Requires the optional ``[viz]`` extra (matplotlib); raises PlotExportError
    with an install hint when it is absent. Refuses to overwrite an existing PNG
    unless *force* is True. Only local file writes — no network, no GUI backend.

    Returns ``{"output_dir", "charts": {name: path}, "row_counts": {name: int}}``.
    """
    plt = _import_matplotlib()  # fail fast before any I/O
    charts = _resolve_charts(chart)
    out_dir = _validate_output_dir(out)

    targets = {name: out_dir / _CHART_FILENAMES[name] for name in charts}
    for target in targets.values():
        if target.exists():
            if target.is_dir():
                raise PlotExportError(f"Output path is an existing directory: {target}")
            if not force:
                raise PlotExportError(
                    f"Output file already exists; pass --force to overwrite: {target}"
                )

    # Query only the seams each requested chart needs (distributions are never read).
    need_runs = "drift-rate" in charts
    need_columns = ("psi-by-column" in charts) or ("top-drifted" in charts)

    from data_quality_toolkit.api import (
        read_drift_columns_sqlite,
        read_drift_runs_sqlite,
        summarize_drift_trends_sqlite,
    )

    runs = (
        read_drift_runs_sqlite(db_path, limit=limit, current_dataset_id=current_dataset_id)
        if need_runs
        else []
    )
    summary = (
        summarize_drift_trends_sqlite(db_path, current_dataset_id=current_dataset_id, limit=limit)
        if need_runs
        else {}
    )
    columns = read_drift_columns_sqlite(db_path) if need_columns else []

    model = build_plot_model(runs=runs, summary=summary, columns=columns)

    written: dict[str, str] = {}
    row_counts: dict[str, int] = {}
    for name in charts:
        target = targets[name]
        _render_chart(plt, name, model[name], target)
        written[name] = str(target)
        row_counts[name] = model[name]["count"]

    logger.info("Drift plots written: %s (charts=%s)", out_dir, ",".join(written))
    return {"output_dir": str(out_dir), "charts": written, "row_counts": row_counts}
