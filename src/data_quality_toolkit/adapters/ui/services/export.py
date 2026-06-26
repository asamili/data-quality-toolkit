"""Star-schema export service wrappers for the dashboard UI."""

from __future__ import annotations

from typing import Any, cast


def _export_csv_to_dir(
    csv_path: str,
    output_dir: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate output_dir with path guard, then call export_csv. Returns (result, None) or (None, error)."""
    try:
        from data_quality_toolkit.shared.path_guard import ensure_safe_output_dir

        safe_dir = ensure_safe_output_dir(output_dir.strip(), create=True)
    except Exception as exc:
        return None, str(exc)
    try:
        from data_quality_toolkit.api import export_csv

        result = export_csv(csv_path.strip(), output_dir=safe_dir)
        return cast(dict[str, Any], result), None
    except Exception as exc:
        return None, str(exc)
