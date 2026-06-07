"""Phase 3: DAX normalization for consistent comparisons."""

from __future__ import annotations

import re

from data_quality_toolkit.utils.logging import get_logger

logger = get_logger(__name__)

# cspell:ignore CALCULATETABLE ALLEXCEPT ALLSELECTED RELATEDTABLE USERELATIONSHIP
# cspell:ignore SUMX AVERAGEX COUNTX COUNTAX COUNTROWS COUNTBLANK MAXX IFERROR
# cspell:ignore FIRSTDATE LASTDATE DATEADD DATEDIFF DATESBETWEEN SAMEPERIODLASTYEAR
# cspell:ignore PARALLELPERIOD TOTALMTD TOTALQTD TOTALYTD ROUNDDOWN WEEKNUM
# cspell:ignore RANKX TOPN GENERATESERIES CROSSJOIN NATURALINNERJOIN NATURALLEFTOUTERJOIN
# cspell:ignore ADDCOLUMNS SELECTCOLUMNS REMOVEFILTERS KEEPFILTERS

# DAX keywords to uppercase
DAX_KEYWORDS = (
    "CALCULATE",
    "CALCULATETABLE",
    "FILTER",
    "ALL",
    "ALLEXCEPT",
    "ALLSELECTED",
    "VALUES",
    "DISTINCT",
    "RELATED",
    "RELATEDTABLE",
    "USERELATIONSHIP",
    "SUM",
    "SUMX",
    "AVERAGE",
    "AVERAGEX",
    "COUNT",
    "COUNTX",
    "COUNTA",
    "COUNTAX",
    "COUNTROWS",
    "COUNTBLANK",
    "MIN",
    "MINX",
    "MAX",
    "MAXX",
    "VAR",
    "RETURN",
    "IF",
    "SWITCH",
    "AND",
    "OR",
    "NOT",
    "TRUE",
    "FALSE",
    "DIVIDE",
    "IFERROR",
    "ISBLANK",
    "BLANK",
    "EARLIER",
    "EARLIEST",
    "FIRSTDATE",
    "LASTDATE",
    "DATEADD",
    "DATEDIFF",
    "DATESBETWEEN",
    "SAMEPERIODLASTYEAR",
    "PARALLELPERIOD",
    "TOTALMTD",
    "TOTALQTD",
    "TOTALYTD",
    "ROUND",
    "ROUNDUP",
    "ROUNDDOWN",
    "INT",
    "ABS",
    "SQRT",
    "POWER",
    "EXP",
    "LOG",
    "CONCATENATE",
    "FORMAT",
    "LEFT",
    "RIGHT",
    "MID",
    "LEN",
    "UPPER",
    "LOWER",
    "TRIM",
    "SUBSTITUTE",
    "REPLACE",
    "FIND",
    "SEARCH",
    "YEAR",
    "MONTH",
    "DAY",
    "WEEKDAY",
    "WEEKNUM",
    "TODAY",
    "NOW",
    "RANKX",
    "TOPN",
    "GENERATE",
    "GENERATESERIES",
    "UNION",
    "INTERSECT",
    "EXCEPT",
    "CROSSJOIN",
    "NATURALINNERJOIN",
    "NATURALLEFTOUTERJOIN",
    "ADDCOLUMNS",
    "SELECTCOLUMNS",
    "REMOVEFILTERS",
    "KEEPFILTERS",
    "MEASURE",
    "DEFINE",
    "EVALUATE",
    "ORDER",
    "BY",
    "ASC",
    "DESC",
)

# Robust C-style block comment pattern (no reluctant quantifier)
# Matches /* ... */ without over-consuming across multiple blocks.
_BLOCK_COMMENT_RE = re.compile(
    r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/",
    flags=re.DOTALL,
)


def normalize_dax(expression: str) -> str:
    """
    Normalize a DAX expression/script so that semantically identical strings compare equal.

    Preserves casing inside:
      - double-quoted strings: "0.00%;-0.00%;0.00%"
      - single-quoted names: 'fact_table'
      - bracketed identifiers: [Column], [Avg Distinct Count]

    Also enforces:
      - single spaces around operators, commas, parentheses, and brackets
      - single spaces just inside brackets: [ x ]
    """
    if not expression:
        return ""

    # Normalize line endings and trim
    text = expression.replace("\r\n", "\n").strip()

    # Remove comments
    text = re.sub(r"--.*$", "", text, flags=re.MULTILINE)
    text = _BLOCK_COMMENT_RE.sub("", text)

    # Collapse early to simplify
    text = re.sub(r"\s+", " ", text)

    protected: list[str] = []

    def _stash(s: str) -> str:
        protected.append(s)
        return f"__DAX_KEEP_{len(protected)-1}__"

    # 1) protect double-quoted strings
    text = re.sub(r'"[^"]*"', lambda m: _stash(m.group(0)), text)
    # 2) protect single-quoted names
    text = re.sub(r"'[^']*'", lambda m: _stash(m.group(0)), text)

    # 3) protect the INNER CONTENT of [ ... ] but keep the brackets,
    #    so we can still normalize spacing around the bracket tokens.
    bracket_inners: list[str] = []

    def _stash_br_inner(m: re.Match[str]) -> str:
        inner = m.group(1)
        bracket_inners.append(inner)
        return f"[__DAX_BR_INNER_{len(bracket_inners)-1}__]"

    text = re.sub(r"\[([^\]]+)\]", _stash_br_inner, text)

    # Uppercase DAX keywords (now that protected regions are out)
    for kw in DAX_KEYWORDS:
        text = re.sub(rf"\b{kw}\b", kw, text, flags=re.IGNORECASE)

    # Normalize spacing around operators, commas, parentheses, and BRACKETS
    text = re.sub(r"\s*([=<>!+\-*/&|,()\[\]])\s*", r" \1 ", text)

    # --- NEW: canonicalize numeric literals (e.g., 100.0 -> 100, 1.2300 -> 1.23)
    text = re.sub(r"\b(\d+)\.0+\b", r"\1", text)  # integer .0… -> integer
    text = re.sub(r"\b(\d+\.\d*?[1-9])0+\b", r"\1", text)  # trim trailing zeros

    # Final collapse (pre-restore)
    text = re.sub(r"\s+", " ", text).strip()

    # Restore bracket inners (then enforce single space just inside [ and ])
    for idx, inner in enumerate(bracket_inners):
        text = text.replace(f"__DAX_BR_INNER_{idx}__", inner)
    # Ensure "[x]" → "[ x ]" and "[   a  b   ]" → "[ a  b ]"
    text = re.sub(r"\[\s*([^\[\]]+?)\s*\]", r"[ \1 ]", text)

    # Restore quoted strings/names
    for idx, original in enumerate(protected):
        text = text.replace(f"__DAX_KEEP_{idx}__", original)

    # One last collapse
    text = re.sub(r"\s+", " ", text).strip()

    logger.debug("Normalized DAX: %s", text[:200])
    return text


def compare_dax(expr1: str, expr2: str) -> bool:
    """Return True if two DAX expressions normalize to the same canonical string."""
    return normalize_dax(expr1) == normalize_dax(expr2)
