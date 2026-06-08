# src/data_quality_toolkit/workflow/pipeline.py
"""Pipeline orchestration."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

from data_quality_toolkit.adapters.exporters.bi_star_schema import (
    StarTables,
    build_star,
    validate_relationships,
)
from data_quality_toolkit.adapters.exporters.filesystem.csv_exporter import write_star_csvs
from data_quality_toolkit.adapters.exporters.issue_export import build_fact_issues
from data_quality_toolkit.adapters.loaders.file.csv_loader import (
    CsvLoader,
    dataset_id_from_file,
    load_csv,
)
from data_quality_toolkit.adapters.storage.connection import _get_db_path, connect
from data_quality_toolkit.adapters.storage.jsonl import append_jsonl_record
from data_quality_toolkit.adapters.storage.schema import ensure_db
from data_quality_toolkit.adapters.storage.writer import persist_export_run
from data_quality_toolkit.domain.assessment.quality_checker import assess
from data_quality_toolkit.domain.profiling.profiling_orchestrator import (
    run_chunked_profiling,
    run_profiling,
)
from data_quality_toolkit.shared.constants import ARTIFACT_SCHEMA_VERSION, DEFAULT_NULL_THRESHOLD
from data_quality_toolkit.shared.models import ProfileResult
from data_quality_toolkit.shared.settings import load_settings
from data_quality_toolkit.utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "run_profile",
    "run_profile_chunked",
    "run_assessment",
    "run_assessment_chunked",
    "run_export_star",
    "run_pipeline_csv_to_star",
]

_CHUNKED_UNSUPPORTED: list[str] = ["unique", "memory_mb"]

# Rules that require unique counts or a full DataFrame — unavailable in chunked mode.
_CHUNKED_UNSUPPORTED_RULES: list[str] = [
    "constant_column",
    "high_cardinality",
    "numeric_outliers",
    "accepted_values_violation",
    "uniqueness_violation",
]


def _compact_profile(prof: ProfileResult) -> dict[str, Any]:
    """Minimize profile for CLI output while keeping useful detail."""
    return {
        "rows": prof["rows"],
        "cols": prof["cols"],
        "memory_mb": prof["memory_mb"],
        "columns": prof["columns"],  # list[ColumnProfile]
    }


def run_profile_chunked(
    csv_path: str, *, chunksize: int = 100_000, **read_csv_kwargs: Any
) -> dict[str, Any]:
    """Chunked profile: streams CSV in chunks, no full-DataFrame load.

    Supported metrics: rows, per-column nulls, numeric min/max.
    Unsupported (marked None / "unknown"): dtype, unique, memory_mb.
    Envelope carries approximate=True and unsupported_metrics list.
    """
    path = Path(csv_path)
    dataset_id = dataset_id_from_file(path)
    # Peek headers without loading data (nrows=0 reads only the header row)
    header_kw = {k: v for k, v in read_csv_kwargs.items() if k not in ("chunksize",)}
    columns: list[str] = pd.read_csv(path, nrows=0, **header_kw).columns.tolist()
    chunks = CsvLoader().load_chunks(csv_path, chunksize=chunksize, **read_csv_kwargs)
    prof = run_chunked_profiling(chunks, dataset_id, columns)
    stat = path.stat()
    meta: dict[str, Any] = {
        "dataset_id": dataset_id,
        "source_path": str(path.resolve()),
        "file_size_bytes": int(stat.st_size),
        "modified_ts": datetime.fromtimestamp(stat.st_mtime, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sample_applied": False,
        "sample_size": None,
        "chunksize": chunksize,
    }
    out: dict[str, Any] = {
        "run_id": prof["run_id"],
        "dataset_id": prof["dataset_id"],
        "ts": prof["ts"],
        "meta": meta,
        "profile": {
            "rows": prof["rows"],
            "cols": prof["cols"],
            "memory_mb": None,
            "columns": prof["columns"],
        },
        "approximate": True,
        "unsupported_metrics": _CHUNKED_UNSUPPORTED,
    }
    logger.info("Chunked profile complete: %d rows, %d cols", prof["rows"], prof["cols"])
    return out


def run_profile(
    csv_path: str, sample_size: int | None = None, **read_csv_kwargs: Any
) -> dict[str, Any]:
    """Load → full profile (dataset + columns) → compact CLI-friendly output."""
    df, meta = load_csv(csv_path, sample_size=sample_size, **read_csv_kwargs)
    prof = run_profiling(df, meta["dataset_id"], sample_size=sample_size)
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
    sample_size: int | None = None,
    **read_csv_kwargs: Any,
) -> dict[str, Any]:
    """Load → profile → assess → optionally persist to SQLite."""
    start = time.time()
    df, meta = load_csv(csv_path, sample_size=sample_size, **read_csv_kwargs)
    prof = run_profiling(df, meta["dataset_id"], sample_size=sample_size)
    # Type shim: assess() expects Dict[str, Any]; prof is a TypedDict
    assessment = assess(cast(dict[str, Any], prof), null_threshold=null_threshold, df=df)
    duration_secs = round(time.time() - start, 3)

    if db_path is not None:
        _persist_assessment_to_db(
            db_path, prof, cast(dict[str, Any], assessment), meta, duration_secs, null_threshold
        )

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


def run_assessment_chunked(
    csv_path: str,
    *,
    chunksize: int = 100_000,
    null_threshold: float = DEFAULT_NULL_THRESHOLD,
    **read_csv_kwargs: Any,
) -> dict[str, Any]:
    """Chunked assessment: stream CSV, run only profile-derivable rules.

    Supported rules: completeness/missing, all_null_column, missing_required_column,
    dtype_mismatch, and column-name hygiene (duplicate/blank/padded/placeholder).
    Unsupported rules are listed in the returned unsupported_rules field.
    No quality_score — returns completeness_score only.
    """
    start = time.time()
    prof_envelope = run_profile_chunked(csv_path, chunksize=chunksize, **read_csv_kwargs)
    raw_prof = prof_envelope["profile"]

    # Build a profile-shaped dict that assess() can consume (run_id, dataset_id, ts, rows, cols, columns)
    prof_dict: dict[str, Any] = {
        "run_id": prof_envelope["run_id"],
        "dataset_id": prof_envelope["dataset_id"],
        "ts": prof_envelope["ts"],
        "rows": raw_prof["rows"],
        "cols": raw_prof["cols"],
        "memory_mb": None,
        "columns": raw_prof["columns"],
    }

    # assess(df=None) automatically skips all full-DataFrame rules:
    # _detect_constant_columns skips unique=None, _detect_high_cardinality skips unique=None,
    # _detect_numeric_outliers returns [] for df=None, accepted_values/uniqueness skipped.
    full_result = assess(prof_dict, null_threshold=null_threshold)
    duration_secs = round(time.time() - start, 3)

    chunked_assessment: dict[str, Any] = {
        "run_id": full_result["run_id"],
        "dataset_id": full_result["dataset_id"],
        "ts": full_result["ts"],
        "score": full_result["score"],
        "completeness_score": full_result["completeness_score"],
        "issues": full_result["issues"],
        "assessment_mode": "chunked",
        "approximate": True,
        "unsupported_rules": _CHUNKED_UNSUPPORTED_RULES,
    }

    out: dict[str, Any] = {
        "run_id": prof_envelope["run_id"],
        "dataset_id": prof_envelope["dataset_id"],
        "ts": prof_envelope["ts"],
        "duration_secs": duration_secs,
        "meta": prof_envelope["meta"],
        "profile": prof_envelope["profile"],
        "assessment": chunked_assessment,
        "approximate": True,
    }
    logger.info(
        "Chunked assessment complete: completeness_score=%.4f issues=%d",
        full_result["completeness_score"],
        len(full_result["issues"]),
    )
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


def _persist_assessment_to_db(
    db_path: Path,
    prof: ProfileResult,
    assessment: dict[str, Any],
    meta: dict[str, Any],
    duration_secs: float,
    null_threshold: float,
    *,
    _ensure_db: Any = None,
    _connect: Any = None,
    _persist: Any = None,
) -> None:
    """Persist an assessment run to SQLite.  All three storage callables are
    injectable for testing; production code uses the module-level defaults."""
    fn_ensure = _ensure_db if _ensure_db is not None else ensure_db
    fn_connect = _connect if _connect is not None else connect
    fn_persist = _persist if _persist is not None else persist_export_run
    all_issues: list[dict[str, Any]] = cast(list[dict[str, Any]], assessment.get("issues", []))
    fn_ensure(db_path)
    _con = fn_connect(db_path)
    try:
        fn_persist(
            _con,
            run_id=prof["run_id"],
            dataset_id=prof["dataset_id"],
            source_path=meta["source_path"],
            ts=prof["ts"],
            score=float(assessment["score"]),
            completeness_score=float(assessment["completeness_score"]),
            quality_score=float(assessment["quality_score"]),
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


def _persist_star_to_sqlite(
    settings: Any,
    prof: ProfileResult,
    assessment: dict[str, Any],
    meta: dict[str, Any],
    all_issues: list[dict[str, Any]],
    duration_secs: float,
    null_threshold: float,
    tables: Any,
    *,
    _get_db: Any = None,
    _ensure_db: Any = None,
    _connect: Any = None,
    _persist: Any = None,
) -> None:
    """Persist a star-export run to SQLite.  All four storage callables are
    injectable for testing; production code uses the module-level defaults."""
    fn_get_db = _get_db if _get_db is not None else _get_db_path
    fn_ensure = _ensure_db if _ensure_db is not None else ensure_db
    fn_connect = _connect if _connect is not None else connect
    fn_persist = _persist if _persist is not None else persist_export_run
    db_path = fn_get_db(settings)
    fn_ensure(db_path)
    _con = fn_connect(db_path)
    try:
        _con.execute("DELETE FROM runs WHERE run_id = ?", (prof["run_id"],))
        _con.commit()
        tables_dict = cast(dict[str, pd.DataFrame], tables)
        fn_persist(
            _con,
            run_id=prof["run_id"],
            dataset_id=prof["dataset_id"],
            source_path=meta["source_path"],
            ts=prof["ts"],
            score=float(assessment["score"]),
            completeness_score=float(assessment["completeness_score"]),
            quality_score=float(assessment["quality_score"]),
            rows=prof["rows"],
            cols=prof["cols"],
            memory_mb=float(prof["memory_mb"]),
            null_threshold=float(null_threshold),
            issues_total=len(all_issues),
            issues_by_severity=_count_by(all_issues, "severity"),
            issues_by_category=_count_by(all_issues, "category"),
            duration_secs=duration_secs,
            columns=cast(list[dict[str, Any]], prof["columns"]),
            quality_metrics=tables_dict["fact_quality_metrics"].to_dict(orient="records"),
            issues=all_issues,
        )
    finally:
        _con.close()


def run_export_star(
    csv_path: str,
    output_dir: str | None = None,
    null_threshold: float = DEFAULT_NULL_THRESHOLD,
    sample_size: int | None = None,
    **read_csv_kwargs: Any,
) -> dict[str, Any]:
    """
    Load CSV -> profile -> assess -> build star -> validate -> export CSVs (+ relationships.json).
    Returns a JSON-serializable dict with paths and light metadata.
    """
    start = time.time()
    df, meta = load_csv(csv_path, sample_size=sample_size, **read_csv_kwargs)
    prof = run_profiling(df, meta["dataset_id"], sample_size=sample_size)

    # Compute assessment so the CLI can show a quality score
    assessment = assess(cast(dict[str, Any], prof), null_threshold=null_threshold, df=df)

    # Build + validate star schema (use precise TypedDict)
    tables: StarTables = build_star(prof, df, source_path=meta["source_path"])
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
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "run_id": prof["run_id"],
        "dataset_id": prof["dataset_id"],
        "ts": prof["ts"],
        "score": assessment["score"],
        "completeness_score": assessment["completeness_score"],
        "quality_score": assessment["quality_score"],
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
        "schema_version": ARTIFACT_SCHEMA_VERSION,
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
        ],
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
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "run_id": quality_report["run_id"],
        "dataset_id": quality_report["dataset_id"],
        "ts": quality_report["ts"],
        "score": quality_report["score"],
        "completeness_score": quality_report["completeness_score"],
        "quality_score": quality_report["quality_score"],
        "issues_total": quality_report["issues_total"],
        "issues_by_severity": quality_report["issues_by_severity"],
        "issues_by_category": quality_report["issues_by_category"],
        "duration_secs": quality_report.get("duration_secs"),
    }
    history_path = star_dir / "quality_history.jsonl"
    append_jsonl_record(history_path, history_record)
    paths["quality_history"] = str(history_path)

    # Persist run to SQLite via injectable helper (additive — failure must not fail export)
    try:
        _persist_star_to_sqlite(
            settings,
            prof,
            cast(dict[str, Any], assessment),
            meta,
            all_issues,
            duration_secs,
            null_threshold,
            tables,
        )
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
