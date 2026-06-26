"""Preprocessing planner: per-column issue detection and transformation recommendations.

This module also defines the dependency-free *recipe model* used by the
Preprocess Studio apply workflow: a serializable per-step structure plus
before/after summary helpers. The transform engine that executes steps lives in
``adapters/ui/services/preprocessing.py``; the model stays here because it is
pure data (no Streamlit, pandas/numpy only) and conceptually part of the
preprocessing workflow.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from data_quality_toolkit.shared.constants import DEFAULT_HIGH_CARDINALITY_THRESHOLD


def iqr_outlier_summary(df: pd.DataFrame, col: str) -> dict[str, Any] | None:
    """Return IQR-based outlier stats. None if non-numeric or fewer than 4 non-null values."""
    series = df[col].dropna()
    if not pd.api.types.is_numeric_dtype(series) or len(series) < 4:
        return None
    qs = series.quantile([0.25, 0.75])
    q1 = float(qs.iloc[0])
    q3 = float(qs.iloc[1])
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    outliers = int(((series < lower) | (series > upper)).sum())
    return {
        "q1": q1,
        "q3": q3,
        "iqr": iqr,
        "lower_fence": lower,
        "upper_fence": upper,
        "outlier_count": outliers,
    }


def plan_preprocessing(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Return per-column preprocessing recommendation rows derived from the DataFrame."""
    rows = len(df)
    plan: list[dict[str, Any]] = []
    for col in df.columns:
        s = df[col]
        is_num = pd.api.types.is_numeric_dtype(s)
        null_pct = float(s.isna().mean())
        unique_ratio = s.nunique() / rows if rows > 0 else 0.0

        issues: list[str] = []
        recs: list[str] = []

        if null_pct > 0.5:
            issues.append(f"high nulls ({null_pct:.0%})")
            recs.append("drop or flag column")
        elif null_pct > 0:
            issues.append(f"nulls ({null_pct:.0%})")
            recs.append("impute with median" if is_num else "impute with mode or 'Unknown'")

        if not is_num and unique_ratio > DEFAULT_HIGH_CARDINALITY_THRESHOLD:
            issues.append(f"high cardinality ({unique_ratio:.0%} unique)")
            recs.append("drop or hash-encode")

        if is_num:
            iqr = iqr_outlier_summary(df, col)
            if iqr is not None and iqr["outlier_count"] > 0:
                issues.append(f"{iqr['outlier_count']} IQR outlier(s)")
                recs.append("consider outlier treatment")
            recs.append("consider scaling")
        elif unique_ratio <= DEFAULT_HIGH_CARDINALITY_THRESHOLD:
            recs.append("label or one-hot encode")

        plan.append(
            {
                "column": col,
                "dtype": str(s.dtype),
                "issues": ", ".join(issues) if issues else "none",
                "recommendations": ", ".join(recs) if recs else "none",
            }
        )
    return plan


# ---------------------------------------------------------------------------
# Recipe model (Preprocess Studio apply workflow)
# ---------------------------------------------------------------------------

RECIPE_SCHEMA_VERSION = "1"

# Recipe-step lifecycle status values.
STATUS_PENDING = "pending"
STATUS_APPLIED = "applied"
STATUS_SKIPPED = "skipped"
STATUS_ERROR = "error"

# Supported operation identifiers. Kept as plain strings so recipes are JSON
# serializable and dispatch happens through an explicit, static lookup (never
# eval/exec or dynamic code generation).
OP_TYPE_CAST = "type_cast"
OP_MISSING = "missing_value"
OP_DROP_DUPLICATES = "drop_duplicates"
OP_OUTLIER = "iqr_outlier"
OP_ENCODING = "encoding"
OP_SCALING = "scaling"
OP_DERIVED = "derived_column"

SUPPORTED_OPERATIONS = (
    OP_TYPE_CAST,
    OP_MISSING,
    OP_DROP_DUPLICATES,
    OP_OUTLIER,
    OP_ENCODING,
    OP_SCALING,
    OP_DERIVED,
)


def _step_fingerprint(operation: str, columns: Sequence[str], parameters: Mapping[str, Any]) -> str:
    """Return a short, deterministic id for a step from its content (no eval)."""
    payload = json.dumps(
        {"operation": operation, "columns": list(columns), "parameters": dict(parameters)},
        sort_keys=True,
        default=str,
    )
    # Non-security use: a short, stable content id for a recipe step.
    return hashlib.sha1(payload.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def make_recipe_step(
    operation: str,
    columns: Sequence[Any] | None = None,
    parameters: Mapping[str, Any] | None = None,
    *,
    step_id: str | None = None,
) -> dict[str, Any]:
    """Build a single, serializable preprocessing recipe step.

    The returned dict carries the operation, target columns, parameters, a
    deterministic ``step_id``, lifecycle ``status`` (initially ``pending``), and
    placeholders for the before/after summaries and any skip/error warning. The
    step is plain data — replaying it executes only safe, named operations.
    """
    cols = [str(c) for c in (columns or [])]
    params = dict(parameters or {})
    sid = step_id or f"step-{_step_fingerprint(operation, cols, params)}"
    return {
        "step_id": sid,
        "operation": str(operation),
        "columns": cols,
        "parameters": params,
        "before": None,
        "after": None,
        "status": STATUS_PENDING,
        "warning": None,
    }


def frame_facts(df: pd.DataFrame) -> dict[str, Any]:
    """Return bounded, serializable shape/quality facts for a DataFrame."""
    rows = int(len(df))
    cols = int(df.shape[1])
    total_cells = rows * cols
    missing = int(df.isna().sum().sum()) if cols else 0
    duplicate = int(df.duplicated().sum()) if rows else 0
    completeness = round(1.0 - (missing / total_cells), 4) if total_cells else 1.0
    missing_pct = round((missing / total_cells) * 100, 4) if total_cells else 0.0
    return {
        "row_count": rows,
        "column_count": cols,
        "missing_cells": missing,
        "missing_pct": missing_pct,
        "duplicate_rows": duplicate,
        "completeness": completeness,
    }


def summarize_before_after(before_df: pd.DataFrame, after_df: pd.DataFrame) -> dict[str, Any]:
    """Compare two DataFrames and return a bounded before/after validation summary."""
    before_dtypes = {str(c): str(t) for c, t in before_df.dtypes.items()}
    after_dtypes = {str(c): str(t) for c, t in after_df.dtypes.items()}
    dtype_changes = {
        col: {"from": before_dtypes[col], "to": after_dtypes[col]}
        for col in before_dtypes
        if col in after_dtypes and before_dtypes[col] != after_dtypes[col]
    }
    added = [c for c in after_dtypes if c not in before_dtypes]
    removed = [c for c in before_dtypes if c not in after_dtypes]
    return {
        "before": frame_facts(before_df),
        "after": frame_facts(after_df),
        "dtype_changes": dtype_changes,
        "added_columns": added,
        "removed_columns": removed,
    }


def recipe_to_json_payload(
    recipe_steps: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a JSON-serializable export payload for a recipe and its summary.

    Deterministic by design: no timestamps or environment values are embedded,
    so identical recipes serialize identically (and stay test-stable).
    """
    return {
        "schema_version": RECIPE_SCHEMA_VERSION,
        "steps": [dict(step) for step in recipe_steps],
        "summary": dict(summary) if summary is not None else None,
    }
