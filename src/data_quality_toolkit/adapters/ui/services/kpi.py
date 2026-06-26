"""KPI catalog and time-dimension service wrappers for the dashboard UI."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any


def _run_kpi_validate(config_path: str) -> tuple[dict[str, Any] | None, str | None]:
    """Call kpi_validate workflow. Returns (result, None) or (None, error_message)."""
    try:
        from data_quality_toolkit.api import kpi_validate as _kpi_validate

        return _kpi_validate(config_path.strip()), None
    except Exception as exc:
        return None, str(exc)


def _generate_dim_time_csv(
    start_date: str,
    end_date: str,
    week_start: int = 1,
    fiscal_year_start: int | None = None,
) -> tuple[str | None, int | None, str | None]:
    """Generate dim_time CSV string in memory (no disk writes).

    Returns (csv_str, row_count, None) or (None, None, error_message).
    """
    try:
        from data_quality_toolkit.adapters.exporters.time.dim_time_generator import (
            generate_dim_time,
        )

        df = generate_dim_time(
            start_date=start_date,
            end_date=end_date,
            week_start=week_start,
            fiscal_year_start=fiscal_year_start,
        )
        return df.to_csv(index=False), len(df), None
    except Exception as exc:
        return None, None, str(exc)


def _kpi_emit_to_bytes(
    config_path: str,
) -> tuple[bytes | None, bytes | None, str | None]:
    """Emit DAX and TMSL to a temp dir, read back bytes, discard temp files.

    Returns (dax_bytes, tmsl_bytes, None) or (None, None, error_message).
    No persistent writes — temp dir is deleted on context exit.
    """
    try:
        from data_quality_toolkit.api import kpi_emit as _kpi_emit

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _kpi_emit(
                config_path,
                tmp_path / "measures.dax",
                tmp_path / "model.tmsl.json",
            )
            dax_bytes = (tmp_path / "measures.dax").read_bytes()
            tmsl_bytes = (tmp_path / "model.tmsl.json").read_bytes()
        return dax_bytes, tmsl_bytes, None
    except Exception as exc:
        return None, None, str(exc)


def _kpi_graph_to_str(
    config_path: str,
    graph_format: str = "mermaid",
) -> tuple[str | None, str | None]:
    """Export KPI graph to a temp file, read back as string, discard temp file.

    Returns (graph_content, None) or (None, error_message).
    No persistent writes — temp dir is deleted on context exit.
    """
    try:
        from data_quality_toolkit.api import kpi_graph as _kpi_graph

        ext = ".dot" if graph_format == "graphviz" else ".mmd"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / f"graph{ext}"
            _kpi_graph(config_path, out, graph_format=graph_format)  # type: ignore[arg-type]
            content = out.read_text(encoding="utf-8")
        return content, None
    except Exception as exc:
        return None, str(exc)
