"""Star-schema export service wrappers for the dashboard UI."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from data_quality_toolkit.shared.managed_export_source import VerifiedManagedExportSource


def _export_csv_to_dir(
    csv_path: str,
    output_dir: str,
    *,
    artifact_meta: Mapping[str, object] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate output_dir with path guard, then call export_csv. Returns (result, None) or (None, error).

    The UI seam opts in to lineage-manifest emission (``artifacts.json`` inside
    the confirmed output directory) so the Deliver pages can load the run
    read-only later. The public API default stays ``emit_manifest=False`` and
    the CLI stays opt-in via ``--manifest``.

    ``artifact_meta`` is optional additive metadata recorded on each artifact the
    emitted manifest describes; it is forwarded unchanged and never inspected
    here. Callers that omit it keep the previous behavior exactly.
    """
    try:
        from data_quality_toolkit.shared.path_guard import ensure_safe_output_dir

        safe_dir = ensure_safe_output_dir(output_dir.strip(), create=True)
    except Exception as exc:
        return None, str(exc)
    try:
        from data_quality_toolkit.api import export_csv

        result = export_csv(
            csv_path.strip(),
            output_dir=safe_dir,
            emit_manifest=True,
            artifact_meta=artifact_meta,
        )
        return cast(dict[str, Any], result), None
    except Exception as exc:
        return None, str(exc)


def _export_managed_source_to_dir(
    source: VerifiedManagedExportSource,
    output_dir: str,
) -> dict[str, Any]:
    """Export one verified managed version; ``_export_csv_to_dir`` stays unmanaged.

    ``source`` is the single provenance authority — there is deliberately no
    separate version, content, path, DataFrame, artifact-meta, or trust
    parameter, and no optional managed argument was added to the legacy helper.
    The provenance object travels whole to the managed public-API sibling, which
    owns manifest emission and managed lineage metadata.

    Unlike the legacy helper this raises rather than returning an error string:
    a managed export failure must be handled explicitly by the caller and never
    silently degrade to an unmanaged result. The output directory still passes
    the shared path guard before anything is written.
    """
    from data_quality_toolkit.shared.path_guard import ensure_safe_output_dir

    safe_dir = ensure_safe_output_dir(output_dir.strip(), create=True)

    from data_quality_toolkit.api import export_csv_managed

    return export_csv_managed(source, output_dir=safe_dir)
