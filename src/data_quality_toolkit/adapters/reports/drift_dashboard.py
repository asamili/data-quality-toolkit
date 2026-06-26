"""Render a static, dependency-free drift analytics dashboard (HTML).

Pure rendering plus a thin convenience builder over the accepted public APIs.
``render_drift_dashboard`` does no I/O: it turns an already-fetched trend
summary dict, a list of drift-run dicts, and a list of per-column drift dicts
into a single self-contained HTML string. ``build_drift_dashboard`` fetches via
``summarize_drift_trends_sqlite`` / ``read_drift_runs_sqlite`` /
``read_drift_columns_sqlite`` and renders.

The dashboard is fully self-contained: only inline minimal CSS, no JavaScript,
no external CDN, no image assets, and all dynamic values are escaped with the
stdlib ``html.escape``. No SQLite schema, importer, query-helper, metric, or
trend-helper behavior is changed.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_quality_toolkit.application.monitoring.view_model import (
    ColumnDrift,
    MonitoringOverview,
    RunRow,
    TrendSummary,
)

# Run-level table columns: (run dict key, display header).
_RUN_COLUMNS: tuple[tuple[str, str], ...] = (
    ("run_id", "run_id"),
    ("created_at", "created_at"),
    ("current_dataset_id", "current_dataset_id"),
    ("status", "status"),
    ("drift_detected", "drift_detected"),
    ("columns_tested", "columns_tested"),
    ("columns_drifted", "columns_drifted"),
)

# Column-level metrics table columns: (column dict key, display header).
_COLUMN_COLUMNS: tuple[tuple[str, str], ...] = (
    ("run_id", "run_id"),
    ("column_name", "column_name"),
    ("kind", "kind"),
    ("drift_detected", "drift_detected"),
    ("psi", "psi"),
    ("js_distance", "js_distance"),
    ("wasserstein", "wasserstein"),
    ("status", "status"),
)

# Summary cards: (summary dict key, display label, default).
_SUMMARY_CARDS: tuple[tuple[str, str, Any], ...] = (
    ("total_runs", "total_runs", 0),
    ("drifted_runs", "drifted_runs", 0),
    ("non_drifted_runs", "non_drifted_runs", 0),
    ("drift_rate", "drift_rate", 0.0),
    ("latest_run_id", "latest_run_id", None),
    ("latest_created_at", "latest_created_at", None),
)

_NO_RUNS_HTML = '<p class="empty">No drift runs available.</p>'
_NO_COLUMNS_HTML = '<p class="empty">No column-level drift rows available.</p>'
_NO_DIST_HTML = '<p class="empty">No distribution rows available.</p>'

# Inline-style colours for the dependency-free distribution bars.
_DIST_REF_COLOR = "#4a90d9"
_DIST_CUR_COLOR = "#d9534f"

_STYLE = """\
body { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
  margin: 2rem; color: #1a1a1a; background: #ffffff; }
h1 { font-size: 1.6rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.2rem; margin-top: 2rem; border-bottom: 1px solid #ddd;
  padding-bottom: 0.25rem; }
.meta { color: #555; font-size: 0.9rem; margin: 0.25rem 0; }
.cards { display: flex; flex-wrap: wrap; gap: 0.75rem; margin-top: 1rem; }
.card { border: 1px solid #ddd; border-radius: 6px; padding: 0.75rem 1rem;
  min-width: 9rem; background: #fafafa; }
.card .label { color: #666; font-size: 0.8rem; text-transform: uppercase;
  letter-spacing: 0.03em; }
.card .value { font-size: 1.3rem; font-weight: 600; margin-top: 0.25rem; }
table { border-collapse: collapse; width: 100%; margin-top: 0.75rem;
  font-size: 0.9rem; }
th, td { border: 1px solid #ddd; padding: 0.4rem 0.6rem; text-align: left; }
th { background: #f2f2f2; }
.empty { color: #777; font-style: italic; }
.dist-group { margin-top: 1rem; }
.dist-group h3 { font-size: 1rem; margin: 0.75rem 0 0.25rem; }
.dist-bin { margin: 0.5rem 0; }
.dist-bin .label { font-size: 0.85rem; color: #555; }
.dist-row { display: flex; align-items: center; gap: 0.5rem; margin: 0.15rem 0; }
.dist-row .tag { width: 2rem; font-size: 0.8rem; color: #666; }
.dist-track { display: inline-block; width: 12rem; height: 0.8rem;
  background: #eee; border: 1px solid #ddd; }
.dist-fill { display: block; height: 100%; }
.dist-row .val { font-size: 0.8rem; }
"""


def _utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (seconds resolution)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _filter_display(value: Any) -> str:
    """Human display for an optional filter / summary value."""
    return "(none)" if value is None else str(value)


def _cell(value: Any) -> str:
    """String for a table cell; ``None`` renders as an empty string."""
    return "" if value is None else str(value)


def _esc(value: Any) -> str:
    """Escape an arbitrary value for safe HTML embedding."""
    return html.escape(str(value))


def _html_table(spec: tuple[tuple[str, str], ...], rows: list[dict[str, Any]]) -> list[str]:
    """Render an HTML table for ``rows`` using a (key, header) ``spec`` (escaped)."""
    out = ["<table>", "<thead><tr>"]
    out.extend(f"<th>{_esc(hdr)}</th>" for _, hdr in spec)
    out.append("</tr></thead>")
    out.append("<tbody>")
    for row in rows:
        out.append("<tr>")
        out.extend(f"<td>{_esc(_cell(row.get(key)))}</td>" for key, _ in spec)
        out.append("</tr>")
    out.append("</tbody>")
    out.append("</table>")
    return out


def _pct(value: Any) -> str:
    """Format a 0..1 probability as a percentage string; ``None`` -> empty."""
    if value is None:
        return ""
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _bar_width(value: Any) -> str:
    """CSS width for a 0..1 probability, clamped to [0, 1] (e.g. ``60.0%``)."""
    try:
        frac = float(value)
    except (TypeError, ValueError):
        frac = 0.0
    frac = max(0.0, min(1.0, frac))
    return f"{frac * 100:.1f}%"


def _group_distributions(
    rows: list[dict[str, Any]],
) -> list[tuple[str, str, Any, list[dict[str, Any]]]]:
    """Group distribution rows by (run_id, column_name), preserving input order."""
    order: list[tuple[str, str]] = []
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("run_id")), str(row.get("column_name")))
        if key not in buckets:
            buckets[key] = {"kind": row.get("kind"), "rows": []}
            order.append(key)
        buckets[key]["rows"].append(row)
    return [(k[0], k[1], buckets[k]["kind"], buckets[k]["rows"]) for k in order]


def _dist_bar_row(tag: str, value: Any, color: str) -> str:
    """One inline-CSS horizontal bar (no JS / no external assets)."""
    width = _bar_width(value)
    return (
        '<div class="dist-row">'
        f'<span class="tag">{tag}</span>'
        '<span class="dist-track">'
        f'<span class="dist-fill" style="width:{width};background:{color};"></span></span>'
        f'<span class="val">{_esc(_pct(value))}</span>'
        "</div>"
    )


def _html_distributions(distributions: list[dict[str, Any]]) -> list[str]:
    """Render the dashboard "Distribution plots" section with inline-CSS bars."""
    out = ["<h2>Distribution plots</h2>"]
    if not distributions:
        out.append(_NO_DIST_HTML)
        return out
    for run_id, column_name, kind, rows in _group_distributions(distributions):
        title = f"run_id={run_id} · column_name={column_name} ({_cell(kind)})"
        out.append('<div class="dist-group">')
        out.append(f"<h3>{_esc(title)}</h3>")
        for row in rows:
            out.append('<div class="dist-bin">')
            out.append(f'<div class="label">{_esc(_cell(row.get("bin_label")))}</div>')
            out.append(_dist_bar_row("ref", row.get("reference_prob"), _DIST_REF_COLOR))
            out.append(_dist_bar_row("cur", row.get("current_prob"), _DIST_CUR_COLOR))
            out.append("</div>")
        out.append("</div>")
    return out


# Empty-state guidance for the Dashboard 2.0 view-model-driven sections.
_NO_TREND_HTML = '<p class="empty">No trend data available.</p>'
_NO_DRIFTED_COLUMNS_HTML = '<p class="empty">No drifted columns detected.</p>'
_NO_METRICS_HTML = '<p class="empty">No metric data available.</p>'

# Trend-summary cards: (TrendSummary attribute, display label).
_TREND_FIELDS: tuple[tuple[str, str], ...] = (
    ("drift_rate", "drift_rate"),
    ("latest_drift_detected", "latest_drift_detected"),
    ("columns_tested_total", "columns_tested_total"),
    ("columns_tested_average", "columns_tested_average"),
    ("columns_drifted_total", "columns_drifted_total"),
    ("columns_drifted_average", "columns_drifted_average"),
)

# Top-drifted-columns table: (ColumnDrift dict key, header).
_TOP_COLUMN_FIELDS: tuple[tuple[str, str], ...] = (
    ("column_name", "column_name"),
    ("kind", "kind"),
    ("psi", "psi"),
    ("js_distance", "js_distance"),
    ("wasserstein", "wasserstein"),
)

# Aggregate-metric rows: (display label, ColumnDrift attribute).
_METRIC_FIELDS: tuple[tuple[str, str], ...] = (
    ("PSI", "psi"),
    ("Jensen-Shannon", "js_distance"),
    ("Wasserstein", "wasserstein"),
)


def _resolve_version() -> str | None:
    """Installed package version for the dashboard header, or ``None`` if absent."""
    try:
        from importlib.metadata import version

        return version("data-quality-toolkit")
    except Exception:  # pragma: no cover - metadata absent in some environments
        return None


def _num(value: float | None) -> str:
    """Format an optional metric value to 4 decimals; ``None`` -> empty string."""
    return "" if value is None else f"{value:.4f}"


def _avg(value: float) -> str:
    """Format an average to 2 decimals."""
    return f"{value:.2f}"


def _html_trend_summary(summary: TrendSummary) -> list[str]:
    """Render the view-model-driven "Trend summary" cards (no I/O)."""
    out = ["<h2>Trend summary</h2>"]
    if summary.total_runs == 0:
        out.append(_NO_TREND_HTML)
        return out
    display: dict[str, str] = {
        "drift_rate": _pct(summary.drift_rate),
        "latest_drift_detected": _filter_display(summary.latest_drift_detected),
        "columns_tested_total": str(summary.columns_tested_total),
        "columns_tested_average": _avg(summary.columns_tested_average),
        "columns_drifted_total": str(summary.columns_drifted_total),
        "columns_drifted_average": _avg(summary.columns_drifted_average),
    }
    out.append('<div class="cards">')
    for attr, label in _TREND_FIELDS:
        out.append('<div class="card">')
        out.append(f'<div class="label">{_esc(label)}</div>')
        out.append(f'<div class="value">{_esc(display[attr])}</div>')
        out.append("</div>")
    out.append("</div>")
    return out


def _html_top_drifted_columns(columns: list[ColumnDrift]) -> list[str]:
    """Render the "Top drifted columns" table from view-model ``ColumnDrift`` objects."""
    out = ["<h2>Top drifted columns</h2>"]
    drifted = [c for c in columns if c.drift_detected]
    if not drifted:
        out.append(_NO_DRIFTED_COLUMNS_HTML)
        return out
    drifted.sort(key=lambda c: (c.psi if c.psi is not None else float("-inf")), reverse=True)
    rows = [c.to_dict() for c in drifted[:10]]
    out.extend(_html_table(_TOP_COLUMN_FIELDS, rows))
    return out


def _html_metric_summary(columns: list[ColumnDrift]) -> list[str]:
    """Render the aggregate PSI / Jensen-Shannon / Wasserstein "Metric summary"."""
    out = ["<h2>Metric summary (PSI / Jensen-Shannon / Wasserstein)</h2>"]
    if not columns:
        out.append(_NO_METRICS_HTML)
        return out
    rows: list[dict[str, Any]] = []
    for label, attr in _METRIC_FIELDS:
        values = [v for v in (getattr(c, attr) for c in columns) if v is not None]
        if values:
            mx: float | None = max(values)
            mean: float | None = sum(values) / len(values)
        else:
            mx = mean = None
        rows.append({"metric": label, "max": _num(mx), "mean": _num(mean)})
    spec = (("metric", "metric"), ("max", "max"), ("mean", "mean"))
    out.extend(_html_table(spec, rows))
    return out


def render_drift_dashboard(
    *,
    summary: dict[str, Any],
    runs: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    db_path: str | Path,
    current_dataset_id: str | None = None,
    limit: int | None = None,
    generated_at: str | None = None,
    distributions: list[dict[str, Any]] | None = None,
    version: str | None = None,
) -> str:
    """Render a static, self-contained drift analytics dashboard as HTML.

    ``summary`` is the dict returned by ``summarize_drift_trends_sqlite``,
    ``runs`` the list from ``read_drift_runs_sqlite`` (newest first), and
    ``columns`` the list from ``read_drift_columns_sqlite``. No I/O is performed.
    ``generated_at`` is embedded verbatim when provided (kept deterministic for
    tests); otherwise the current UTC time is used. A zero-summary with empty
    ``runs``/``columns`` renders a valid zero dashboard with clear empty-state
    messages. Output is dependency-free (inline CSS, no JS, no external assets);
    all dynamic values are escaped with ``html.escape``.

    ``distributions`` is the optional list from ``read_drift_distributions_sqlite``.
    When ``None`` (default) no plot section is rendered. When provided (including
    an empty list) a "Distribution plots" section is added; an empty list renders
    a clear empty-state. Bars are dependency-free inline-CSS paired bars.
    """
    generated_at = generated_at or _utc_now_iso()
    db_path = str(db_path)

    # Consume the shared monitoring view-model: a single normalized projection of
    # the already-fetched dicts drives the trend-summary and column metric
    # sections (and the same value objects power the Streamlit Drift Explorer).
    overview = MonitoringOverview(
        summary=TrendSummary.from_summary(summary),
        runs=[RunRow.from_row(r) for r in runs],
        db_path=db_path,
        current_dataset_id=current_dataset_id,
        limit=limit,
        generated_at=generated_at,
    )
    column_drifts = [ColumnDrift.from_row(c) for c in columns]

    meta = [
        ("generated_at", generated_at),
        ("database", db_path),
    ]
    if version is not None:
        meta.append(("toolkit_version", str(version)))
    if current_dataset_id is not None:
        meta.append(("current_dataset_id filter", str(current_dataset_id)))
    if limit is not None:
        meta.append(("limit", str(limit)))

    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append("<title>Drift Analytics Dashboard</title>")
    parts.append(f"<style>\n{_STYLE}</style>")
    parts.append("</head>")
    parts.append("<body>")
    parts.append("<h1>Drift Analytics Dashboard</h1>")
    for label, value in meta:
        parts.append(f'<p class="meta"><strong>{_esc(label)}:</strong> {_esc(value)}</p>')

    parts.append("<h2>Summary</h2>")
    parts.append('<div class="cards">')
    for key, label, default in _SUMMARY_CARDS:
        value = summary.get(key, default)
        parts.append('<div class="card">')
        parts.append(f'<div class="label">{_esc(label)}</div>')
        parts.append(f'<div class="value">{_esc(_filter_display(value))}</div>')
        parts.append("</div>")
    parts.append("</div>")

    parts.extend(_html_trend_summary(overview.summary))

    parts.append("<h2>Runs</h2>")
    if not runs:
        parts.append(_NO_RUNS_HTML)
    else:
        parts.extend(_html_table(_RUN_COLUMNS, runs))

    parts.append("<h2>Column-level drift metrics</h2>")
    if not columns:
        parts.append(_NO_COLUMNS_HTML)
    else:
        parts.extend(_html_table(_COLUMN_COLUMNS, columns))

    parts.extend(_html_top_drifted_columns(column_drifts))
    parts.extend(_html_metric_summary(column_drifts))

    if distributions is not None:
        parts.extend(_html_distributions(distributions))

    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts) + "\n"


def build_drift_dashboard(
    db_path: str | Path,
    *,
    current_dataset_id: str | None = None,
    limit: int | None = None,
    generated_at: str | None = None,
    include_plots: bool = False,
) -> str:
    """Fetch drift history from SQLite and render a static HTML dashboard.

    The run-level overview (trend summary + recent runs) is built through the
    shared monitoring view-model ``build_monitoring_overview`` (which itself reads
    only via the root ``data_quality_toolkit.api`` seam). Column-level rows and,
    when ``include_plots`` is true, distribution bins are fetched database-wide
    via ``read_drift_columns_sqlite`` / ``read_drift_distributions_sqlite``. A
    missing or empty database yields a valid zero dashboard rather than raising.
    """
    from data_quality_toolkit.application.monitoring.view_model import (
        build_monitoring_overview,
    )

    overview = build_monitoring_overview(
        db_path, current_dataset_id=current_dataset_id, limit=limit
    )

    from data_quality_toolkit.api import read_drift_columns_sqlite

    columns = read_drift_columns_sqlite(db_path)
    distributions: list[dict[str, Any]] | None = None
    if include_plots:
        from data_quality_toolkit.api import read_drift_distributions_sqlite

        distributions = read_drift_distributions_sqlite(db_path)
    return render_drift_dashboard(
        summary=overview.summary.to_dict(),
        runs=[run.to_dict() for run in overview.runs],
        columns=columns,
        db_path=db_path,
        current_dataset_id=current_dataset_id,
        limit=limit,
        generated_at=generated_at,
        distributions=distributions,
        version=_resolve_version(),
    )
