# Phase 3: DAG operations for KPI dependencies.
from __future__ import annotations

from typing import cast

from data_quality_toolkit.utils.logging import get_logger

from .schema import Catalog

logger = get_logger(__name__)


def build_graph(catalog: Catalog) -> dict[str, list[str]]:
    """
    Build dependency graph from catalog.

    Returns:
        Adjacency list representation of dependencies
    """
    graph: dict[str, list[str]] = {}
    kpi_ids = catalog.kpi_ids

    for kpi in catalog.kpis:
        for dep in kpi.depends_on:
            if dep not in kpi_ids:
                raise ValueError(f"KPI '{kpi.id}' depends on unknown KPI '{dep}'")
        graph[kpi.id] = list(kpi.depends_on)

    logger.debug("Built dependency graph with %d nodes", len(graph))
    return graph


def detect_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """
    Detect cycles in dependency graph using color-based DFS (0=unvisited, 1=visiting, 2=done).
    Returns a list of cycles; each cycle is a list of node IDs in traversal order.
    """
    # fromkeys keeps the same default value instance; that's fine for ints/None here
    color = cast(dict[str, int], dict.fromkeys(graph, 0))
    parent = cast(dict[str, str | None], dict.fromkeys(graph, None))
    cycles: list[list[str]] = []

    def backtrack_cycle(start: str, end: str) -> list[str]:
        # Reconstruct path that closes the cycle: ... -> end -> ... -> start -> end
        path: list[str] = [end]
        cur: str | None = start
        # Walk parents until we reach `end` or None (defensive)
        while cur is not None and cur != end:
            path.append(cur)
            cur = parent.get(cur)
        path.append(end)
        # Rotate to start at `end` only once
        # Example built path: [end, ..., start, end] -> keep [end, ..., start]
        return path[:-1]

    def dfs(u: str) -> None:
        color[u] = 1  # visiting
        for v in graph.get(u, []):
            state = color.get(v, 0)
            if state == 0:
                parent[v] = u
                dfs(v)
            elif state == 1:
                # back edge u -> v: cycle found
                cycles.append(backtrack_cycle(u, v))
        color[u] = 2  # done

    for node in graph:
        if color[node] == 0:
            dfs(node)

    return cycles


def topo_sort(graph: dict[str, list[str]]) -> list[str]:
    """
    Topologically sort the graph (dependencies first). Raises ValueError on cycles.
    """
    color = cast(dict[str, int], dict.fromkeys(graph, 0))
    order: list[str] = []

    def dfs(u: str) -> None:
        state = color[u]
        if state == 1:
            raise ValueError(f"Cycle detected at '{u}'")
        if state == 2:
            return
        color[u] = 1
        for v in graph.get(u, []):
            dfs(v)
        color[u] = 2
        order.append(u)

    for n in graph:
        if color[n] == 0:
            dfs(n)

    logger.debug("Topological sort: %s", order)
    return order  # deps first


def get_execution_order(catalog: Catalog) -> list[str]:
    """
    Get KPI execution order (dependencies first). Raises ValueError if cycles exist.
    """
    graph = build_graph(catalog)
    cycles = detect_cycles(graph)
    if cycles:
        cycle_str = ", ".join(" -> ".join(c) for c in cycles)
        raise ValueError(f"Dependency cycles detected: {cycle_str}")
    return topo_sort(graph)
