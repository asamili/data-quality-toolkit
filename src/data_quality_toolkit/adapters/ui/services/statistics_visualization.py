"""Framework-free chart-data builders for Statistics Lab result evidence.

Every builder in this module turns an *already computed* statistical result (or
the exact analyzed inputs the runner retained for it) into bounded, deterministic
plotting data. Nothing here executes, re-runs, or re-derives a statistical test:
no statistic, no p-value, no alpha decision, no alternative, and no paired
direction is produced or changed. The only quantities derived are display
geometry that follows arithmetically from values the result already exposes
(observed minus expected, a Pearson residual, a chi-square cell contribution and
its share, an observed proportion, a paired difference).

Structural rules (mirrors the EDA visual-discovery builder tier):

* no Streamlit, no session state, no filesystem, no network, no writes;
* no random sampling — every cap uses deterministic positional selection;
* inputs are never mutated;
* nothing raises for hostile operator data; unusable input returns a typed
  ``unavailable`` state instead of a fabricated or zero-filled value.

Every builder returns the shared contract
``{"status": ..., "reason": ..., "data": DataFrame, **meta}`` where ``status`` is
``"ok"`` or ``"unavailable"``. An absent estimate, interval, expected matrix or
raw analyzed input is reported as unavailable and never replaced with zero.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

# ── performance and privacy bounds ────────────────────────────────────────────
#
# Named ceilings for every result-native evidence view. They bound both compute
# and how much of the analyzed data can reach a chart, tooltip or table.

RESULT_CHART_MAX_ROWS = 5_000
PAIRED_PLOT_MAX_PAIRS = 500
PAIRED_LINE_DISPLAY_MAX = 100
CONTINGENCY_MAX_ROWS = 20
CONTINGENCY_MAX_COLUMNS = 20
CONTINGENCY_MAX_CELLS = 400
GOF_MAX_CATEGORIES = 40
DISTRIBUTION_CURVE_MAX_POINTS = 401
POWER_CURVE_MAX_POINTS = 101
CI_PLOT_MAX_ESTIMATES = 50

# How many largest-residual contingency cells are ranked for the evidence table.
CONTINGENCY_RANKED_CELL_LIMIT = 10
# Expected-count floor below which a contingency cell is reported as sparse.
# Informational only: it mirrors the diagnostics the result already carries and
# never switches, re-runs or invalidates the test.
SPARSE_EXPECTED_FLOOR = 5.0
# Bounded, control-character-free display text for any category label.
LABEL_MAX_TEXT = 100

_BLANK_LABEL = "(blank)"
_UNSAFE_LABEL = "(unavailable)"

_GOF_COLUMNS = [
    "category",
    "observed",
    "expected",
    "difference",
    "contribution",
    "contribution_share",
]
_CONTINGENCY_COLUMNS = [
    "row_category",
    "col_category",
    "observed",
    "expected",
    "residual",
    "contribution",
    "direction",
]
_ESTIMATE_COLUMNS = ["label", "estimate", "lower", "upper", "confidence", "n", "interval_available"]
_PAIRED_COLUMNS = ["pair", "before", "after", "difference"]
_PROPORTION_COLUMNS = [
    "label",
    "successes",
    "total",
    "proportion",
    "lower",
    "upper",
    "interval_available",
]
_GROUP_COLUMNS = ["group", "n", "center", "lower", "upper", "interval_available"]
_DISTRIBUTION_COLUMNS = ["x", "value", "shaded"]
_POWER_COLUMNS = ["parameter", "value"]

_ABOVE = "observed above expected"
_BELOW = "observed below expected"
_MATCHES = "observed matches expected"


# ── shared helpers ────────────────────────────────────────────────────────────


def _empty_frame(columns: Sequence[str]) -> pd.DataFrame:
    """Return an empty frame carrying the builder's stable display columns."""
    return pd.DataFrame(columns=list(columns))


