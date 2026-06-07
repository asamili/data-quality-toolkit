"""Phase 3: DAX and TMSL generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_quality_toolkit.utils.helpers import ensure_dir
from data_quality_toolkit.utils.logging import get_logger

from .dag import get_execution_order
from .schema import Catalog
from .validators import validate_dax_syntax

logger = get_logger(__name__)

# cspell:ignore TMSL tmsl kpis

# Default table name for measures in Power BI
MEASURE_TABLE = "Quality"


def _format_measure_name(title: str) -> str:
    """Format measure name for Power BI."""
    # Keep the nice title as-is
    return title


def _apply_scaling(expression: str, scale: float) -> str:
    """Apply scaling factor to expression if needed."""
    if abs(scale - 1.0) < 1e-9:
        return expression
    return f"( {expression} ) * {scale}"


def emit_dax(catalog: Catalog) -> str:
    """
    Generate DAX measures from KPI catalog.

    Args:
        catalog: KPI catalog

    Returns:
        DAX script with all measures
    """
    logger.info("Generating DAX measures")

    # Get execution order
    execution_order = get_execution_order(catalog)
    kpi_index = {kpi.id: kpi for kpi in catalog.kpis}

    measures = []

    for kpi_id in execution_order:
        kpi = kpi_index[kpi_id]

        if kpi.hidden:
            logger.debug(f"Skipping hidden KPI: {kpi_id}")
            continue

        # Format measure name
        measure_name = _format_measure_name(kpi.title)

        # Apply scaling
        expression = _apply_scaling(kpi.expression, kpi.scale)

        # Validate DAX syntax
        if not validate_dax_syntax(expression):
            logger.warning(f"Potential syntax issue in KPI '{kpi_id}': {expression}")

        # Build measure definition
        measure_def = f"MEASURE '{MEASURE_TABLE}'[{measure_name}] = {expression}"

        # Add format string if specified
        if kpi.format_string:
            measure_def += f'\n    FORMAT_STRING = "{kpi.format_string}"'

        # Add description as comment
        if kpi.description:
            measures.append(f"-- {kpi.description}")

        measures.append(measure_def)
        measures.append("")  # Empty line between measures

    dax_script = "\n".join(measures).strip() + "\n"

    logger.info(f"Generated {len(execution_order)} DAX measures")
    return dax_script


def write_dax(catalog: Catalog, output_path: str | Path) -> str:
    """
    Write DAX measures to file.

    Args:
        catalog: KPI catalog
        output_path: Output file path

    Returns:
        Path to written file
    """
    dax_content = emit_dax(catalog)

    output_file = Path(output_path)
    ensure_dir(output_file.parent)

    output_file.write_text(dax_content, encoding="utf-8")

    logger.info(f"Wrote DAX measures to {output_file}")
    return str(output_file)


def build_tmsl_measures(catalog: Catalog) -> list[dict[str, Any]]:
    """Build TMSL measure definitions."""
    execution_order = get_execution_order(catalog)
    kpi_index = {kpi.id: kpi for kpi in catalog.kpis}

    measures: list[dict[str, Any]] = []
    for kpi_id in execution_order:
        kpi = kpi_index[kpi_id]
        if kpi.hidden:
            continue

        measure: dict[str, Any] = {
            "name": _format_measure_name(kpi.title),
            "expression": _apply_scaling(kpi.expression, kpi.scale),
        }
        if kpi.description:
            measure["description"] = kpi.description
        if kpi.format_string:
            measure["formatString"] = kpi.format_string

        measures.append(measure)
    return measures


def write_tmsl(catalog: Catalog, output_path: str | Path) -> str:
    """
    Write TMSL (Tabular Model Scripting Language) for measures.

    Args:
        catalog: KPI catalog
        output_path: Output file path

    Returns:
        Path to written file
    """
    logger.info("Generating TMSL for measures")

    measures = build_tmsl_measures(catalog)

    # Build TMSL createOrReplace command
    tmsl = {
        "createOrReplace": {
            "object": {"database": "Model", "table": MEASURE_TABLE},
            "table": {
                "name": MEASURE_TABLE,
                "description": "Data Quality Measures",
                "measures": measures,
            },
        }
    }

    output_file = Path(output_path)
    ensure_dir(output_file.parent)

    output_file.write_text(json.dumps(tmsl, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(f"Wrote TMSL to {output_file}")
    return str(output_file)
