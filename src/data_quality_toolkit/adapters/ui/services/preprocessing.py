"""Preprocess Studio transform engine: deterministic, dependency-free apply helpers.

Streamlit-free, pandas/numpy only. Every ``apply_*`` copies its input first,
never mutates in place, handles missing columns and empty frames gracefully, and
returns ``(new_df, status)`` where ``status`` carries a recipe-step ``status``
plus an optional human-readable ``warning``. Replay dispatches through an
explicit, static lookup keyed by operation name — there is no ``eval``/``exec``/
``query`` or dynamic code generation, and no arbitrary user expressions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.services.preprocessing_calculations import CALC_DISPATCH
from data_quality_toolkit.application.workflow.preprocessing import (
    OP_DERIVED,
    OP_DROP_DUPLICATES,
    OP_ENCODING,
    OP_MISSING,
    OP_OUTLIER,
    OP_SCALING,
    OP_TYPE_CAST,
    STATUS_APPLIED,
    STATUS_ERROR,
    STATUS_SKIPPED,
    frame_facts,
    iqr_outlier_summary,
    output_collision_warning,
    output_collisions,
)

# Bounds (constants.py is read-only for this gate, so these live locally).
MAX_ONEHOT_CARDINALITY = 50
PREVIEW_ROWS = 50
LARGE_ROW_THRESHOLD = 100_000

# Recognised string tokens for safe, simple boolean casting.
_BOOL_TRUE = {"true", "t", "yes", "y", "1"}
_BOOL_FALSE = {"false", "f", "no", "n", "0"}

_DERIVED_DATETIME = ("year", "month", "day", "day_of_week")
_DERIVED_TEXT_LENGTH = "text_length"
_DERIVED_KINDS = frozenset(_DERIVED_DATETIME) | {_DERIVED_TEXT_LENGTH}

# Generated-destination naming rules. Declared once so recipe admission and
# execution can never disagree about the name a family will write.
_OUTLIER_FLAG_SUFFIX = "__outlier"
_ONE_HOT = "one_hot"
_ENCODING_SUFFIXES = {"frequency": "__freq", "label": "__label"}

StatusDict = dict[str, Any]
ApplyResult = tuple[pd.DataFrame, StatusDict]


# ── helpers ──────────────────────────────────────────────────────────────────


def _status(status: str, *, warning: str | None = None, detail: str | None = None) -> StatusDict:
    return {"status": status, "warning": warning, "detail": detail}


def _present_columns(df: pd.DataFrame, columns: Sequence[str]) -> tuple[list[str], list[str]]:
    present = [c for c in columns if c in df.columns]
    missing = [c for c in columns if c not in df.columns]
    return present, missing


def _join(warnings: Sequence[str]) -> str | None:
    return "; ".join(w for w in warnings if w) or None


def is_large_frame(df: pd.DataFrame) -> bool:
    """Return True when the frame is large enough to warrant a preview warning."""
    return int(len(df)) > LARGE_ROW_THRESHOLD


def preview_frame(df: pd.DataFrame, rows: int = PREVIEW_ROWS) -> pd.DataFrame:
    """Return a bounded head slice for safe in-UI preview rendering."""
    return df.head(rows)


def deterministic_output_names(
    operation: str,
    columns: Sequence[str],
    parameters: Mapping[str, Any],
) -> list[str]:
    """Return the create-only destinations a step will write, when they are knowable.

    Empty for in-place, row-only, unknown, and value-dependent operations: a
    one-hot expansion names its outputs after the categories actually present,
    so only execution can enumerate them. Recipe admission uses this to reserve
    what a recipe can prove statically without a frame; execution against the
    real frame stays authoritative.
    """
    params = dict(parameters or {})
    names = [str(column) for column in columns]
    if operation == OP_OUTLIER and str(params.get("strategy", "flag")) == "flag":
        return [f"{column}{_OUTLIER_FLAG_SUFFIX}" for column in names]
    if operation == OP_ENCODING:
        suffix = _ENCODING_SUFFIXES.get(str(params.get("strategy", _ONE_HOT)))
        return [f"{column}{suffix}" for column in names] if suffix else []
    if operation == OP_DERIVED:
        source = str(params.get("source_column") or (names[0] if names else ""))
        kind = str(params.get("derived_kind", ""))
        return [f"{source}__{kind}"] if source and kind in _DERIVED_KINDS else []
    return []


# ── transforms ───────────────────────────────────────────────────────────────


def _to_boolean(series: pd.Series) -> pd.Series:
    def convert(value: Any) -> Any:
        if pd.isna(value):
            return pd.NA
        token = str(value).strip().lower()
        if token in _BOOL_TRUE:
            return True
        if token in _BOOL_FALSE:
            return False
        return pd.NA

    return series.map(convert).astype("boolean")


def _cast_series(series: pd.Series, target_type: str) -> pd.Series | None:
    """Return *series* cast to *target_type*, or None for an unknown type."""
    if target_type == "numeric":
        return pd.to_numeric(series, errors="coerce")
    if target_type == "string":
        return series.astype("string")
    if target_type == "datetime":
        return pd.to_datetime(series, errors="coerce")
    if target_type == "boolean":
        return _to_boolean(series)
    return None


def apply_type_cast(
    df: pd.DataFrame,
    columns: Sequence[str],
    target_type: str,
    errors: str = "coerce",
) -> ApplyResult:
    """Cast selected columns to numeric/string/datetime/boolean; unparsed → null."""
    out = df.copy()
    present, missing = _present_columns(out, columns)
    if not present:
        return out, _status(STATUS_SKIPPED, warning=f"No target columns present: {missing}")
    warnings: list[str] = []
    if missing:
        warnings.append(f"skipped missing columns {missing}")
    for col in present:
        before_na = int(out[col].isna().sum())
        cast = _cast_series(out[col], target_type)
        if cast is None:
            return out, _status(STATUS_SKIPPED, warning=f"Unknown target_type '{target_type}'")
        new_na = int(cast.isna().sum()) - before_na
        if new_na > 0:
            warnings.append(f"{col}: {new_na} value(s) became null on cast")
        out[col] = cast
    return out, _status(STATUS_APPLIED, warning=_join(warnings))


def _fill_numeric(
    out: pd.DataFrame, present: Sequence[str], strategy: str, warnings: list[str]
) -> None:
    for col in present:
        if not pd.api.types.is_numeric_dtype(out[col]):
            warnings.append(f"{col}: {strategy} skipped (non-numeric)")
            continue
        value = out[col].mean() if strategy == "mean" else out[col].median()
        out[col] = out[col].fillna(value)


def _fill_mode(out: pd.DataFrame, present: Sequence[str], warnings: list[str]) -> None:
    for col in present:
        modes = out[col].mode(dropna=True)
        if modes.empty:
            warnings.append(f"{col}: mode skipped (no non-null values)")
            continue
        out[col] = out[col].fillna(modes.iloc[0])


def apply_missing_value_strategy(
    df: pd.DataFrame,
    columns: Sequence[str],
    strategy: str,
    fill_value: Any = None,
) -> ApplyResult:
    """Handle missing values via drop/mean/median/mode/constant on selected columns."""
    out = df.copy()
    present, missing = _present_columns(out, columns)
    if not present:
        return out, _status(STATUS_SKIPPED, warning=f"No target columns present: {missing}")
    warnings: list[str] = []
    if missing:
        warnings.append(f"skipped missing columns {missing}")
    if strategy == "drop":
        out = out.dropna(subset=present)
    elif strategy in {"mean", "median"}:
        _fill_numeric(out, present, strategy, warnings)
    elif strategy == "mode":
        _fill_mode(out, present, warnings)
    elif strategy == "constant":
        # fill_value is a plain value supplied by the user — never evaluated.
        for col in present:
            out[col] = out[col].fillna(fill_value)
    else:
        return out, _status(STATUS_SKIPPED, warning=f"Unknown strategy '{strategy}'")
    return out, _status(STATUS_APPLIED, warning=_join(warnings))


def apply_drop_duplicates(df: pd.DataFrame, subset: Sequence[str] | None = None) -> ApplyResult:
    """Drop exact duplicate rows, optionally keyed on a subset of columns."""
    out = df.copy()
    warnings: list[str] = []
    use_subset: list[str] | None = None
    if subset:
        present, missing = _present_columns(out, subset)
        if missing:
            warnings.append(f"ignored missing subset columns {missing}")
        use_subset = present or None
    before = len(out)
    out = out.drop_duplicates(subset=use_subset)
    removed = before - len(out)
    return out, _status(
        STATUS_APPLIED, warning=_join(warnings), detail=f"removed {removed} duplicate row(s)"
    )


def _iqr_summaries(
    out: pd.DataFrame, numeric_cols: Sequence[str], warnings: list[str]
) -> dict[str, Mapping[str, Any]]:
    """Return usable IQR bounds per column, warning about the ones without any.

    Computed up front so the flag destinations are known before anything is
    written. No strategy changes another column's bounds, so resolving them
    first is equivalent to resolving them inside the write loop.
    """
    summaries: dict[str, Mapping[str, Any]] = {}
    for col in numeric_cols:
        summary = iqr_outlier_summary(out, col)
        if summary is None:
            warnings.append(f"{col}: insufficient data for IQR")
            continue
        summaries[col] = summary
    return summaries


def _apply_iqr_columns(
    out: pd.DataFrame,
    summaries: Mapping[str, Mapping[str, Any]],
    strategy: str,
) -> pd.DataFrame:
    """Apply the chosen IQR strategy across columns with usable bounds."""
    remove_mask = pd.Series(False, index=out.index)
    for col, summary in summaries.items():
        lower, upper = summary["lower_fence"], summary["upper_fence"]
        out_of_bounds = ((out[col] < lower) | (out[col] > upper)).fillna(False)
        if strategy == "flag":
            out[f"{col}{_OUTLIER_FLAG_SUFFIX}"] = out_of_bounds
        elif strategy == "clip":
            out[col] = out[col].clip(lower=lower, upper=upper)
        else:  # remove
            remove_mask = remove_mask | out_of_bounds
    return out[~remove_mask] if strategy == "remove" else out


def apply_iqr_outlier_strategy(
    df: pd.DataFrame,
    columns: Sequence[str],
    strategy: str,
) -> ApplyResult:
    """Flag, clip, or remove IQR outliers on selected numeric columns.

    ``flag`` creates ``{column}__outlier``; every such destination is checked
    against the frame before any of them is written, so a collision refuses the
    whole step and leaves the existing column untouched. ``clip`` rewrites its
    own selected column and ``remove`` drops rows, so neither creates a
    destination that could collide.
    """
    out = df.copy()
    present, missing = _present_columns(out, columns)
    if not present:
        return out, _status(STATUS_SKIPPED, warning=f"No target columns present: {missing}")
    if strategy not in {"flag", "clip", "remove"}:
        return out, _status(STATUS_SKIPPED, warning=f"Unknown strategy '{strategy}'")
    warnings: list[str] = []
    if missing:
        warnings.append(f"skipped missing columns {missing}")
    numeric_cols = [c for c in present if pd.api.types.is_numeric_dtype(out[c])]
    non_numeric = [c for c in present if c not in numeric_cols]
    if non_numeric:
        warnings.append(f"skipped non-numeric columns {non_numeric}")
    if not numeric_cols:
        return out, _status(STATUS_SKIPPED, warning=_join(warnings) or "no numeric columns")
    summaries = _iqr_summaries(out, numeric_cols, warnings)
    refused = (
        output_collisions(out.columns, [f"{col}{_OUTLIER_FLAG_SUFFIX}" for col in summaries])
        if strategy == "flag"
        else []
    )
    if refused:
        return out, _status(STATUS_ERROR, warning=output_collision_warning(refused))
    out = _apply_iqr_columns(out, summaries, strategy)
    return out, _status(STATUS_APPLIED, warning=_join(warnings))


def _one_hot_columns(
    out: pd.DataFrame,
    present: Sequence[str],
    max_cardinality: int,
    warnings: list[str],
) -> list[str]:
    """Return the columns within the cardinality bound; skip+warn over it."""
    encode_cols: list[str] = []
    for col in present:
        card = int(out[col].nunique(dropna=True))
        if card > max_cardinality:
            warnings.append(f"{col}: skipped one-hot (cardinality {card} > {max_cardinality})")
            continue
        encode_cols.append(col)
    return encode_cols


def _one_hot_destinations(out: pd.DataFrame, encode_cols: Sequence[str]) -> list[str]:
    """Return the dummy names expanding *encode_cols* would emit, values included.

    Derived from the real expansion of just those columns, so the candidate set
    can never drift from what ``pd.get_dummies`` actually produces - and a name
    two different sources would both emit appears twice, as it must.
    """
    if not encode_cols:
        return []
    cols = list(encode_cols)
    dummies = pd.get_dummies(out[cols], columns=cols, prefix=cols)
    return [str(name) for name in dummies.columns]


def _apply_one_hot(
    out: pd.DataFrame,
    present: Sequence[str],
    max_cardinality: int,
    warnings: list[str],
) -> tuple[pd.DataFrame | None, list[str]]:
    """Expand one-hot dummies, or return the destinations that refuse the write."""
    encode_cols = _one_hot_columns(out, present, max_cardinality, warnings)
    # The expansion consumes its own source columns, so those names are the one
    # thing it is entitled to replace.
    refused = output_collisions(
        out.columns, _one_hot_destinations(out, encode_cols), replaces=encode_cols
    )
    if refused:
        return None, refused
    if encode_cols:
        out = pd.get_dummies(out, columns=encode_cols, prefix=encode_cols)
    return out, []


def _encode_frequency(out: pd.DataFrame, present: Sequence[str]) -> pd.DataFrame:
    suffix = _ENCODING_SUFFIXES["frequency"]
    for col in present:
        counts = out[col].value_counts(dropna=True)
        out[f"{col}{suffix}"] = out[col].map(counts).fillna(0).astype(int)
    return out


def _encode_label(out: pd.DataFrame, present: Sequence[str]) -> pd.DataFrame:
    suffix = _ENCODING_SUFFIXES["label"]
    for col in present:
        categories = sorted({str(v) for v in out[col].dropna().unique()})
        mapping = {cat: idx for idx, cat in enumerate(categories)}
        out[f"{col}{suffix}"] = out[col].astype("string").map(mapping).astype("Int64")
    return out


def _apply_suffix_encoding(
    out: pd.DataFrame, present: Sequence[str], strategy: str
) -> tuple[pd.DataFrame | None, list[str]]:
    """Write every ``{column}__freq`` / ``{column}__label``, or refuse them all."""
    suffix = _ENCODING_SUFFIXES[strategy]
    refused = output_collisions(out.columns, [f"{col}{suffix}" for col in present])
    if refused:
        return None, refused
    encode = _encode_frequency if strategy == "frequency" else _encode_label
    return encode(out, present), []


def apply_encoding(
    df: pd.DataFrame,
    columns: Sequence[str],
    strategy: str,
    max_cardinality: int = MAX_ONEHOT_CARDINALITY,
) -> ApplyResult:
    """Encode categorical columns via one-hot / frequency / label (deterministic).

    Every destination the chosen strategy would emit is checked against the
    frame first, so a collision with an unrelated existing column - or between
    two generated names - refuses the whole step and writes nothing.
    """
    out = df.copy()
    present, missing = _present_columns(out, columns)
    if not present:
        return out, _status(STATUS_SKIPPED, warning=f"No target columns present: {missing}")
    if strategy != _ONE_HOT and strategy not in _ENCODING_SUFFIXES:
        return out, _status(STATUS_SKIPPED, warning=f"Unknown strategy '{strategy}'")
    warnings: list[str] = []
    if missing:
        warnings.append(f"skipped missing columns {missing}")
    if strategy == _ONE_HOT:
        encoded, refused = _apply_one_hot(out, present, max_cardinality, warnings)
    else:
        encoded, refused = _apply_suffix_encoding(out, present, strategy)
    if encoded is None:
        return out, _status(STATUS_ERROR, warning=output_collision_warning(refused))
    return encoded, _status(STATUS_APPLIED, warning=_join(warnings))


def apply_scaling(df: pd.DataFrame, columns: Sequence[str], strategy: str) -> ApplyResult:
    """Scale numeric columns via min-max or z-score; zero-variance → 0."""
    out = df.copy()
    present, missing = _present_columns(out, columns)
    if not present:
        return out, _status(STATUS_SKIPPED, warning=f"No target columns present: {missing}")
    if strategy not in {"minmax", "zscore"}:
        return out, _status(STATUS_SKIPPED, warning=f"Unknown strategy '{strategy}'")
    warnings: list[str] = []
    if missing:
        warnings.append(f"skipped missing columns {missing}")
    for col in present:
        if not pd.api.types.is_numeric_dtype(out[col]):
            warnings.append(f"{col}: skipped (non-numeric)")
            continue
        series = out[col].astype(float)
        if strategy == "minmax":
            cmin, cmax = series.min(), series.max()
            span = cmax - cmin
            if pd.isna(span) or span == 0:
                out[col] = 0.0
                warnings.append(f"{col}: zero variance → set to 0")
            else:
                out[col] = (series - cmin) / span
        else:  # zscore
            mean, std = series.mean(), series.std(ddof=0)
            if pd.isna(std) or std == 0:
                out[col] = 0.0
                warnings.append(f"{col}: zero variance → set to 0")
            else:
                out[col] = (series - mean) / std
    return out, _status(STATUS_APPLIED, warning=_join(warnings))


def apply_safe_derived_column(
    df: pd.DataFrame,
    source_column: str,
    derived_kind: str,
) -> ApplyResult:
    """Add a safe derived column (datetime parts or text length). No free-form formulas.

    The destination ``{source}__{kind}`` is resolved and checked before any
    parsing or assignment, so an existing column of that name is never replaced.
    """
    out = df.copy()
    if source_column not in out.columns:
        return out, _status(STATUS_SKIPPED, warning=f"Source column '{source_column}' not present")
    if derived_kind not in _DERIVED_KINDS:
        return out, _status(STATUS_SKIPPED, warning=f"Unknown derived_kind '{derived_kind}'")
    target = f"{source_column}__{derived_kind}"
    refused = output_collisions(out.columns, [target])
    if refused:
        return out, _status(STATUS_ERROR, warning=output_collision_warning(refused))
    series = out[source_column]
    if derived_kind == _DERIVED_TEXT_LENGTH:
        out[target] = series.astype("string").str.len().astype("Int64")
        return out, _status(STATUS_APPLIED)
    parsed = pd.to_datetime(series, errors="coerce")
    if int(parsed.notna().sum()) == 0:
        return out, _status(STATUS_SKIPPED, warning=f"{source_column}: no parseable datetimes")
    part = {
        "year": parsed.dt.year,
        "month": parsed.dt.month,
        "day": parsed.dt.day,
        "day_of_week": parsed.dt.dayofweek,
    }[derived_kind]
    out[target] = part.astype("Int64")
    return out, _status(STATUS_APPLIED)


# ── replay evidence contract ─────────────────────────────────────────────────

# The two statuses ``apply_recipe`` records for a step that ran to completion.
# ``skipped`` belongs here: the engine records why the step did not apply, the
# durable recipe carries that verdict, and the confirmation vocabulary admits it.
# ``error`` never belongs here — the operation did not happen.
_COMPLETED_STATUSES = frozenset({STATUS_APPLIED, STATUS_SKIPPED})

# Fixed refusal codes. None interpolates a path, column, parameter, or any other
# authored value, so a refusal is safe to surface and to persist verbatim.
REPLAY_OK = ""
REPLAY_FAILED = "REPLAY_FAILED"
REPLAY_INCOMPLETE = "REPLAY_INCOMPLETE"
REPLAY_EVIDENCE_INVALID = "REPLAY_EVIDENCE_INVALID"


def _step_identity(step: Mapping[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    """Return the stable fields tying one execution record to its authored step."""
    return (
        str(step.get("step_id") or ""),
        str(step.get("operation", "")),
        tuple(str(column) for column in (step.get("columns") or [])),
    )


def replay_refusal_code(authored_steps: Any, executed_steps: Any) -> str:
    """Return ``REPLAY_OK`` only when evidence proves a complete, successful replay.

    ``executed_steps`` must be what :func:`apply_recipe` returned for
    ``authored_steps``: one record per authored step, in recipe order, each
    naming the same step and each reporting a status the engine only records for
    an operation that ran to completion. A missing, extra, reordered,
    substituted, errored, or unrecognised record is refused. A partial replay is
    never a successful one, so this is the single predicate both confirmation
    paths ask before anything durable is written.
    """
    if not isinstance(authored_steps, list | tuple) or not authored_steps:
        return REPLAY_EVIDENCE_INVALID
    if not isinstance(executed_steps, list | tuple) or not executed_steps:
        return REPLAY_EVIDENCE_INVALID
    if len(executed_steps) != len(authored_steps):
        return REPLAY_INCOMPLETE
    for authored, executed in zip(authored_steps, executed_steps, strict=True):
        if not isinstance(authored, Mapping) or not isinstance(executed, Mapping):
            return REPLAY_EVIDENCE_INVALID
        if _step_identity(executed) != _step_identity(authored):
            return REPLAY_INCOMPLETE
        status = executed.get("status")
        if status == STATUS_ERROR:
            return REPLAY_FAILED
        if status not in _COMPLETED_STATUSES:
            return REPLAY_EVIDENCE_INVALID
    return REPLAY_OK


# ── replay engine ────────────────────────────────────────────────────────────


def _dispatch_step(
    df: pd.DataFrame,
    operation: str,
    columns: Sequence[str],
    parameters: Mapping[str, Any],
) -> ApplyResult:
    """Route a single step to its transform via an explicit, static lookup."""
    params = dict(parameters or {})
    if operation == OP_TYPE_CAST:
        return apply_type_cast(
            df,
            columns,
            str(params.get("target_type", "")),
            errors=str(params.get("errors", "coerce")),
        )
    if operation == OP_MISSING:
        return apply_missing_value_strategy(
            df, columns, str(params.get("strategy", "")), fill_value=params.get("fill_value")
        )
    if operation == OP_DROP_DUPLICATES:
        return apply_drop_duplicates(df, subset=params.get("subset") or list(columns) or None)
    if operation == OP_OUTLIER:
        return apply_iqr_outlier_strategy(df, columns, str(params.get("strategy", "flag")))
    if operation == OP_ENCODING:
        return apply_encoding(
            df,
            columns,
            str(params.get("strategy", "one_hot")),
            max_cardinality=int(params.get("max_cardinality", MAX_ONEHOT_CARDINALITY)),
        )
    if operation == OP_SCALING:
        return apply_scaling(df, columns, str(params.get("strategy", "minmax")))
    if operation == OP_DERIVED:
        source = params.get("source_column") or (columns[0] if columns else "")
        return apply_safe_derived_column(df, str(source), str(params.get("derived_kind", "")))
    calc = CALC_DISPATCH.get(operation)
    if calc is not None:
        # Calculated-column transforms read their inputs from ``parameters`` and
        # share the same ``(new_df, status)`` contract as the transforms above.
        return calc(df, params)
    return df.copy(), _status(STATUS_SKIPPED, warning=f"Unknown operation '{operation}'")


def apply_recipe(
    df: pd.DataFrame,
    recipe_steps: Sequence[Mapping[str, Any]],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Replay recipe steps in order against a copy of *df*.

    Returns ``(final_df, executed_steps)``. Each executed step is a *copy* of the
    input step enriched with before/after facts, a resolved ``status``, and any
    warning — the input steps are never mutated. The replay never raises: an
    operation that errors is marked ``error`` and replay continues with the
    pre-step frame.
    """
    current = df.copy()
    executed: list[dict[str, Any]] = []
    for raw in recipe_steps:
        step = dict(raw)
        operation = str(step.get("operation", ""))
        columns = list(step.get("columns") or [])
        parameters = dict(step.get("parameters") or {})
        before_df = current
        step["before"] = frame_facts(before_df)
        try:
            result_df, status = _dispatch_step(before_df, operation, columns, parameters)
        except Exception as exc:  # noqa: BLE001 - replay must never raise
            step["status"] = STATUS_ERROR
            step["warning"] = f"{type(exc).__name__}: {exc}"
            step["after"] = step["before"]
            executed.append(step)
            continue
        step["status"] = status.get("status", STATUS_APPLIED)
        step["warning"] = _join([status.get("warning") or "", status.get("detail") or ""])
        step["after"] = frame_facts(result_df)
        current = result_df
        executed.append(step)
    return current, executed