def _evidence(
    status: str,
    data: pd.DataFrame,
    *,
    reason: str | None = None,
    **meta: Any,
) -> dict[str, Any]:
    """Return the shared evidence-builder contract."""
    result: dict[str, Any] = {"status": status, "reason": reason, "data": data}
    result.update(meta)
    return result


def _unavailable(columns: Sequence[str], reason: str, **meta: Any) -> dict[str, Any]:
    """Return a typed unavailable state — never a fabricated or zero-filled row."""
    return _evidence("unavailable", _empty_frame(columns), reason=reason, **meta)


def _finite(value: Any) -> float | None:
    """Return a finite float, or None when the value is missing/non-numeric/infinite."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_int(value: Any) -> int | None:
    number = _finite(value)
    return None if number is None else int(number)


def _bounded_cap(requested: Any, ceiling: int) -> int:
    """Clamp a caller-supplied cap to its view ceiling and the global row ceiling.

    ``RESULT_CHART_MAX_ROWS`` is the absolute ceiling for any single evidence
    frame, so no view can ever be widened past it by a caller argument.
    """
    try:
        wanted = int(requested)
    except (TypeError, ValueError):
        wanted = ceiling
    return max(1, min(wanted, int(ceiling), RESULT_CHART_MAX_ROWS))


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


def safe_label(value: Any) -> str:
    """Return bounded, control-character-free display text for a category value.

    Labels reaching this module are already collision-safe (the statistics
    service owns typed category identity). This is a second, defensive bound so
    no unbounded or control-character text can reach a chart axis or tooltip.
    """
    try:
        text = value if isinstance(value, str) else str(value)
    except Exception:
        return _UNSAFE_LABEL
    cleaned = "".join(character for character in text if ord(character) >= 32)
    if not cleaned:
        return _BLANK_LABEL
    if len(cleaned) > LABEL_MAX_TEXT:
        return cleaned[: LABEL_MAX_TEXT - 1] + "…"
    return cleaned


def deterministic_positions(count: int, maximum: int) -> list[int]:
    """Return bounded, evenly spaced positional offsets (never random sampling).

    Positions are offsets into the caller's own ordering, never DataFrame index
    labels or source row identifiers.
    """
    total = max(0, int(count))
    limit = max(1, int(maximum))
    if total <= limit:
        return list(range(total))
    spread = np.linspace(0, total - 1, limit).round().astype(int)
    return [int(position) for position in dict.fromkeys(spread.tolist())]


def _result_is_ok(result: Mapping[str, Any]) -> bool:
    return str(result.get("status") or "") == "ok"


# ── chi-square goodness of fit ────────────────────────────────────────────────


def _gof_rows(
    entries: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[float | None]]:
    """Build per-category observed/expected rows plus their cell contributions."""
    rows: list[dict[str, Any]] = []
    contributions: list[float | None] = []
    for entry in entries:
        observed = _finite(entry.get("observed"))
        expected = _finite(entry.get("expected_count"))
        difference = None if observed is None or expected is None else observed - expected
        contribution: float | None = None
        if observed is not None and expected is not None and expected > 0.0:
            contribution = (observed - expected) ** 2 / expected
        contributions.append(contribution)
        rows.append(
            {
                "category": safe_label(entry.get("category")),
                "observed": observed,
                "expected": _round(expected),
                "difference": _round(difference),
                "contribution": None,
                "contribution_share": None,
            }
        )
    return rows, contributions


def _long_form_counts(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Reshape observed/expected rows into grouped-bar plotting form."""
    records = [
        {"category": row["category"], "measure": measure, "count": row[measure]}
        for row in rows
        for measure in ("observed", "expected")
        if row[measure] is not None
    ]
    return pd.DataFrame(records, columns=["category", "measure", "count"])


