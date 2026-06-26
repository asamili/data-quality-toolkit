"""Drift-history Excel (``.xlsx``) workbook export (v2.6.1).

Local, opt-in export behind the existing ``[powerbi]`` extra. Reads an existing
drift-monitoring SQLite database through the public ``data_quality_toolkit.api``
seam and writes a multi-sheet ``.xlsx`` workbook with openpyxl in write-only
(streaming) mode. No schema changes, no network, no cloud, no ``.pbix``.

Security: every string cell — headers, data, and metadata — is neutralized
against spreadsheet formula injection (CWE-1236). The exporter emits no formulas,
macros, external links, or embedded objects.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_quality_toolkit.shared.constants import VERSION
from data_quality_toolkit.shared.exceptions import DQTError
from data_quality_toolkit.shared.path_guard import PathGuardError, validate_output_dir
from data_quality_toolkit.utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "XlsxExportError",
    "escape_formula",
    "build_workbook_model",
    "export_drift_history_xlsx",
]

_OPENPYXL_HINT = (
    "openpyxl is not installed; install the powerbi extra: "
    "pip install data-quality-toolkit[powerbi]"
)

# Leading characters a spreadsheet may interpret as the start of a formula.
_FORMULA_PREFIXES = ("=", "+", "-", "@")

# Column orders mirror adapters/storage/queries.py reader output (stable headers).
_RUNS_HEADERS = (
    "run_id",
    "created_at",
    "baseline_path",
    "current_path",
    "baseline_dataset_id",
    "current_dataset_id",
    "status",
    "alpha",
    "columns_tested",
    "columns_skipped",
    "columns_drifted",
    "drift_detected",
    "report_path",
    "schema_version",
)
_COLUMN_HEADERS = (
    "run_id",
    "column_name",
    "kind",
    "test",
    "statistic",
    "p_value",
    "drift_detected",
    "reference_n",
    "current_n",
    "status",
    "skip_reason",
    "psi",
    "js_distance",
    "wasserstein",
)
_DIST_HEADERS = (
    "run_id",
    "column_name",
    "kind",
    "bin_index",
    "bin_label",
    "reference_prob",
    "current_prob",
)


class XlsxExportError(DQTError):
    """Raised when the drift-history ``.xlsx`` export fails."""


def _import_openpyxl() -> Any:
    """Return the openpyxl module, or raise XlsxExportError with an install hint.

    Isolated so callers and tests can simulate the missing-dependency path
    without installing or uninstalling openpyxl.
    """
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch in tests
        raise XlsxExportError(_OPENPYXL_HINT, hint=_OPENPYXL_HINT) from exc
    return openpyxl


def escape_formula(value: Any) -> Any:
    """Neutralize spreadsheet formula injection for a single cell value.

    String values that could be parsed as a formula are prefixed with a single
    quote so spreadsheet software treats them as literal text. A value is treated
    as dangerous when its first non-control character is one of ``= + - @``, or
    when it leads with a tab/carriage return (which some clients strip before
    parsing). Non-string values are returned unchanged.
    """
    if not isinstance(value, str) or not value:
        return value
    if value[0] in ("\t", "\r"):
        return "'" + value
    stripped = value.lstrip("\t\r\n ")
    if stripped and stripped[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def _records_sheet(headers: tuple[str, ...], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Build an escaped header row + data rows (header order) for tabular records."""
    return {
        "headers": [escape_formula(h) for h in headers],
        "rows": [[escape_formula(rec.get(h)) for h in headers] for rec in records],
        "count": len(records),
    }


def _kv_sheet(mapping: dict[str, Any]) -> dict[str, Any]:
    """Build an escaped two-column (key/value) sheet from a mapping."""
    return {
        "headers": [escape_formula("key"), escape_formula("value")],
        "rows": [[escape_formula(str(k)), escape_formula(v)] for k, v in mapping.items()],
        "count": len(mapping),
    }


