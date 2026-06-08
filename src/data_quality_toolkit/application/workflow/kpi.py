"""Application workflow for KPI catalog operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal


def validate_kpi_catalog(config_path: str | Path) -> dict[str, Any]:
    """
    Load and validate a KPI catalog (schema, semantics, dependency cycles).

    Args:
        config_path: Path to KPI catalog YAML file.

    Returns:
        dict with "status" ("valid" or "invalid"), "kpis" count, and summary fields.
        Valid result also includes "grains", "dependencies", and "by_grain".
        Invalid result includes "reason" and "cycles" (each cycle has first node appended).
    """
    from data_quality_toolkit.domain.semantics import load_catalog, validate_semantics
    from data_quality_toolkit.domain.semantics.dag import build_graph, detect_cycles

    catalog = load_catalog(config_path)

    graph = build_graph(catalog)
    raw_cycles = detect_cycles(graph)

    if raw_cycles:
        return {
            "status": "invalid",
            "reason": "cycles",
            "kpis": len(catalog.kpis),
            "cycles": [c + [c[0]] for c in raw_cycles],
        }

    validate_semantics(catalog)

    by_grain: dict[str, int] = {}
    for kpi in catalog.kpis:
        by_grain[kpi.grain] = by_grain.get(kpi.grain, 0) + 1

    deps_count = sum(len(k.depends_on) for k in catalog.kpis)

    return {
        "status": "valid",
        "kpis": len(catalog.kpis),
        "cycles": 0,
        "grains": list(by_grain.keys()),
        "dependencies": deps_count,
        "by_grain": by_grain,
    }


def emit_kpi_artifacts(
    config_path: str | Path,
    dax_out: str | Path,
    tmsl_out: str | Path,
) -> dict[str, Any]:
    """
    Load KPI catalog, validate semantics, and emit DAX + TMSL artifacts.

    Args:
        config_path: Path to KPI catalog YAML.
        dax_out: Output path for DAX measures file.
        tmsl_out: Output path for TMSL model JSON.

    Returns:
        dict with status, kpi count, and written file paths ("dax", "tmsl").
    """
    from data_quality_toolkit.domain.semantics import (
        load_catalog,
        validate_semantics,
        write_dax,
        write_tmsl,
    )

    catalog = load_catalog(config_path)
    validate_semantics(catalog)

    dax_path = write_dax(catalog, dax_out)
    tmsl_path = write_tmsl(catalog, tmsl_out)

    return {
        "status": "success",
        "kpis": len(catalog.kpis),
        "dax": dax_path,
        "tmsl": tmsl_path,
    }


def export_kpi_graph(
    config_path: str | Path,
    out: str | Path,
    graph_format: Literal["mermaid", "graphviz"] = "mermaid",
) -> dict[str, Any]:
    """
    Load KPI catalog and export dependency graph (Mermaid or Graphviz).

    Extension is adjusted automatically (.mmd for mermaid, .dot for graphviz).

    Args:
        config_path: Path to KPI catalog YAML.
        out: Output file path (extension adjusted to match format if needed).
        graph_format: "mermaid" (default, .mmd) or "graphviz" (.dot).

    Returns:
        dict with status, graph file path, format, and node count.
    """
    from data_quality_toolkit.domain.semantics import graph_export, load_catalog, write_mermaid

    catalog = load_catalog(config_path)

    fmt = str(graph_format).lower()
    out_path = str(out)

    if fmt == "graphviz":
        if out_path.endswith(".mmd"):
            out_path = out_path[:-4] + ".dot"
        graph_path = graph_export.write_graphviz(catalog, out_path)
    else:
        if not out_path.endswith(".mmd"):
            out_path = out_path + ".mmd"
        graph_path = write_mermaid(catalog, out_path)

    return {
        "status": "success",
        "graph": graph_path,
        "format": fmt,
        "nodes": len(catalog.kpis),
    }


def generate_dim_time_workflow(
    start_date: str = "2018-01-01",
    end_date: str = "2030-12-31",
    *,
    week_start: int = 1,
    fiscal_year_start: int | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Generate a time dimension table. If output_dir is given, write dim_time.csv.

    Args:
        start_date: Inclusive start date (YYYY-MM-DD).
        end_date: Inclusive end date (YYYY-MM-DD).
        week_start: 1..7 (1=Monday, 7=Sunday).
        fiscal_year_start: Fiscal year start month (1..12), optional.
        output_dir: If provided, write dim_time.csv to this directory and return path.

    Returns:
        dict with rows, start_date, end_date, week_start, and optionally path.
    """
    from data_quality_toolkit.adapters.exporters.time.dim_time_generator import generate_dim_time
    from data_quality_toolkit.utils.helpers import ensure_dir

    df = generate_dim_time(
        start_date=start_date,
        end_date=end_date,
        week_start=week_start,
        fiscal_year_start=fiscal_year_start,
    )

    result: dict[str, Any] = {
        "rows": int(len(df)),
        "start_date": start_date,
        "end_date": end_date,
        "week_start": week_start,
    }
    if fiscal_year_start is not None:
        result["fiscal_year_start"] = fiscal_year_start

    if output_dir is not None:
        out_dir = ensure_dir(Path(output_dir))
        out_path = out_dir / "dim_time.csv"
        df.to_csv(out_path, index=False)
        result["path"] = str(out_path)

    return result
