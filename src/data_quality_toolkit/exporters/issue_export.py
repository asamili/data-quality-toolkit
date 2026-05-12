"""Phase 1: Export detected issues as a star-schema fact table."""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_quality_toolkit.utils.logging import get_logger

logger = get_logger(__name__)

_FACT_ISSUES_COLUMNS = [
    "run_id",
    "dataset_id",
    "column_id",
    "issue_type",
    "severity",
    "category",
    "message",
]


def _build_column_id_map(dataset_id: str, columns: list[dict[str, Any]]) -> dict[str, str]:
    """Return {column_name -> column_id} from profiled columns list."""
    return {str(col.get("name", "")): f"{dataset_id}:{col.get('name', '')}" for col in columns}


def build_fact_issues(
    run_id: str,
    dataset_id: str,
    issues: list[dict[str, Any]],
    columns: list[dict[str, Any]],
) -> pd.DataFrame:
    """
    Build fact_issues DataFrame from normalized assessment issues.

    Args:
        run_id:     Run identifier (FK to fact_profile_runs).
        dataset_id: Dataset identifier (FK to dim_dataset).
        issues:     List of issue dicts with keys: type, column, severity,
                    category, message.
        columns:    Profiled column list used to resolve column_id.
                    Issues whose column name is not in this list get
                    column_id=None (nullable FK).

    Returns:
        DataFrame with columns: run_id, dataset_id, column_id, issue_type,
        severity, category, message.
    """
    if not issues:
        return pd.DataFrame(columns=_FACT_ISSUES_COLUMNS)

    col_id_map = _build_column_id_map(dataset_id, columns)

    rows = []
    for issue in issues:
        col_name = issue.get("column", "")
        rows.append(
            {
                "run_id": run_id,
                "dataset_id": dataset_id,
                "column_id": col_id_map.get(col_name),  # None if not found
                "issue_type": issue.get("type", ""),
                "severity": issue.get("severity", ""),
                "category": issue.get("category", ""),
                "message": issue.get("message", ""),
            }
        )

    df = pd.DataFrame(rows, columns=_FACT_ISSUES_COLUMNS)
    logger.info("fact_issues built: %d rows", len(df))
    return df
