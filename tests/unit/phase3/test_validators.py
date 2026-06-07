from __future__ import annotations

from typing import Literal

import pytest

from data_quality_toolkit.domain.semantics.schema import KPI, Catalog
from data_quality_toolkit.domain.semantics.validators import validate_dax_syntax, validate_semantics


def _kpi(
    id: str,
    *,
    title: str | None = None,
    expr: str = "1",
    grain: Literal["global", "dataset", "table", "column", "time"] = "global",
    unit: Literal["count", "percent", "ratio", "currency", "score", "days", "hours"] = "count",
    depends_on: list[str] | tuple[str, ...] = (),
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


def test_validate_semantics_ok() -> None:
    a = _kpi("a", unit="count")
    b = _kpi("b", unit="count", depends_on=("a",))
    cat = Catalog(kpis=[a, b], description=None)
    validate_semantics(cat)  # should not raise


def test_duplicate_ids_raise() -> None:
    a1 = _kpi("x")
    a2 = _kpi("x")
    cat = Catalog(kpis=[a1, a2], description=None)
    with pytest.raises(ValueError, match="Duplicate KPI IDs"):
        validate_semantics(cat)


def test_unknown_dep_raises() -> None:
    a = _kpi("a")
    b = _kpi("b", depends_on=("zzz",))
    cat = Catalog(kpis=[a, b], description=None)
    with pytest.raises(ValueError, match="depends on unknown"):
        validate_semantics(cat)


def test_grain_mismatch_raises() -> None:
    a = _kpi("a", grain="table")
    b = _kpi("b", grain="column", depends_on=("a",))
    cat = Catalog(kpis=[a, b], description=None)
    with pytest.raises(ValueError, match="Grain mismatch"):
        validate_semantics(cat)


def test_grain_global_allowed() -> None:
    g = _kpi("g", grain="global")
    t = _kpi("t", grain="table", depends_on=("g",))
    cat = Catalog(kpis=[g, t], description=None)
    validate_semantics(cat)  # global is compatible with any grain


def test_unit_mismatch_raises() -> None:
    a = _kpi("a", unit="count")
    b = _kpi("b", unit="percent", depends_on=("a",))
    cat = Catalog(kpis=[a, b], description=None)
    with pytest.raises(ValueError, match="Unit mismatch"):
        validate_semantics(cat)


def test_score_is_relaxed() -> None:
    s = _kpi("s", unit="score")
    p = _kpi("p", unit="percent", depends_on=("s",))
    cat = Catalog(kpis=[s, p], description=None)
    validate_semantics(cat)  # allowed: dependency is 'score'


def test_cycle_detection_raises() -> None:
    a = _kpi("a", depends_on=("b",))
    b = _kpi("b", depends_on=("a",))
    cat = Catalog(kpis=[a, b], description=None)
    with pytest.raises(ValueError, match="Dependency cycles detected"):
        validate_semantics(cat)


def test_validate_dax_syntax_balancing() -> None:
    assert validate_dax_syntax("SUM('t'[x])")
    assert not validate_dax_syntax("SUM('t'[x)")  # missing ')'
    assert not validate_dax_syntax("SUM('t[x])")  # bracket mismatch
    assert not validate_dax_syntax("SUM('t'[x])'")  # odd single quotes
