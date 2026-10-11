"""Bounded, deterministic Smart Data Overview preview model (pure UI service).

This module answers six questions about the *already loaded* analysis frame and
profile, without ever loading, profiling, or assessing anything a second time:

1. what kind of dataset is active,
2. how it is shaped,
3. which semantic role each column is *likely* to have,
4. which records give a useful bounded preview,
5. which factual risks or heuristic warnings deserve attention,
6. whether the reading is exact or sample-derived.

Boundaries encoded here:

* Pure and framework-free. It imports no Streamlit, reads no file, touches no
  session state, mutates no DataFrame, alters no lifecycle state, activates no
  version, writes no artifact, performs no network access, uses no random
  sampling, and adds no dependency.
* One-pass reuse. Column facts come from the profile the page already holds;
  content-level heuristics read only a *bounded head* of the frame the page
  already has in memory.
* Facts and heuristics never blur. Every signal and callout carries an explicit
  evidence class (:data:`EVIDENCE_FACT`, :data:`EVIDENCE_SAMPLE`,
  :data:`EVIDENCE_HEURISTIC`, :data:`EVIDENCE_UNAVAILABLE`), and a likely role is
  a suggestion — never schema truth.
* Large-mode honesty. When the caller declares :data:`ANALYSIS_SAMPLE`, every
  exact-fact classification is downgraded to a bounded-sample classification, so
  nothing derived from a sample can be presented as a dataset-wide property.
* Identity is display-safe by construction. :class:`PreviewIdentity` carries only
  values a caller has already reduced to safe presentation text; this module
  never receives, infers, or emits an absolute path.

Every bound is a named module constant so the limits are visible in code and
directly testable.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

__all__ = [
    "ANALYSIS_FULL",
    "ANALYSIS_SAMPLE",
    "DATETIME_TEXT_MIN_VALUES",
    "DATETIME_TEXT_RATIO",
    "EVIDENCE_FACT",
    "EVIDENCE_HEURISTIC",
    "EVIDENCE_LABELS",
    "EVIDENCE_SAMPLE",
    "EVIDENCE_UNAVAILABLE",
    "HIGH_MISSING_PCT",
    "IDENTIFIER_MIN_NON_NULL",
    "IDENTIFIER_UNIQUENESS_RATIO",
    "MAX_CALLOUTS",
    "MAX_CATEGORY_VALUES",
    "MAX_CONTENT_COLUMNS",
    "MAX_CONTENT_ROWS",
    "MAX_GROUP_COLUMNS",
    "MAX_NAMES_PER_CALLOUT",
    "MAX_RECORD_COLUMNS",
    "MAX_RECORD_ROWS",
    "MAX_RECORD_ROWS_PER_STRATEGY",
    "MAX_RECORD_SCAN_ROWS",
    "NEAR_EMPTY_PCT",
    "ROLE_CATEGORICAL",
    "ROLE_DATETIME",
    "ROLE_IDENTIFIER",
    "ROLE_MEASURE",
    "ROLE_OTHER",
    "ROLE_PRECEDENCE",
    "ROLE_TITLES",
    "SEVERITY_ATTENTION",
    "SEVERITY_LABELS",
    "SEVERITY_NOTE",
    "STRATEGY_DESCRIPTIONS",
    "STRATEGY_EVEN_SPREAD",
    "STRATEGY_FIRST_ROWS",
    "STRATEGY_MOST_MISSING",
    "STRATEGY_ORDER",
    "STRATEGY_TITLES",
    "WIDE_COLUMN_THRESHOLD",
    "ZERO_HEAVY_RATIO",
    "Callout",
    "ColumnFacts",
    "ColumnSignal",
    "PreviewIdentity",
    "RecordSelection",
    "SelectedRecord",
    "SemanticGroup",
    "SmartOverview",
    "build_smart_overview",
]

# --- Analysis modes ----------------------------------------------------------

#: Exact reading over the fully materialized analysis frame.
ANALYSIS_FULL = "full"
#: Bounded reading: the caller only holds a sample or an approximate profile.
ANALYSIS_SAMPLE = "sample"

# --- Evidence vocabulary -----------------------------------------------------

EVIDENCE_FACT = "fact"
EVIDENCE_SAMPLE = "sample"
EVIDENCE_HEURISTIC = "heuristic"
EVIDENCE_UNAVAILABLE = "unavailable"

#: Operator-facing wording for each evidence class. Text, never colour, carries
#: the distinction, so the preview stays readable without colour perception.
EVIDENCE_LABELS: dict[str, str] = {
    EVIDENCE_FACT: "fact",
    EVIDENCE_SAMPLE: "bounded sample",
    EVIDENCE_HEURISTIC: "likely (heuristic)",
    EVIDENCE_UNAVAILABLE: "not evaluated",
}

# --- Roles -------------------------------------------------------------------

ROLE_IDENTIFIER = "identifier"
ROLE_DATETIME = "datetime"
ROLE_CATEGORICAL = "categorical"
ROLE_MEASURE = "measure"
ROLE_OTHER = "other"

#: Documented precedence: the first rule that matches wins, so every analyzed
#: column receives exactly one primary likely role.
ROLE_PRECEDENCE: tuple[str, ...] = (
    ROLE_IDENTIFIER,
    ROLE_DATETIME,
    ROLE_CATEGORICAL,
    ROLE_MEASURE,
    ROLE_OTHER,
)

ROLE_TITLES: dict[str, str] = {
    ROLE_IDENTIFIER: "Likely identifiers",
    ROLE_DATETIME: "Date / time fields",
    ROLE_CATEGORICAL: "Categorical fields",
    ROLE_MEASURE: "Measures",
    ROLE_OTHER: "Other / unclassified",
}

# --- Callout severity --------------------------------------------------------

SEVERITY_ATTENTION = "attention"
SEVERITY_NOTE = "note"

SEVERITY_LABELS: dict[str, str] = {
    SEVERITY_ATTENTION: "Attention",
    SEVERITY_NOTE: "Note",
}

_SEVERITY_RANK: dict[str, int] = {SEVERITY_ATTENTION: 0, SEVERITY_NOTE: 1}

# --- Record strategies -------------------------------------------------------

STRATEGY_FIRST_ROWS = "first_rows"
STRATEGY_EVEN_SPREAD = "even_spread"
STRATEGY_MOST_MISSING = "most_missing"

#: Deterministic application order; earlier strategies win a deduplication tie.
STRATEGY_ORDER: tuple[str, ...] = (
    STRATEGY_FIRST_ROWS,
    STRATEGY_EVEN_SPREAD,
    STRATEGY_MOST_MISSING,
)

STRATEGY_TITLES: dict[str, str] = {
    STRATEGY_FIRST_ROWS: "First rows",
    STRATEGY_EVEN_SPREAD: "Evenly spread",
    STRATEGY_MOST_MISSING: "Most missing fields",
}

STRATEGY_DESCRIPTIONS: dict[str, str] = {
    STRATEGY_FIRST_ROWS: "the first rows in file order",
    STRATEGY_EVEN_SPREAD: "evenly spaced positions across the frame",
    STRATEGY_MOST_MISSING: "rows with the most empty fields in the scanned range",
}

# --- Explicit performance bounds ---------------------------------------------

#: Rows read for any content-level heuristic (datetime text, zero-heavy numeric).
MAX_CONTENT_ROWS = 500
#: Columns eligible for content-level heuristics, taken in frame order.
MAX_CONTENT_COLUMNS = 60
#: Columns displayed per semantic group.
MAX_GROUP_COLUMNS = 12
#: Rows contributed by a single record strategy.
MAX_RECORD_ROWS_PER_STRATEGY = 3
#: Rows displayed in total after deduplication across strategies.
MAX_RECORD_ROWS = 9
#: Columns displayed in the record preview.
MAX_RECORD_COLUMNS = 12
#: Rows scanned when ranking rows by missing-field count.
MAX_RECORD_SCAN_ROWS = 5_000
#: Callouts displayed after ranking.
MAX_CALLOUTS = 6
#: Distinct values a text column may hold and still read as categorical.
MAX_CATEGORY_VALUES = 50
#: Column names named inline in one callout before the rest are counted.
MAX_NAMES_PER_CALLOUT = 3

# --- Heuristic thresholds ----------------------------------------------------

#: Column count above which the dataset reads as unusually wide.
WIDE_COLUMN_THRESHOLD = 50
#: Dataset-level missing share (percent) that warrants attention.
HIGH_MISSING_PCT = 20.0
#: Per-column missing share (percent) that marks a column as near-empty.
NEAR_EMPTY_PCT = 95.0
#: Uniqueness ratio required before a column may read as an identifier.
IDENTIFIER_UNIQUENESS_RATIO = 0.98
#: Non-null values required before identifier evidence is considered at all.
IDENTIFIER_MIN_NON_NULL = 5
#: Share of inspected text values that must parse before a datetime suggestion.
DATETIME_TEXT_RATIO = 0.9
#: Non-null text values required before datetime-string detection is attempted.
DATETIME_TEXT_MIN_VALUES = 5
#: Share of inspected non-null numeric values equal to zero that is worth noting.
ZERO_HEAVY_RATIO = 0.9

# --- Internal dtype kinds ----------------------------------------------------

_KIND_DATETIME = "datetime"
_KIND_BOOLEAN = "boolean"
_KIND_CATEGORY = "category"
_KIND_NUMERIC = "numeric"
_KIND_TEXT = "text"
_KIND_OTHER = "other"

_NUMERIC_DTYPE_PREFIXES = ("int", "uint", "float", "complex", "decimal")
_TEXT_DTYPE_PREFIXES = ("object", "string", "str")
_FLOAT_DTYPE_PREFIXES = ("float", "complex", "decimal")

#: Structural name tokens only. Deliberately no PII or sensitive-attribute
#: vocabulary: this service classifies shape, never meaning about people.
_IDENTIFIER_NAME_TOKENS = frozenset(
    {
        "code",
        "guid",
        "id",
        "identifier",
        "ids",
        "key",
        "no",
        "num",
        "number",
        "pk",
        "ref",
        "reference",
        "sku",
        "uuid",
    }
)

#: Conservative shape gate applied before any datetime parse is attempted, so a
#: bare numeric string can never be coerced into a date.
_DATETIME_TEXT_PATTERN = re.compile(r"^\s*\d{1,4}[-/]\d{1,2}[-/]\d{1,4}([ T]\d{1,2}:\d{2})?")

_NO_COLUMNS_REASON = "No columns are available to preview."
_NO_FRAME_REASON = (
    "Representative records are not available here: no full DataFrame is loaded in " "this mode."
)
_NO_ROWS_REASON = "The dataset has no rows, so there are no records to preview."


# --- Presentation identity ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreviewIdentity:
    """Display-safe identity of the dataset the preview describes.

    Every field is presentation text the caller has already reduced to a safe
    form. There is no path, no full hash, and no full UUID here by construction,
    so the preview cannot leak one.
    """

    status: str = "Dataset selected"
    label: str = "No dataset selected"
    short_version_id: str = ""
    mode_label: str = ""

    @property
    def line(self) -> str:
        """Return the single-line identity descriptor for the preview header."""
        status = f"{self.status} {self.short_version_id}".strip()
        parts = [part for part in (status, self.label, self.mode_label) if part]
        return " · ".join(parts)


# --- Column model ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ColumnFacts:
    """Counted facts for one column, reused from the caller's existing profile.

    ``non_null``, ``missing`` and ``distinct`` are ``None`` when the source did
    not compute them (an approximate large-mode profile omits unique counts);
    ``None`` means *not evaluated*, never zero.
    """

    name: str
    dtype: str
    non_null: int | None = None
    missing: int | None = None
    distinct: int | None = None


@dataclass(frozen=True, slots=True)
class ColumnSignal:
    """Compact per-column signals plus the column's single likely role."""

    name: str
    dtype: str
    role: str
    role_evidence: str
    non_null: int | None
    missing_pct: float | None
    distinct: int | None
    unique_pct: float | None
    content_analyzed: bool


