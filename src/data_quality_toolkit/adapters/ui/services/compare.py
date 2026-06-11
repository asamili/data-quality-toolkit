"""Run-to-run comparison service wrapper for the dashboard UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data_quality_toolkit.shared.error_contract import to_error_info


def _run_compare(db_path_str: str, dataset_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """Compare last two runs for dataset_id. Returns (result, None) or (None, error_message).

    Infers history_path from db_path: {db_path.parent}/star/quality_history.jsonl.
    Returns (None, message) when fewer than 2 runs exist — a valid user-facing state,
    not an unexpected error, so the caller should render st.info, not st.error.
    """
    try:
        from data_quality_toolkit.application.workflow.compare import compare_last_two_runs

        db_path = Path(db_path_str.strip())
        history_path = db_path.parent / "star" / "quality_history.jsonl"
        result = compare_last_two_runs(dataset_id.strip(), history_path)

        if result.get("error") == "not_enough_runs":
            return None, result["message"]
        return result, None
    except Exception as exc:
        return None, to_error_info(exc)["message"]
