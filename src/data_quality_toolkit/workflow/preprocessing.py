"""Preprocessing planner: per-column issue detection and transformation recommendations."""

from __future__ import annotations

from typing import Any

import pandas as pd


def iqr_outlier_summary(df: pd.DataFrame, col: str) -> dict[str, Any] | None:
    """Return IQR-based outlier stats. None if non-numeric or fewer than 4 non-null values."""
    series = df[col].dropna()
    if not pd.api.types.is_numeric_dtype(series) or len(series) < 4:
        return None
    q1 = float(series.quantile(0.25))
    q3 = float(series.quantile(0.75))
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
        is_num = pd.api.types.is_numeric_dtype(df[col])
        null_pct = float(df[col].isna().mean())
        unique_ratio = df[col].nunique() / rows if rows > 0 else 0.0

        issues: list[str] = []
        recs: list[str] = []

        if null_pct > 0.5:
            issues.append(f"high nulls ({null_pct:.0%})")
            recs.append("drop or flag column")
        elif null_pct > 0:
            issues.append(f"nulls ({null_pct:.0%})")
            recs.append("impute with median" if is_num else "impute with mode or 'Unknown'")

        if not is_num and unique_ratio > 0.9:
            issues.append(f"high cardinality ({unique_ratio:.0%} unique)")
            recs.append("drop or hash-encode")

        if is_num:
            iqr = iqr_outlier_summary(df, col)
            if iqr is not None and iqr["outlier_count"] > 0:
                issues.append(f"{iqr['outlier_count']} IQR outlier(s)")
                recs.append("consider outlier treatment")
            recs.append("consider scaling")
        elif unique_ratio <= 0.9:
            recs.append("label or one-hot encode")

        plan.append(
            {
                "column": col,
                "dtype": str(df[col].dtype),
                "issues": ", ".join(issues) if issues else "none",
                "recommendations": ", ".join(recs) if recs else "none",
            }
        )
    return plan
