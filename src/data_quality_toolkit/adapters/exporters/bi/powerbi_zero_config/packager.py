# cspell:ignore pbit nrows
"""Phase 2: Power BI package validation and integrity checks (refactored)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, TypedDict, cast

import pandas as pd

from data_quality_toolkit.domain.semantics.schema import Catalog
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


class _SemanticContractSummary(TypedDict, total=False):
    valid: bool
    errors: list[str]
    warnings: list[str]
    checked_kpis: int
    checked_tables: list[str]
    checked_columns: int


# ------------------------ constants ------------------------ #

STAR_DIR = "star"
TIME_DIR = "time"
TIME_TABLES = {"dim_time"}  # tables expected under time/

MODEL_PBIT = "model.pbit"
PARAMETERS_JSON = "parameters.json"
RELATIONSHIPS_JSON = "relationships.json"

_FACT_ISSUES_REQUIRED_COLUMNS = [
    "run_id",
    "dataset_id",
    "column_id",
    "issue_type",
    "severity",
    "category",
    "message",
]

_REQUIRED_STAR_TABLES = [
    "dim_dataset",
    "dim_column",
    "fact_profile_runs",
    "fact_quality_metrics",
    "fact_issues",
]

_STAR_TABLE_REQUIRED_COLUMNS = {
    "fact_issues": _FACT_ISSUES_REQUIRED_COLUMNS,
}


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
        f"{STAR_DIR}/fact_issues.csv",
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


def _check_required_star_columns(star_dir: Path) -> list[str]:
    """Validate explicit package-contract table columns."""
    errors: list[str] = []
    for table, required_columns in _STAR_TABLE_REQUIRED_COLUMNS.items():
        csv_path = star_dir / f"{table}.csv"
        if not csv_path.exists():
            continue
        headers = _csv_headers(csv_path)
        if headers is None:
            errors.append(f"Cannot read {STAR_DIR}/{table}.csv headers")
            continue
        missing = [col for col in required_columns if col not in headers]
        if missing:
            errors.append(f"{STAR_DIR}/{table}.csv missing required columns: {missing}")
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


def _looks_like_powerbi_package(path: Path) -> bool:
    """Return True when path has the package layout rather than a bare star directory."""
    return (path / STAR_DIR).is_dir()


def _star_dir_for_contract(path: Path) -> Path:
    """Resolve the star CSV directory for a package or a bare star directory."""
    return path / STAR_DIR if _looks_like_powerbi_package(path) else path


def _star_relpath(table: str, *, package_layout: bool) -> str:
    """Return a human-readable relative CSV path for validation errors."""
    filename = f"{table}.csv"
    return f"{STAR_DIR}/{filename}" if package_layout else filename


def _check_required_star_files(star_dir: Path, *, package_layout: bool) -> list[str]:
    """Validate required star CSV files for package or bare-star semantic checks."""
    errors: list[str] = []
    for table in _REQUIRED_STAR_TABLES:
        if not (star_dir / f"{table}.csv").exists():
            errors.append(
                f"Missing required file: {_star_relpath(table, package_layout=package_layout)}"
            )
    return errors


def _headers_for_semantic_table(
    table: str,
    star_dir: Path,
    headers_cache: dict[str, list[str] | None],
    errors: list[str],
    *,
    package_layout: bool,
) -> list[str] | None:
    """Load and cache a source table header for semantic-contract validation."""
    if table in headers_cache:
        return headers_cache[table]

    csv_path = star_dir / f"{table}.csv"
    relpath = _star_relpath(table, package_layout=package_layout)
    if not csv_path.exists():
        errors.append(f"Missing source table CSV for semantic contract: {relpath}")
        headers_cache[table] = None
        return None

    headers = _csv_headers(csv_path)
    if headers is None:
        errors.append(f"Cannot read semantic source table headers: {relpath}")
        headers_cache[table] = None
        return None

    headers_cache[table] = headers
    return headers


def _source_column_ref(
    kpi_id: str,
    source_table: str | None,
    source_column: str,
    errors: list[str],
) -> tuple[str, str] | None:
    """Resolve a KPI source column to (table, column)."""
    if "." in source_column:
        table, column = source_column.split(".", 1)
        table = table.strip()
        column = column.strip()
        if table and column:
            return table, column
        errors.append(f"KPI '{kpi_id}' has malformed source column: {source_column}")
        return None

    if source_table:
        return source_table, source_column

    errors.append(
        f"KPI '{kpi_id}' has unqualified source column without source_table: {source_column}"
    )
    return None


def _validate_semantic_contract(
    catalog: Catalog, package_or_star_dir: Path
) -> _SemanticContractSummary:
    """
    Validate KPI source provenance against exported star/package CSV headers.

    Internal helper for package-contract checks. It intentionally stays out of
    module __all__ and CLI/API surfaces.
    """
    root = Path(package_or_star_dir)
    package_layout = _looks_like_powerbi_package(root)
    star_dir = _star_dir_for_contract(root)

    errors: list[str] = []
    warnings: list[str] = []
    checked_tables: set[str] = set()
    checked_columns = 0
    headers_cache: dict[str, list[str] | None] = {}

    if package_layout:
        req_errs, req_warns = _check_required(root)
        errors.extend(req_errs)
        warnings.extend(req_warns)
        errors.extend(_check_parameters(root))
    else:
        errors.extend(_check_required_star_files(star_dir, package_layout=False))

    errors.extend(_check_required_star_columns(star_dir))

    for kpi in catalog.kpis:
        if kpi.source_table:
            checked_tables.add(kpi.source_table)
            _headers_for_semantic_table(
                kpi.source_table,
                star_dir,
                headers_cache,
                errors,
                package_layout=package_layout,
            )

        for source_column in kpi.source_columns or []:
            source_ref = _source_column_ref(kpi.id, kpi.source_table, source_column, errors)
            if source_ref is None:
                continue
            table, column = source_ref
            checked_tables.add(table)
            checked_columns += 1
            headers = _headers_for_semantic_table(
                table,
                star_dir,
                headers_cache,
                errors,
                package_layout=package_layout,
            )
            if headers is not None and column not in headers:
                errors.append(f"KPI '{kpi.id}' source column not found: {table}.{column}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "checked_kpis": len(catalog.kpis),
        "checked_tables": sorted(checked_tables),
        "checked_columns": checked_columns,
    }


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

    # 4) Explicit package-contract columns
    errors.extend(_check_required_star_columns(package_path / STAR_DIR))

    # 5) CSV readability
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
