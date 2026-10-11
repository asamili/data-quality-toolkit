"""Pure classification of an Export source against the active dataset.

Two related questions are answered here, both without Streamlit, pandas, file IO,
or session-state mutation:

* *Before* an export — :func:`classify_export_source` decides whether the CSV path
  the Export page will actually use is the active dataset's source, and therefore
  whether the active managed lifecycle identities may legitimately be attached to
  the resulting export evidence. A path the operator overrode by hand is a
  different dataset and must never inherit the active version's identity.
* *After* an export — :func:`compare_latest_export` decides whether a historical
  :class:`ExportArtifactContext` came from whatever dataset is active *now*. The
  historical context is read-only evidence here: comparison classifies it, never
  clears, overwrites, or relabels it.

Identity rules encoded here:

* A managed match requires consistent lifecycle identity (``version_id`` *and*
  ``content_id``), never a merely matching path — the same path can hold a
  different managed version, and the same version id can hold different content.
* A legacy match is by normalized source binding, which is all an unmanaged
  dataset has.
* Path comparison is lexical only (``normpath``/``normcase``): nothing is opened,
  stat-ed, resolved through symlinks, or hashed, and lifecycle status is never
  inferred from a filename.
* Every presentation field is a basename. Absolute paths live only in
  :attr:`ExportSourceAlignment.binding`, which is internal comparison state and
  must not be rendered.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from data_quality_toolkit.adapters.ui.services.artifacts import redact_path_to_basename
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.export_context import ExportArtifactContext
from data_quality_toolkit.shared.managed_export_source import VerifiedManagedExportSource

__all__ = [
    "MANAGED_SOURCE_ORIGIN",
    "ExportSourceAlignment",
    "ExportSourceStatus",
    "LatestExportMatch",
    "classify_export_source",
    "classify_verified_managed_export_source",
    "compare_latest_export",
    "export_source_warning",
    "latest_export_match_label",
    "managed_manifest_metadata",
    "normalize_source_binding",
]

# Stable marker recorded in manifest metadata so a reader can tell that an
# export's source identity came from a managed lifecycle version rather than
# being inferred.
MANAGED_SOURCE_ORIGIN = "managed_version"


class ExportSourceStatus(Enum):
    """How the effective Export source relates to the active DatasetContext."""

    ACTIVE_MANAGED = "active_managed"
    ACTIVE_LEGACY = "active_legacy"
    EXPLICIT_OVERRIDE = "explicit_override"
    NO_ACTIVE_DATASET = "no_active_dataset"


class LatestExportMatch(Enum):
    """How a historical export's recorded source relates to the active dataset."""

    MATCHES_ACTIVE_MANAGED = "matches_active_managed"
    MATCHES_ACTIVE_LEGACY = "matches_active_legacy"
    OTHER_DATASET = "other_dataset"
    NO_ACTIVE_DATASET = "no_active_dataset"
    INSUFFICIENT_LINKAGE = "insufficient_linkage"


# Operator-facing status text. Both match kinds collapse to one phrase: whether
# the active dataset is managed or legacy is the Start page's story, not a
# distinction the Artifact Center needs to relitigate.
_MATCH_LABELS: dict[LatestExportMatch, str] = {
    LatestExportMatch.MATCHES_ACTIVE_MANAGED: "Matches active dataset",
    LatestExportMatch.MATCHES_ACTIVE_LEGACY: "Matches active dataset",
    LatestExportMatch.OTHER_DATASET: "Exported from another dataset",
    LatestExportMatch.NO_ACTIVE_DATASET: "No active dataset for comparison",
    LatestExportMatch.INSUFFICIENT_LINKAGE: "Source match unavailable for this older export",
}


def normalize_source_binding(value: str | None) -> str:
    """Return a lexically normalized path for comparison, or ``""`` when blank.

    Purely textual: ``normpath`` collapses redundant separators and ``.``/``..``
    segments, and ``normcase`` applies the platform's case/separator convention.
    Neither touches the filesystem, so a missing file compares exactly like a
    present one and no path is ever resolved through a symlink.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    return os.path.normcase(os.path.normpath(text))


def _text(value: str | None) -> str:
    """Read an optional identity field as stripped text."""
    return value.strip() if isinstance(value, str) else ""


@dataclass(frozen=True, slots=True)
class ExportSourceAlignment:
    """Immutable verdict on the Export source, safe to render except ``binding``.

    ``binding`` holds a normalized local path for session-only comparison and is
    the one field that must never reach the UI; ``display_name`` is its basename
    counterpart. Lifecycle identities are populated only for
    :attr:`ExportSourceStatus.ACTIVE_MANAGED`, so an override cannot carry them
    even if a caller ignores :attr:`may_attach_lifecycle_identity`.
    """

    status: ExportSourceStatus
    display_name: str = ""
    binding: str = ""
    source_present: bool = False
    version_id: str = ""
    family_id: str = ""
    content_id: str = ""

    @property
    def matches_active_source(self) -> bool:
        """True when the effective Export source is the active dataset's source."""
        return self.status in (
            ExportSourceStatus.ACTIVE_MANAGED,
            ExportSourceStatus.ACTIVE_LEGACY,
        )

    @property
    def may_attach_lifecycle_identity(self) -> bool:
        """True only when the source is the active *managed* version.

        A legacy match has no lifecycle identity to attach, and an override
        belongs to a different dataset entirely.
        """
        return self.status is ExportSourceStatus.ACTIVE_MANAGED

    @property
    def should_warn(self) -> bool:
        """True when a real, non-active source is about to be exported.

        A blank field has nothing to warn about yet, and with no active dataset
        there is nothing to differ from.
        """
        return self.source_present and self.status is ExportSourceStatus.EXPLICIT_OVERRIDE


