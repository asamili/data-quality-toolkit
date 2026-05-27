"""Phase 1: Issue detection (stub for future expansion)."""

from typing import Any

from data_quality_toolkit.shared.constants import (
    DEFAULT_HIGH_CARDINALITY_THRESHOLD,
    DEFAULT_OUTLIER_FRACTION_THRESHOLD,
)


def _detect_duplicate_column_names(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for col in columns:
        name = str(col.get("name", ""))
        key = name.lower()
        if key in seen:
            issues.append(
                {
                    "type": "duplicate_column_name",
                    "column": name,
                    "first_seen_as": seen[key],
                    "severity": "high",
                    "category": "Schema",
                    "message": f"Duplicate column name '{name}' (already seen as '{seen[key]}')",
                }
            )
        else:
            seen[key] = name
    return issues


def _detect_high_cardinality(columns: list[dict[str, Any]], rows: int) -> list[dict[str, Any]]:
    if rows <= 1:
        return []
    issues: list[dict[str, Any]] = []
    for col in columns:
        dtype = str(col.get("dtype", ""))
        if "int" in dtype or "float" in dtype:
            continue
        unique = col.get("unique")
        if unique is None:
            continue
        unique_ratio = int(unique) / rows
        if unique_ratio > DEFAULT_HIGH_CARDINALITY_THRESHOLD:
            name = col.get("name", "")
            pct_display = round(unique_ratio * 100, 1)
            issues.append(
                {
                    "type": "high_cardinality",
                    "column": name,
                    "pct": round(unique_ratio, 6),
                    "severity": "medium",
                    "category": "Cardinality",
                    "message": f"Column '{name}' has high cardinality ({pct_display}% unique values)",
                }
            )
    return issues


def _detect_numeric_outliers(df: Any, columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    df_columns = set(df.columns) if hasattr(df, "columns") else set()
    for col in columns:
        dtype = str(col.get("dtype", ""))
        if "int" not in dtype and "float" not in dtype:
            continue
        name = col.get("name", "")
        if name not in df_columns:
            continue
        series = df[name].dropna()
        if len(series) < 4:
            continue
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        outlier_fraction = float(((series < lower) | (series > upper)).mean())
        if outlier_fraction > DEFAULT_OUTLIER_FRACTION_THRESHOLD:
            pct_display = round(outlier_fraction * 100, 1)
            issues.append(
                {
                    "type": "numeric_outliers",
                    "column": name,
                    "pct": round(outlier_fraction, 6),
                    "severity": "low",
                    "category": "Distribution",
                    "message": f"Column '{name}' has {pct_display}% outliers by IQR",
                }
            )
    return issues


def detect_advanced_issues(df: Any, profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Detect advanced quality issues: high cardinality and numeric outliers."""
    columns: list[dict[str, Any]] = profile.get("columns", [])
    rows = int(profile.get("rows", 0) or 0)
    return _detect_high_cardinality(columns, rows) + _detect_numeric_outliers(df, columns)


def _detect_blank_column_names(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for col in columns:
        name = col.get("name", "")
        if isinstance(name, str) and not name.strip():
            issues.append(
                {
                    "type": "blank_column_name",
                    "column": repr(name),
                    "severity": "high",
                    "category": "Schema",
                    "message": f"Column name is blank or whitespace-only: {repr(name)}",
                }
            )
    return issues


_PLACEHOLDER_NAMES: frozenset[str] = frozenset(
    {
        "unnamed",
        "unknown",
        "n/a",
        "na",
        "none",
        "null",
    }
)

_PLACEHOLDER_PATTERN_PREFIXES: tuple[str, ...] = ("unnamed:",)


def _is_placeholder(name: str) -> bool:
    key = name.strip().lower()
    if key in _PLACEHOLDER_NAMES:
        return True
    return any(key.startswith(p) for p in _PLACEHOLDER_PATTERN_PREFIXES)


def _detect_placeholder_column_names(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for col in columns:
        name = col.get("name", "")
        if isinstance(name, str) and name.strip() and _is_placeholder(name):
            issues.append(
                {
                    "type": "placeholder_column_name",
                    "column": name,
                    "severity": "medium",
                    "category": "Schema",
                    "message": f"Column name appears to be a placeholder: '{name}'",
                }
            )
    return issues


def _detect_padded_column_names(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for col in columns:
        name = col.get("name", "")
        if isinstance(name, str) and name != name.strip() and name.strip():
            issues.append(
                {
                    "type": "padded_column_name",
                    "column": repr(name),
                    "suggested": name.strip(),
                    "severity": "medium",
                    "category": "Schema",
                    "message": f"Column name has leading/trailing whitespace: {repr(name)}",
                }
            )
    return issues


def _detect_constant_columns(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag columns with exactly one distinct non-null value."""
    issues: list[dict[str, Any]] = []
    for col in columns:
        unique = col.get("unique")
        if unique is None:
            continue
        if int(unique) == 1:
            name = col.get("name", "")
            issues.append(
                {
                    "type": "constant_column",
                    "column": name,
                    "severity": "medium",
                    "category": "Completeness",
                    "message": f"Column '{name}' has only one distinct non-null value",
                }
            )
    return issues


def _detect_all_null_columns(columns: list[dict[str, Any]], rows: int) -> list[dict[str, Any]]:
    """Flag columns where every row is null (nulls == row count) in a non-empty dataset."""
    if rows <= 0:
        return []
    issues: list[dict[str, Any]] = []
    for col in columns:
        nulls = col.get("nulls")
        if nulls is None:
            continue
        if int(nulls) >= rows:
            name = col.get("name", "")
            issues.append(
                {
                    "type": "all_null_column",
                    "column": name,
                    "severity": "high",
                    "category": "Completeness",
                    "message": f"Column '{name}' is entirely null across all {rows} rows",
                }
            )
    return issues


def detect_issues(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return all structural and completeness issues detected from a profile."""
    columns: list[dict[str, Any]] = profile.get("columns", [])
    rows = int(profile.get("rows", 0) or 0)
    return (
        _detect_duplicate_column_names(columns)
        + _detect_blank_column_names(columns)
        + _detect_padded_column_names(columns)
        + _detect_placeholder_column_names(columns)
        + _detect_constant_columns(columns)
        + _detect_all_null_columns(columns, rows)
    )