@dataclass(frozen=True, slots=True)
class SemanticGroup:
    """One semantic group and the bounded set of columns displayed for it."""

    role: str
    title: str
    total_columns: int
    signals: tuple[ColumnSignal, ...]

    @property
    def truncated(self) -> bool:
        """True when the group holds more columns than are displayed."""
        return self.total_columns > len(self.signals)


# --- Record selection --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SelectedRecord:
    """One selected row: its integer position and the strategy that picked it."""

    position: int
    strategy: str


@dataclass(frozen=True, slots=True)
class RecordSelection:
    """Deterministic, bounded record picks — never a statistical sample."""

    available: bool
    evidence: str
    reason: str = ""
    records: tuple[SelectedRecord, ...] = ()
    columns: tuple[str, ...] = ()
    total_columns: int = 0
    scanned_rows: int = 0
    strategies: tuple[str, ...] = ()

    @property
    def columns_truncated(self) -> bool:
        """True when the record preview shows fewer columns than the frame has."""
        return self.total_columns > len(self.columns)


# --- Callouts ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Callout:
    """One ranked shape or risk observation with its evidence class."""

    key: str
    severity: str
    evidence: str
    message: str


# --- Assembled preview -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SmartOverview:
    """The complete bounded preview model for one already-loaded dataset."""

    identity: PreviewIdentity
    analysis_mode: str
    rows: int | None
    columns: int
    shape_evidence: str
    groups: tuple[SemanticGroup, ...]
    selection: RecordSelection
    callouts: tuple[Callout, ...]
    content_columns_inspected: int
    content_rows_inspected: int

    @property
    def sample_derived(self) -> bool:
        """True when every reading is bounded-sample rather than dataset-wide."""
        return self.analysis_mode == ANALYSIS_SAMPLE

    @property
    def displayed_signals(self) -> tuple[ColumnSignal, ...]:
        """Return displayed signals in group precedence then column order."""
        return tuple(signal for group in self.groups for signal in group.signals)

    @property
    def groups_truncated(self) -> bool:
        """True when any group displays fewer columns than it holds."""
        return any(group.truncated for group in self.groups)

    def group_summary(self) -> str:
        """Return the compact ``title: count`` line for the non-empty groups."""
        if not self.groups:
            return "No column groups available."
        return " · ".join(f"{group.title}: {group.total_columns}" for group in self.groups)


