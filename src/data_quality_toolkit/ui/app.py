"""Streamlit dashboard app for Data Quality Toolkit."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data_quality_toolkit.storage.connection import StorageError
from data_quality_toolkit.storage.reader import read_run_history


def _load_run_history(
    db_path_str: str, dataset_id: str
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Fetch run history records. Returns (records, None) or (None, error_message)."""
    try:
        records = read_run_history(Path(db_path_str.strip()), dataset_id.strip())
        return records, None
    except StorageError as exc:
        return None, str(exc)


def _extract_trend_data(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract ts/score pairs from run history records, skipping rows missing either field."""
    result = []
    for r in records:
        ts = r.get("ts")
        score = r.get("score")
        if ts is None or score is None:
            continue
        result.append({"ts": ts, "score": score})
    return result


def main() -> None:
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError(
            "Streamlit is not installed. "
            "Install the UI extra when available: pip install data-quality-toolkit[ui]"
        ) from exc

    st.title("Data Quality Toolkit Dashboard")
    st.caption("Phase 4 dashboard")

    st.header("Run History")
    db_path_str = st.text_input("Database path", placeholder="path/to/dqt.db")
    dataset_id = st.text_input("Dataset ID", placeholder="my_dataset")

    if not db_path_str or not dataset_id:
        st.info("Enter a database path and dataset ID to load run history.")
        return

    records, err = _load_run_history(db_path_str, dataset_id)
    if err is not None:
        st.error(f"Storage error: {err}")
        return

    if not records:
        st.warning("No run history found for this dataset.")
        return

    trend = _extract_trend_data(records)
    if len(trend) >= 2:
        st.subheader("Score Trend")
        st.line_chart({"Score": [r["score"] for r in trend]})

    st.dataframe(records)


if __name__ == "__main__":
    main()
