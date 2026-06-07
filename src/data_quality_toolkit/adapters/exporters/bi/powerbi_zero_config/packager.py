# cspell:ignore pbit nrows
"""Phase 2: Power BI package validation and integrity checks (refactored)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, TypedDict, cast

import pandas as pd

from data_quality_toolkit.utils.logging import get_logger

__all__ = ["validate_relationships", "validate_package"]

logger = get_logger("dqt.exporters.bi.powerbi_zero_config.packager")


class ValidationSummary(TypedDict, total=False):
    valid: bool
    errors: list[str]
    warnings: list[str]
    file_count: int
    csv_count: int
    relationships_count: int


# ------------------------ constants ------------------------ #

STAR_DIR = "star"
TIME_DIR = "time"
TIME_TABLES = {"dim_time"}  # tables expected under time/

MODEL_PBIT = "model.pbit"
PARAMETERS_JSON = "parameters.json"
RELATIONSHIPS_JSON = "relationships.json"


# ------------------------ low-level helpers ------------------------ #


def _json_load(path: Path) -> dict[str, Any]:
    """Load JSON and ensure top-level object is a dict."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        # Avoid constructing json.JSONDecodeError manually (signature is tricky)
        raise ValueError("Top-level JSON is not an object")
    return cast(dict[str, Any], data)


def _csv_headers(csv_path: Path) -> list[str] | None:
    """Return CSV headers or None if file missing/unreadable."""
    if not csv_path.exists():
        return None
    try:
        df = pd.read_csv(csv_path, nrows=0)  # fast header read
        return list(df.columns)
    except Exception:
        return None


def _required_files() -> list[str]:
    """List of required files; model.pbit is warning-only."""
    return [
        MODEL_PBIT,
        PARAMETERS_JSON,
        RELATIONSHIPS_JSON,
        f"{STAR_DIR}/dim_dataset.csv",
        f"{STAR_DIR}/dim_column.csv",
        f"{STAR_DIR}/fact_profile_runs.csv",
        f"{STAR_DIR}/fact_quality_metrics.csv",
        f"{TIME_DIR}/dim_time.csv",
    ]


def _csv_path_for(package_dir: Path, table: str) -> Path:
    """Resolve a table name to its CSV path inside the package."""
    subdir = TIME_DIR if table in TIME_TABLES else STAR_DIR
    return package_dir / subdir / f"{table}.csv"


def _build_headers_index(package_dir: Path, tables: list[str]) -> dict[str, list[str]]:
    """
    Build {table: headers} mapping from CSVs inside the package.
    Missing/unreadable CSVs are represented by an empty list to simplify checks.
    """
    out: dict[str, list[str]] = {}
    for t in tables:
        csv_path = _csv_path_for(package_dir, t)
        headers = _csv_headers(csv_path)
        out[t] = headers or []
    return out


# ------------------------ mid-level validators ------------------------ #