# --- Evidence helpers --------------------------------------------------------


def _sample_mode(analysis_mode: str) -> bool:
    return analysis_mode == ANALYSIS_SAMPLE


def _evidence(evidence: str, *, sample: bool) -> str:
    """Downgrade an exact fact to a bounded-sample observation in sample mode."""
    if sample and evidence == EVIDENCE_FACT:
        return EVIDENCE_SAMPLE
    return evidence


# --- Name and dtype classification -------------------------------------------


def _name_tokens(name: str) -> list[str]:
    """Return lowercase alphanumeric tokens of a column name."""
    normalized = re.sub(r"[^0-9a-z]+", "_", str(name).strip().lower())
    return [token for token in normalized.split("_") if token]


def _has_identifier_name_hint(name: str) -> bool:
    """True when the final name token is a structural identifier word."""
    tokens = _name_tokens(name)
    return bool(tokens) and tokens[-1] in _IDENTIFIER_NAME_TOKENS


def _dtype_kind(dtype: str) -> str:
    """Map a pandas dtype string to a coarse, stable kind."""
    value = str(dtype).strip().lower()
    if value.startswith("timedelta"):
        return _KIND_OTHER
    if value.startswith(("datetime", "period")):
        return _KIND_DATETIME
    if value.startswith("bool"):
        return _KIND_BOOLEAN
    if value.startswith("category"):
        return _KIND_CATEGORY
    if value.startswith(_NUMERIC_DTYPE_PREFIXES):
        return _KIND_NUMERIC
    if value.startswith(_TEXT_DTYPE_PREFIXES):
        return _KIND_TEXT
    return _KIND_OTHER


