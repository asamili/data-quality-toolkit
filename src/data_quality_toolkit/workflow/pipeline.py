# src/data_quality_toolkit/workflow/pipeline.py
"""Phase 1: Pipeline orchestration."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, cast

import pandas as pd

from data_quality_toolkit.assessment.quality_checker import assess
from data_quality_toolkit.exporters.bi_star_schema import (
    StarTables,
    build_star,
    validate_relationships,
)
from data_quality_toolkit.exporters.filesystem.csv_exporter import write_star_csvs
from data_quality_toolkit.exporters.issue_export import build_fact_issues
from data_quality_toolkit.loaders.file.csv_loader import load_csv
from data_quality_toolkit.profiling.profiling_orchestrator import run_profiling
from data_quality_toolkit.shared.constants import DEFAULT_NULL_THRESHOLD
from data_quality_toolkit.shared.models import ProfileResult
from data_quality_toolkit.shared.settings import load_settings
from data_quality_toolkit.storage.connection import _get_db_path, connect
from data_quality_toolkit.storage.schema import ensure_db
from data_quality_toolkit.storage.writer import persist_export_run
from data_quality_toolkit.utils.logging import get_logger

logger = get_logger(__name__)

__all__ = ["run_profile", "run_assessment", "run_export_star", "run_pipeline_csv_to_star"]


def _compact_profile(prof: ProfileResult) -> dict[str, Any]:
    """Minimize profile for CLI output while keeping useful detail."""
    return {
        "rows": prof["rows"],
        "cols": prof["cols"],
        "memory_mb": prof["memory_mb"],
        "columns": prof["columns"],  # list[ColumnProfile]
    }


def run_profile(csv_path: str, **read_csv_kwargs: Any) -> dict[str, Any]:
    """Load → full profile (dataset + columns) → compact CLI-friendly output."""
    df, meta = load_csv(csv_path, **read_csv_kwargs)
    prof = run_profiling(df, meta["dataset_id"])
    out: dict[str, Any] = {
        "run_id": prof["run_id"],
        "dataset_id": prof["dataset_id"],
        "ts": prof["ts"],
        "meta": meta,
        "profile": _compact_profile(prof),
    }
    logger.info("Profile complete")
    return out


def run_assessment(
    csv_path: str,
    null_threshold: float = DEFAULT_NULL_THRESHOLD,
    db_path: Path | None = None,
    **read_csv_kwargs: Any,
) -> dict[str, Any]:
    """Load → profile → assess → optionally persist to SQLite."""
    start = time.time()
    df, meta = load_csv(csv_path, **read_csv_kwargs)
    prof = run_profiling(df, meta["dataset_id"])
    # Type shim: assess() expects Dict[str, Any]; prof is a TypedDict
    assessment = assess(cast(dict[str, Any], prof), null_threshold=null_threshold)
    duration_secs = round(time.time() - start, 3)

    if db_path is not None:
        all_issues: list[dict[str, Any]] = cast(list[dict[str, Any]], assessment.get("issues", []))
        ensure_db(db_path)
        _con = connect(db_path)
        try:
            persist_export_run(
                _con,
                run_id=prof["run_id"],
                dataset_id=prof["dataset_id"],
                source_path=meta["source_path"],
                ts=prof["ts"],
                score=float(assessment["score"]),
                rows=prof["rows"],
                cols=prof["cols"],
                memory_mb=float(prof["memory_mb"]),
                null_threshold=float(null_threshold),
                issues_total=len(all_issues),
                issues_by_severity=_count_by(all_issues, "severity"),
                issues_by_category=_count_by(all_issues, "category"),
                duration_secs=duration_secs,
                columns=cast(list[dict[str, Any]], prof["columns"]),
                quality_metrics=[],
                issues=all_issues,
            )
        finally:
            _con.close()

    out: dict[str, Any] = {
        "run_id": prof["run_id"],
        "dataset_id": prof["dataset_id"],
        "ts": prof["ts"],
        "duration_secs": duration_secs,
        "meta": meta,
        "profile": _compact_profile(prof),
        "assessment": assessment,
    }
    logger.info("Assessment complete")
    return out


def run_pipeline_csv_to_star(csv_path: str, **read_csv_kwargs: Any) -> dict[str, Any]:
    """
    Back-compat shim: run Phase-1 and return a dict that includes 'artifacts'
    compatible with older examples/tests.
    """
    out = run_export_star(csv_path, **read_csv_kwargs)
    export_paths = out.get("export_paths") or {}
    # Normalize to an 'artifacts' mapping expected by earlier code samples
    return {
        "run_id": out.get("run_id"),
        "dataset_id": out.get("dataset_id"),
        "ts": out.get("ts"),
        "artifacts": {
            # These keys are the common ones consumers look up
            "dim_dataset": export_paths.get("dim_dataset"),
            "dim_column": export_paths.get("dim_column"),
            "fact_profile_runs": export_paths.get("fact_profile_runs"),
            "fact_quality_metrics": export_paths.get("fact_quality_metrics"),
            # Keep the relationships file available too
            "relationships": export_paths.get("relationships"),
        },
        "export_paths": export_paths,  # keep full detail for new callers
        "profile": out.get("profile"),
        "assessment": out.get("assessment"),
        "star": out.get("star"),
        "meta": out.get("meta"),
    }


def _count_by(issues: list[dict[str, Any]], key: str) -> dict[str, int]:
    """Count issues grouped by a string field (e.g. 'severity', 'category')."""
    out: dict[str, int] = {}
    for issue in issues:
        v = str(issue.get(key, "unknown"))
        out[v] = out.get(v, 0) + 1
    return out


def run_export_star(
    csv_path: str,
    output_dir: str | None = None,
    null_threshold: float = DEFAULT_NULL_THRESHOLD,
    **read_csv_kwargs: Any,
) -> dict[str, Any]:
    """
    Load CSV -> profile -> assess -> build star -> validate -> export CSVs (+ relationships.json).
    Returns a JSON-serializable dict with paths and light metadata.
    """
    start = time.time()
    df, meta = load_csv(csv_path, **read_csv_kwargs)
    prof = run_profiling(df, meta["dataset_id"])

    # Compute assessment so the CLI can show a quality score
    assessment = assess(cast(dict[str, Any], prof), null_threshold=null_threshold)

    # Build + validate star schema (use precise TypedDict)
    tables: StarTables = build_star(prof, df)
    validate_relationships(tables)

    # Choose output dir: CLI flag > settings.export_base_dir
    settings = load_settings()
    base_out = Path(output_dir or settings.export_base_dir)

    # write_star_csvs expects a plain dict[str, DataFrame]; cast once here
    paths = write_star_csvs(cast(dict[str, pd.DataFrame], tables), output_dir=str(base_out))

    # Export issue signal as fact_issues.csv (additive — does not modify existing tables)
    fact_issues_df = build_fact_issues(
        run_id=prof["run_id"],
        dataset_id=prof["dataset_id"],
        issues=cast(list[dict[str, Any]], assessment.get("issues", [])),
        columns=cast(list[dict[str, Any]], prof["columns"]),
    )
    star_dir = base_out / "star"
    star_dir.mkdir(parents=True, exist_ok=True)
    fact_issues_path = star_dir / "fact_issues.csv"
    fact_issues_df.to_csv(fact_issues_path, index=False)
    paths["fact_issues"] = str(fact_issues_path)

    # Write per-run quality report (single sharable artifact for CI gates / async review)
    all_issues: list[dict[str, Any]] = cast(list[dict[str, Any]], assessment.get("issues", []))
    quality_report: dict[str, Any] = {
        "run_id": prof["run_id"],
        "dataset_id": prof["dataset_id"],
        "ts": prof["ts"],
        "score": assessment["score"],
        "rows": prof["rows"],
        "cols": prof["cols"],
        "issues_total": len(all_issues),
        "issues_by_severity": _count_by(all_issues, "severity"),
        "issues_by_category": _count_by(all_issues, "category"),
        "artifacts": {},  # filled after relationships.json is written below
    }
    # Placeholder path written after relationships block; keep ref for post-fill
    quality_report_path = star_dir / "quality_report.json"

    # Emit relationships.json for BI wiring
    rel = {
        "relationships": [
            {
                "from": "fact_profile_runs",
                "to": "dim_dataset",
                "from_column": "dataset_id",
                "to_column": "dataset_id",
            },
            {
                "from": "fact_quality_metrics",
                "to": "dim_column",
                "from_column": "column_id",
                "to_column": "column_id",
            },
            {
                "from": "dim_column",
                "to": "dim_dataset",
                "from_column": "dataset_id",
                "to_column": "dataset_id",
            },
        ]
    }
    rel_path = base_out / "star" / "relationships.json"
    rel_path.write_text(json.dumps(rel, indent=2), encoding="utf-8")
    paths["relationships"] = str(rel_path)

    # Finalise and write quality_report.json now that all artifact paths are known
    duration_secs = round(time.time() - start, 3)
    quality_report["duration_secs"] = duration_secs
    quality_report["artifacts"] = {k: v for k, v in paths.items() if k != "relationships"}
    quality_report_path.write_text(
        json.dumps(quality_report, indent=2, default=str), encoding="utf-8"
    )
    paths["quality_report"] = str(quality_report_path)

    # Append a compact history record so `compare` can diff run-to-run
    history_record: dict[str, Any] = {
        "run_id": quality_report["run_id"],
        "dataset_id": quality_report["dataset_id"],
        "ts": quality_report["ts"],
        "score": quality_report["score"],
        "issues_total": quality_report["issues_total"],
        "issues_by_severity": quality_report["issues_by_severity"],
        "issues_by_category": quality_report["issues_by_category"],
        "duration_secs": quality_report.get("duration_secs"),
    }
    history_path = star_dir / "quality_history.jsonl"
    with history_path.open("a", encoding="utf-8") as _hf:
        _hf.write(json.dumps(history_record, default=str) + "\n")
    paths["quality_history"] = str(history_path)

    # Persist run to SQLite (additive — failure must not fail export)
    try:
        _db_path = _get_db_path(settings)
        ensure_db(_db_path)
        _con = connect(_db_path)
        try:
            # ensure_db may have imported the current run from quality_history.jsonl
            # (when runs table was empty); remove that partial record so persist_export_run
            # can insert it with full data (rows, cols, memory_mb, null_threshold).
            _con.execute("DELETE FROM runs WHERE run_id = ?", (prof["run_id"],))
            _con.commit()
            persist_export_run(
                _con,
                run_id=prof["run_id"],
                dataset_id=prof["dataset_id"],
                source_path=meta["source_path"],
                ts=prof["ts"],
                score=float(assessment["score"]),
                rows=prof["rows"],
                cols=prof["cols"],
                memory_mb=float(prof["memory_mb"]),
                null_threshold=float(null_threshold),
                issues_total=len(all_issues),
                issues_by_severity=_count_by(all_issues, "severity"),
                issues_by_category=_count_by(all_issues, "category"),
                duration_secs=duration_secs,
                columns=cast(list[dict[str, Any]], prof["columns"]),
                quality_metrics=cast(dict[str, pd.DataFrame], tables)[
                    "fact_quality_metrics"
                ].to_dict(orient="records"),
                issues=all_issues,
            )
        finally:
            _con.close()
    except Exception as exc:
        logger.warning("SQLite persistence failed: %s", exc)

    logger.info(
        "quality_report.json written: score=%.4f issues=%d",
        quality_report["score"],
        quality_report["issues_total"],
    )

    # rows summary: iterate with a dict[str, DataFrame] view for clean typing
    tables_dict = cast(dict[str, pd.DataFrame], tables)
    out: dict[str, Any] = {
        "run_id": prof["run_id"],
        "dataset_id": prof["dataset_id"],
        "ts": prof["ts"],
        "duration_secs": duration_secs,
        "meta": meta,
        "profile": {
            "rows": prof["rows"],
            "cols": prof["cols"],
            "memory_mb": prof["memory_mb"],
        },
        "assessment": assessment,
        "star": {
            "tables": list(tables_dict.keys()),
            "rows": {k: int(len(v)) for k, v in tables_dict.items()},
        },
        "export_paths": paths,
    }
    logger.info("Star export complete")
    return out
