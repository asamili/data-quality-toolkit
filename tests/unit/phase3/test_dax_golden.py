# tests/unit/phase3/test_dax_golden.py
"""Phase 3: Golden DAX test (order/spacing/comment insensitive, semantically parsed)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from data_quality_toolkit.domain.semantics import (
    emit_dax,
    load_catalog,
    normalize_dax,
    validate_semantics,
)


class ParsedMeasure(NamedTuple):
    table: str
    name: str
    expr_norm: str
    fmt: str | None


# Split *before* each MEASURE line, allowing any table and optional spaces before '['
_MEASURE_SPLIT = re.compile(r"(?=MEASURE\s+'[^']+'\s*\[)", flags=re.IGNORECASE)

# Capture the header: MEASURE 'Table'[ Name ] = ...
_HEADER_RE = re.compile(
    r"""^MEASURE\s+'(?P<table>[^']+)'\s*\[\s*(?P<name>[^\]]+?)\s*\]\s*=\s*(?P<rest>.*)$""",
    flags=re.IGNORECASE | re.DOTALL,
)

# Capture an optional FORMAT_STRING anywhere in the block
_FMT_RE = re.compile(r'FORMAT_STRING\s*=\s*"(?P<fmt>[^"]*)"', flags=re.IGNORECASE)


def _parse_measures(script: str) -> set[ParsedMeasure]:
    """Parse a DAX script into a set of ParsedMeasure entries."""
    chunks = [c.strip() for c in _MEASURE_SPLIT.split(script) if c.strip()]
    out: set[ParsedMeasure] = set()

    for chunk in chunks:
        m = _HEADER_RE.match(chunk)
        if not m:
            # Skip anything that isn’t a MEASURE block (shouldn’t happen with splitter)
            continue

        table = m.group("table")
        name = m.group("name")
        rest = m.group("rest").strip()

        # Pull out FORMAT_STRING if present
        fmt_match = _FMT_RE.search(rest)
        fmt = fmt_match.group("fmt") if fmt_match else None

        # Expression is everything before the FORMAT_STRING occurrence (or whole rest)
        expr = rest[: fmt_match.start()].strip() if fmt_match else rest

        # Normalize expression only (ignore whitespace/keyword casing/etc.)
        expr_norm = normalize_dax(expr)

        out.add(ParsedMeasure(table=table, name=name, expr_norm=expr_norm, fmt=fmt))

    return out


def test_golden_dax() -> None:
    """Test DAX output matches golden file (ignoring order/whitespace/comments)."""
    # Load & validate catalog
    catalog = load_catalog("config/kpi_catalog.yaml")
    validate_semantics(catalog)

    # Generate and parse
    generated = emit_dax(catalog)
    gen_set = _parse_measures(generated)

    # Load golden, parse
    expected_text = Path("tests/golden/quality_measures_expected.dax").read_text(encoding="utf-8")
    exp_set = _parse_measures(expected_text)

    # Compare sets (order-insensitive, whitespace-insensitive)
    assert gen_set == exp_set
