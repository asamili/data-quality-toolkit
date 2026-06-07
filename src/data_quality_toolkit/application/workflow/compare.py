# src/data_quality_toolkit/workflow/compare.py
"""Minimal run-to-run comparison helper.

Reads run history from SQLite (primary) or quality_history.jsonl (fallback)
and compares the latest two runs for a dataset_id.
History file is appended-to by run_export_star; one JSON record per line.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from data_quality_toolkit.adapters.storage.connection import StorageError
from data_quality_toolkit.adapters.storage.reader import read_run_history


def _load_history(history_path: Path) -> list[dict[str, Any]]:
    """Load records from a newline-delimited JSON history file. Skips malformed lines."""
    if not history_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # skip malformed lines silently
    return records


def _safe_delta(a: Any, b: Any) -> float | None:
    """Return b - a as float, or None if either is not numeric."""
    try:
        return round(float(b) - float(a), 6)
    except (TypeError, ValueError):
        return None


def _dict_delta(a: Any, b: Any) -> dict[str, int] | None:
    """Return per-key delta of b - a for two str->int count dicts.

    Returns None if either input is not a dict (e.g. absent from old history records).
    Keys present in only one dict are treated as 0 in the other.
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        return None
    keys = sorted(set(a) | set(b))
    return {k: int(b.get(k, 0)) - int(a.get(k, 0)) for k in keys}


def _find_db_path(history_path: Path) -> Path | None:
    """Resolve candidate SQLite DB path without importing settings.

    Checks DQT_DB_PATH env var first; then infers {outdir}/dqt.db from
    history_path = {outdir}/star/quality_history.jsonl. Returns None if no
    existing DB is found.
    """
    override = os.environ.get("DQT_DB_PATH")
    if override:
        p = Path(override)
        return p if p.exists() else None
    candidate = history_path.parent.parent / "dqt.db"
    return candidate if candidate.exists() else None


def _runs_from_sqlite(history_path: Path, dataset_id: str) -> list[dict[str, Any]]:
    """Try SQLite; return [] on absent DB or any read failure."""
    db_path = _find_db_path(history_path)
    if db_path is None:
        return []
    try:
        return read_run_history(db_path, dataset_id)
    except StorageError:
        return []


def compare_last_two_runs(
    dataset_id: str,
    history_path: Path,
) -> dict[str, Any]:
    """
    Compare the latest two runs for *dataset_id*.

    SQLite is the primary source when a usable DB with >=2 matching runs is
    found via DQT_DB_PATH or inferred from *history_path*. Falls back to
    *history_path* (JSONL) when the DB is absent, unreadable, or has fewer
    than 2 matching runs.

    Returns a comparison dict on success, or an error dict when fewer than 2
    runs exist for this dataset.
    """
    runs = _runs_from_sqlite(history_path, dataset_id)
    if len(runs) < 2:
        all_records = _load_history(history_path)
        runs = [r for r in all_records if r.get("dataset_id") == dataset_id]

    if len(runs) < 2:
        return {
            "error": "not_enough_runs",
            "message": (
                f"Found {len(runs)} run(s) for dataset '{dataset_id}'. "
                "Need at least 2 completed export-star runs for the same dataset "
                "in the same --outdir. "
                "Run 'dqt export-star <csv> --outdir <dir>' at least twice, "
                "then retry compare."
            ),
            "dataset_id": dataset_id,
            "runs_found": len(runs),
        }

    # Last two by insertion/ts order = most recent pair
    prev = runs[-2]
    curr = runs[-1]

    return {
        "dataset_id": dataset_id,
        "current_run_id": curr.get("run_id"),
        "previous_run_id": prev.get("run_id"),
        "current_score": curr.get("score"),
        "previous_score": prev.get("score"),
        "score_delta": _safe_delta(prev.get("score"), curr.get("score")),
        "current_completeness_score": curr.get("completeness_score"),
        "previous_completeness_score": prev.get("completeness_score"),
        "current_quality_score": curr.get("quality_score"),
        "previous_quality_score": prev.get("quality_score"),
        "current_issues_total": curr.get("issues_total"),
        "previous_issues_total": prev.get("issues_total"),
        "issues_delta": _safe_delta(prev.get("issues_total"), curr.get("issues_total")),
        "previous_issues_by_severity": prev.get("issues_by_severity"),
        "current_issues_by_severity": curr.get("issues_by_severity"),
        "issues_by_severity_delta": _dict_delta(
            prev.get("issues_by_severity"), curr.get("issues_by_severity")
        ),
        "previous_issues_by_category": prev.get("issues_by_category"),
        "current_issues_by_category": curr.get("issues_by_category"),
        "issues_by_category_delta": _dict_delta(
            prev.get("issues_by_category"), curr.get("issues_by_category")
        ),
        "current_duration_secs": curr.get("duration_secs"),
        "previous_duration_secs": prev.get("duration_secs"),
        "duration_delta": _safe_delta(prev.get("duration_secs"), curr.get("duration_secs")),
        "current_ts": curr.get("ts"),
        "previous_ts": prev.get("ts"),
    }
