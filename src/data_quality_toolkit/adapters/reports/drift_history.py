"""Render drift-history monitoring reports (Markdown / HTML).

Pure rendering plus a thin convenience builder over the accepted public APIs.
``render_drift_history_report`` does no I/O: it turns an already-fetched trend
summary dict and a list of drift-run dicts into a Markdown (default) or HTML
string. ``build_drift_history_report`` fetches via
``summarize_drift_trends_sqlite`` / ``read_drift_runs_sqlite`` and renders.

No SQLite schema, importer, query-helper, or trend-helper behavior is changed.
HTML output is dependency-free (stdlib ``html.escape`` only).
"""

from __future__ import annotations

import html
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Recent-runs table columns: (run dict key, display header).
_RUN_COLUMNS: tuple[tuple[str, str], ...] = (
    ("run_id", "run_id"),
    ("created_at", "created_at"),
    ("current_dataset_id", "current_dataset_id"),
    ("status", "status"),
    ("columns_tested", "columns_tested"),
    ("columns_drifted", "columns_drifted"),
    ("drift_detected", "drift_detected"),
)

# Column-level drift metrics table columns: (column dict key, display header).
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

_NO_COLUMN_ROWS_MD = "_No column-level drift rows available._"
_NO_COLUMN_ROWS_HTML = "<p>No column-level drift rows available.</p>"

_NO_DIST_ROWS_MD = "_No distribution rows available._"
_NO_DIST_ROWS_HTML = "<p>No distribution rows available.</p>"

# Inline-style colours for the dependency-free distribution bars.
_DIST_REF_COLOR = "#4a90d9"
_DIST_CUR_COLOR = "#d9534f"


def _utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (seconds resolution)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _filter_display(value: Any) -> str:
    """Human display for an optional filter value."""
    return "(none)" if value is None else str(value)


def _cell(value: Any) -> str:
    """String for a table cell; empty filters render as an empty string."""
    return "" if value is None else str(value)


def _md_table(spec: tuple[tuple[str, str], ...], rows: list[dict[str, Any]]) -> list[str]:
    """Render a Markdown table for ``rows`` using a (key, header) ``spec``."""
    headers = [hdr for _, hdr in spec]
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        cells = [_cell(row.get(key)) for key, _ in spec]
        out.append("| " + " | ".join(cells) + " |")
    return out


def _html_table(spec: tuple[tuple[str, str], ...], rows: list[dict[str, Any]]) -> list[str]:
    """Render an HTML table for ``rows`` using a (key, header) ``spec`` (escaped)."""
    out = ["<table>", "<thead><tr>"]
    out.extend(f"<th>{html.escape(hdr)}</th>" for _, hdr in spec)
    out.append("</tr></thead>")
    out.append("<tbody>")
    for row in rows:
        out.append("<tr>")
        out.extend(f"<td>{html.escape(_cell(row.get(key)))}</td>" for key, _ in spec)
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


def _md_bar(value: Any, width: int = 10) -> str:
    """Compact unicode block bar for a 0..1 probability (markdown-safe)."""
    try:
        frac = float(value)
    except (TypeError, ValueError):
        return ""
    frac = max(0.0, min(1.0, frac))
    return "█" * int(round(frac * width))


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


def _md_distributions(distributions: list[dict[str, Any]]) -> list[str]:
    """Render the markdown "Distribution plots" section (HTML-safe compact bars)."""
    out = ["## Distribution plots", ""]
    if not distributions:
        out.append(_NO_DIST_ROWS_MD)
        out.append("")
        return out
    for run_id, column_name, kind, rows in _group_distributions(distributions):
        out.append(f"### run_id={run_id} · column_name={column_name} ({_cell(kind)})")
        out.append("")
        out.append("| bin_label | reference | current | reference bar | current bar |")
        out.append("| --- | --- | --- | --- | --- |")
        for row in rows:
            ref = row.get("reference_prob")
            cur = row.get("current_prob")
            out.append(
                f"| {_cell(row.get('bin_label'))} | {_pct(ref)} | {_pct(cur)} "
                f"| {_md_bar(ref)} | {_md_bar(cur)} |"
            )
        out.append("")
    return out


def _html_bar_row(tag: str, value: Any, color: str) -> str:
    """One inline-CSS horizontal bar (no JS / no external assets)."""
    width = _bar_width(value)
    pct = html.escape(_pct(value))
    return (
        '<div style="display:flex;align-items:center;gap:0.5rem;margin:0.15rem 0;">'
        f'<span style="width:2rem;font-size:0.8rem;color:#666;">{tag}</span>'
        '<span style="display:inline-block;width:12rem;height:0.8rem;'
        'background:#eee;border:1px solid #ddd;">'
        f'<span style="display:block;height:100%;width:{width};'
        f'background:{color};"></span></span>'
        f'<span style="font-size:0.8rem;">{pct}</span>'
        "</div>"
    )