def build_workbook_model(
    *,
    runs: list[dict[str, Any]],
    summary: dict[str, Any],
    columns: list[dict[str, Any]] | None,
    distributions: list[dict[str, Any]] | None,
    metadata: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build the pure, openpyxl-free workbook model (sheet -> headers/rows/count).

    ``columns`` is ``None`` when the columns sheet is excluded; ``distributions``
    is ``None`` when the distributions sheet is excluded. Sheet insertion order is
    the workbook order: runs, trend_summary, [columns], [distributions], metadata.
    """
    model: dict[str, dict[str, Any]] = {}
    model["runs"] = _records_sheet(_RUNS_HEADERS, runs)
    model["trend_summary"] = _kv_sheet(summary)
    if columns is not None:
        model["columns"] = _records_sheet(_COLUMN_HEADERS, columns)
    if distributions is not None:
        model["distributions"] = _records_sheet(_DIST_HEADERS, distributions)
    model["metadata"] = _kv_sheet(metadata)
    return model


def _build_metadata(
    db_path: str | Path,
    output_path: str | Path,
    current_dataset_id: str | None,
    limit: int | None,
    include_columns: bool,
    include_distributions: bool,
) -> dict[str, Any]:
    """Build provenance metadata. No secrets/env values — only caller-supplied args."""
    return {
        "tool_version": VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "db_path": str(db_path),
        "output_path": str(output_path),
        "current_dataset_id": "" if current_dataset_id is None else current_dataset_id,
        "limit": "" if limit is None else str(limit),
        "include_columns": str(include_columns),
        "include_distributions": str(include_distributions),
    }


def _validate_output_path(output_path: str | Path, *, force: bool) -> Path:
    """Validate the ``.xlsx`` output path; refuse overwrite unless ``force``.

    Enforces a non-empty path, the ``.xlsx`` extension, and reuses path_guard
    traversal/symlink rules against the parent directory. Returns the resolved
    Path. Raises XlsxExportError on any violation.
    """
    raw = str(output_path).strip()
    if not raw:
        raise XlsxExportError("Output path must not be empty.")

    p = Path(raw)
    if p.suffix.lower() != ".xlsx":
        raise XlsxExportError(f"Output path must end with .xlsx, got: {p.name}")

    try:
        validate_output_dir(p.parent, must_be_absolute=False)
    except PathGuardError as exc:
        raise XlsxExportError(str(exc)) from exc

    resolved = p.resolve()
    if resolved.exists():
        if resolved.is_dir():
            raise XlsxExportError(f"Output path is an existing directory: {resolved}")
        if not force:
            raise XlsxExportError(
                f"Output file already exists; pass --force to overwrite: {resolved}"
            )
    return resolved


def export_drift_history_xlsx(
    db_path: str | Path,
    output_path: str | Path,
    *,
    current_dataset_id: str | None = None,
    limit: int | None = None,
    include_columns: bool = True,
    include_distributions: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Export drift-history monitoring data to a multi-sheet ``.xlsx`` workbook.

    Reads an existing monitoring SQLite database through the
    ``data_quality_toolkit.api`` seam (no schema changes) and writes a workbook
    with sheets: ``runs``, ``trend_summary``, ``columns`` (when
    ``include_columns``), ``distributions`` (when ``include_distributions``), and
    ``metadata``. A missing or empty database yields a valid zero-state workbook.

    Requires the optional ``[powerbi]`` extra (openpyxl); raises XlsxExportError
    with an install hint when it is absent. Refuses to overwrite an existing file
    unless ``force`` is True. All string cells are escaped against formula
    injection.

    Returns ``{"output_path", "sheets", "row_counts"}``.
    """
    openpyxl = _import_openpyxl()  # fail fast before any I/O
    out = _validate_output_path(output_path, force=force)

    from data_quality_toolkit.api import (
        read_drift_columns_sqlite,
        read_drift_distributions_sqlite,
        read_drift_runs_sqlite,
        summarize_drift_trends_sqlite,
    )

    runs = read_drift_runs_sqlite(db_path, limit=limit, current_dataset_id=current_dataset_id)
    summary = summarize_drift_trends_sqlite(
        db_path, current_dataset_id=current_dataset_id, limit=limit
    )
    columns = read_drift_columns_sqlite(db_path) if include_columns else None
    distributions = read_drift_distributions_sqlite(db_path) if include_distributions else None

    metadata = _build_metadata(
        db_path, output_path, current_dataset_id, limit, include_columns, include_distributions
    )
    model = build_workbook_model(
        runs=runs,
        summary=summary,
        columns=columns,
        distributions=distributions,
        metadata=metadata,
    )

    wb = openpyxl.Workbook(write_only=True)
    sheets: list[str] = []
    row_counts: dict[str, int] = {}
    for name, sheet in model.items():
        ws = wb.create_sheet(title=name)
        ws.append(sheet["headers"])
        for row in sheet["rows"]:
            ws.append(row)
        sheets.append(name)
        row_counts[name] = sheet["count"]

    try:
        wb.save(str(out))
    except OSError as exc:
        raise XlsxExportError(f"Failed to write workbook to {out}: {exc}") from exc

    logger.info("Drift workbook written: %s (sheets=%s)", out, ",".join(sheets))
    return {"output_path": str(out), "sheets": sheets, "row_counts": row_counts}
