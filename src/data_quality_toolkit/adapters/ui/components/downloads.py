"""Download-button helpers shared across dashboard pages."""

from __future__ import annotations

from typing import Any

import pandas as pd

MIME_CSV = "text/csv"


def csv_download_button(st: Any, label: str, df: pd.DataFrame, file_name: str) -> None:
    """Render a download button serving *df* as a CSV file (no index column)."""
    st.download_button(
        label,
        data=df.to_csv(index=False),
        file_name=file_name,
        mime=MIME_CSV,
    )
