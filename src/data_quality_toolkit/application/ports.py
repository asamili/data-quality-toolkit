"""Application port protocols for pipeline workflow dependencies.

These Protocol types define the minimal interfaces the pipeline workflow
layer requires from adapter-layer implementations.  They serve as the
target inversion boundary for H1 (application → adapter coupling documented
in pyproject.toml) and allow dependency injection in tests without patching.

Current status: H1 imports remain in pipeline.py as documented exceptions.
These protocols are the *intended* future interface; the concrete wiring
lives at the api.py / cli boundary.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol

import pandas as pd


class CsvLoaderPort(Protocol):
    """Load a CSV source into a DataFrame with loader metadata."""

    def __call__(
        self,
        source: str,
        *,
        sample_size: int | None = None,
        **kw: Any,
    ) -> tuple[pd.DataFrame, dict[str, Any]]: ...

    def load_chunks(
        self,
        source: str,
        chunksize: int = 100_000,
        **kw: Any,
    ) -> Iterator[pd.DataFrame]: ...


class StarBuilderPort(Protocol):
    """Build a BI star schema from a profiling result."""

    def __call__(
        self,
        profile: Any,
        df: pd.DataFrame,
        *,
        source_path: str = "",
    ) -> Any: ...


class StarWriterPort(Protocol):
    """Write star schema DataFrames to disk and return artifact paths."""

    def __call__(
        self,
        tables: dict[str, pd.DataFrame],
        *,
        output_dir: str,
    ) -> dict[str, str]: ...


class IssueExporterPort(Protocol):
    """Build a fact_issues DataFrame from run assessment data."""

    def __call__(
        self,
        *,
        run_id: str,
        dataset_id: str,
        issues: list[dict[str, Any]],
        columns: list[dict[str, Any]],
    ) -> pd.DataFrame: ...


__all__ = [
    "CsvLoaderPort",
    "IssueExporterPort",
    "StarBuilderPort",
    "StarWriterPort",
]