def _check_required(package_path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for rel in _required_files():
        full = package_path / rel
        if not full.exists():
            if rel == MODEL_PBIT:
                warnings.append(f"{rel} not found (placeholder OK for testing)")
            else:
                errors.append(f"Missing required file: {rel}")
    return errors, warnings


def _check_parameters(package_path: Path) -> list[str]:
    errors: list[str] = []
    params_path = package_path / PARAMETERS_JSON
    if not params_path.exists():
        return errors  # already flagged by required-files check
    try:
        params = _json_load(params_path)
        has_base_folder = any(
            isinstance(p, dict) and p.get("name") == "BaseFolder"
            for p in params.get("parameters", [])
        )
        if not has_base_folder:
            errors.append("BaseFolder parameter not found in parameters.json")
    except ValueError as e:
        # json.JSONDecodeError is a subclass of ValueError; no need to list both (Sonar S5713)
        errors.append(f"Invalid parameters.json: {e}")
    return errors


def _collect_csvs(package_path: Path) -> list[Path]:
    csvs = list((package_path / STAR_DIR).glob("*.csv"))
    csvs.extend((package_path / TIME_DIR).glob("*.csv"))
    return csvs


def _check_csv_readability(csv_files: list[Path]) -> list[str]:
    errors: list[str] = []
    for p in csv_files:
        try:
            pd.read_csv(p, nrows=1)
        except Exception as e:
            errors.append(f"Cannot read {p.name}: {e}")
    return errors


def _validate_primary_key(table: str, pk: Any, headers: list[str], errors: list[str]) -> None:
    """Validate primary_key entry."""
    if pk is None:
        return
    if not isinstance(pk, list) or not all(isinstance(x, str) for x in pk):
        errors.append(f"{table}.primary_key is not a list of strings")
        return
    for col in pk:
        if col not in headers:
            errors.append(f"{table}.{col} not found in CSV")


def _validate_foreign_keys(
    table: str, fks: Any, headers_index: dict[str, list[str]], errors: list[str]
) -> None:
    """Validate foreign_keys entries."""
    if fks is None:
        return
    if not isinstance(fks, list):
        errors.append(f"{table}.foreign_keys is not a list")
        return
    for fk in fks:
        # expect [col, ref_table, ref_col]
        if not (isinstance(fk, list) and len(fk) == 3 and all(isinstance(x, str) for x in fk)):
            errors.append(f"{table}.foreign_keys has malformed entry")
            continue
        col, ref_table, ref_col = fk
        table_headers = headers_index.get(table, [])
        if col not in table_headers:
            errors.append(f"{table}.{col} not found in CSV")
        ref_headers = headers_index.get(ref_table, [])
        # Only check referenced column if referenced table exists
        if ref_headers and ref_col not in ref_headers:
            errors.append(f"{ref_table}.{ref_col} not found in CSV")


def _validate_table_keys(
    table: str,
    spec: dict[str, Any],
    headers_index: dict[str, list[str]],
    errors: list[str],
) -> None:
    """Validate tables[table] primary_key and foreign_keys shapes/columns."""
    headers = headers_index.get(table, [])
    _validate_primary_key(table, spec.get("primary_key"), headers, errors)
    _validate_foreign_keys(table, spec.get("foreign_keys"), headers_index, errors)


def _extract_table_names_from_relationship(rel: Any) -> set[str]:
    """Extract table names from a single relationship entry."""
    names: set[str] = set()
    if not isinstance(rel, dict):
        return names
    from_v = rel.get("from")
    to_v = rel.get("to")
    if isinstance(from_v, list) and from_v:
        names.add(str(from_v[0]))
    if isinstance(to_v, list) and to_v:
        names.add(str(to_v[0]))
    return names


def _collect_table_names_from_spec(spec: dict[str, Any]) -> set[str]:
    """Extract a set of table names referenced by 'tables' and 'relationships'."""
    names: set[str] = set()

    # tables section
    tables_spec = spec.get("tables", {}) or {}
    if isinstance(tables_spec, dict):
        names.update(str(k) for k in tables_spec.keys())

    # relationships section
    relationships = spec.get("relationships", []) or []
    if isinstance(relationships, list):
        for rel in relationships:
            names.update(_extract_table_names_from_relationship(rel))

    return names


def _validate_relationship_entry(
    rel: dict[str, Any],
    headers_index: dict[str, list[str]],
    errors: list[str],
) -> None:
    """Validate a single relationship dict."""
    if not isinstance(rel, dict) or "from" not in rel or "to" not in rel:
        errors.append("Malformed relationship entry")
        return

    from_val = rel.get("from")
    to_val = rel.get("to")
    if not (
        isinstance(from_val, list)
        and len(from_val) == 2
        and isinstance(to_val, list)
        and len(to_val) == 2
    ):
        errors.append("Malformed relationship entry")
        return

    from_table, from_col = str(from_val[0]), str(from_val[1])
    to_table, to_col = str(to_val[0]), str(to_val[1])

    from_headers = headers_index.get(from_table, [])
    to_headers = headers_index.get(to_table, [])

    if not from_headers:
        errors.append(f"{from_table}.csv not found")
    elif from_col not in from_headers:
        errors.append(f"{from_table}.{from_col} not found in CSV")

    if not to_headers:
        errors.append(f"{to_table}.csv not found")
    elif to_col not in to_headers:
        errors.append(f"{to_table}.{to_col} not found in CSV")


def _validate_relationships_list(
    relationships: list[Any],
    headers_index: dict[str, list[str]],
    errors: list[str],
) -> None:
    for rel in relationships:
        _validate_relationship_entry(rel, headers_index, errors)


# ------------------------ public API ------------------------ #


def _load_relationships_spec(rel_path: Path, errors: list[str]) -> dict[str, Any] | None:
    """Load and validate the relationships.json spec."""
    if not rel_path.exists():
        errors.append(f"{RELATIONSHIPS_JSON} not found")
        return None
    try:
        return _json_load(rel_path)
    except ValueError as e:
        errors.append(f"Invalid {RELATIONSHIPS_JSON}: {e}")
        return None


def _extract_relationships(spec: dict[str, Any], errors: list[str]) -> list[Any]:
    """Extract relationships list or record an error."""
    relationships = spec.get("relationships", []) or []
    if not isinstance(relationships, list):
        errors.append(f"{RELATIONSHIPS_JSON} has non-list 'relationships'")
        return []
    return relationships


def validate_relationships(package_dir: Path) -> dict[str, Any]:
    """
    Validate relationships against actual CSV headers in the package.

    Returns:
        {"valid": bool, "errors": list[str], "relationships_count": int}
    """
    errors: list[str] = []
    rel_path = Path(package_dir) / RELATIONSHIPS_JSON

    spec = _load_relationships_spec(rel_path, errors)
    if spec is None:
        return {"valid": False, "errors": errors, "relationships_count": 0}

    relationships = _extract_relationships(spec, errors)
    if not relationships and errors:
        return {"valid": False, "errors": errors, "relationships_count": 0}

    # Build headers index for tables referenced
    table_names = _collect_table_names_from_spec(spec)
    headers_index = _build_headers_index(Path(package_dir), sorted(table_names))

    # Validate table key specs (primary/foreign) if provided
    tables_spec = spec.get("tables", {}) or {}
    if isinstance(tables_spec, dict):
        for t, t_spec in tables_spec.items():
            if isinstance(t_spec, dict):
                _validate_table_keys(str(t), t_spec, headers_index, errors)

    # Validate each relationship entry
    _validate_relationships_list(relationships, headers_index, errors)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "relationships_count": len(relationships),
    }


