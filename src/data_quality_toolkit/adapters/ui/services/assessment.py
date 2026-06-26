"""Profiling, assessment, and run-history service wrappers for the dashboard UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from data_quality_toolkit.adapters.storage.connection import StorageError
from data_quality_toolkit.adapters.storage.reader import read_run_history
from data_quality_toolkit.api import assess_csv as _assess_csv
from data_quality_toolkit.shared.error_contract import to_error_info


def _load_run_history(
    db_path_str: str, dataset_id: str
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Fetch run history records. Returns (records, None) or (None, error_message)."""
    try:
        records = read_run_history(Path(db_path_str.strip()), dataset_id.strip())
        return records, None
    except StorageError as exc:
        return None, to_error_info(exc)["message"]


def _run_assess_csv(path_str: str) -> tuple[dict[str, Any] | None, str | None]:
    """Call the public assess_csv API and return (result, None) or (None, error_message).

    Mirrors the _load_run_history pattern: thin wrapper that isolates exception
    handling so the Streamlit caller can stay free of bare try/except blocks.
    Routing through api.assess_csv gives the UI the same hardened load_csv path
    (row cap, max_rows_in_memory guard) that the CLI and Python API use.
    """
    try:
        result = _assess_csv(path_str.strip())
        return cast(dict[str, Any], result), None
    except Exception as exc:
        return None, to_error_info(exc)["message"]


def _load_profile_chunked(
    path_str: str,
    chunksize: int,
) -> tuple[dict[str, Any] | None, str | None]:
    """Call profile_csv(chunksize=N) and return (envelope, None) or (None, error).

    No full-DataFrame load — stores only the returned profile envelope.
    """
    try:
        from data_quality_toolkit.api import profile_csv as _profile_csv_fn

        return cast(dict[str, Any], _profile_csv_fn(path_str.strip(), chunksize=chunksize)), None
    except Exception as exc:
        return None, to_error_info(exc)["message"]
