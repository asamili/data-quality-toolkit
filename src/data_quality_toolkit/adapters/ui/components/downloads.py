"""Download-button helpers shared across dashboard pages."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

MIME_CSV = "text/csv"
MIME_JSON = "application/json"


def csv_download_button(st: Any, label: str, df: pd.DataFrame, file_name: str) -> None:
    """Render a download button serving *df* as a CSV file (no index column)."""
    st.download_button(
        label,
        data=df.to_csv(index=False),
        file_name=file_name,
        mime=MIME_CSV,
    )


def json_download_button(st: Any, label: str, payload: Any, file_name: str) -> None:
    """Render a download button serving *payload* as pretty-printed JSON in-memory.

    The payload is serialized in-process and streamed to the browser via
    ``st.download_button``; no file is written server-side during page render.
    """
    st.download_button(
        label,
        data=json.dumps(payload, indent=2, default=str),
        file_name=file_name,
        mime=MIME_JSON,
    )
