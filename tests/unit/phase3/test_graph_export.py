from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from data_quality_toolkit.domain.semantics.graph_export import (
    _get_node_color,
    _get_node_shape,
    write_graphviz,
    write_mermaid,
)
from data_quality_toolkit.domain.semantics.schema import KPI, Catalog, Grain, Unit


def _kpi(
    id: str,
    *,
    title: str | None = None,
    expr: str = "1",
    grain: Grain = "global",
    unit: Unit = "count",
    depends_on: Iterable[str] = (),
) -> KPI:
    return KPI(
        id=id,
        title=title or id.upper(),
        expression=expr,
        grain=grain,
        unit=unit,
        depends_on=list(depends_on),
        description=None,
        format_string=None,
    )


def test_write_mermaid_nodes_edges_and_styles(tmp_path: Path) -> None:
    # a -> b -> c, with different grains to exercise shapes/classes
    a = _kpi("a", title="A", grain="global")
    b = _kpi("b", title="B", grain="dataset", depends_on=("a",))
    c = _kpi("c", title="C", grain="column", depends_on=("b",))
    cat = Catalog(kpis=[a, b, c], description=None)

    out_file = tmp_path / "graph.mmd"
    result_path = write_mermaid(cat, out_file)
    assert result_path == str(out_file)

    text = out_file.read_text(encoding="utf-8")

    # header
    assert text.startswith("flowchart TB")

    # node definitions (shape + label)
    # Labels include a newline in Mermaid as \n and unit is shown in parentheses
    assert 'a["A\\n(count)"]' in text  # global -> rectangle [ ]
    assert 'b(["B\\n(count)"])' in text  # dataset -> stadium ([ ])
    assert 'c(("C\\n(count)"))' in text  # column -> circle (( ))

    # edges (dependencies)
    assert "a --> b" in text
    assert "b --> c" in text

    # styling sections present
    assert "classDef global" in text
    assert "classDef dataset" in text
    assert "classDef column" in text

    # class application per grain
    assert "class a global" in text
    assert "class b dataset" in text
    assert "class c column" in text


def test_write_graphviz_nodes_edges_and_colors(tmp_path: Path) -> None:
    a = _kpi("a", title="A", grain="global")
    b = _kpi("b", title="B", grain="dataset", depends_on=("a",))
    c = _kpi("c", title="C", grain="column", depends_on=("b",))
    cat = Catalog(kpis=[a, b, c], description=None)

    out_file = tmp_path / "graph.dot"
    result_path = write_graphviz(cat, out_file)
    assert result_path == str(out_file)

    dot = out_file.read_text(encoding="utf-8")

    # header and basic graph attributes
    assert dot.splitlines()[0].strip() == "digraph KPIs {"
    assert "rankdir=BT;" in dot
    assert "node [shape=box, style=rounded];" in dot

    # nodes: label has a newline and unit on second line; fillcolor by grain
    assert 'a [label="A\\ncount", fillcolor="lightblue", style="rounded,filled"];' in dot
    assert 'b [label="B\\ncount", fillcolor="lavender", style="rounded,filled"];' in dot
    assert 'c [label="C\\ncount", fillcolor="lightgreen", style="rounded,filled"];' in dot

    # edges
    assert "a -> b;" in dot
    assert "b -> c;" in dot

    # closing brace
    assert dot.strip().endswith("}")


def test_get_node_shape_mapping() -> None:
    # Known grains
    assert _get_node_shape("global") == ("[", "]")
    assert _get_node_shape("dataset") == ("([", "])")
    assert _get_node_shape("table") == ("{", "}")
    assert _get_node_shape("column") == ("((", "))")
    assert _get_node_shape("time") == ("{{", "}}")
    # Fallback for unknown grain
    assert _get_node_shape("unknown") == ("[", "]")


def test_get_node_color_mapping() -> None:
    # Known grains
    assert _get_node_color("global") == "lightblue"
    assert _get_node_color("dataset") == "lavender"
    assert _get_node_color("table") == "lightyellow"
    assert _get_node_color("column") == "lightgreen"
    assert _get_node_color("time") == "lightcoral"
    # Fallback for unknown grain
    assert _get_node_color("wut") == "white"
