"""Public Python API for data_quality_toolkit.

Thin wrappers over workflow.pipeline and workflow.compare.
CLI behavior is unchanged — these functions call the same internal implementations.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _build_csv_kwargs(
    sep: str | None,
    encoding: str | None,
    na_values: list[str] | None,
) -> dict[str, Any]:
    kw: dict[str, Any] = {}
    if sep is not None:
        kw["sep"] = sep
    if encoding is not None:
        kw["encoding"] = encoding
    if na_values is not None:
        kw["na_values"] = na_values
    return kw


def _apply_sample_size(sample_size: int | None) -> None:
    # Matches CLI _apply_overrides: set env var so load_csv picks it up
    if sample_size is not None:
        os.environ["SAMPLE_SIZE"] = str(int(sample_size))


def profile_csv(
    path: str | Path,
    *,
    sep: str | None = None,
    encoding: str | None = None,
    na_values: list[str] | None = None,
    sample_size: int | None = None,
) -> dict[str, Any]:
    """Profile a CSV file. Returns profile metadata — no disk writes."""
    from data_quality_toolkit.application.workflow.pipeline import run_profile

    _apply_sample_size(sample_size)
    return run_profile(str(path), **_build_csv_kwargs(sep, encoding, na_values))


def assess_csv(
    path: str | Path,
    *,
    null_threshold: float | None = None,
    sep: str | None = None,
    encoding: str | None = None,
    na_values: list[str] | None = None,
    sample_size: int | None = None,
) -> dict[str, Any]:
    """Profile and assess a CSV file. Returns profile + quality score + issues. No disk writes."""
    from data_quality_toolkit.application.workflow.pipeline import run_assessment

    _apply_sample_size(sample_size)
    kw = _build_csv_kwargs(sep, encoding, na_values)
    if null_threshold is not None:
        return run_assessment(str(path), null_threshold=null_threshold, **kw)
    return run_assessment(str(path), **kw)


def export_csv(
    path: str | Path,
    *,
    output_dir: str | Path | None = None,
    null_threshold: float | None = None,
    sep: str | None = None,
    encoding: str | None = None,
    na_values: list[str] | None = None,
    sample_size: int | None = None,
) -> dict[str, Any]:
    """Full pipeline: profile → assess → star schema → write artifacts. Returns run metadata."""
    from data_quality_toolkit.application.workflow.pipeline import run_export_star

    _apply_sample_size(sample_size)
    kw = _build_csv_kwargs(sep, encoding, na_values)
    out_dir = str(output_dir) if output_dir is not None else None
    if null_threshold is not None:
        return run_export_star(str(path), output_dir=out_dir, null_threshold=null_threshold, **kw)
    return run_export_star(str(path), output_dir=out_dir, **kw)


def compare_runs(
    path: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Compare the last two export_csv runs for this CSV. output_dir must match export_csv call."""
    from data_quality_toolkit.adapters.loaders.file.csv_loader import _dataset_id_from_file
    from data_quality_toolkit.application.workflow.compare import compare_last_two_runs

    dataset_id = _dataset_id_from_file(Path(path))
    history_path = Path(output_dir) / "star" / "quality_history.jsonl"
    return compare_last_two_runs(dataset_id, history_path)