def build_gof_evidence(
    result: Mapping[str, Any],
    *,
    max_categories: int = GOF_MAX_CATEGORIES,
) -> dict[str, Any]:
    """Prepare observed-versus-expected evidence for a completed goodness-of-fit result.

    Reads only the ``categories`` contract the result already returned. The
    chi-square cell contribution is computed only where the expected count is
    finite and strictly positive; an invalid expected count leaves that cell's
    contribution unavailable rather than zero, and contribution shares are
    produced only when every displayed cell has a contribution and their total is
    positive. The statistic, p-value and decision are never recomputed.
    """
    if not _result_is_ok(result):
        return _unavailable(_GOF_COLUMNS, "no completed goodness-of-fit result to visualize")
    entries = [entry for entry in (result.get("categories") or []) if isinstance(entry, Mapping)]
    if not entries:
        return _unavailable(_GOF_COLUMNS, "the result exposes no per-category evidence")

    limit = _bounded_cap(max_categories, GOF_MAX_CATEGORIES)
    shown = entries[:limit]
    rows, contributions = _gof_rows(shown)
    present = [value for value in contributions if value is not None]
    total = float(sum(present))
    contribution_available = len(present) == len(contributions) and total > 0.0
    for row, contribution in zip(rows, contributions):
        row["contribution"] = _round(contribution)
        if contribution_available and contribution is not None:
            row["contribution_share"] = _round(contribution / total)

    observed_total = sum(row["observed"] or 0.0 for row in rows)
    sample_size = _finite_int(result.get("valid_rows"))
    return _evidence(
        "ok",
        pd.DataFrame(rows, columns=_GOF_COLUMNS),
        comparison=_long_form_counts(rows),
        category_count=len(entries),
        displayed_categories=len(rows),
        truncated=len(rows) < len(entries),
        sample_size=sample_size if sample_size is not None else int(observed_total),
        contribution_available=contribution_available,
        total_contribution=_round(total) if contribution_available else None,
    )


# ── chi-square independence / homogeneity ─────────────────────────────────────


def _contingency_cell(entry: Mapping[str, Any]) -> dict[str, Any]:
    observed = _finite(entry.get("observed"))
    expected = _finite(entry.get("expected"))
    residual: float | None = None
    contribution: float | None = None
    direction = _MATCHES
    if observed is not None and expected is not None and expected > 0.0:
        residual = (observed - expected) / math.sqrt(expected)
        contribution = (observed - expected) ** 2 / expected
        if observed > expected:
            direction = _ABOVE
        elif observed < expected:
            direction = _BELOW
    return {
        "row_category": safe_label(entry.get("row_category")),
        "col_category": safe_label(entry.get("col_category")),
        "observed": observed,
        "expected": _round(expected),
        "residual": _round(residual),
        "contribution": _round(contribution),
        "direction": direction if residual is not None else None,
    }


def _contingency_bounds_error(
    n_rows: int,
    n_cols: int,
    n_cells: int,
    *,
    max_rows: int,
    max_columns: int,
    max_cells: int,
) -> str | None:
    if n_rows > max_rows:
        return f"table has {n_rows} row categories; the evidence view is bounded at {max_rows}"
    if n_cols > max_columns:
        return (
            f"table has {n_cols} column categories; the evidence view is bounded at {max_columns}"
        )
    if n_cells > max_cells:
        return f"table has {n_cells} cells; the evidence view is bounded at {max_cells}"
    return None


