from typing import Any, NotRequired, TypedDict, cast

import pytest
from pydantic import ValidationError

from data_quality_toolkit.domain.semantics.schema import KPI, Catalog


class KPIKwargsLoose(TypedDict, total=False):
    # Loose types on purpose to exercise runtime validation without mypy fighting us
    id: str
    title: str
    expression: str
    grain: str  # not Literal[...] so we can pass "row"
    unit: str  # not Literal[...] so we can pass "meters"
    scale: float
    depends_on: list[str]
    description: str | None
    format_string: str | None
    hidden: bool


class CatalogKwargsLoose(TypedDict, total=False):
    kpis: list["KPI"]  # forward ok in tests
    version: NotRequired[str]
    description: NotRequired[str | None]
    # NOTE: no extra fields declared on purpose (we’ll use Any cast when needed)


def test_kpi_minimal_valid():
    k = KPI(
        id="completeness_pct",
        title="Completeness %",
        expression="AVERAGE('fact_quality_metrics'[completeness])",
        grain="global",
        unit="percent",
        description=None,
        format_string=None,
    )
    assert k.scale == pytest.approx(1.0)
    assert k.depends_on == []
    assert k.hidden is False
    assert k.description is None
    assert k.format_string is None


def test_kpi_whitespace_is_stripped():
    k = KPI(
        id="  completeness_pct  ",
        title="  Completeness % ",
        expression="  SUM( x ) ",
        grain="global",
        unit="percent",
        description=None,
        format_string=None,
    )
    assert k.id == "completeness_pct"
    assert k.title == "Completeness %"
    assert k.expression == "SUM( x )"


def test_kpi_forbids_extra_fields():
    with pytest.raises(ValidationError):
        bad: dict[str, Any] = {
            "id": "x",
            "title": "X",
            "expression": "1",
            "grain": "global",
            "unit": "count",
            "description": None,
            "format_string": None,
            "not_allowed": "boom",  # extra field on purpose
        }
        # call constructor via Any to avoid mypy complaining about unexpected kw
        ctor = cast(Any, KPI)
        ctor(**bad)


def test_kpi_enum_validation():
    # Invalid unit
    with pytest.raises(ValidationError):
        payload_unit: KPIKwargsLoose = {
            "id": "bad_unit",
            "title": "Bad Unit",
            "expression": "1",
            "grain": "global",
            "unit": "meters",  # intentionally invalid
            "description": None,
            "format_string": None,
        }
        ctor = cast(Any, KPI)  # avoid Literal type-check on purpose
        ctor(**payload_unit)

    # Invalid grain
    with pytest.raises(ValidationError):
        payload_grain: KPIKwargsLoose = {
            "id": "bad_grain",
            "title": "Bad Grain",
            "expression": "1",
            "grain": "row",  # intentionally invalid
            "unit": "count",
            "description": None,
            "format_string": None,
        }
        ctor = cast(Any, KPI)  # avoid Literal type-check on purpose
        ctor(**payload_grain)


def test_depends_on_default_is_independent():
    k1 = KPI(
        id="a",
        title="A",
        expression="1",
        grain="global",
        unit="count",
        description=None,
        format_string=None,
    )
    k2 = KPI(
        id="b",
        title="B",
        expression="1",
        grain="global",
        unit="count",
        description=None,
        format_string=None,
    )
    k1.depends_on.append("b")
    assert k1.depends_on == ["b"]
    assert k2.depends_on == []  # ensure no shared default list


def test_catalog_minimal_and_helpers():
    k = KPI(
        id="distinct_avg",
        title="Avg Distinct Count",
        expression="AVERAGE('fact_quality_metrics'[distinct_count])",
        grain="global",
        unit="count",
        description=None,
        format_string=None,
    )
    cat = Catalog(kpis=[k], description=None)
    assert cat.version == "1.0.0"
    assert cat.get_kpi("distinct_avg") is not None
    assert cat.get_kpi("missing") is None
    assert cat.kpi_ids == {"distinct_avg"}


def test_catalog_forbids_extra_fields():
    k = KPI(
        id="x",
        title="X",
        expression="1",
        grain="global",
        unit="count",
        description=None,
        format_string=None,
    )
    with pytest.raises(ValidationError):
        extra: dict[str, Any] = {"kpis": [k], "extra_field": True}  # extra on purpose
        ctor = cast(Any, Catalog)
        ctor(**extra)