def _html_distributions(distributions: list[dict[str, Any]]) -> list[str]:
    """Render the HTML "Distribution plots" section with inline-CSS paired bars."""
    out = ["<h2>Distribution plots</h2>"]
    if not distributions:
        out.append(_NO_DIST_ROWS_HTML)
        return out
    for run_id, column_name, kind, rows in _group_distributions(distributions):
        title = f"run_id={run_id} · column_name={column_name} ({_cell(kind)})"
        out.append(f"<h3>{html.escape(title)}</h3>")
        for row in rows:
            label = html.escape(_cell(row.get("bin_label")))
            out.append('<div style="margin:0.5rem 0;">')
            out.append(f'<div style="font-size:0.85rem;color:#555;">{label}</div>')
            out.append(_html_bar_row("ref", row.get("reference_prob"), _DIST_REF_COLOR))
            out.append(_html_bar_row("cur", row.get("current_prob"), _DIST_CUR_COLOR))
            out.append("</div>")
    return out


def render_drift_history_report(
    *,
    summary: dict[str, Any],
    runs: list[dict[str, Any]],
    db_path: str | Path,
    current_dataset_id: str | None = None,
    limit: int | None = None,
    generated_at: str | None = None,
    fmt: str = "md",
    columns: list[dict[str, Any]] | None = None,
    distributions: list[dict[str, Any]] | None = None,
) -> str:
    """Render a drift-history monitoring report from fetched data.

    ``summary`` is the dict returned by ``summarize_drift_trends_sqlite`` and
    ``runs`` the list returned by ``read_drift_runs_sqlite`` (newest first). No
    I/O is performed. ``generated_at`` is embedded verbatim when provided (kept
    deterministic for tests); otherwise the current UTC time is used. ``fmt`` is
    ``"md"`` (default) or ``"html"``. A zero-summary with empty ``runs`` renders
    a valid zero report.

    ``columns`` is the optional list returned by ``read_drift_columns_sqlite``.
    When ``None`` (default) no column-level section is rendered. When provided
    (including an empty list) a "Column-level drift metrics" section is added;
    an empty list renders a "no rows available" placeholder.

    ``distributions`` is the optional list returned by
    ``read_drift_distributions_sqlite``. When ``None`` (default) no plot section
    is rendered. When provided (including an empty list) a "Distribution plots"
    section is added; an empty list renders a clear empty-state. Bars are
    dependency-free (markdown unicode blocks / HTML inline-CSS bars).
    """
    generated_at = generated_at or _utc_now_iso()
    if fmt == "html":
        return _render_html(
            summary=summary,
            runs=runs,
            db_path=str(db_path),
            current_dataset_id=current_dataset_id,
            limit=limit,
            generated_at=generated_at,
            columns=columns,
            distributions=distributions,
        )
    return _render_markdown(
        summary=summary,
        runs=runs,
        db_path=str(db_path),
        current_dataset_id=current_dataset_id,
        limit=limit,
        generated_at=generated_at,
        columns=columns,
        distributions=distributions,
    )


def _render_markdown(
    *,
    summary: dict[str, Any],
    runs: list[dict[str, Any]],
    db_path: str,
    current_dataset_id: str | None,
    limit: int | None,
    generated_at: str,
    columns: list[dict[str, Any]] | None = None,
    distributions: list[dict[str, Any]] | None = None,
) -> str:
    lines: list[str] = []
    lines.append("# Drift History Monitoring Report")
    lines.append("")
    lines.append(f"- **generated_at:** {generated_at}")
    lines.append(f"- **database:** {db_path}")
    lines.append(f"- **current_dataset_id filter:** {_filter_display(current_dataset_id)}")
    lines.append(f"- **limit:** {_filter_display(limit)}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **total_runs:** {summary.get('total_runs', 0)}")
    lines.append(f"- **drifted_runs:** {summary.get('drifted_runs', 0)}")
    lines.append(f"- **non_drifted_runs:** {summary.get('non_drifted_runs', 0)}")
    lines.append(f"- **drift_rate:** {summary.get('drift_rate', 0.0)}")
    lines.append(f"- **latest_run_id:** {_filter_display(summary.get('latest_run_id'))}")
    lines.append(f"- **latest_created_at:** {_filter_display(summary.get('latest_created_at'))}")
    lines.append(
        f"- **latest_drift_detected:** {_filter_display(summary.get('latest_drift_detected'))}"
    )
    lines.append(f"- **columns_tested_total:** {summary.get('columns_tested_total', 0)}")
    lines.append(f"- **columns_tested_average:** {summary.get('columns_tested_average', 0.0)}")
    lines.append(f"- **columns_drifted_total:** {summary.get('columns_drifted_total', 0)}")
    lines.append(f"- **columns_drifted_average:** {summary.get('columns_drifted_average', 0.0)}")
    lines.append("")
    lines.append("## Recent Runs")
    lines.append("")
    if not runs:
        lines.append("_(no runs)_")
        lines.append("")
    else:
        lines.extend(_md_table(_RUN_COLUMNS, runs))
        lines.append("")

    if columns is not None:
        lines.append("## Column-level drift metrics")
        lines.append("")
        if not columns:
            lines.append(_NO_COLUMN_ROWS_MD)
        else:
            lines.extend(_md_table(_COLUMN_COLUMNS, columns))
        lines.append("")

    if distributions is not None:
        lines.extend(_md_distributions(distributions))

    return "\n".join(lines) + "\n"


