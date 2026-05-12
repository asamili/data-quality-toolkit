"""Phase 3: Semantic validators for KPIs."""

from __future__ import annotations

from data_quality_toolkit.utils.logging import get_logger

from .dag import build_graph, detect_cycles
from .schema import Catalog, Grain

logger = get_logger(__name__)


def _check_duplicates(cat: Catalog) -> None:
    ids = [k.id for k in cat.kpis]
    if len(set(ids)) != len(ids):
        dup = {x for x in ids if ids.count(x) > 1}
        raise ValueError(f"Duplicate KPI IDs found: {dup}")


def _check_kpi_semantics(cat: Catalog) -> None:
    # Build index once
    idx = {k.id: k for k in cat.kpis}

    for k in cat.kpis:
        # Validate references exist
        for dep in k.depends_on:
            if dep not in idx:
                raise ValueError(f"KPI '{k.id}' depends on unknown '{dep}'")

        # Grain rule: deps must be same grain or global
        dep_grains: set[Grain] = {idx[d].grain for d in k.depends_on}
        invalid_grains = {g for g in dep_grains if g not in ("global", k.grain)}
        if invalid_grains:
            raise ValueError(
                f"Grain mismatch for '{k.id}': dependencies have {dep_grains}, "
                f"but KPI has grain '{k.grain}'"
            )

        # Unit rule: allow mixing with 'score'; otherwise must match KPI's unit
        dep_units = {idx[d].unit for d in k.depends_on}
        if dep_units:
            non_score = {u for u in dep_units if u != "score"}
            if non_score and k.unit != "score" and any(u != k.unit for u in non_score):
                raise ValueError(
                    f"Unit mismatch for '{k.id}': dependencies have {dep_units}, "
                    f"but KPI has unit '{k.unit}'"
                )


def validate_semantics(catalog: Catalog) -> None:
    """
    Validate semantic consistency of KPI catalog.

    Raises:
        ValueError: If validation fails
    """
    logger.info("Validating KPI catalog semantics")
    _check_duplicates(catalog)
    _check_kpi_semantics(catalog)

    # Graph checks (unknown deps already handled)
    graph = build_graph(catalog)
    cycles = detect_cycles(graph)
    if cycles:
        cycle_str = ", ".join(" -> ".join(c + [c[0]]) for c in cycles)
        raise ValueError(f"Dependency cycles detected: {cycle_str}")

    logger.info("Catalog validation passed")


def validate_dax_syntax(expression: str) -> bool:
    """
    Very basic DAX syntax sanity check.
    Returns True if parentheses, brackets, and single quotes are balanced.
    """
    if expression.count("(") != expression.count(")"):
        return False
    if expression.count("[") != expression.count("]"):
        return False
    if expression.count("'") % 2 != 0:
        return False
    return True
