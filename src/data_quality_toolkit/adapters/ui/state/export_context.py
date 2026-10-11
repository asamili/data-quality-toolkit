"""Typed session-only context describing the latest successful Export.

Written only after a confirmed Export returns successfully with artifacts, and
consumed by the Artifact Center "Latest Export" section so the operator can
inspect the run without re-entering paths or IDs. The context intentionally
performs no disk I/O: full paths inside it stay internal and are redacted to
basenames at display time by the existing artifact presentation helpers.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from data_quality_toolkit.adapters.ui.state.keys import EXPORT_ARTIFACT_CONTEXT

if TYPE_CHECKING:  # import-time cycle: the alignment service imports this module
    from data_quality_toolkit.adapters.ui.services.export_alignment import ExportSourceAlignment


@dataclass(frozen=True, slots=True)
class ExportArtifactContext:
    """Safe metadata snapshot of the latest successful Export run.

    ``export_paths`` and ``output_dir`` hold full local paths for internal
    read-only use (previews/downloads); they must never be rendered as primary
    UI output.

    The ``source_*`` fields are additive session-only evidence describing which
    dataset the export was produced *from*, so the Artifact Center can later say
    whether this export matches whatever dataset is active now. They all default
    to empty: older constructors stay valid, and a context stored before source
    linkage existed simply reports no linkage rather than a guessed match. This
    is historical evidence, never a second active pointer — nothing here tracks
    what is active, only what this one export came from, and it deliberately
    survives a dataset switch.

    ``source_binding`` holds a normalized local path for session-only comparison
    and follows the same rule as ``export_paths``: internal use only, never
    rendered. ``source_display_name`` is its basename counterpart.
    """

    export_paths: Mapping[str, str]
    output_dir: str
    run_id: str
    dataset_id: str
    exported_at: str = ""
    quality_db_status: str = ""
    source_status: str = ""
    source_display_name: str = ""
    source_binding: str = ""
    source_version_id: str = ""
    source_family_id: str = ""
    source_content_id: str = ""


def get_export_artifact_context(state: Mapping[str, Any]) -> ExportArtifactContext | None:
    """Return the latest-export context, ignoring malformed session values."""
    value = state.get(EXPORT_ARTIFACT_CONTEXT)
    return value if isinstance(value, ExportArtifactContext) else None


def set_export_artifact_context(
    state: MutableMapping[str, Any], context: ExportArtifactContext
) -> None:
    """Replace the latest-export context. A newer success always wins."""
    state[EXPORT_ARTIFACT_CONTEXT] = context


def _source_linkage_fields(alignment: ExportSourceAlignment | None) -> dict[str, str]:
    """Project an Export source verdict onto the context's ``source_*`` fields.

    The single enforcement point for lifecycle attachment: version, family, and
    content identities are copied only when the alignment says the source *is*
    the active managed version. An explicit override or a legacy match therefore
    cannot inherit the active version's identity even if a caller hands over an
    alignment that carries one.
    """
    if alignment is None:
        return {}
    managed = alignment.may_attach_lifecycle_identity
    return {
        "source_status": alignment.status.value,
        "source_display_name": alignment.display_name,
        "source_binding": alignment.binding,
        "source_version_id": alignment.version_id if managed else "",
        "source_family_id": alignment.family_id if managed else "",
        "source_content_id": alignment.content_id if managed else "",
    }


def export_artifact_context_from_result(
    result: Mapping[str, Any] | None,
    output_dir: str,
    alignment: ExportSourceAlignment | None = None,
) -> ExportArtifactContext | None:
    """Build a context from a successful Export result, or ``None``.

    Returns ``None`` unless the result carries a non-empty ``export_paths``
    mapping — a failed or artifact-less run must not produce a context.

    ``alignment`` is optional so existing callers and tests keep working. When
    supplied it records which dataset the export came from; the export's own
    compatibility ``dataset_id`` always comes from the result either way, so an
    override still reports the dataset it really exported.
    """
    if not isinstance(result, Mapping):
        return None
    raw_paths = result.get("export_paths")
    if not isinstance(raw_paths, Mapping):
        return None
    paths = {
        str(key): str(value).strip()
        for key, value in raw_paths.items()
        if isinstance(value, str) and value.strip()
    }
    if not paths:
        return None

    def _text(key: str) -> str:
        value = result.get(key)
        return value.strip() if isinstance(value, str) else ""

    return ExportArtifactContext(
        export_paths=MappingProxyType(paths),
        output_dir=str(output_dir).strip(),
        run_id=_text("run_id"),
        dataset_id=_text("dataset_id"),
        exported_at=_text("ts"),
        quality_db_status=_text("quality_db_status"),
        **_source_linkage_fields(alignment),
    )
