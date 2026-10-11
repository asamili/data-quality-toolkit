"""Safe, non-eval calculated-column transforms for Preprocess Studio.

Extends the recipe engine with column arithmetic, scalar operations,
conditional columns, numeric binning, and string operations. Every function
copies its input first, never mutates in place, resolves an explicit output
column (a new column by default, an existing one only when the caller opts in),
and returns the same ``(new_df, status)`` contract as ``services.preprocessing``.

No ``eval``/``exec``/``query`` or arbitrary user expressions are used anywhere:
each operation is chosen from a fixed enum and dispatched through explicit
branches. Invalid numeric conversions coerce to null rather than raising, and
divide-by-zero produces null (never an exception).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from data_quality_toolkit.application.workflow.preprocessing import (
    STATUS_APPLIED,
    STATUS_SKIPPED,
    output_collisions,
)

# Operation identifiers (UI-layer only; kept out of the read-only workflow module).
OP_CALC_ARITHMETIC = "calc_arithmetic"
OP_CALC_SCALAR = "calc_scalar"
OP_CALC_CONDITIONAL = "calc_conditional"
OP_CALC_BINNING = "calc_binning"
OP_CALC_STRING = "calc_string"

CALC_OPERATIONS: frozenset[str] = frozenset(
    {
        OP_CALC_ARITHMETIC,
        OP_CALC_SCALAR,
        OP_CALC_CONDITIONAL,
        OP_CALC_BINNING,
        OP_CALC_STRING,
    }
)

MIN_BINS = 2
MAX_BINS = 50

_ARITHMETIC_OPS = frozenset({"add", "subtract", "multiply", "divide", "power"})
_SCALAR_OPS = frozenset({"add", "subtract", "multiply", "divide", "power", "round"})
_POWER_CONSTANT_ROLES = frozenset({"exponent", "base"})
_COMPARATORS = frozenset({"==", "!=", ">", ">=", "<", "<="})
_ORDERED_COMPARATORS = frozenset({">", ">=", "<", "<="})
_STRING_OPS = frozenset({"upper", "lower", "strip", "length", "replace", "concat"})

_INF = [float("inf"), float("-inf")]

StatusDict = dict[str, Any]
ApplyResult = tuple[pd.DataFrame, StatusDict]


# ── helpers ──────────────────────────────────────────────────────────────────


def _status(status: str, *, warning: str | None = None, detail: str | None = None) -> StatusDict:
    return {"status": status, "warning": warning, "detail": detail}


def _join(warnings: Sequence[str]) -> str | None:
    return "; ".join(w for w in warnings if w) or None


def _resolve_output(
    df: pd.DataFrame, params: Mapping[str, Any], default_name: str
) -> tuple[str | None, str | None]:
    """Resolve the destination column: new by default, existing only on opt-in.

    Returns ``(column_name, error)``. Existing mode requires a real column that
    is present so an accidental overwrite of a missing target is impossible.
    The default mode asks the shared output-destination policy, so calculated
    columns and every other family answer to one collision rule.
    """
    mode = str(params.get("output_mode", "new")).strip().lower()
    name = str(params.get("output_column") or "").strip()
    if mode == "existing":
        # The established explicit-overwrite contract: the operator named this
        # exact destination, so the policy permits it rather than refusing it.
        if not name:
            return None, "no existing target column selected"
        if name not in df.columns:
            return None, f"target column '{name}' not present"
        return name, None
    target = name or default_name
    if output_collisions(df.columns, [target]):
        return (
            None,
            f"output column '{target}' already exists; use explicit overwrite mode to replace it",
        )
    return target, None


def _power_result(base: pd.Series, exponent: pd.Series) -> tuple[pd.Series, str | None]:
    """Return real-valued ``base ** exponent`` with invalid/non-finite rows nulled."""
    base_values = base.astype("float64").to_numpy()
    exponent_values = exponent.astype("float64").to_numpy()
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        values = np.power(base_values, exponent_values)
    invalid_mask = ~np.isfinite(values)
    result = pd.Series(values, index=base.index, dtype="float64")
    invalid_count = int(invalid_mask.sum())
    if invalid_count:
        result = result.mask(invalid_mask)
        return result, f"{invalid_count} invalid or non-finite power result(s) set to null"
    return result, None


def _scalar_result(
    series: pd.Series, operator: str, scalar: float, *, constant_role: str = "exponent"
) -> tuple[pd.Series | None, str | None, str | None]:
    """Return ``(result, warning, error)`` for one scalar operator."""
    if operator == "add":
        return series + scalar, None, None
    if operator == "subtract":
        return series - scalar, None, None
    if operator == "multiply":
        return series * scalar, None, None
    if operator == "divide":
        if scalar == 0:
            return None, None, "divide by zero scalar"
        return series / scalar, None, None
    if operator == "power":
        constant = pd.Series(scalar, index=series.index, dtype="float64")
        if constant_role == "base":
            result, warning = _power_result(constant, series)
        else:
            result, warning = _power_result(series, constant)
        return result, warning, None
    return series.round(int(scalar)), None, None


# ── transforms ───────────────────────────────────────────────────────────────


def apply_arithmetic(df: pd.DataFrame, params: Mapping[str, Any]) -> ApplyResult:
    """Compute ``left <op> right`` between two columns (add/subtract/multiply/divide)."""
    out = df.copy()
    left = str(params.get("left_column") or "")
    right = str(params.get("right_column") or "")
    operator = str(params.get("operator") or "")
    missing = [c for c in (left, right) if c not in out.columns]
    if missing:
        return out, _status(STATUS_SKIPPED, warning=f"missing column(s): {missing}")
    if operator not in _ARITHMETIC_OPS:
        return out, _status(STATUS_SKIPPED, warning=f"unknown operator '{operator}'")
    target, err = _resolve_output(out, params, f"{left}__{operator}__{right}")
    if err is not None:
        return out, _status(STATUS_SKIPPED, warning=err)
    left_num = pd.to_numeric(out[left], errors="coerce")
    right_num = pd.to_numeric(out[right], errors="coerce")
    warnings: list[str] = []
    if operator == "add":
        result = left_num + right_num
    elif operator == "subtract":
        result = left_num - right_num
    elif operator == "multiply":
        result = left_num * right_num
    elif operator == "divide":
        zero_rows = int((right_num == 0).sum())
        if zero_rows:
            warnings.append(f"{zero_rows} divide-by-zero row(s) set to null")
        result = left_num / right_num.mask(right_num == 0)
    else:  # power
        result, warning = _power_result(left_num, right_num)
        if warning:
            warnings.append(warning)
    result = result.replace(_INF, pd.NA)
    out[target] = result
    return out, _status(STATUS_APPLIED, warning=_join(warnings), detail=f"wrote '{target}'")


def apply_scalar(df: pd.DataFrame, params: Mapping[str, Any]) -> ApplyResult:
    """Apply a scalar op (add/subtract/multiply/divide/round) to one numeric column."""
    out = df.copy()
    source = str(params.get("source_column") or "")
    operator = str(params.get("operator") or "")
    if source not in out.columns:
        return out, _status(STATUS_SKIPPED, warning=f"source column '{source}' not present")
    if operator not in _SCALAR_OPS:
        return out, _status(STATUS_SKIPPED, warning=f"unknown operator '{operator}'")
    try:
        scalar = float(params.get("scalar"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return out, _status(STATUS_SKIPPED, warning="invalid scalar value")
    target, err = _resolve_output(out, params, f"{source}__{operator}")
    if err is not None:
        return out, _status(STATUS_SKIPPED, warning=err)
    series = pd.to_numeric(out[source], errors="coerce")
    constant_role = "exponent"
    if operator == "power":
        constant_role = str(params.get("constant_role", "exponent") or "exponent").strip().lower()
        if constant_role not in _POWER_CONSTANT_ROLES:
            return out, _status(STATUS_SKIPPED, warning=f"unknown constant_role '{constant_role}'")
    result, warning, op_err = _scalar_result(series, operator, scalar, constant_role=constant_role)
    if op_err is not None or result is None:
        return out, _status(STATUS_SKIPPED, warning=op_err or "scalar operation failed")
    result = result.replace(_INF, pd.NA)
    out[target] = result
    return out, _status(
        STATUS_APPLIED,
        warning=warning if operator == "power" else None,
        detail=f"wrote '{target}'",
    )


def _build_condition_mask(
    column: pd.Series, comparator: str, raw_value: Any
) -> tuple[pd.Series | None, str | None]:
    """Return ``(boolean_mask, error)`` for a source column and comparator.

    Ordered comparators (``>``/``>=``/``<``/``<=``) require a numeric value;
    equality comparators fall back to a string comparison when the value or
    column is not numeric.
    """
    if comparator in _ORDERED_COMPARATORS:
        column_num = pd.to_numeric(column, errors="coerce")
        try:
            compare_num = float("" if raw_value is None else raw_value)
        except (TypeError, ValueError):
            return None, "comparison value must be numeric for this comparator"
        ordered = {
            ">": column_num > compare_num,
            ">=": column_num >= compare_num,
            "<": column_num < compare_num,
            "<=": column_num <= compare_num,
        }
        return ordered[comparator], None
    compare_text = "" if raw_value is None else str(raw_value)
    compare_cast: Any = compare_text
    left = column.astype("string")
    if pd.api.types.is_numeric_dtype(column):
        try:
            compare_cast = float(compare_text)
            left = pd.to_numeric(column, errors="coerce")
        except ValueError:
            compare_cast = compare_text
            left = column.astype("string")
    mask = left == compare_cast if comparator == "==" else left != compare_cast
    return mask, None


def apply_conditional(df: pd.DataFrame, params: Mapping[str, Any]) -> ApplyResult:
    """Build a column: ``result_value`` where ``source <comparator> value`` else fallback."""
    out = df.copy()
    source = str(params.get("source_column") or "")
    comparator = str(params.get("comparator") or "")
    if source not in out.columns:
        return out, _status(STATUS_SKIPPED, warning=f"source column '{source}' not present")
    if comparator not in _COMPARATORS:
        return out, _status(STATUS_SKIPPED, warning=f"unknown comparator '{comparator}'")
    target, err = _resolve_output(out, params, f"{source}__flag")
    if err is not None:
        return out, _status(STATUS_SKIPPED, warning=err)
    mask, mask_err = _build_condition_mask(out[source], comparator, params.get("compare_value"))
    if mask_err is not None or mask is None:
        return out, _status(STATUS_SKIPPED, warning=mask_err or "could not evaluate condition")
    out[target] = pd.Series(params.get("result_value"), index=out.index).where(
        mask.fillna(False), params.get("fallback_value")
    )
    return out, _status(STATUS_APPLIED, detail=f"wrote '{target}'")


def apply_binning(df: pd.DataFrame, params: Mapping[str, Any]) -> ApplyResult:
    """Assign equal-width bin labels for a numeric column via ``pd.cut``."""
    out = df.copy()
    source = str(params.get("source_column") or "")
    if source not in out.columns:
        return out, _status(STATUS_SKIPPED, warning=f"source column '{source}' not present")
    try:
        requested = int(params.get("num_bins", 4))
    except (TypeError, ValueError):
        return out, _status(STATUS_SKIPPED, warning="invalid bin count")
    bins = min(max(requested, MIN_BINS), MAX_BINS)
    target, err = _resolve_output(out, params, f"{source}__bin")
    if err is not None:
        return out, _status(STATUS_SKIPPED, warning=err)
    series = pd.to_numeric(out[source], errors="coerce").replace(_INF, pd.NA)
    if series.dropna().nunique() < 2:
        return out, _status(STATUS_SKIPPED, warning="insufficient distinct numeric values to bin")
    try:
        binned = pd.cut(series, bins=bins, duplicates="drop")
    except (ValueError, TypeError) as exc:
        return out, _status(STATUS_SKIPPED, warning=f"binning failed: {exc}")
    out[target] = binned.astype("string")
    return out, _status(STATUS_APPLIED, detail=f"wrote '{target}' with up to {bins} bins")


_SIMPLE_STRING_OPS = {
    "upper": lambda series: series.str.upper(),
    "lower": lambda series: series.str.lower(),
    "strip": lambda series: series.str.strip(),
    "length": lambda series: series.str.len().astype("Int64"),
}


def _string_replace(
    series: pd.Series, params: Mapping[str, Any]
) -> tuple[pd.Series | None, str | None]:
    find = "" if params.get("find") is None else str(params.get("find"))
    replacement = "" if params.get("replace") is None else str(params.get("replace"))
    if find == "":
        return None, "replace requires a non-empty search string"
    # regex=False keeps this a literal, injection-free substitution.
    return series.str.replace(find, replacement, regex=False), None


def _string_concat(series: pd.Series, df: pd.DataFrame, params: Mapping[str, Any]) -> pd.Series:
    result = series.fillna("")
    other = params.get("other_column")
    if other and str(other) in df.columns:
        result = result.str.cat(df[str(other)].astype("string").fillna(""))
    literal = params.get("literal")
    if literal:
        result = result + str(literal)
    return result


def apply_string_op(df: pd.DataFrame, params: Mapping[str, Any]) -> ApplyResult:
    """Apply a string transform (upper/lower/strip/length/replace/concat)."""
    out = df.copy()
    source = str(params.get("source_column") or "")
    operation = str(params.get("operation") or "")
    if source not in out.columns:
        return out, _status(STATUS_SKIPPED, warning=f"source column '{source}' not present")
    if operation not in _STRING_OPS:
        return out, _status(STATUS_SKIPPED, warning=f"unknown string operation '{operation}'")
    target, err = _resolve_output(out, params, f"{source}__{operation}")
    if err is not None:
        return out, _status(STATUS_SKIPPED, warning=err)
    series = out[source].astype("string")
    simple = _SIMPLE_STRING_OPS.get(operation)
    if simple is not None:
        result = simple(series)
    elif operation == "replace":
        result, replace_err = _string_replace(series, params)
        if replace_err is not None or result is None:
            return out, _status(STATUS_SKIPPED, warning=replace_err or "replace failed")
    else:  # concat
        result = _string_concat(series, out, params)
    out[target] = result
    return out, _status(STATUS_APPLIED, detail=f"wrote '{target}'")


# Operation identifier -> transform. Consumed by the recipe dispatcher.
CALC_DISPATCH = {
    OP_CALC_ARITHMETIC: apply_arithmetic,
    OP_CALC_SCALAR: apply_scalar,
    OP_CALC_CONDITIONAL: apply_conditional,
    OP_CALC_BINNING: apply_binning,
    OP_CALC_STRING: apply_string_op,
}