def validate_package(package_dir: Path) -> ValidationSummary:
    """Validate complete Power BI package integrity."""
    package_path = Path(package_dir)
    logger.info("Validating Power BI package at %s", package_path)

    errors: list[str] = []
    warnings: list[str] = []

    # 1) Required files present
    req_errs, req_warns = _check_required(package_path)
    errors.extend(req_errs)
    warnings.extend(req_warns)

    # model.pbit: warn if invalid
    model_path = package_path / MODEL_PBIT
    if model_path.exists():
        try:
            if not zipfile.is_zipfile(model_path):
                errors.append(
                    f"{MODEL_PBIT} is not a valid Power BI template archive. "
                    "Export a real .pbit from Power BI Desktop and place it under templates."
                )
        except Exception as e:
            errors.append(f"Cannot inspect {MODEL_PBIT}: {e}")

    # 2) Relationships correctness
    rel_summary = validate_relationships(package_path)
    if not rel_summary.get("valid", False):
        errors.extend(rel_summary.get("errors", []))

    # 3) Parameters sanity
    errors.extend(_check_parameters(package_path))

    # 4) CSV readability
    csv_files = _collect_csvs(package_path)
    errors.extend(_check_csv_readability(csv_files))

    valid = len(errors) == 0
    if valid:
        logger.info("Package validation passed")
    else:
        logger.warning("Package validation failed with %s errors", len(errors))

    return {
        "valid": valid,
        "errors": errors,
        "warnings": warnings,
        "file_count": len(list(package_path.rglob("*"))),
        "csv_count": len(csv_files),
        "relationships_count": int(rel_summary.get("relationships_count", 0)),
    }