def classify_export_source(
    source_path: str | None, context: DatasetContext | None
) -> ExportSourceAlignment:
    """Classify the effective Export source against the active dataset context.

    Pure: compares normalized paths without opening, stat-ing, or hashing
    anything, and never infers a managed version from a filename.
    """
    binding = normalize_source_binding(source_path)
    display_name = redact_path_to_basename(source_path)
    present = bool(binding)

    if context is None:
        return ExportSourceAlignment(
            status=ExportSourceStatus.NO_ACTIVE_DATASET,
            display_name=display_name,
            binding=binding,
            source_present=present,
        )

    if present and binding == normalize_source_binding(context.source_path):
        if context.managed:
            return ExportSourceAlignment(
                status=ExportSourceStatus.ACTIVE_MANAGED,
                display_name=display_name,
                binding=binding,
                source_present=True,
                version_id=_text(context.version_id),
                family_id=_text(context.family_id),
                content_id=_text(context.content_id),
            )
        return ExportSourceAlignment(
            status=ExportSourceStatus.ACTIVE_LEGACY,
            display_name=display_name,
            binding=binding,
            source_present=True,
        )

    return ExportSourceAlignment(
        status=ExportSourceStatus.EXPLICIT_OVERRIDE,
        display_name=display_name,
        binding=binding,
        source_present=present,
    )


def classify_verified_managed_export_source(
    source: VerifiedManagedExportSource,
) -> ExportSourceAlignment:
    """Classify verified managed provenance; ``classify_export_source`` is unchanged.

    ``source`` is the single provenance authority — there is deliberately no
    separate path, context, version, content, or trust parameter, and no
    optional managed argument was added to the legacy classifier.

    Because the provenance was already verified against a live managed trust
    root before this object could exist, the verdict is unconditionally
    :attr:`ExportSourceStatus.ACTIVE_MANAGED`: there is no path comparison to
    make and no way for a manual override to reach this function. The verified
    identities are carried straight through, so
    :func:`managed_manifest_metadata` projects the same four persisted keys it
    does for the legacy managed path.
    """
    return ExportSourceAlignment(
        status=ExportSourceStatus.ACTIVE_MANAGED,
        display_name=source.display_name,
        binding=normalize_source_binding(source.source_path),
        source_present=True,
        version_id=_text(source.version_id),
        family_id=_text(source.family_id),
        content_id=_text(source.content_id),
    )


def export_source_warning(alignment: ExportSourceAlignment) -> str:
    """Return the operator warning for a non-active Export source, else ``""``.

    Names the source by basename only, so the notice states which file the export
    will belong to without echoing a local path.
    """
    if not alignment.should_warn:
        return ""
    name = alignment.display_name or "the selected file"
    return (
        f"Export source `{name}` is not the active dataset. This export will belong to "
        "that manually selected source, not the active managed version — its lifecycle "
        "version identity is not recorded for it."
    )


def managed_manifest_metadata(alignment: ExportSourceAlignment) -> dict[str, object] | None:
    """Project a managed-source verdict onto additive manifest metadata, or ``None``.

    Returns a fresh mapping of exactly the four persisted keys when the export's
    effective source *is* the active managed version, and ``None`` otherwise — a
    legacy match, an explicit override, and a no-active-dataset export all record
    nothing rather than borrowing an identity they do not have.

    Deliberately all-or-nothing: a managed context missing any of the three
    identities yields ``None`` rather than partial metadata, because a half-linked
    export is worse evidence than an unlinked one — it looks authoritative while
    being unresolvable.

    Only lifecycle identities and a fixed origin marker are projected. The
    source path, normalized binding, operator label, root/parent identities, and
    compatibility ``dataset_id`` are all deliberately excluded: this mapping is
    persisted to disk, so anything host-specific or path-like must not reach it.
    """
    if not alignment.may_attach_lifecycle_identity:
        return None
    version_id = _text(alignment.version_id)
    family_id = _text(alignment.family_id)
    content_id = _text(alignment.content_id)
    if not (version_id and family_id and content_id):
        return None
    return {
        "source_version_id": version_id,
        "source_family_id": family_id,
        "source_content_id": content_id,
        "source_origin": MANAGED_SOURCE_ORIGIN,
    }


def compare_latest_export(
    context: ExportArtifactContext, active: DatasetContext | None
) -> LatestExportMatch:
    """Classify a historical export's source against the active dataset.

    Read-only in both directions: the historical context is evidence and is never
    mutated here. An export recorded before source linkage existed reports
    :attr:`LatestExportMatch.INSUFFICIENT_LINKAGE` rather than being guessed at —
    silence is safer than a fabricated match.
    """
    if active is None:
        return LatestExportMatch.NO_ACTIVE_DATASET
    if not _text(getattr(context, "source_status", "")):
        return LatestExportMatch.INSUFFICIENT_LINKAGE

    if active.managed:
        version_id = _text(getattr(context, "source_version_id", ""))
        content_id = _text(getattr(context, "source_content_id", ""))
        matches = (
            bool(version_id)
            and bool(content_id)
            and version_id == _text(active.version_id)
            and content_id == _text(active.content_id)
        )
        return (
            LatestExportMatch.MATCHES_ACTIVE_MANAGED if matches else LatestExportMatch.OTHER_DATASET
        )

    binding = _text(getattr(context, "source_binding", ""))
    if binding and binding == normalize_source_binding(active.source_path):
        return LatestExportMatch.MATCHES_ACTIVE_LEGACY
    return LatestExportMatch.OTHER_DATASET


def latest_export_match_label(match: LatestExportMatch) -> str:
    """Return the concise, path-free operator status for a comparison outcome."""
    return _MATCH_LABELS[match]
