from __future__ import annotations

from data_quality_toolkit.domain.semantics.normalizer import compare_dax, normalize_dax


def test_keyword_upper_and_whitespace():
    raw = "calculate ( sum ( 't'[x] ) )"
    got = normalize_dax(raw)
    assert got == "CALCULATE ( SUM ( 't' [ x ] ) )"


def test_comments_removed_and_spacing_normalized():
    expr = """
    /* block
       comment */
    SUM(-- line comment
        't'[x]   )  /* another */ +  /* and one more */ 1
    """
    got = normalize_dax(expr)
    # comments gone, single spaces around operators/paren/commas
    assert got == "SUM ( 't' [ x ] ) + 1"


def test_multiple_block_comments_not_overmatched():
    expr = "SUM('t'[x]) /*a*/ + /*b*/ 1 /*c*/"
    got = normalize_dax(expr)
    assert got == "SUM ( 't' [ x ] ) + 1"


def test_compare_equivalent_expressions_true():
    a = " sum('t'[x])"
    b = "SUM ( 't' [ x ] )"
    assert compare_dax(a, b) is True


def test_compare_different_expressions_false():
    a = "SUM('t'[x])"
    b = "SUM('t'[y])"
    assert compare_dax(a, b) is False
