# src/data_quality_toolkit/exporters/bi/powerbi_exporter.py
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, TypedDict, cast

from data_quality_toolkit.adapters.exporters.bi.powerbi_zero_config.generator import (
    generate_powerbi_package,
)
from data_quality_toolkit.adapters.exporters.bi.powerbi_zero_config.packager import validate_package
from data_quality_toolkit.adapters.exporters.time.dim_time_generator import write_dim_time
from data_quality_toolkit.utils.helpers import ensure_dir
from data_quality_toolkit.utils.logging import get_logger

__all__ = ["export_powerbi_package"]

LOGGER_NAME: Final[str] = "dqt.exporters.bi.powerbi_exporter"
logger = get_logger(LOGGER_NAME)


class _ValidationResult(TypedDict, total=False):
    valid: bool
    errors: list[str]
    warnings: list[str]
    csv_count: int  # optional, some validators include this


class PowerBIPackageResult(TypedDict):
    package_dir: str
    files: dict[str, str]
    validation: _ValidationResult
    time_range: str
    base_folder: str
    dim_time_path: str


def _ensure_files_mapping(obj: Any) -> dict[str, str]:
    # Preferred shape: dict[str, str]
    if isinstance(obj, dict):
        out: dict[str, str] = {}
        for k, v in obj.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError("generator returned invalid 'files' mapping (non-str key/value)")
            out[k] = v
        return out

    # Back-compat: list[str | Path]
    if isinstance(obj, list):
        out2: dict[str, str] = {}
        for p in obj:
            if isinstance(p, str | Path):
                p_str = str(p)
                out2[Path(p_str).name] = p_str
            else:
                raise ValueError("generator returned invalid 'files' list (non-pathlike element)")
        return out2

    raise ValueError("generator returned invalid 'files' mapping (not a dict or list)")


def _normalize_validation(obj: Mapping[str, Any] | object) -> _ValidationResult:
    """
    Accept arbitrary dict-like validator output and return a well-typed _ValidationResult.
    """
    if not isinstance(obj, Mapping):
        return {"valid": False, "errors": ["validator returned non-dict result"]}

    valid = bool(obj.get("valid", False))

    raw_errs = obj.get("errors", [])
    errors: list[str]
    if isinstance(raw_errs, list):
        errors = [str(e) for e in raw_errs]
    elif raw_errs is not None:
        errors = [str(raw_errs)]
    else:
        errors = []

    vr: _ValidationResult = {"valid": valid, "errors": errors}

    raw_warns = obj.get("warnings", [])
    if isinstance(raw_warns, list):
        vr["warnings"] = [str(w) for w in raw_warns]

    if "csv_count" in obj:
        try:
            vr["csv_count"] = int(cast(Any, obj)["csv_count"])
        except (KeyError, TypeError, ValueError) as e:
            logger = get_logger("dqt.exporters.bi.powerbi_exporter")
            logger.debug("csv_count not set: %s", e.__class__.__name__)

    return vr


def export_powerbi_package(
    star_dir: str | Path,
    output_dir: str | Path,
    time_start: str = "2018-01-01",
    time_end: str = "2030-12-31",
    base_folder: str = "./dist",
    fiscal_year_start: int | None = None,
) -> PowerBIPackageResult:
    """
    Create a complete Power BI package.

    Steps:
      1) Generate `time/dim_time.csv` inside `output_dir`
      2) Generate Power BI zero-config package scaffold
      3) Validate package and return normalized, typed result
    """
    star_path = Path(star_dir)
    if not star_path.exists() or not star_path.is_dir():
        raise FileNotFoundError(f"star_dir not found or not a directory: {star_path}")

    output_path = ensure_dir(Path(output_dir))
    logger.info(
        "Exporting Power BI package | star_dir=%s output_dir=%s time=[%s..%s] fiscal=%s base=%s",
        star_path,
        output_path,
        time_start,
        time_end,
        fiscal_year_start,
        base_folder,
    )

    # 1) time dimension
    time_dir = ensure_dir(output_path / "time")
    dim_time_path = write_dim_time(
        output_dir=time_dir,
        start_date=time_start,
        end_date=time_end,
        fiscal_year_start=fiscal_year_start,
    )

    # 2) generate package
    package_info = generate_powerbi_package(
        star_dir=star_path,
        output_dir=output_path,
        base_folder=base_folder,
        dim_time_path=dim_time_path,
    )
    files = _ensure_files_mapping(package_info.get("files"))

    # 3) validate + normalize
    validation_raw = validate_package(output_path)  # TypedDict is fine; treat as Mapping
    validation = _normalize_validation(validation_raw)

    if not validation.get("valid", False):
        errs = validation.get("errors", [])
        logger.error("Power BI package validation failed: %s", errs)
        raise ValueError(f"Invalid Power BI package: {errs}")

    result: PowerBIPackageResult = {
        "package_dir": str(output_path),
        "files": files,
        "validation": validation,
        "time_range": f"{time_start} to {time_end}",
        "base_folder": base_folder,
        "dim_time_path": str(dim_time_path),
    }
    logger.info("Power BI package created at %s", output_path)
    return result
