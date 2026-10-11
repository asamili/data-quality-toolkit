"""UI service: surface the Power BI zero-config package flow (generate/validate).

Thin wrappers over the existing zero-config generator/packager. Backend modules
are imported lazily inside functions so importing this module stays lightweight
and free of heavy/optional dependencies (matching ``services.export`` and
``services.kpi``). Display-facing data is basename-only; full paths are retained
in the result for local read/download but must be redacted before display.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data_quality_toolkit.adapters.ui.services.artifacts import (
    infer_artifact_category,
    infer_artifact_type,
    redact_path_to_basename,
)

LIFECYCLE_NOT_GENERATED = "Not generated"
LIFECYCLE_GENERATED = "Generated (not validated)"
LIFECYCLE_VALID = "Validated — valid"
LIFECYCLE_INVALID = "Validated — invalid"


def lifecycle_label(*, generated: bool, valid: bool | None) -> str:
    """Return the package lifecycle label for the given generate/validate state."""
    if not generated:
        return LIFECYCLE_NOT_GENERATED
    if valid is None:
        return LIFECYCLE_GENERATED
    return LIFECYCLE_VALID if valid else LIFECYCLE_INVALID


def _safe_size(path: Path) -> int | None:
    try:
        return int(path.stat().st_size)
    except OSError:
        return None


def package_file_rows(files_map: dict[str, str]) -> list[dict[str, Any]]:
    """Return basename-only rows (File/Type/Category/Size) for generated files."""
    rows: list[dict[str, Any]] = []
    for name, full_path in sorted(files_map.items()):
        basename = redact_path_to_basename(full_path) or str(name)
        rows.append(
            {
                "File": basename,
                "Type": infer_artifact_type(basename),
                "Category": infer_artifact_category(name, basename),
                "Size": _safe_size(Path(full_path)),
            }
        )
    return rows


def generate_package(
    star_dir: str,
    output_dir: str,
    base_folder: str,
    dim_time_path: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate the output dir, generate the package, and return a safe result.

    Returns ``(result, None)`` or ``(None, error)``. ``result`` keeps the full
    ``files`` mapping (name -> path) and ``output_dir`` for local read/download;
    callers must redact those to basenames before display.
    """
    star = star_dir.strip()
    if not star or not Path(star).is_dir():
        redacted = redact_path_to_basename(star) or "the selected directory"
        return None, f"Star schema directory not found: {redacted}"
    try:
        from data_quality_toolkit.shared.path_guard import ensure_safe_output_dir

        safe_out = ensure_safe_output_dir(output_dir.strip(), create=True)
    except Exception as exc:
        return None, str(exc)
    try:
        from data_quality_toolkit.adapters.exporters.bi.powerbi_zero_config.generator import (
            generate_powerbi_package,
        )

        result = generate_powerbi_package(
            Path(star),
            Path(safe_out),
            base_folder=base_folder.strip() or "./dist",
            dim_time_path=dim_time_path.strip() if dim_time_path else None,
        )
        return dict(result), None
    except Exception as exc:
        return None, str(exc)


def validate_generated_package(output_dir: str) -> tuple[dict[str, Any] | None, str | None]:
    """Validate a generated package directory; returns (summary, None) or (None, error)."""
    out = output_dir.strip()
    if not out or not Path(out).is_dir():
        return None, "Package directory not found."
    try:
        from data_quality_toolkit.adapters.exporters.bi.powerbi_zero_config.packager import (
            validate_package,
        )

        return dict(validate_package(Path(out))), None
    except Exception as exc:
        return None, str(exc)