def build_contingency_evidence(
    result: Mapping[str, Any],
    *,
    max_rows: int = CONTINGENCY_MAX_ROWS,
    max_columns: int = CONTINGENCY_MAX_COLUMNS,
    max_cells: int = CONTINGENCY_MAX_CELLS,
    ranked_limit: int = CONTINGENCY_RANKED_CELL_LIMIT,
) -> dict[str, Any]:
    """Prepare residual/contribution evidence for a completed contingency chi-square result.

    Uses the result's own ``cells``, ``row_labels`` and ``col_labels``; only the
    Pearson residual and the chi-square cell contribution are derived, and only
    where the expected count is finite and strictly positive. A table wider or
    taller than the bounds returns a typed unavailable state — categories are
    never silently dropped. The statistic, p-value and decision are untouched.
    """
    if not _result_is_ok(result):
        return _unavailable(_CONTINGENCY_COLUMNS, "no completed chi-square result to visualize")
    entries = [entry for entry in (result.get("cells") or []) if isinstance(entry, Mapping)]
    row_labels = [safe_label(label) for label in (result.get("row_labels") or [])]
    col_labels = [safe_label(label) for label in (result.get("col_labels") or [])]
    if not entries or not row_labels or not col_labels:
        return _unavailable(_CONTINGENCY_COLUMNS, "the result exposes no contingency-cell evidence")

    n_rows = len(row_labels)
    n_cols = len(col_labels)
    n_cells = len(entries)
    bounds_error = _contingency_bounds_error(
        n_rows,
        n_cols,
        n_cells,
        max_rows=_bounded_cap(max_rows, CONTINGENCY_MAX_ROWS),
        max_columns=_bounded_cap(max_columns, CONTINGENCY_MAX_COLUMNS),
        max_cells=_bounded_cap(max_cells, CONTINGENCY_MAX_CELLS),
    )
    if bounds_error is not None:
        return _unavailable(
            _CONTINGENCY_COLUMNS,
            bounds_error,
            row_count=n_rows,
            col_count=n_cols,
            cell_count=n_cells,
        )

    cells = [_contingency_cell(entry) for entry in entries]
    data = pd.DataFrame(cells, columns=_CONTINGENCY_COLUMNS)
    expected_values = [value for value in (cell["expected"] for cell in cells) if value is not None]
    low_expected = sum(1 for value in expected_values if value < SPARSE_EXPECTED_FLOOR)
    residual_cells = [cell for cell in cells if cell["residual"] is not None]
    ranked_order = sorted(
        range(len(cells)),
        key=lambda index: (
            -abs(cells[index]["residual"] or 0.0),
            index,
        ),
    )
    ranked_rows = [cells[index] for index in ranked_order if cells[index]["residual"] is not None]
    ranked = pd.DataFrame(
        ranked_rows[: _bounded_cap(ranked_limit, CONTINGENCY_MAX_CELLS)],
        columns=_CONTINGENCY_COLUMNS,
    )
    return _evidence(
        "ok",
        data,
        row_labels=row_labels,
        col_labels=col_labels,
        row_count=n_rows,
        col_count=n_cols,
        cell_count=n_cells,
        residual_available=bool(residual_cells),
        ranked=ranked,
        min_expected=min(expected_values) if expected_values else None,
        low_expected_cells=low_expected,
        sparse_expected=bool(low_expected),
        truncated=False,
    )


# ── estimates and confidence intervals ────────────────────────────────────────


