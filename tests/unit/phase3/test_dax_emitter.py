from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from data_quality_toolkit.semantics.dax_emitter import (
    MEASURE_TABLE,
    build_tmsl_measures,
    emit_dax,
    write_dax,
    write_tmsl,
)
from data_quality_toolkit.semantics.schema import KPI, Catalog, Grain, Unit


def _kpi(
    id: str,
    *,
    title: str | None = None,
    expr: str = "1",
    grain: Grain = "global",  # <- use Grain Literal
    unit: Unit = "count",  # <- use Unit Literal
    scale: float = 1.0,
    depends_on: Iterable[str] = (),
    hidden: bool = False,
    description: str | None = None,
    format_string: str | None = None,
) -> KPI:
    return KPI(
        id=id,
        title=title or id.upper(),
        expression=expr,
        grain=grain,
        unit=unit,
        scale=scale,
        depends_on=list(depends_on),
        hidden=hidden,
        description=description,
        format_string=format_string,
    )


def test_emit_dax_basic_and_scaling_and_format_and_description() -> None:
    k1 = _kpi(
        "k1",
        title="K1 Title",
        expr="SUM('t'[x])",
        scale=100.0,  # should wrap and multiply
        description="Percent of something",
        format_string="0.00%;-0.00%;0.00%",
    )
    cat = Catalog(kpis=[k1], description=None)
    dax = emit_dax(cat)

    # description comment first, then measure line
    assert "-- Percent of something" in dax
    assert f"MEASURE '{MEASURE_TABLE}'[K1 Title] =" in dax
    # scaling applied
    assert "( SUM ( 't' [ x ] ) ) * 100.0" in dax or "( SUM('t'[x]) ) * 100.0" in dax
    # format string emitted
    assert 'FORMAT_STRING = "0.00%;-0.00%;0.00%"' in dax


def test_emit_dax_skips_hidden_and_respects_dependencies() -> None:
    # a -> b (b depends on a). Hidden KPI should be skipped entirely.
    a = _kpi("a", title="A", expr="1")
    b = _kpi("b", title="B", expr="A", depends_on=("a",))
    hidden = _kpi("h", hidden=True)  # should not appear
    cat = Catalog(kpis=[b, hidden, a], description=None)

    dax = emit_dax(cat)
    # hidden not present
    assert "MEASURE" in dax and "H" not in dax
    # dependency order: measure A must appear before B in the file
    idx_a = dax.index("MEASURE")
    idx_b = dax.rindex("MEASURE")  # last occurrence should be B here
    assert idx_a < idx_b
    assert "[A] =" in dax  # <- plain string, no f-string
    assert "[B] =" in dax  # <- plain string, no f-string


def test_build_tmsl_measures_shape_and_values() -> None:
    k1 = _kpi(
        "k1",
        title="K1",
        expr="SUM('t'[x])",
        description="desc",
        format_string="#,##0",
    )
    k2 = _kpi("k2", title="K2", expr="1", scale=10.0)
    k3 = _kpi("k3", title="K3", expr="1", hidden=True)  # excluded
    cat = Catalog(kpis=[k1, k2, k3], description=None)

    measures = build_tmsl_measures(cat)
    names = [m["name"] for m in measures]
    assert names == ["K1", "K2"]  # hidden excluded

    m1 = measures[0]
    assert m1["name"] == "K1"
    assert "SUM" in m1["expression"]
    assert m1["description"] == "desc"
    assert m1["formatString"] == "#,##0"

    m2 = measures[1]
    assert m2["name"] == "K2"
    # scaling applied in expression
    assert "( 1 ) * 10.0" in m2["expression"]


def test_write_dax_and_write_tmsl_files(tmp_path: Path) -> None:
    a = _kpi("a", title="A", expr="1")
    b = _kpi("b", title="B", expr="A", depends_on=("a",))
    cat = Catalog(kpis=[a, b], description=None)

    # DAX file
    dax_fp = tmp_path / "measures.dax"
    out_path_dax = write_dax(cat, dax_fp)
    assert out_path_dax == str(dax_fp)
    text = dax_fp.read_text(encoding="utf-8")
    assert "MEASURE" in text and "[A]" in text and "[B]" in text

    # TMSL file
    tmsl_fp = tmp_path / "measures.json"
    out_path_tmsl = write_tmsl(cat, tmsl_fp)
    assert out_path_tmsl == str(tmsl_fp)
    obj = json.loads(tmsl_fp.read_text(encoding="utf-8"))

    # Shape checks
    assert "createOrReplace" in obj
    table = obj["createOrReplace"]["table"]
    assert table["name"] == MEASURE_TABLE
    assert isinstance(table["measures"], list)
    # two visible measures
    assert {m["name"] for m in table["measures"]} == {"A", "B"}
