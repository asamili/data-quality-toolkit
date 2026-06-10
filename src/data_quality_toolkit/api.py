"""Public Python API for data_quality_toolkit.

Thin wrappers over workflow.pipeline and workflow.compare.
CLI behavior is unchanged — these functions call the same internal implementations.
"""

# mypy: warn_unused_ignores = false

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from data_quality_toolkit.application.workflow.elt_pipeline import ELTPipeline


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


def profile_csv(
    path: str | Path,
    *,
    sep: str | None = None,
    encoding: str | None = None,
    na_values: list[str] | None = None,
    sample_size: int | None = None,
    chunksize: int | None = None,
) -> dict[str, Any]:
    """Profile a CSV file. Returns profile metadata — no disk writes.

    chunksize=None (default): full in-memory load, all metrics available.
    chunksize=N: streams in chunks; approximate=True, unsupported_metrics populated.
    """
    kw = _build_csv_kwargs(sep, encoding, na_values)
    if chunksize is not None:
        from data_quality_toolkit.application.workflow.pipeline import run_profile_chunked

        return run_profile_chunked(str(path), chunksize=chunksize, **kw)
    from data_quality_toolkit.application.workflow.pipeline import run_profile

    return run_profile(str(path), sample_size=sample_size, **kw)


def assess_csv(
    path: str | Path,
    *,
    null_threshold: float | None = None,
    sep: str | None = None,
    encoding: str | None = None,
    na_values: list[str] | None = None,
    sample_size: int | None = None,
    chunksize: int | None = None,
) -> dict[str, Any]:
    """Profile and assess a CSV file. Returns profile + quality score + issues. No disk writes.

    chunksize=None (default): full in-memory load, all rules available.
    chunksize=N: streams in chunks; partial assessment, assessment_mode='chunked',
                 approximate=True, unsupported_rules populated; no quality_score.
    """
    kw = _build_csv_kwargs(sep, encoding, na_values)
    if chunksize is not None:
        from data_quality_toolkit.application.workflow.pipeline import run_assessment_chunked

        if null_threshold is not None:
            return run_assessment_chunked(
                str(path), chunksize=chunksize, null_threshold=null_threshold, **kw
            )
        return run_assessment_chunked(str(path), chunksize=chunksize, **kw)
    from data_quality_toolkit.application.workflow.pipeline import run_assessment

    if null_threshold is not None:
        return run_assessment(
            str(path), null_threshold=null_threshold, sample_size=sample_size, **kw
        )
    return run_assessment(str(path), sample_size=sample_size, **kw)


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

    kw = _build_csv_kwargs(sep, encoding, na_values)
    out_dir = str(output_dir) if output_dir is not None else None
    if null_threshold is not None:
        return run_export_star(
            str(path),
            output_dir=out_dir,
            null_threshold=null_threshold,
            sample_size=sample_size,
            **kw,
        )
    return run_export_star(str(path), output_dir=out_dir, sample_size=sample_size, **kw)


def create_manifest(run_id: str, sessions_root: str | Path) -> dict[str, Any]:
    """Build a lineage manifest for a specific run.

    Reuses existing lineage manifest builder. Returns a plain dictionary.
    """
    from data_quality_toolkit.lineage.manifest.builder import build_manifest

    manifest = build_manifest(run_id=run_id, sessions_root=Path(sessions_root))
    return manifest.model_dump(mode="json", by_alias=True)  # type: ignore


def compare_runs(
    path: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Compare the last two export_csv runs for this CSV. output_dir must match export_csv call."""
    from data_quality_toolkit.adapters.loaders.file.csv_loader import dataset_id_from_file
    from data_quality_toolkit.application.workflow.compare import compare_last_two_runs

    dataset_id = dataset_id_from_file(Path(path))
    history_path = Path(output_dir) / "star" / "quality_history.jsonl"
    return compare_last_two_runs(dataset_id, history_path)


def plan_csv(
    path: str | Path,
    *,
    sep: str | None = None,
    encoding: str | None = None,
    na_values: list[str] | None = None,
    sample_size: int | None = None,
) -> dict[str, Any]:
    """Return per-column preprocessing recommendations for a CSV. No disk writes."""
    from data_quality_toolkit.adapters.loaders.file.csv_loader import load_csv
    from data_quality_toolkit.application.workflow.preprocessing import plan_preprocessing

    kw = _build_csv_kwargs(sep, encoding, na_values)
    df, meta = load_csv(str(path), sample_size=sample_size, **kw)
    return {
        "dataset_id": meta["dataset_id"],
        "columns": plan_preprocessing(df),
    }


def kpi_validate(config_path: str | Path) -> dict[str, Any]:
    """Validate a KPI catalog YAML (schema, semantics, dependency cycles). No disk writes."""
    from data_quality_toolkit.application.workflow.kpi import validate_kpi_catalog

    return validate_kpi_catalog(config_path)


def kpi_emit(
    config_path: str | Path,
    dax_out: str | Path,
    tmsl_out: str | Path,
) -> dict[str, Any]:
    """Load KPI catalog, validate, and emit DAX + TMSL files. Writes two output files."""
    from data_quality_toolkit.application.workflow.kpi import emit_kpi_artifacts

    return emit_kpi_artifacts(config_path, dax_out, tmsl_out)


def kpi_graph(
    config_path: str | Path,
    out: str | Path,
    graph_format: Literal["mermaid", "graphviz"] = "mermaid",
) -> dict[str, Any]:
    """Export KPI dependency graph as Mermaid (.mmd) or Graphviz (.dot). Writes one file."""
    from data_quality_toolkit.application.workflow.kpi import export_kpi_graph

    return export_kpi_graph(config_path, out, graph_format=graph_format)


def generate_dim_time(
    start_date: str = "2018-01-01",
    end_date: str = "2030-12-31",
    *,
    week_start: int = 1,
    fiscal_year_start: int | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Generate a time dimension table.

    If output_dir is provided, writes dim_time.csv and includes "path" in the result.
    Without output_dir, returns metadata only (rows, start_date, end_date, week_start).
    """
    from data_quality_toolkit.application.workflow.kpi import generate_dim_time_workflow

    return generate_dim_time_workflow(
        start_date=start_date,
        end_date=end_date,
        week_start=week_start,
        fiscal_year_start=fiscal_year_start,
        output_dir=output_dir,
    )


def create_elt_pipeline(run_id: str, sessions_root: str | Path) -> ELTPipeline:
    """Create a new ELT pipeline for orchestration."""
    from data_quality_toolkit.application.workflow.elt_pipeline import (
        create_elt_pipeline as _create,
    )

    return _create(run_id, sessions_root)