def _is_float_dtype(dtype: str) -> bool:
    return str(dtype).strip().lower().startswith(_FLOAT_DTYPE_PREFIXES)


# --- Column facts ------------------------------------------------------------


def _safe_int(value: Any) -> int | None:
    """Return a non-negative int, or None for absent/unusable values."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        number = int(value)
    except (OverflowError, ValueError):
        return None
    return number if number >= 0 else None


def _facts_from_profile(profile: Mapping[str, Any], rows: int | None) -> list[ColumnFacts]:
    """Build column facts from the profile the page already holds (no new pass)."""
    facts: list[ColumnFacts] = []
    for entry in profile.get("columns") or []:
        if not isinstance(entry, Mapping):
            continue
        missing = _safe_int(entry.get("nulls"))
        non_null = None if rows is None or missing is None else max(rows - missing, 0)
        facts.append(
            ColumnFacts(
                name=str(entry.get("name", "")),
                dtype=str(entry.get("dtype", "")),
                non_null=non_null,
                missing=missing,
                distinct=_safe_int(entry.get("unique")),
            )
        )
    return facts


def _facts_from_frame(frame: pd.DataFrame) -> list[ColumnFacts]:
    """Fallback facts when no profile is supplied.

    Non-null counts are exact and cheap; distinct counts are computed only for
    the first :data:`MAX_CONTENT_COLUMNS` columns, so a very wide frame stays
    bounded and the remaining columns honestly report *not evaluated*.
    """
    facts: list[ColumnFacts] = []
    row_count = int(len(frame))
    for position, name in enumerate(frame.columns):
        series = frame.iloc[:, position]
        non_null = int(series.notna().sum())
        distinct = int(series.nunique(dropna=True)) if position < MAX_CONTENT_COLUMNS else None
        facts.append(
            ColumnFacts(
                name=str(name),
                dtype=str(series.dtype),
                non_null=non_null,
                missing=max(row_count - non_null, 0),
                distinct=distinct,
            )
        )
    return facts


def _resolve_rows(profile: Mapping[str, Any] | None, frame: pd.DataFrame | None) -> int | None:
    if profile is not None:
        rows = _safe_int(profile.get("rows"))
        if rows is not None:
            return rows
    return int(len(frame)) if frame is not None else None


def _resolve_columns(
    profile: Mapping[str, Any] | None,
    frame: pd.DataFrame | None,
    facts: Sequence[ColumnFacts],
) -> int:
    if profile is not None:
        columns = _safe_int(profile.get("cols"))
        if columns is not None:
            return columns
    if frame is not None:
        return int(frame.shape[1])
    return len(facts)


# --- Bounded content heuristics ----------------------------------------------


def _looks_like_datetime_text(value: Any) -> bool:
    return bool(_DATETIME_TEXT_PATTERN.match(str(value)))


def _column_is_datetime_text(series: pd.Series) -> bool:
    """True when a bounded, conservative read suggests datetime strings.

    Two gates must both pass: enough inspected values must *look* like a date,
    and enough of those must actually parse. Never raises — an unparseable
    column simply fails the check.
    """
    values = series.dropna()
    if int(len(values)) < DATETIME_TEXT_MIN_VALUES:
        return False
    text = values.astype(str)
    shaped = text[text.map(_looks_like_datetime_text)]
    if int(len(shaped)) < DATETIME_TEXT_MIN_VALUES:
        return False
    if float(len(shaped)) / float(len(text)) < DATETIME_TEXT_RATIO:
        return False
    try:
        parsed = pd.to_datetime(shaped, errors="coerce", utc=True, format="mixed")
    except (TypeError, ValueError):
        return False
    return bool(float(parsed.notna().mean()) >= DATETIME_TEXT_RATIO)


def _bounded_head(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the bounded, read-only slice used by every content heuristic."""
    return frame.iloc[:MAX_CONTENT_ROWS, :MAX_CONTENT_COLUMNS]


