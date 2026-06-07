from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from data_quality_toolkit.domain.semantics.catalog_loader import load_catalog, save_catalog
from data_quality_toolkit.domain.semantics.schema import KPI, Catalog


def write_yaml(p: Path, data: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_load_catalog_ok(tmp_path: Path) -> None:
    catalog_fp = tmp_path / "kpi_catalog.yaml"
    data = {
        "kpis": [
            {
                "id": "completeness_pct",
                "title": "Completeness %",
                "expression": "AVERAGE('fact_quality_metrics'[completeness])",
                "grain": "global",
                "unit": "percent",
                "scale": 100.0,
                "depends_on": [],
            },
            {
                "id": "distinct_avg",
                "title": "Avg Distinct Count",
                "expression": "AVERAGE('fact_quality_metrics'[distinct_count])",
                "grain": "global",
                "unit": "count",
                "depends_on": [],
            },
        ],
        "version": "1.0.0",
    }
    write_yaml(catalog_fp, data)

    cat = load_catalog(catalog_fp)
    assert isinstance(cat, Catalog)
    assert cat.kpi_ids == {"completeness_pct", "distinct_avg"}


def test_load_catalog_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    with pytest.raises(FileNotFoundError):
        load_catalog(missing)


def test_load_catalog_invalid_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("kpis:\n  - id: a\n    title: A\n    expression: [", encoding="utf-8")
    with pytest.raises(ValueError) as ei:
        load_catalog(bad)
    assert "Invalid YAML" in str(ei.value)


def test_load_catalog_invalid_schema(tmp_path: Path) -> None:
    bad_schema = tmp_path / "bad_schema.yaml"
    data = {
        "kpis": [
            {
                "id": "bad_unit",
                "title": "Bad",
                "expression": "1",
                "grain": "global",
                "unit": "meters",  # invalid
            }
        ]
    }
    write_yaml(bad_schema, data)
    # load_catalog wraps pydantic errors as ValueError
    with pytest.raises(ValueError):
        load_catalog(bad_schema)


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    k1 = KPI(
        id="k1",
        title="K1",
        expression="1",
        grain="global",
        unit="count",
        description=None,
        format_string=None,
    )
    k2 = KPI(
        id="k2",
        title="K2",
        expression="SUM('t'[x])",
        grain="global",
        unit="count",
        description=None,
        format_string=None,
    )
    cat = Catalog(kpis=[k1, k2], version="1.0.0", description=None)

    out_fp = tmp_path / "out" / "catalog.yaml"
    save_catalog(cat, out_fp)

    loaded = load_catalog(out_fp)
    assert loaded.kpi_ids == {"k1", "k2"}

    k2_loaded = loaded.get_kpi("k2")
    assert k2_loaded is not None  # mypy/pylance: narrow KPI | None -> KPI
    assert k2_loaded.expression == "SUM('t'[x])"
