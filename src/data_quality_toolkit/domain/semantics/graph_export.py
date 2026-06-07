"""Phase 3: Graph visualization exports."""

from __future__ import annotations

from pathlib import Path

from data_quality_toolkit.utils.helpers import ensure_dir
from data_quality_toolkit.utils.logging import get_logger

from .dag import build_graph
from .schema import Catalog

logger = get_logger(__name__)


def write_mermaid(catalog: Catalog, output_path: str | Path) -> str:
    """
    Export KPI dependency graph as Mermaid diagram.

    Args:
        catalog: KPI catalog
        output_path: Output file path

    Returns:
        Path to written file
    """
    logger.info("Generating Mermaid graph")

    graph = build_graph(catalog)

    lines = ["flowchart TB"]
    lines.append("")

    # Define nodes with styling
    lines.append("  %% Node definitions")
    for kpi in catalog.kpis:
        # Use different shapes based on grain
        shape = _get_node_shape(kpi.grain)
        label = f"{kpi.title}\\n({kpi.unit})"
        lines.append(f'  {kpi.id}{shape[0]}"{label}"{shape[1]}')

    lines.append("")
    lines.append("  %% Dependencies")

    # Add edges
    for node, dependencies in graph.items():
        for dep in dependencies:
            lines.append(f"  {dep} --> {node}")

    # Add styling
    lines.append("")
    lines.append("  %% Styling")
    lines.append("  classDef global fill:#e1f5fe,stroke:#01579b,stroke-width:2px")
    lines.append("  classDef dataset fill:#f3e5f5,stroke:#4a148c,stroke-width:2px")
    lines.append("  classDef column fill:#fff3e0,stroke:#e65100,stroke-width:2px")

    # Apply styles
    for kpi in catalog.kpis:
        if kpi.grain == "global":
            lines.append(f"  class {kpi.id} global")
        elif kpi.grain == "dataset":
            lines.append(f"  class {kpi.id} dataset")
        elif kpi.grain == "column":
            lines.append(f"  class {kpi.id} column")

    mermaid_content = "\n".join(lines) + "\n"

    output_file = Path(output_path)
    ensure_dir(output_file.parent)

    output_file.write_text(mermaid_content, encoding="utf-8")

    logger.info(f"Wrote Mermaid graph to {output_file}")
    return str(output_file)


def _get_node_shape(grain: str) -> tuple[str, str]:
    """Get Mermaid node shape based on grain."""
    shapes = {
        "global": ("[", "]"),  # Rectangle
        "dataset": ("([", "])"),  # Stadium
        "table": ("{", "}"),  # Rhombus
        "column": ("((", "))"),  # Circle
        "time": ("{{", "}}"),  # Hexagon
    }
    return shapes.get(grain, ("[", "]"))


def write_graphviz(catalog: Catalog, output_path: str | Path) -> str:
    """
    Export KPI dependency graph as Graphviz DOT file.

    Args:
        catalog: KPI catalog
        output_path: Output file path

    Returns:
        Path to written file
    """
    logger.info("Generating Graphviz DOT file")

    graph = build_graph(catalog)

    lines = ["digraph KPIs {"]
    lines.append("  rankdir=BT;")
    lines.append("  node [shape=box, style=rounded];")
    lines.append("")

    # Define nodes
    for kpi in catalog.kpis:
        label = f"{kpi.title}\\n{kpi.unit}"
        color = _get_node_color(kpi.grain)
        lines.append(f'  {kpi.id} [label="{label}", fillcolor="{color}", style="rounded,filled"];')

    lines.append("")

    # Add edges
    for node, dependencies in graph.items():
        for dep in dependencies:
            lines.append(f"  {dep} -> {node};")

    lines.append("}")

    dot_content = "\n".join(lines) + "\n"

    output_file = Path(output_path)
    ensure_dir(output_file.parent)

    output_file.write_text(dot_content, encoding="utf-8")

    logger.info(f"Wrote Graphviz DOT to {output_file}")
    return str(output_file)


def _get_node_color(grain: str) -> str:
    """Get node color based on grain."""
    colors = {
        "global": "lightblue",
        "dataset": "lavender",
        "table": "lightyellow",
        "column": "lightgreen",
        "time": "lightcoral",
    }
    return colors.get(grain, "white")