def _content_series(head: pd.DataFrame, name: str) -> pd.Series | None:
    """Return one column of the bounded head, or None when it is ambiguous."""
    try:
        series = head[name]
    except (KeyError, TypeError):
        return None
    return series if isinstance(series, pd.Series) else None


def _datetime_text_columns(head: pd.DataFrame, kinds: Mapping[str, str]) -> frozenset[str]:
    """Return text columns of the bounded head that read as datetime strings."""
    detected: set[str] = set()
    for name in head.columns:
        key = str(name)
        if kinds.get(key) != _KIND_TEXT:
            continue
        series = _content_series(head, key)
        if series is not None and _column_is_datetime_text(series):
            detected.add(key)
    return frozenset(detected)


def _numeric_content_columns(
    head: pd.DataFrame, kinds: Mapping[str, str]
) -> tuple[list[str], list[str]]:
    """Return ``(zero_heavy, non_finite)`` numeric column names from the head."""
    zero_heavy: list[str] = []
    non_finite: list[str] = []
    for name in head.columns:
        key = str(name)
        if kinds.get(key) != _KIND_NUMERIC:
            continue
        series = _content_series(head, key)
        if series is None:
            continue
        values = series.dropna()
        if int(len(values)) == 0:
            continue
        if bool(values.isin([float("inf"), float("-inf")]).any()):
            non_finite.append(key)
        zeros = int((values == 0).sum())
        if float(zeros) / float(len(values)) >= ZERO_HEAVY_RATIO:
            zero_heavy.append(key)
    return zero_heavy, non_finite


# --- Role resolution ---------------------------------------------------------


def _is_likely_identifier(facts: ColumnFacts, kind: str) -> bool:
    """Conservative identifier evidence: uniqueness *and* a structural name hint.

    Uniqueness alone is never sufficient — that would relabel every continuous
    measure, every free-text note field, and every date string as a key. A
    continuous float is excluded outright, and both integers and text must carry
    a structural name token (``id``, ``key``, ``code``, ``number``, …) on top of
    near-total uniqueness over enough non-null values.
    """
    if kind not in (_KIND_NUMERIC, _KIND_TEXT) or _is_float_dtype(facts.dtype):
        return False
    non_null, distinct = facts.non_null, facts.distinct
    if non_null is None or distinct is None or non_null < IDENTIFIER_MIN_NON_NULL:
        return False
    if float(distinct) < float(non_null) * IDENTIFIER_UNIQUENESS_RATIO:
        return False
    return _has_identifier_name_hint(facts.name)


def _resolve_role(facts: ColumnFacts, kind: str, *, datetime_text: bool) -> tuple[str, str]:
    """Return ``(role, evidence)`` under the documented precedence.

    Precedence is identifier, datetime, categorical, measure, other; the first
    matching rule wins, so a column always carries exactly one primary role.
    """
    if facts.non_null == 0:
        return ROLE_OTHER, EVIDENCE_FACT
    if _is_likely_identifier(facts, kind):
        return ROLE_IDENTIFIER, EVIDENCE_HEURISTIC
    if kind == _KIND_DATETIME:
        return ROLE_DATETIME, EVIDENCE_FACT
    if datetime_text:
        return ROLE_DATETIME, EVIDENCE_HEURISTIC
    if kind in (_KIND_BOOLEAN, _KIND_CATEGORY):
        return ROLE_CATEGORICAL, EVIDENCE_FACT
    if kind == _KIND_TEXT:
        if facts.distinct is None:
            return ROLE_OTHER, EVIDENCE_UNAVAILABLE
        # A category must actually repeat: an all-distinct text column is free
        # text, not a small value set, so it stays unclassified.
        repeats = facts.non_null is None or facts.distinct < facts.non_null
        if facts.distinct <= MAX_CATEGORY_VALUES and repeats:
            return ROLE_CATEGORICAL, EVIDENCE_HEURISTIC
        return ROLE_OTHER, EVIDENCE_HEURISTIC
    if kind == _KIND_NUMERIC:
        return ROLE_MEASURE, EVIDENCE_FACT
    return ROLE_OTHER, EVIDENCE_HEURISTIC