def _render_html(
    *,
    summary: dict[str, Any],
    runs: list[dict[str, Any]],
    db_path: str,
    current_dataset_id: str | None,
    limit: int | None,
    generated_at: str,
    columns: list[dict[str, Any]] | None = None,
    distributions: list[dict[str, Any]] | None = None,
) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value))

    meta = [
        ("generated_at", generated_at),
        ("database", db_path),
        ("current_dataset_id filter", _filter_display(current_dataset_id)),
        ("limit", _filter_display(limit)),
    ]
    metrics = [
        ("total_runs", summary.get("total_runs", 0)),
        ("drifted_runs", summary.get("drifted_runs", 0)),
        ("non_drifted_runs", summary.get("non_drifted_runs", 0)),
        ("drift_rate", summary.get("drift_rate", 0.0)),
        ("latest_run_id", _filter_display(summary.get("latest_run_id"))),
        ("latest_created_at", _filter_display(summary.get("latest_created_at"))),
        ("latest_drift_detected", _filter_display(summary.get("latest_drift_detected"))),
        ("columns_tested_total", summary.get("columns_tested_total", 0)),
        ("columns_tested_average", summary.get("columns_tested_average", 0.0)),
        ("columns_drifted_total", summary.get("columns_drifted_total", 0)),
        ("columns_drifted_average", summary.get("columns_drifted_average", 0.0)),
    ]

    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append("<title>Drift History Monitoring Report</title>")
    parts.append("</head>")
    parts.append("<body>")
    parts.append("<h1>Drift History Monitoring Report</h1>")
    parts.append("<ul>")
    for label, value in meta:
        parts.append(f"<li><strong>{esc(label)}:</strong> {esc(value)}</li>")
    parts.append("</ul>")
    parts.append("<h2>Summary</h2>")
    parts.append("<ul>")
    for label, value in metrics:
        parts.append(f"<li><strong>{esc(label)}:</strong> {esc(value)}</li>")
    parts.append("</ul>")
    parts.append("<h2>Recent Runs</h2>")
    if not runs:
        parts.append("<p>(no runs)</p>")
    else:
        parts.extend(_html_table(_RUN_COLUMNS, runs))

    if columns is not None:
        parts.append("<h2>Column-level drift metrics</h2>")
        if not columns:
            parts.append(_NO_COLUMN_ROWS_HTML)
        else:
            parts.extend(_html_table(_COLUMN_COLUMNS, columns))

    if distributions is not None:
        parts.extend(_html_distributions(distributions))

    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts) + "\n"


def build_drift_history_report(
    db_path: str | Path,
    *,
    current_dataset_id: str | None = None,
    limit: int | None = None,
    fmt: str = "md",
    generated_at: str | None = None,
    include_columns: bool = False,
    include_plots: bool = False,
) -> str:
    """Fetch drift history from SQLite and render a report string.

    Reuses the accepted public APIs ``summarize_drift_trends_sqlite`` and
    ``read_drift_runs_sqlite``. A missing or empty database yields a valid
    zero report. ``fmt`` is ``"md"`` (default) or ``"html"``. When
    ``include_columns`` is true, per-column drift rows are fetched via
    ``read_drift_columns_sqlite`` and rendered as an extra section. When
    ``include_plots`` is true, persisted distribution bins are fetched via
    ``read_drift_distributions_sqlite`` and rendered as a "Distribution plots"
    section (an empty database renders a clear empty-state).
    """
    from data_quality_toolkit.api import (
        read_drift_runs_sqlite,
        summarize_drift_trends_sqlite,
    )

    summary = summarize_drift_trends_sqlite(
        db_path, current_dataset_id=current_dataset_id, limit=limit
    )
    runs = read_drift_runs_sqlite(db_path, current_dataset_id=current_dataset_id, limit=limit)
    columns: list[dict[str, Any]] | None = None
    if include_columns:
        from data_quality_toolkit.api import read_drift_columns_sqlite

        columns = read_drift_columns_sqlite(db_path)
    distributions: list[dict[str, Any]] | None = None
    if include_plots:
        from data_quality_toolkit.api import read_drift_distributions_sqlite

        distributions = read_drift_distributions_sqlite(db_path)
    return render_drift_history_report(
        summary=summary,
        runs=runs,
        db_path=db_path,
        current_dataset_id=current_dataset_id,
        limit=limit,
        generated_at=generated_at,
        fmt=fmt,
        columns=columns,
        distributions=distributions,
    )