def _estimate_row(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    estimate = _finite(entry.get("estimate"))
    if estimate is None:
        return None
    lower = _finite(entry.get("lower"))
    upper = _finite(entry.get("upper"))
    interval_available = lower is not None and upper is not None and lower <= upper
    return {
        "label": safe_label(entry.get("label")),
        "estimate": _round(estimate),
        "lower": _round(lower) if interval_available else None,
        "upper": _round(upper) if interval_available else None,
        "confidence": _round(_finite(entry.get("confidence"))),
        "n": _finite_int(entry.get("n")),
        "interval_available": interval_available,
    }


def build_estimate_interval_evidence(
    estimates: Sequence[Mapping[str, Any]],
    *,
    reference: Any = None,
    max_estimates: int = CI_PLOT_MAX_ESTIMATES,
) -> dict[str, Any]:
    """Prepare point-and-interval evidence for estimates the result already exposes.

    An interval is carried only when both bounds are finite and ordered; a
    missing or partial interval is reported as unavailable for that estimate and
    is never substituted with ``[0, 0]``. The reference line is emitted only when
    the caller supplies a finite, mathematically meaningful reference value.
    """
    entries = [entry for entry in estimates if isinstance(entry, Mapping)]
    if not entries:
        return _unavailable(_ESTIMATE_COLUMNS, "no estimate is available to visualize")
    limit = _bounded_cap(max_estimates, CI_PLOT_MAX_ESTIMATES)
    rows = [row for row in (_estimate_row(entry) for entry in entries[:limit]) if row is not None]
    if not rows:
        return _unavailable(
            _ESTIMATE_COLUMNS,
            "the result exposes no finite point estimate",
            estimate_count=len(entries),
        )
    reference_value = _finite(reference)
    return _evidence(
        "ok",
        pd.DataFrame(rows, columns=_ESTIMATE_COLUMNS),
        estimate_count=len(entries),
        displayed_estimates=len(rows),
        truncated=len(entries) > limit,
        intervals_available=any(row["interval_available"] for row in rows),
        reference=_round(reference_value),
        reference_available=reference_value is not None,
    )


# ── paired results ────────────────────────────────────────────────────────────


def _difference_summary(differences: np.ndarray) -> dict[str, float | None]:
    if differences.size == 0:
        return {
            "minimum": None,
            "q1": None,
            "median": None,
            "q3": None,
            "maximum": None,
            "mean": None,
        }
    quartiles = np.quantile(differences, [0.25, 0.5, 0.75])
    return {
        "minimum": round(float(differences.min()), 6),
        "q1": round(float(quartiles[0]), 6),
        "median": round(float(quartiles[1]), 6),
        "q3": round(float(quartiles[2]), 6),
        "maximum": round(float(differences.max()), 6),
        "mean": round(float(differences.mean()), 6),
    }


def _long_form_pairs(lines: pd.DataFrame) -> pd.DataFrame:
    """Reshape anonymous before/after pairs into connected-line plotting form."""
    records = [
        {"pair": int(row["pair"]), "measurement": measurement, "value": row[measurement]}
        for row in lines.to_dict("records")
        for measurement in ("before", "after")
    ]
    return pd.DataFrame(records, columns=["pair", "measurement", "value"])


def build_paired_evidence(
    before: Sequence[Any],
    after: Sequence[Any],
    *,
    total_rows: int | None = None,
    max_pairs: int = PAIRED_PLOT_MAX_PAIRS,
    max_lines: int = PAIRED_LINE_DISPLAY_MAX,
) -> dict[str, Any]:
    """Prepare anonymous paired before/after evidence from the retained analyzed inputs.

    Pairs are formed positionally and a pair is kept only when both members are
    finite — exactly the pairwise exclusion the paired runners already applied,
    so the reported complete-pair count agrees with the computed result. The
    difference keeps the contract direction (first measurement minus second) and
    is never reversed. Only an anonymous 1-based pair position is emitted: no row
    identifier, DataFrame index, or source position ever reaches the chart.
    """
    try:
        first = np.asarray(before, dtype=float).ravel()
        second = np.asarray(after, dtype=float).ravel()
    except (TypeError, ValueError):
        return _unavailable(_PAIRED_COLUMNS, "the paired columns are not numeric")
    if first.size != second.size:
        return _unavailable(_PAIRED_COLUMNS, "paired inputs must have equal length")

    keep = np.isfinite(first) & np.isfinite(second)
    complete = int(keep.sum())
    source_rows = int(total_rows) if total_rows is not None else int(first.size)
    excluded = max(0, source_rows - complete)
    if complete < 1:
        return _unavailable(
            _PAIRED_COLUMNS,
            "no complete pair remains after excluding rows with a missing or non-finite value",
            complete_pairs=0,
            excluded_rows=excluded,
        )

    kept_before = first[keep]
    kept_after = second[keep]
    differences = kept_before - kept_after
    positions = deterministic_positions(complete, _bounded_cap(max_pairs, PAIRED_PLOT_MAX_PAIRS))
    rows = [
        {
            "pair": index + 1,
            "before": round(float(kept_before[position]), 6),
            "after": round(float(kept_after[position]), 6),
            "difference": round(float(differences[position]), 6),
        }
        for index, position in enumerate(positions)
    ]
    data = pd.DataFrame(rows, columns=_PAIRED_COLUMNS)
    line_positions = deterministic_positions(
        len(rows), _bounded_cap(max_lines, PAIRED_LINE_DISPLAY_MAX)
    )
    lines = data.iloc[line_positions].reset_index(drop=True)
    return _evidence(
        "ok",
        data,
        complete_pairs=complete,
        excluded_rows=excluded,
        displayed_pairs=len(data),
        truncated=len(data) < complete,
        lines=lines,
        lines_long=_long_form_pairs(lines),
        displayed_lines=len(lines),
        lines_truncated=len(lines) < len(data),
        difference_summary=_difference_summary(differences),
        zero_reference=0.0,
    )


# ── proportions ───────────────────────────────────────────────────────────────


def _proportion_row(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    total = _finite_int(entry.get("total"))
    successes = _finite_int(entry.get("successes"))
    if total is None or successes is None or total <= 0:
        return None
    proportion = _finite(entry.get("proportion"))
    if proportion is None:
        proportion = successes / total
    lower = _finite(entry.get("lower"))
    upper = _finite(entry.get("upper"))
    interval_available = lower is not None and upper is not None and lower <= upper
    return {
        "label": safe_label(entry.get("label")),
        "successes": successes,
        "total": total,
        "proportion": _round(proportion),
        "lower": _round(lower) if interval_available else None,
        "upper": _round(upper) if interval_available else None,
        "interval_available": interval_available,
    }


def build_proportion_evidence(
    groups: Sequence[Mapping[str, Any]],
    *,
    reference: Any = None,
    difference: Any = None,
) -> dict[str, Any]:
    """Prepare bounded proportion evidence from the counts a proportion result exposes.

    Successes, totals and the observed proportion come from the result itself; no
    new interval formula is introduced, so uncertainty whiskers appear only when
    the caller passes bounds the existing result already produced. Group labels
    are the collision-safe typed labels the service assigned — this builder never
    re-derives category identity from text.
    """
    entries = [entry for entry in groups if isinstance(entry, Mapping)]
    rows = [row for row in (_proportion_row(entry) for entry in entries) if row is not None]
    if not rows:
        return _unavailable(_PROPORTION_COLUMNS, "no proportion with a positive denominator")
    reference_value = _finite(reference)
    difference_value = _finite(difference)
    return _evidence(
        "ok",
        pd.DataFrame(rows, columns=_PROPORTION_COLUMNS),
        group_count=len(rows),
        intervals_available=any(row["interval_available"] for row in rows),
        reference=_round(reference_value),
        reference_available=reference_value is not None,
        difference=_round(difference_value),
        difference_available=difference_value is not None,
    )


# ── group and effect comparison ───────────────────────────────────────────────


def _group_row(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    center = _finite(entry.get("center"))
    if center is None:
        return None
    lower = _finite(entry.get("lower"))
    upper = _finite(entry.get("upper"))
    interval_available = lower is not None and upper is not None and lower <= upper
    return {
        "group": safe_label(entry.get("group")),
        "n": _finite_int(entry.get("n")),
        "center": _round(center),
        "lower": _round(lower) if interval_available else None,
        "upper": _round(upper) if interval_available else None,
        "interval_available": interval_available,
    }


def build_group_comparison_evidence(
    groups: Sequence[Mapping[str, Any]],
    *,
    max_groups: int = CI_PLOT_MAX_ESTIMATES,
) -> dict[str, Any]:
    """Prepare a bounded per-group centre (and interval where available) comparison.

    Only values the existing result already returned are plotted — group sizes,
    group centres, and any interval the result carries. No raw observation is
    plotted, no post-hoc pairwise comparison is derived, and no interval is
    invented for a group that has none.
    """
    entries = [entry for entry in groups if isinstance(entry, Mapping)]
    if not entries:
        return _unavailable(_GROUP_COLUMNS, "no group summary is available to visualize")
    limit = _bounded_cap(max_groups, CI_PLOT_MAX_ESTIMATES)
    rows = [row for row in (_group_row(entry) for entry in entries[:limit]) if row is not None]
    if not rows:
        return _unavailable(
            _GROUP_COLUMNS,
            "the result exposes no finite group centre",
            group_count=len(entries),
        )
    return _evidence(
        "ok",
        pd.DataFrame(rows, columns=_GROUP_COLUMNS),
        group_count=len(entries),
        displayed_groups=len(rows),
        truncated=len(entries) > limit,
        intervals_available=any(row["interval_available"] for row in rows),
    )


# ── bounded parameter grids, distribution curves and power curves ─────────────


def build_parameter_grid(
    lower: Any,
    upper: Any,
    *,
    points: int,
    maximum: int,
    integer: bool = False,
) -> list[float]:
    """Return a bounded, deterministic, evenly spaced parameter grid.

    Returns an empty grid for non-finite or inverted bounds rather than raising.
    ``integer=True`` collapses duplicates so a discrete axis never repeats a
    value.
    """
    low = _finite(lower)
    high = _finite(upper)
    ceiling = max(2, _bounded_cap(maximum, RESULT_CHART_MAX_ROWS))
    if low is None or high is None or high < low:
        return []
    count = min(max(2, int(points)), ceiling)
    if math.isclose(low, high):
        return [round(low, 10)] if not integer else [float(int(round(low)))]
    grid = np.linspace(low, high, count)
    if integer:
        unique = dict.fromkeys(int(round(float(value))) for value in grid)
        return [float(value) for value in unique]
    return [round(float(value), 10) for value in grid]


def _curve_points(
    evaluate: Callable[[float], Mapping[str, Any]],
    grid: Sequence[float],
    *,
    value_field: str,
) -> tuple[list[tuple[float, float]], int]:
    """Evaluate a grid, keeping only usable points and counting the skipped ones."""
    points: list[tuple[float, float]] = []
    invalid = 0
    for raw in grid:
        position = _finite(raw)
        if position is None:
            invalid += 1
            continue
        try:
            evaluated = evaluate(position)
        except Exception:
            invalid += 1
            continue
        if not isinstance(evaluated, Mapping) or str(evaluated.get("status") or "") != "ok":
            invalid += 1
            continue
        value = _finite(evaluated.get(value_field))
        if value is None:
            invalid += 1
            continue
        points.append((position, value))
    return points, invalid


def _shaded(position: float, shade_lower: float | None, shade_upper: float | None) -> bool:
    if shade_lower is None and shade_upper is None:
        return False
    if shade_lower is not None and position < shade_lower:
        return False
    if shade_upper is not None and position > shade_upper:
        return False
    return True


def build_distribution_curve(
    evaluate: Callable[[float], Mapping[str, Any]],
    grid: Sequence[float],
    *,
    marker: Any = None,
    shade_lower: Any = None,
    shade_upper: Any = None,
    max_points: int = DISTRIBUTION_CURVE_MAX_POINTS,
) -> dict[str, Any]:
    """Prepare a bounded theoretical-distribution curve from the existing calculators.

    ``evaluate`` is the existing distribution lookup supplied by the caller; this
    module adds no distribution family and no new formula. Points whose lookup is
    unavailable or non-finite are skipped and counted — never coerced to zero.
    The shaded region marks exactly the interval the caller's own calculation
    covers.
    """
    limit = max(2, _bounded_cap(max_points, DISTRIBUTION_CURVE_MAX_POINTS))
    positions = deterministic_positions(len(grid), limit)
    bounded = [grid[position] for position in positions]
    points, invalid = _curve_points(evaluate, bounded, value_field="value")
    if not points:
        return _unavailable(
            _DISTRIBUTION_COLUMNS,
            "the distribution curve is unavailable for the selected parameters",
            requested_points=len(grid),
            invalid_points=invalid,
        )
    low = _finite(shade_lower)
    high = _finite(shade_upper)
    rows = [
        {
            "x": round(position, 10),
            "value": round(value, 10),
            "shaded": _shaded(position, low, high),
        }
        for position, value in points
    ]
    marker_value = _finite(marker)
    return _evidence(
        "ok",
        pd.DataFrame(rows, columns=_DISTRIBUTION_COLUMNS),
        points=len(rows),
        requested_points=len(grid),
        truncated=len(bounded) < len(grid),
        invalid_points=invalid,
        marker=_round(marker_value, 10),
        marker_available=marker_value is not None,
        shade_lower=_round(low, 10),
        shade_upper=_round(high, 10),
        shaded_points=sum(1 for row in rows if row["shaded"]),
    )


def build_power_curve(
    evaluate: Callable[[float], Mapping[str, Any]],
    grid: Sequence[float],
    *,
    value_field: str = "power",
    selected: Any = None,
    max_points: int = POWER_CURVE_MAX_POINTS,
) -> dict[str, Any]:
    """Prepare a bounded power / required-sample-size curve for one varying parameter.

    ``evaluate`` is the existing closed-form power calculator supplied by the
    caller; no power formula is added or re-derived here. A parameter value the
    calculator reports as invalid or unavailable is skipped safely and counted,
    so an undefined point never becomes a plotted zero.
    """
    limit = max(2, _bounded_cap(max_points, POWER_CURVE_MAX_POINTS))
    positions = deterministic_positions(len(grid), limit)
    bounded = [grid[position] for position in positions]
    points, invalid = _curve_points(evaluate, bounded, value_field=value_field)
    if not points:
        return _unavailable(
            _POWER_COLUMNS,
            "the curve is unavailable for every value in the selected range",
            requested_points=len(grid),
            invalid_points=invalid,
        )
    rows = [
        {"parameter": round(position, 10), "value": round(value, 10)} for position, value in points
    ]
    selected_value = _finite(selected)
    return _evidence(
        "ok",
        pd.DataFrame(rows, columns=_POWER_COLUMNS),
        points=len(rows),
        requested_points=len(grid),
        truncated=len(bounded) < len(grid),
        invalid_points=invalid,
        value_field=str(value_field),
        selected=_round(selected_value, 10),
        selected_available=selected_value is not None,
    )


__all__ = [
    "CI_PLOT_MAX_ESTIMATES",
    "CONTINGENCY_MAX_CELLS",
    "CONTINGENCY_MAX_COLUMNS",
    "CONTINGENCY_MAX_ROWS",
    "CONTINGENCY_RANKED_CELL_LIMIT",
    "DISTRIBUTION_CURVE_MAX_POINTS",
    "GOF_MAX_CATEGORIES",
    "LABEL_MAX_TEXT",
    "PAIRED_LINE_DISPLAY_MAX",
    "PAIRED_PLOT_MAX_PAIRS",
    "POWER_CURVE_MAX_POINTS",
    "RESULT_CHART_MAX_ROWS",
    "SPARSE_EXPECTED_FLOOR",
    "build_contingency_evidence",
    "build_distribution_curve",
    "build_estimate_interval_evidence",
    "build_gof_evidence",
    "build_group_comparison_evidence",
    "build_paired_evidence",
    "build_parameter_grid",
    "build_power_curve",
    "build_proportion_evidence",
    "deterministic_positions",
    "safe_label",
]