def _percentage(part: int | None, whole: int | None) -> float | None:
    if part is None or whole is None or whole <= 0:
        return None
    return round(float(part) / float(whole) * 100.0, 2)


def _build_signal(
    facts: ColumnFacts,
    kind: str,
    rows: int | None,
    *,
    datetime_text: bool,
    analyzed: bool,
    sample: bool,
) -> ColumnSignal:
    role, evidence = _resolve_role(facts, kind, datetime_text=datetime_text)
    return ColumnSignal(
        name=facts.name,
        dtype=facts.dtype,
        role=role,
        role_evidence=_evidence(evidence, sample=sample),
        non_null=facts.non_null,
        missing_pct=_percentage(facts.missing, rows),
        distinct=facts.distinct,
        unique_pct=_percentage(facts.distinct, facts.non_null),
        content_analyzed=analyzed,
    )


def _group_signals(signals: Sequence[ColumnSignal]) -> tuple[SemanticGroup, ...]:
    """Group signals by role in precedence order, bounded per group."""
    groups: list[SemanticGroup] = []
    for role in ROLE_PRECEDENCE:
        members = [signal for signal in signals if signal.role == role]
        if not members:
            continue
        groups.append(
            SemanticGroup(
                role=role,
                title=ROLE_TITLES[role],
                total_columns=len(members),
                signals=tuple(members[:MAX_GROUP_COLUMNS]),
            )
        )
    return tuple(groups)


# --- Record strategies -------------------------------------------------------


def _first_positions(rows: int) -> list[int]:
    return list(range(min(rows, MAX_RECORD_ROWS_PER_STRATEGY)))


