from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

import pytest

from data_quality_toolkit.semantics.dag import (
    build_graph,
    detect_cycles,
    get_execution_order,
    topo_sort,
)
from data_quality_toolkit.semantics.schema import KPI, Catalog


def _kpi(
    id: str,
    *,
    title: str | None = None,
    expr: str = "1",
    grain: Literal["global", "dataset", "table", "column", "time"] = "global",
    unit: Literal["count", "percent", "ratio", "currency", "score", "days", "hours"] = "count",
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


def test_build_graph_ok_and_unknown_dep() -> None:
    a = _kpi("a")
    b = _kpi("b", depends_on=("a",))
    cat = Catalog(kpis=[a, b], description=None)

    g = build_graph(cat)
    assert g == {"a": [], "b": ["a"]}

    # unknown dep
    c = _kpi("c", depends_on=("zzz",))
    cat_bad = Catalog(kpis=[a, c], description=None)
    with pytest.raises(ValueError):
        build_graph(cat_bad)


def test_detect_cycles_none_and_one_cycle() -> None:
    a = _kpi("a")
    b = _kpi("b", depends_on=("a",))
    c = _kpi("c", depends_on=("b",))
    cat = Catalog(kpis=[a, b, c], description=None)
    g = build_graph(cat)
    assert detect_cycles(g) == []

    # introduce cycle a <- c
    g["a"] = ["c"]
    cycles = detect_cycles(g)
    assert cycles  # not empty
    # the cycle should include a and c (ordering may vary)
    flat = {n for cyc in cycles for n in cyc}
    assert {"a", "c"}.issubset(flat)


def test_topo_sort_dependencies_before_dependents() -> None:
    a = _kpi("a")
    b = _kpi("b", depends_on=("a",))
    c = _kpi("c", depends_on=("b",))
    d = _kpi("d", depends_on=("a",))
    cat = Catalog(kpis=[a, b, c, d], description=None)
    g = build_graph(cat)
    order = topo_sort(g)

    # dependencies must appear before their consumers
    idx = {n: i for i, n in enumerate(order)}
    assert idx["a"] < idx["b"]
    assert idx["b"] < idx["c"]
    assert idx["a"] < idx["d"]


def test_topo_sort_raises_on_cycle() -> None:
    a = _kpi("a", depends_on=("c",))
    b = _kpi("b", depends_on=("a",))
    c = _kpi("c", depends_on=("b",))
    cat = Catalog(kpis=[a, b, c], description=None)
    g = build_graph(cat)
    with pytest.raises(ValueError):
        topo_sort(g)


def test_get_execution_order_ok_and_cycle_error() -> None:
    a = _kpi("a")
    b = _kpi("b", depends_on=("a",))
    cat = Catalog(kpis=[a, b], description=None)
    order = get_execution_order(cat)
    assert order.index("a") < order.index("b")

    # now with cycle
    a2 = _kpi("a", depends_on=("b",))
    b2 = _kpi("b", depends_on=("a",))
    with pytest.raises(ValueError):
        get_execution_order(Catalog(kpis=[a2, b2], description=None))