def _spread_positions(rows: int) -> list[int]:
    """Return evenly spaced positions across the frame (integer math only)."""
    picks = min(rows, MAX_RECORD_ROWS_PER_STRATEGY)
    if picks <= 0:
        return []
    if picks == 1:
        return [0]
    return [(index * (rows - 1)) // (picks - 1) for index in range(picks)]


def _most_missing_positions(frame: pd.DataFrame, scanned: int) -> list[int]:
    """Return positions with the most empty fields within the scanned range."""
    if scanned <= 0 or frame.shape[1] == 0:
        return []
    counts = frame.iloc[:scanned].isna().sum(axis=1).to_numpy()
    ranked = sorted(range(len(counts)), key=lambda index: (-int(counts[index]), index))
    return [index for index in ranked if int(counts[index]) > 0][:MAX_RECORD_ROWS_PER_STRATEGY]


def _dedupe_records(
    candidates: Sequence[tuple[str, Sequence[int]]],
) -> tuple[SelectedRecord, ...]:
    """Merge strategy picks, keeping the first strategy that claimed each row."""
    seen: set[int] = set()
    records: list[SelectedRecord] = []
    for strategy, positions in candidates:
        for position in positions:
            if position in seen or len(records) >= MAX_RECORD_ROWS:
                continue
            seen.add(position)
            records.append(SelectedRecord(position=position, strategy=strategy))
    return tuple(records)


def _select_records(frame: pd.DataFrame | None, *, sample: bool) -> RecordSelection:
    """Pick deterministic, bounded preview rows from the already-loaded frame.

    The frame is the only authority for positional selection: a profile row count
    may describe the source file rather than the frame actually in memory.
    """
    if frame is None:
        return RecordSelection(
            available=False, evidence=EVIDENCE_UNAVAILABLE, reason=_NO_FRAME_REASON
        )
    row_count = int(len(frame))
    if frame.shape[1] == 0:
        return RecordSelection(
            available=False, evidence=EVIDENCE_UNAVAILABLE, reason=_NO_COLUMNS_REASON
        )
    if row_count == 0:
        return RecordSelection(
            available=False, evidence=EVIDENCE_UNAVAILABLE, reason=_NO_ROWS_REASON
        )
    scanned = min(row_count, MAX_RECORD_SCAN_ROWS)
    candidates: list[tuple[str, Sequence[int]]] = [
        (STRATEGY_FIRST_ROWS, _first_positions(row_count)),
        (STRATEGY_EVEN_SPREAD, _spread_positions(row_count)),
        (STRATEGY_MOST_MISSING, _most_missing_positions(frame, scanned)),
    ]
    records = _dedupe_records(candidates)
    columns = tuple(str(name) for name in frame.columns[:MAX_RECORD_COLUMNS])
    return RecordSelection(
        available=bool(records),
        evidence=EVIDENCE_SAMPLE if sample else EVIDENCE_FACT,
        reason="" if records else _NO_ROWS_REASON,
        records=records,
        columns=columns,
        total_columns=int(frame.shape[1]),
        scanned_rows=scanned,
        strategies=tuple(strategy for strategy, positions in candidates if positions),
    )


# --- Callouts ----------------------------------------------------------------


def _name_list(names: Sequence[str]) -> str:
    """Return a bounded, deterministic inline list of column names."""
    shown = list(names[:MAX_NAMES_PER_CALLOUT])
    rendered = ", ".join(f"`{name}`" for name in shown)
    remaining = len(names) - len(shown)
    return f"{rendered} and {remaining} more" if remaining > 0 else rendered


def _shape_callouts(rows: int | None, columns: int, *, sample: bool) -> list[Callout]:
    out: list[Callout] = []
    fact = _evidence(EVIDENCE_FACT, sample=sample)
    if columns == 0:
        out.append(
            Callout(
                key="no_columns",
                severity=SEVERITY_ATTENTION,
                evidence=fact,
                message="This dataset has no columns, so there is nothing to profile.",
            )
        )
    if rows == 0:
        out.append(
            Callout(
                key="empty_dataset",
                severity=SEVERITY_ATTENTION,
                evidence=fact,
                message="This dataset has no rows. Every derived measure is undefined.",
            )
        )
    if columns > WIDE_COLUMN_THRESHOLD:
        out.append(
            Callout(
                key="wide_dataset",
                severity=SEVERITY_NOTE,
                evidence=fact,
                message=(
                    f"Wide dataset: {columns} columns (above {WIDE_COLUMN_THRESHOLD}). "
                    "Grouped signals below are capped per group."
                ),
            )
        )
    return out


def _missingness_callouts(
    facts: Sequence[ColumnFacts], rows: int | None, *, sample: bool
) -> list[Callout]:
    out: list[Callout] = []
    fact = _evidence(EVIDENCE_FACT, sample=sample)
    measured = [item for item in facts if item.missing is not None]
    if rows and measured:
        total = sum(int(item.missing or 0) for item in measured)
        overall = round(float(total) / float(rows * len(measured)) * 100.0, 2)
        if overall >= HIGH_MISSING_PCT:
            out.append(
                Callout(
                    key="high_missingness",
                    severity=SEVERITY_ATTENTION,
                    evidence=fact,
                    message=f"About {overall}% of measured cells are empty across the dataset.",
                )
            )
    near_empty = [
        item.name for item in measured if (_percentage(item.missing, rows) or 0.0) >= NEAR_EMPTY_PCT
    ]
    if near_empty:
        out.append(
            Callout(
                key="near_empty_columns",
                severity=SEVERITY_ATTENTION,
                evidence=fact,
                message=(
                    f"{len(near_empty)} column(s) are at least {NEAR_EMPTY_PCT:.0f}% empty: "
                    f"{_name_list(near_empty)}."
                ),
            )
        )
    constant = [item.name for item in facts if item.distinct == 1 and (item.non_null or 0) > 0]
    if constant:
        out.append(
            Callout(
                key="constant_columns",
                severity=SEVERITY_NOTE,
                evidence=fact,
                message=(
                    f"{len(constant)} column(s) hold a single distinct value: "
                    f"{_name_list(constant)}."
                ),
            )
        )
    return out


def _duplicate_callout(
    duplicate_rows: int | None, rows: int | None, *, sample: bool
) -> list[Callout]:
    if duplicate_rows is None or duplicate_rows <= 0:
        return []
    share = _percentage(duplicate_rows, rows)
    suffix = f" ({share}% of rows)" if share is not None else ""
    return [
        Callout(
            key="duplicate_rows",
            severity=SEVERITY_ATTENTION,
            evidence=_evidence(EVIDENCE_FACT, sample=sample),
            message=f"{duplicate_rows} fully duplicated row(s){suffix}.",
        )
    ]


def _role_callouts(signals: Sequence[ColumnSignal], kinds: Mapping[str, str]) -> list[Callout]:
    out: list[Callout] = []
    identifiers = [s.name for s in signals if s.role == ROLE_IDENTIFIER]
    if identifiers:
        out.append(
            Callout(
                key="likely_identifiers",
                severity=SEVERITY_NOTE,
                evidence=EVIDENCE_HEURISTIC,
                message=(
                    f"{len(identifiers)} column(s) look like identifiers rather than "
                    f"measures: {_name_list(identifiers)}. Confirm before aggregating."
                ),
            )
        )
    datetime_text = [
        s.name for s in signals if s.role == ROLE_DATETIME and s.role_evidence == EVIDENCE_HEURISTIC
    ]
    if datetime_text:
        out.append(
            Callout(
                key="datetime_text",
                severity=SEVERITY_NOTE,
                evidence=EVIDENCE_HEURISTIC,
                message=(
                    f"{len(datetime_text)} text column(s) look like dates: "
                    f"{_name_list(datetime_text)}. Parsing them would enable time analysis."
                ),
            )
        )
    high_cardinality = [
        s.name
        for s in signals
        if kinds.get(s.name) == _KIND_TEXT
        and s.role == ROLE_OTHER
        and s.distinct is not None
        and s.distinct > MAX_CATEGORY_VALUES
    ]
    if high_cardinality:
        out.append(
            Callout(
                key="high_cardinality_text",
                severity=SEVERITY_NOTE,
                evidence=EVIDENCE_HEURISTIC,
                message=(
                    f"{len(high_cardinality)} text column(s) hold more than "
                    f"{MAX_CATEGORY_VALUES} distinct values: {_name_list(high_cardinality)}."
                ),
            )
        )
    return out


def _numeric_callouts(zero_heavy: Sequence[str], non_finite: Sequence[str]) -> list[Callout]:
    out: list[Callout] = []
    if zero_heavy:
        out.append(
            Callout(
                key="zero_heavy_numeric",
                severity=SEVERITY_NOTE,
                evidence=EVIDENCE_SAMPLE,
                message=(
                    f"In the inspected rows, {len(zero_heavy)} numeric column(s) are almost "
                    f"entirely zero: {_name_list(zero_heavy)}."
                ),
            )
        )
    if non_finite:
        out.append(
            Callout(
                key="non_finite_numeric",
                severity=SEVERITY_NOTE,
                evidence=EVIDENCE_SAMPLE,
                message=(
                    f"In the inspected rows, {len(non_finite)} numeric column(s) contain "
                    f"infinite values: {_name_list(non_finite)}."
                ),
            )
        )
    return out


def _rank_callouts(callouts: Sequence[Callout]) -> tuple[Callout, ...]:
    """Rank by severity, keeping build order within a severity, then cap."""
    ordered = sorted(
        enumerate(callouts),
        key=lambda pair: (_SEVERITY_RANK.get(pair[1].severity, 1), pair[0]),
    )
    return tuple(callout for _, callout in ordered[:MAX_CALLOUTS])


# --- Public builder ----------------------------------------------------------


def build_smart_overview(
    *,
    identity: PreviewIdentity | None = None,
    profile: Mapping[str, Any] | None = None,
    frame: pd.DataFrame | None = None,
    duplicate_rows: int | None = None,
    analysis_mode: str = ANALYSIS_FULL,
) -> SmartOverview:
    """Build the bounded Smart Preview model from data the caller already holds.

    ``profile`` is the page's existing profiling result and is the preferred
    source of counted facts; ``frame`` is the page's existing analysis frame and
    is read only through a bounded head plus positional record selection. Neither
    input is loaded, re-profiled, reassessed, or mutated here. Passing
    ``analysis_mode=ANALYSIS_SAMPLE`` marks every exact classification as
    bounded-sample instead, which is the correct declaration for large-file mode.
    """
    mode = analysis_mode if analysis_mode in (ANALYSIS_FULL, ANALYSIS_SAMPLE) else ANALYSIS_FULL
    sample = _sample_mode(mode)
    rows = _resolve_rows(profile, frame)
    facts = _facts_from_profile(profile, rows) if profile is not None else []
    if not facts and frame is not None:
        facts = _facts_from_frame(frame)
    columns = _resolve_columns(profile, frame, facts)
    kinds = {item.name: _dtype_kind(item.dtype) for item in facts}

    head = _bounded_head(frame) if frame is not None else None
    analyzed = frozenset(str(name) for name in head.columns) if head is not None else frozenset()
    datetime_text = _datetime_text_columns(head, kinds) if head is not None else frozenset()
    zero_heavy, non_finite = _numeric_content_columns(head, kinds) if head is not None else ([], [])

    signals = [
        _build_signal(
            item,
            kinds.get(item.name, _KIND_OTHER),
            rows,
            datetime_text=item.name in datetime_text,
            analyzed=item.name in analyzed,
            sample=sample,
        )
        for item in facts
    ]
    callouts = _rank_callouts(
        [
            *_shape_callouts(rows, columns, sample=sample),
            *_duplicate_callout(duplicate_rows, rows, sample=sample),
            *_missingness_callouts(facts, rows, sample=sample),
            *_role_callouts(signals, kinds),
            *_numeric_callouts(zero_heavy, non_finite),
        ]
    )
    return SmartOverview(
        identity=identity if identity is not None else PreviewIdentity(),
        analysis_mode=mode,
        rows=rows,
        columns=columns,
        shape_evidence=_evidence(EVIDENCE_FACT, sample=sample),
        groups=_group_signals(signals),
        selection=_select_records(frame, sample=sample),
        callouts=callouts,
        content_columns_inspected=len(analyzed),
        content_rows_inspected=int(len(head)) if head is not None else 0,
    )
